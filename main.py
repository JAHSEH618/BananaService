import asyncio
import base64
import io
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
import tos
from PIL import Image
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import FileResponse, StreamingResponse
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

# ============ 本地图片存储 ============
IMAGE_STORAGE_DIR = Path(settings.image_storage_dir)

_MIME_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_FILE_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "webp": ".webp",
}

_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# ============ 图片格式检测 ============
def _detect_image_format(raw_bytes: bytes) -> str:
    """通过文件头魔数检测图片格式，返回格式名 (jpeg/png/webp)"""
    if len(raw_bytes) >= 8 and raw_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "png"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b'RIFF' and raw_bytes[8:12] == b'WEBP':
        return "webp"
    return "jpeg"


# ============ TOS 客户端构建 ============
def _build_tos_client() -> TosClientV2:
    """兼容不同 tos SDK 版本的构造参数差异。"""
    base_kwargs = {
        "ak": settings.tos_access_key,
        "sk": settings.tos_secret_key,
        "endpoint": settings.tos_endpoint,
        "region": settings.tos_region,
    }
    preferred_kwargs = {
        "connection_time": 60,
        "socket_timeout": 30,
        "max_retry_count": 3,
    }

    try:
        return TosClientV2(**base_kwargs, **preferred_kwargs)
    except TypeError as e:
        logger.warning("当前 tos SDK 不支持部分高级参数，已降级为基础初始化: %s", e)

    try:
        return TosClientV2(**base_kwargs, max_retry_count=3)
    except TypeError as e:
        logger.warning("当前 tos SDK 不支持 max_retry_count，继续降级: %s", e)

    return TosClientV2(**base_kwargs)


# ============ 本地图片存储 ============
def _save_raw_image_to_local(raw_bytes: bytes) -> Optional[str]:
    """将原始图片字节保存到本地磁盘，PNG/WebP 自动转为 JPEG 以大幅缩减体积。"""
    try:
        fmt = _detect_image_format(raw_bytes)
        if fmt in ("png", "webp"):
            # PNG/WebP → JPEG: 对于摄影类图片，体积从 2-5MB 降至 200-500KB
            img = Image.open(io.BytesIO(raw_bytes))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            filename = f"{uuid.uuid4().hex}.jpg"
            filepath = IMAGE_STORAGE_DIR / filename
            img.save(filepath, format="JPEG", quality=90, optimize=True)
            orig_kb = len(raw_bytes) / 1024
            new_kb = filepath.stat().st_size / 1024
            logger.info(f"PNG/WebP→JPEG 转换: {orig_kb:.0f}KB → {new_kb:.0f}KB ({new_kb/orig_kb*100:.0f}%)")
        else:
            # JPEG 直写，无额外开销
            filename = f"{uuid.uuid4().hex}.jpg"
            filepath = IMAGE_STORAGE_DIR / filename
            filepath.write_bytes(raw_bytes)
        return filename
    except Exception as e:
        logger.error(f"保存图片到本地失败: {e}")
        return None


async def _save_raw_images_to_local(raw_images: List[bytes]) -> List[Optional[str]]:
    """批量保存原始图片字节到本地目录"""
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _save_raw_image_to_local, raw)
        for raw in raw_images
    ]
    return await asyncio.gather(*tasks)


# ============ 过期图片清理 ============
def _cleanup_old_images():
    """清理过期的本地图片文件"""
    if not IMAGE_STORAGE_DIR.exists():
        return
    retention_seconds = settings.image_retention_hours * 3600
    now = time.time()
    cleaned = 0
    for filepath in IMAGE_STORAGE_DIR.iterdir():
        if filepath.is_file() and filepath.suffix.lower() in _EXTENSION_TO_MIME:
            if now - filepath.stat().st_mtime > retention_seconds:
                try:
                    filepath.unlink()
                    cleaned += 1
                except OSError:
                    pass
    if cleaned > 0:
        logger.info(f"清理了 {cleaned} 个过期图片文件")


# ============ TOS 上传（后台） ============
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
    extension = _FILE_EXTENSIONS.get(image_format, ".jpg")
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


async def _upload_single_raw_to_tos(image_bytes: bytes) -> Optional[str]:
    """将原始图片字节上传到 TOS，返回公网 URL"""
    if not _tos_client or not _tos_executor:
        return None

    fmt = _detect_image_format(image_bytes)
    object_key = _generate_tos_object_key(settings.tos_upload_prefix, fmt)
    content_type = _MIME_TYPES.get(fmt, "image/jpeg")
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
        url = f"https://{settings.tos_public_domain}/{object_key}"
        logger.info(f"TOS 上传成功: {url[:80]}")
        return url
    except tos.exceptions.TosClientError as e:
        logger.error("TOS Client 错误: key=%s, error=%s", object_key, e)
        return None
    except tos.exceptions.TosServerError as e:
        logger.error(
            "TOS Server 错误: key=%s, status=%s, code=%s, message=%s",
            object_key, e.status_code, e.code, e.message,
        )
        return None
    except Exception as e:
        logger.error("TOS 上传异常: key=%s, error=%s", object_key, e)
        return None


async def _background_upload_to_tos(raw_images: List[bytes]):
    """后台 TOS 上传（fire-and-forget），不阻塞响应"""
    try:
        tasks = [_upload_single_raw_to_tos(raw) for raw in raw_images]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if isinstance(r, str))
        logger.info(f"后台 TOS 上传完成: {ok}/{len(raw_images)} 成功")
    except Exception as e:
        logger.error(f"后台 TOS 上传异常: {e}")


# ============ 应用生命周期 ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理资源"""
    global _genai_client, _tos_client, _tos_executor

    # 创建本地图片存储目录
    IMAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"本地图片存储目录: {IMAGE_STORAGE_DIR.resolve()}")

    # 启动时清理过期图片
    _cleanup_old_images()

    # 初始化 Gemini 客户端
    logger.info("正在初始化 Gemini 客户端...")
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

        _tos_client = _build_tos_client()
        _tos_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="banana_tos")
        logger.info(
            "TOS 上传已启用 - endpoint=%s, region=%s, bucket=%s",
            settings.tos_endpoint, settings.tos_region, settings.tos_bucket_name,
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
    version="1.2.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ============ 数据模型 ============
class GenerateImageRequest(BaseModel):
    prompt: str
    image_base64: Optional[str] = None
    model: str = "gemini-3.1-flash-image-preview"
    aspect_ratio: Optional[str] = None
    person_generation: Optional[str] = None
    include_base64: bool = True  # 设为 False 可大幅减小响应体积


class ImageResponse(BaseModel):
    images: Optional[List[str]] = None
    image_urls: Optional[List[str]] = None
    proxy_urls: Optional[List[str]] = None
    text: Optional[str] = None
    metadata: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    version: str


# ============ API Key 认证 ============
async def verify_api_key(x_api_key: str = Header(..., description="API 密钥")):
    if not settings.service_api_key:
        logger.error("服务未配置 SERVICE_API_KEY")
        raise HTTPException(status_code=500, detail="服务配置错误：未配置 API Key")

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
    return HealthResponse(status="healthy", version="1.2.0")


@app.post("/generate", response_model=ImageResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def generate_image(
    request: Request,
    body: GenerateImageRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    生成图像接口。

    优化点：
    - 使用 raw bytes 全程传递，零 base64 编解码开销用于磁盘存储
    - TOS 上传为 fire-and-forget 后台任务，不阻塞响应
    - include_base64=False 时跳过 base64 编码，大幅缩减响应体积
    """
    has_image = body.image_base64 is not None
    logger.info(f"收到生成请求: prompt='{body.prompt[:50]}...', model={body.model}, has_image={has_image}")

    try:
        # 构建请求内容
        parts = []

        if body.image_base64:
            image_data = body.image_base64
            mime_type = "image/jpeg"

            if 'base64,' in image_data:
                header = image_data.split('base64,')[0]
                if 'image/png' in header:
                    mime_type = "image/png"
                elif 'image/webp' in header:
                    mime_type = "image/webp"
                image_data = image_data.split('base64,')[1]

            image_bytes = base64.b64decode(image_data)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

        parts.append(types.Part.from_text(text=body.prompt))

        contents = [types.Content(role="user", parts=parts)]

        image_config_args = {"image_size": "1K"}
        if body.aspect_ratio:
            image_config_args["aspect_ratio"] = body.aspect_ratio
        if body.person_generation:
            image_config_args["person_generation"] = body.person_generation

        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(**image_config_args),
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        )

        # ---- 核心：直接收集 raw bytes，不做 base64 编码 ----
        response_raw_images: List[bytes] = []
        response_text_parts: List[str] = []

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
                        response_raw_images.append(part.inline_data.data)
                    elif part.text:
                        response_text_parts.append(part.text)

        if not response_raw_images:
            logger.warning("生成结果为空")
            raise HTTPException(status_code=500, detail="未生成任何图像")

        response_text = "".join(response_text_parts) if response_text_parts else None
        logger.info(f"生成成功: {len(response_raw_images)} 张图像, 文本: {bool(response_text)}")

        # 1. 保存到本地磁盘（raw bytes 直写，无 base64 开销）
        local_filenames = await _save_raw_images_to_local(response_raw_images)
        local_urls = [f"/images/{fn}" for fn in local_filenames if fn is not None]
        logger.info(f"本地存储: {len(local_urls)}/{len(response_raw_images)} 成功")

        # 2. TOS 上传：fire-and-forget，不阻塞响应
        if settings.tos_upload_enabled:
            asyncio.create_task(_background_upload_to_tos(response_raw_images))

        # 3. 仅在客户端明确需要时才做 base64 编码
        #    如果本地存储全部失败，则无论 include_base64 设置如何，都返回 base64 作为兜底
        images_b64 = None
        if not local_urls:
            logger.error("本地存储全部失败，返回 base64 兜底")
            images_b64 = [base64.b64encode(raw).decode('utf-8') for raw in response_raw_images]
        elif body.include_base64:
            images_b64 = [base64.b64encode(raw).decode('utf-8') for raw in response_raw_images]

        return ImageResponse(
            images=images_b64,
            image_urls=None,  # TOS 异步上传中，URL 尚不可用
            proxy_urls=local_urls if local_urls else None,
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


# ============ 本地图片服务端点 ============
@app.get("/images/{filename}")
async def serve_local_image(filename: str):
    """提供本地存储的生成图片。文件名为随机 UUID，不可预测。"""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="无效的文件名")

    filepath = IMAGE_STORAGE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="图片不存在或已过期")

    ext = filepath.suffix.lower()
    content_type = _EXTENSION_TO_MIME.get(ext, "image/jpeg")

    return FileResponse(
        filepath,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ============ 图片代理端点（保留兼容） ============
@app.get("/image-proxy")
async def image_proxy(
    url: str,
    api_key: str = Depends(verify_api_key)
):
    """图片代理下载端点（保留向后兼容）。"""
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="无效的图片 URL")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"TOS 返回 HTTP {resp.status_code}")

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
        host="0.0.0.0",
        port=settings.port,
        workers=settings.workers,
        reload=False
    )
