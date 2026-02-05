import asyncio
import base64
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
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
# 使用 httpx.AsyncClient 配置连接池
_http_client: Optional[httpx.AsyncClient] = None
_genai_client: Optional[genai.Client] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化连接池，关闭时清理资源"""
    global _http_client, _genai_client
    
    # 启动时初始化
    logger.info("正在初始化连接池...")
    
    # 创建带连接池的 httpx 客户端
    _http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        ),
        timeout=httpx.Timeout(settings.request_timeout_seconds),
    )
    
    # 初始化 Gemini 客户端
    _genai_client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"client": _http_client}
    )
    
    logger.info(f"服务已启动 - 最大连接数: {settings.max_connections}, 超时: {settings.request_timeout_seconds}s")
    
    yield
    
    # 关闭时清理资源
    logger.info("正在关闭连接池...")
    if _http_client:
        await _http_client.aclose()
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
    model: str = "gemini-3-pro-image-preview"
    aspect_ratio: Optional[str] = None
    number_of_images: int = 1


class ImageResponse(BaseModel):
    images: List[str]  # Base64 编码的图像列表
    metadata: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    version: str


# ============ API 端点 ============
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点，用于 K8s/Docker 探活"""
    return HealthResponse(status="healthy", version="1.0.0")


@app.post("/generate", response_model=ImageResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def generate_image(request: Request, body: GenerateImageRequest):
    """
    生成图像接口
    
    - **prompt**: 图像描述文本
    - **image_base64**: 输入图片 (可选, base64 编码)
    - **model**: 使用的模型名称
    - **number_of_images**: 生成图像数量
    """
    has_image = body.image_base64 is not None
    logger.info(f"收到生成请求: prompt='{body.prompt[:50]}...', model={body.model}, has_image={has_image}")
    
    try:
        # 构建请求内容
        parts = [types.Part.from_text(text=body.prompt)]
        
        # 如果有输入图片，添加图片 Part
        if body.image_base64:
            # 解析 base64 数据 (支持 data:image/xxx;base64,xxx 格式)
            image_data = body.image_base64
            if 'base64,' in image_data:
                image_data = image_data.split('base64,')[1]
            
            image_bytes = base64.b64decode(image_data)
            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg"  # 默认 JPEG，也支持 PNG
                )
            )
        
        contents = [
            types.Content(
                role="user",
                parts=parts,
            ),
        ]

        # 配置生成参数
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(image_size="1K") if "pro-image" in body.model else None
        )

        response_images = []
        
        # 使用超时控制
        async with asyncio.timeout(settings.request_timeout_seconds):
            stream = await _genai_client.aio.models.generate_content_stream(
                model=body.model,
                contents=contents,
                config=generate_content_config,
            )
            
            async for chunk in stream:
                if (
                    chunk.candidates is None
                    or not chunk.candidates
                    or chunk.candidates[0].content is None
                    or chunk.candidates[0].content.parts is None
                ):
                    continue
                
                for part in chunk.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        b64_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                        response_images.append(b64_data)

        if not response_images:
            logger.warning("生成结果为空")
            raise HTTPException(status_code=500, detail="未生成任何图像")

        logger.info(f"生成成功: {len(response_images)} 张图像")
        return ImageResponse(images=response_images)

    except asyncio.TimeoutError:
        logger.error(f"请求超时: {settings.request_timeout_seconds}s")
        raise HTTPException(status_code=504, detail="请求超时")
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=False  # 生产环境关闭热重载
    )
