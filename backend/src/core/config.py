"""
Configuration management for the backend
"""
import os
from typing import Optional, Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""
    
    # Provider Switch（仅 deepseek / openai）
    llm_provider: Literal["deepseek", "openai"] = Field("deepseek", env="LLM_PROVIDER")

    # DeepSeek 配置（仅当 llm_provider=deepseek 使用）
    deepseek_api_key: Optional[str] = Field(None, env="DEEPSEEK_API_KEY")
    deepseek_base_url: Optional[str] = Field("https://api.deepseek.com/v1", env="DEEPSEEK_BASE_URL")
    deepseek_model: Optional[str] = Field("deepseek-chat", env="DEEPSEEK_MODEL")

    # OpenAI 配置（仅当 llm_provider=openai 使用）
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field("https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model: Optional[str] = Field("gpt-4o-mini", env="OPENAI_MODEL")
    # Provider + planner method
    llm_provider: Literal["deepseek", "openai"] = Field("deepseek", env="LLM_PROVIDER")
    structured_planner_method: Literal["auto", "tool_calling", "json_mode", "json_schema", "disabled"] = Field("auto", env="STRUCTURED_PLANNER_METHOD")
    # Embeddings-specific OpenAI-compatible configuration (optional overrides)
    openai_embed_api_key: Optional[str] = Field(None, env="OPENAI_EMBED_API_KEY")
    openai_embed_base_url: Optional[str] = Field(None, env="OPENAI_EMBED_BASE_URL")
    openai_embed_model: Optional[str] = Field(None, env="OPENAI_EMBED_MODEL")
    openai_embed_dim: Optional[int] = Field(None, env="OPENAI_EMBED_DIM")
    # Vector storage configuration
    documents_collection_name: Optional[str] = Field("documents", env="DOCUMENTS_COLLECTION_NAME")
    reset_documents_collection_on_startup: bool = Field(False, env="RESET_DOCUMENTS_COLLECTION_ON_STARTUP")

    # Web search providers
    tavily_api_key: Optional[str] = Field(None, env="TAVILY_API_KEY")
    
    # Database Configuration
    mysql_host: Optional[str] = Field(None, env="MYSQL_HOST")
    mysql_port: int = Field(3306, env="MYSQL_PORT")
    mysql_user: Optional[str] = Field(None, env="MYSQL_USER")
    mysql_password: Optional[str] = Field(None, env="MYSQL_PASSWORD")
    mysql_database: Optional[str] = Field(None, env="MYSQL_DATABASE")
    # PostgreSQL DSN for thread persistence (e.g., postgresql://user:pass@host:5432/db?sslmode=disable)
    pg_dsn: Optional[str] = Field(None, env="PG_DSN")
    
    # Milvus Configuration
    milvus_address: Optional[str] = Field(None, env="MILVUS_ADDRESS")
    milvus_ssl: bool = Field(False, env="MILVUS_SSL")

    # Neo4j / Graphiti configuration
    neo4j_uri: Optional[str] = Field(None, env="NEO4J_URI")
    neo4j_user: Optional[str] = Field(None, env="NEO4J_USER")
    neo4j_password: Optional[str] = Field(None, env="NEO4J_PASSWORD")
    neo4j_database: Optional[str] = Field("neo4j", env="NEO4J_DATABASE")
    
    # Server Configuration
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(3001, env="PORT")
    debug: bool = Field(False, env="DEBUG")
    # Trace events (SSE observability)
    trace_events: bool = Field(False, env="TRACE_EVENTS")
    # JWT
    jwt_secret: Optional[str] = Field(None, env="JWT_SECRET")
    
    # CORS Configuration
    cors_origins: list = Field(["*"], env="CORS_ORIGINS")
    
    # Voice / ASR Configuration
    enable_voice: bool = Field(False, env="ENABLE_VOICE")
    whisper_model: str = Field("base", env="WHISPER_MODEL")
    asr_language: Optional[str] = Field(None, env="ASR_LANGUAGE")

    # Vision / Image Recognition Configuration
    enable_vision: bool = Field(True, env="ENABLE_VISION")
    vision_max_image_size: int = Field(20, env="VISION_MAX_IMAGE_SIZE")  # MB

    # RAG Configuration
    rag_attempts_max: int = Field(1, env="RAG_ATTEMPTS_MAX")
    rag_top_k_fast: int = Field(6, env="RAG_TOP_K_FAST")
    rag_top_k_precise: int = Field(20, env="RAG_TOP_K_PRECISE")
    rag_mmr_lambda: float = Field(0.3, env="RAG_MMR_LAMBDA")
    rag_min_score: float = Field(0.5, env="RAG_MIN_SCORE")
    rag_min_margin: float = Field(0.05, env="RAG_MIN_MARGIN")
    rag_min_avg: float = Field(0.45, env="RAG_MIN_AVG")
    rag_enable_rerank: bool = Field(False, env="RAG_ENABLE_RERANK")
    rag_sources_default: list = Field(["vector"], env="RAG_SOURCES_DEFAULT")
    
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


# LLM factory: centralize chat LLM construction（严格按 provider 选择变量）
def get_chat_llm(temperature: float = 0.1, **kwargs):
    """Return a ChatOpenAI-compatible LLM based on current settings.

    This factory does NOT decide planner method; it only builds the LLM
    with base_url/api_key/model according to env.
    """
    try:
        from langchain_openai import ChatOpenAI
    except Exception as e:
        raise RuntimeError(f"langchain_openai not installed: {e}")

    cfg = resolve_llm_config()
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    model = cfg["model"]

    client = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        **kwargs,
    )
    try:
        print(f"[LLM] provider={settings.llm_provider} base_url={base_url} model={model}")
    except Exception:
        pass
    return client


def resolve_llm_config() -> dict:
    """Resolve provider-specific base_url/api_key/model strictly by LLM_PROVIDER.

    - deepseek: 只读 DEEPSEEK_* 变量；缺失关键值报错
    - openai: 只读 OPENAI_* 变量；缺失关键值报错
    """
    provider = settings.llm_provider
    if provider == "deepseek":
        base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        api_key = settings.deepseek_api_key
        model = settings.deepseek_model or "deepseek-chat"
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        return {"base_url": base_url, "api_key": api_key, "model": model}
    else:  # openai
        base_url = settings.openai_base_url or "https://api.openai.com/v1"
        api_key = settings.openai_api_key
        model = settings.openai_model or "gpt-4o-mini"
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return {"base_url": base_url, "api_key": api_key, "model": model}