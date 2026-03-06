from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # Gemini API
    gemini_api_key: str = ""
    
    # 服务 API Key (调用接口时需要提供此密钥)
    service_api_key: str = ""
    
    # 性能配置
    request_timeout_seconds: int = 120  # 生图请求超时时间
    max_connections: int = 100  # 最大连接数
    max_keepalive_connections: int = 20  # 最大保持连接数
    
    # 速率限制
    rate_limit_per_minute: int = 60  # 每分钟最大请求数
    
    # TOS 直传配置
    tos_upload_enabled: bool = False  # 是否启用 TOS 上传
    tos_region: str = "ap-southeast-1"
    tos_endpoint: str = "tos-ap-southeast-1.volces.com"
    tos_bucket_name: str = "aipohto-lky"
    tos_access_key: str = ""
    tos_secret_key: str = ""
    tos_public_domain: str = "aipohto-lky.tos-ap-southeast-1.volces.com"
    tos_upload_prefix: str = "generated/"  # TOS 存储路径前缀
    
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4  # 建议设置为 CPU 核心数
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
