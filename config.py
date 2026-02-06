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
