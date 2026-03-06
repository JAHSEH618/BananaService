import asyncio
import base64
import io
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import tos
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from google import genai
from google.genai import types
from tos import TosClientV2

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
_tos_client: Optional[TosClientV2] = None
_tos_executor: Optional[ThreadPoolExecutor] = None

_TOS_MIME_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_TOS_FILE_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "webp": ".webp",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理资源"""
    global _genai_client, _tos_client, _tos_executor
    
    # 启动时初始化
    logger.info("正在初始化 Gemini 客户端...")
    
    # 初始化 Gemini 客户端 (SDK 内部管理连接池)
    _genai_client = genai.Client(api_key=settings.gemini_api_key)
    
    # 初始化 TOS SDK 客户端
    if settings.tos_upload_enabled:
        required_fields = {
            "tos_access_key": settings.tos_access_key,
            "tos_secret_key": settings.tos_secret_key,
            "tos_bucket_name": settings.tos_bucket_name,
            "tos_public_domain": settings.tos_public_domain,
        }
        missing_fields = [key for key, value in required_fields.items() if not value]
        if missing_fields:
            raise RuntimeError(
                f"TOS 上传已启用，但缺少必要配置: {', '.join(missing_fields)}"
            )

        _tos_client = TosClientV2(
            ak=settings.tos_access_key,
            sk=settings.tos_secret_key,
            endpoint=settings.tos_endpoint,
            region=settings.tos_region,
            connection_time=60,
            socket_timeout=30,
            max_retry_count=3,
        )
        _tos_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="banana_tos")
        logger.info(
            "TOS 上传已启用 - endpoint=%s, region=%s, bucket=%s",
            settings.tos_endpoint,
            settings.tos_region,
            settings.tos_bucket_name,
        )
    else:
        logger.info("TOS 上传已禁用")
    
    logger.info(f"服务已启动 - 超时: {settings.request_timeout_seconds}s, 速率限制: {settings.rate_limit_per_minute}/min")
    
    yield
    
    # 关闭时清理
    if _tos_executor:
        _tos_executor.shutdown(wait=True)
        _tos_executor = None
    _tos_client = None
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
    image_urls: Optional[List[Optional[str]]] = None  # TOS 公网 URL 列表
    proxy_urls: Optional[List[Optional[str]]] = None  # 后端代理 URL（供内网设备访问）
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


# ============ TOS 上传 ============
def _normalize_image_format(image_format: str) -> str:
    fmt = image_format.lower()
    return fmt if fmt in _TOS_FILE_EXTENSIONS else "jpeg"


def _strip_data_uri_prefix(image_base64: str) -> str:
    if "base64," in image_base64:
        return image_base64.split("base64,", 1)[1]
    return image_base64


def _generate_tos_object_key(prefix: str, image_format: str) -> str:
    clean_prefix = prefix.strip()
    if clean_prefix and not clean_prefix.endswith("/"):
        clean_prefix = f"{clean_prefix}/"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:20]
    unique_id = uuid.uuid4().hex[:12]
    extension = _TOS_FILE_EXTENSIONS.get(image_format, ".jpg")
    return f"{clean_prefix}{unique_id}_{timestamp}{extension}"


def _upload_to_tos_sync(
    client: TosClientV2,
    bucket_name: str,
    object_key: str,
    image_bytes: bytes,
    content_type: str,
):
    return client.put_object(
        bucket=bucket_name,
        key=object_key,
        content=io.BytesIO(image_bytes),
        content_type=content_type,
        content_length=len(image_bytes),
    )


async def _upload_single_image_to_tos(base64_image: str, image_format: str) -> Optional[str]:
    if not _tos_client or not _tos_executor:
        return None

    try:
        image_bytes = base64.b64decode(_strip_data_uri_prefix(base64_image), validate=True)
    except Exception as e:
        logger.warning("Base64 解码失败，跳过上传: %s", e)
        return None

    object_key = _generate_tos_object_key(settings.tos_upload_prefix, image_format)
    content_type = _TOS_MIME_TYPES.get(image_format, "image/jpeg")
    loop = asyncio.get_running_loop()

    try:
        await loop.run_in_executor(
            _tos_executor,
            _upload_to_tos_sync,
            _tos_client,
            settings.tos_bucket_name,
            object_key,
            image_bytes,
            content_type,
        )
        return f"https://{settings.tos_public_domain}/{object_key}"
    except tos.exceptions.TosClientError as e:
        logger.error("TOS Client 错误: key=%s, error=%s", object_key, e)
        return None
    except tos.exceptions.TosServerError as e:
        logger.error(
            "TOS Server 错误: key=%s, status=%s, code=%s, message=%s",
            object_key,
            e.status_code,
            e.code,
            e.message,
        )
        return None
    except Exception as e:
        logger.error("TOS 上传异常: key=%s, error=%s", object_key, e)
        return None


async def upload_images_to_tos(base64_images: List[str], image_format: str = "jpeg") -> List[Optional[str]]:
    """
    将 base64 图片批量上传到 TOS，返回公网 URL 列表。
    上传失败的位置返回 None。
    """
    if not _tos_client or not _tos_executor or not settings.tos_upload_enabled:
        return [None] * len(base64_images)

    normalized_format = _normalize_image_format(image_format)
    upload_tasks = [
        _upload_single_image_to_tos(img_b64, normalized_format)
        for img_b64 in base64_images
    ]
    return await asyncio.gather(*upload_tasks)


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
        
        # 使用超时控制（包含生成 + TOS 上传）
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

            # 上传到 TOS
            image_urls = None
            if settings.tos_upload_enabled:
                logger.info(f"正在上传 {len(response_images)} 张图片到 TOS...")
                image_urls = await upload_images_to_tos(response_images)
                uploaded_count = sum(1 for u in image_urls if u is not None)
                logger.info(f"TOS 上传完成: {uploaded_count}/{len(response_images)} 成功")

            # 生成代理 URL（让 App 通过本服务下载，不直连 TOS）
            proxy_urls = None
            if image_urls:
                proxy_urls = [
                    f"/image-proxy?url={url}" if url else None
                    for url in image_urls
                ]

            return ImageResponse(
                images=response_images,
                image_urls=image_urls,
                proxy_urls=proxy_urls,
                text=response_text,
            )

    except asyncio.TimeoutError:
        logger.error(f"请求超时: {settings.request_timeout_seconds}s")
        raise HTTPException(status_code=504, detail="请求超时")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 图片代理端点 ============
@app.get("/image-proxy")
async def image_proxy(
    url: str,
    api_key: str = Depends(verify_api_key)
):
    """
    图片代理下载端点：由后端从 TOS 下载图片后返回给客户端。
    解决 Android 设备直连 TOS 东南亚节点 connection reset 的问题。
    """
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="无效的图片 URL")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"TOS 返回 HTTP {resp.status_code}"
                )

            content_type = resp.headers.get("content-type", "image/jpeg")
            content = resp.content

        logger.info(f"图片代理成功: {len(content)} bytes, url={url[:80]}")
        return StreamingResponse(
            iter([content]),
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"图片代理失败: {e}, url={url[:80]}")
        raise HTTPException(status_code=502, detail=f"图片代理失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # 强制绑定 0.0.0.0 以支持容器/外部访问
        port=settings.port,
        workers=settings.workers,
        reload=False  # 生产环境关闭热重载
    )
