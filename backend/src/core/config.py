"""
Configuration management for the backend
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""
    
    # OpenAI Configuration
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field("https://api.openai.com/v1", env="OPENAI_BASE_URL")
    
    # Database Configuration
    mysql_host: Optional[str] = Field(None, env="MYSQL_HOST")
    mysql_port: int = Field(3306, env="MYSQL_PORT")
    mysql_user: Optional[str] = Field(None, env="MYSQL_USER")
    mysql_password: Optional[str] = Field(None, env="MYSQL_PASSWORD")
    mysql_database: Optional[str] = Field(None, env="MYSQL_DATABASE")
    
    # Milvus Configuration
    milvus_address: Optional[str] = Field(None, env="MILVUS_ADDRESS")
    milvus_ssl: bool = Field(False, env="MILVUS_SSL")
    
    # Server Configuration
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(3001, env="PORT")
    debug: bool = Field(False, env="DEBUG")
    
    # CORS Configuration
    cors_origins: list = Field(["*"], env="CORS_ORIGINS")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # 允许额外字段


# Global settings instance
settings = Settings()


def get_mysql_config() -> dict:
    """Get MySQL configuration from environment variables; raise if required values missing."""
    required = {
        "MYSQL_HOST": settings.mysql_host,
        "MYSQL_USER": settings.mysql_user,
        "MYSQL_PASSWORD": settings.mysql_password,
        "MYSQL_DATABASE": settings.mysql_database,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing required MySQL env vars: {', '.join(missing)}")
    return {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "database": settings.mysql_database,
    }


def get_milvus_config() -> dict:
    """Get Milvus configuration"""
    return {
        "address": settings.milvus_address,
        "ssl": settings.milvus_ssl,
    } 