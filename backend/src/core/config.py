"""
Configuration management for the financial expert backend
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
    mysql_host: str = Field("47.251.112.46", env="MYSQL_HOST")
    mysql_port: int = Field(3306, env="MYSQL_PORT")
    mysql_user: str = Field("root", env="MYSQL_USER")
    mysql_password: str = Field("Zy1$$", env="MYSQL_PASSWORD")
    mysql_database: str = Field("crawler", env="MYSQL_DATABASE")
    
    # Milvus Configuration
    milvus_address: str = Field("47.251.112.46:19530", env="MILVUS_ADDRESS")
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
    """Get MySQL configuration"""
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