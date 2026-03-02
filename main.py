import asyncio
import base64
import logging
import mimetypes
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from google import genai
from google.genai import types

from config import get_settings

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============ 配置加载 ============
settings = get_settings()

# ============ 速率限制器 ============
limiter = Limiter(key_func=get_remote_address)

# ============ 全局客户端 ============
_genai_client: Optional[genai.Client] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理资源"""
    global _genai_client
    
    # 启动时初始化
    logger.info("正在初始化 Gemini 客户端...")
    
    # 初始化 Gemini 客户端 (SDK 内部管理连接池)
    _genai_client = genai.Client(api_key=settings.gemini_api_key)
    
    logger.info(f"服务已启动 - 超时: {settings.request_timeout_seconds}s, 速率限制: {settings.rate_limit_per_minute}/min")
    
    yield
    
    # 关闭时清理
    logger.info("服务已关闭")


# ============ FastAPI 应用 ============
app = FastAPI(
    title="Gemini 图像生成服务",
    description="高并发 Gemini API 中转服务",
    version="1.0.0",
    lifespan=lifespan
)

# 添加速率限制异常处理
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ============ 数据模型 ============
class GenerateImageRequest(BaseModel):
    prompt: str
    image_base64: Optional[str] = None  # 输入图片 (base64 编码)
    model: str = "gemini-3.1-flash-image-preview"
    aspect_ratio: Optional[str] = None
    person_generation: Optional[str] = None  # 例如 "ALLOW_ADULT"


class ImageResponse(BaseModel):
    images: List[str]  # Base64 编码的图像列表
    text: Optional[str] = None  # 模型返回的文本 (如有)
    metadata: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    version: str


# ============ API Key 认证 ============
async def verify_api_key(x_api_key: str = Header(..., description="API 密钥")):
    """
    验证 API Key
    需要在请求头中提供 X-API-Key
    """
    if not settings.service_api_key:
        logger.error("服务未配置 SERVICE_API_KEY")
        raise HTTPException(
            status_code=500,
            detail="服务配置错误：未配置 API Key"
        )
    
    if x_api_key != settings.service_api_key:
        logger.warning(f"无效的 API Key: {x_api_key[:8]}...")
        raise HTTPException(
            status_code=401,
            detail="无效的 API Key",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    return x_api_key


# ============ API 端点 ============
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点，用于 K8s/Docker 探活"""
    return HealthResponse(status="healthy", version="1.0.0")


@app.post("/generate", response_model=ImageResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def generate_image(
    request: Request, 
    body: GenerateImageRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    生成图像接口
    
    - **prompt**: 图像描述文本
    - **image_base64**: 输入图片 (可选, base64 编码)
    - **model**: 使用的模型名称
    - **aspect_ratio**: 宽高比 (可选)
    - **person_generation**: 人体生成策略 (可选)
    
    固定配置: image_size="1K", thinking_level="minimal"
    """
    has_image = body.image_base64 is not None
    logger.info(f"收到生成请求: prompt='{body.prompt[:50]}...', model={body.model}, has_image={has_image}")
    
    try:
        # 构建请求内容
        parts = []
        
        # 如果有输入图片，先添加图片 Part
        if body.image_base64:
            # 解析 base64 数据 (支持 data:image/xxx;base64,xxx 格式)
            image_data = body.image_base64
            mime_type = "image/jpeg"  # 默认 JPEG
            
            if 'base64,' in image_data:
                # 尝试从 data URI 中提取 mime_type
                header = image_data.split('base64,')[0]
                if 'image/png' in header:
                    mime_type = "image/png"
                elif 'image/webp' in header:
                    mime_type = "image/webp"
                image_data = image_data.split('base64,')[1]
            
            image_bytes = base64.b64decode(image_data)
            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            )
        
        # 添加文本提示词
        parts.append(types.Part.from_text(text=body.prompt))
        
        contents = [
            types.Content(
                role="user",
                parts=parts,
            ),
        ]

        # 配置生成参数
        image_config_args = {"image_size": "1K"}  # 固定为 1K
        if body.aspect_ratio:
            image_config_args["aspect_ratio"] = body.aspect_ratio
        if body.person_generation:
            image_config_args["person_generation"] = body.person_generation
            
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(**image_config_args),
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),  # 固定为 minimal
        )

        response_images = []
        response_text_parts = []
        
        # 使用超时控制
        async with asyncio.timeout(settings.request_timeout_seconds):
            stream = await _genai_client.aio.models.generate_content_stream(
                model=body.model,
                contents=contents,
                config=generate_content_config,
            )
            
            async for chunk in stream:
                if chunk.parts is None:
                    continue
                
                for part in chunk.parts:
                    if part.inline_data and part.inline_data.data:
                        # 图像数据
                        b64_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                        response_images.append(b64_data)
                    elif part.text:
                        # 文本数据
                        response_text_parts.append(part.text)

        if not response_images:
            logger.warning("生成结果为空")
            raise HTTPException(status_code=500, detail="未生成任何图像")

        response_text = "".join(response_text_parts) if response_text_parts else None
        logger.info(f"生成成功: {len(response_images)} 张图像, 文本: {bool(response_text)}")
        return ImageResponse(images=response_images, text=response_text)

    except asyncio.TimeoutError:
        logger.error(f"请求超时: {settings.request_timeout_seconds}s")
        raise HTTPException(status_code=504, detail="请求超时")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # 强制绑定 0.0.0.0 以支持容器/外部访问
        port=settings.port,
        workers=settings.workers,
        reload=False  # 生产环境关闭热重载
    )
