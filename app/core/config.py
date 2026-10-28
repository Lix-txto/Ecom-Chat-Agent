from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目全局配置（LLM 字段已提前落位：Chat 走 DeepSeek，Embedding 走硅基流动）。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- App ----
    APP_NAME: str = "E-commerce Smart Agent"
    DEBUG: bool = True

    # ---- 数据库 ----
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "admin"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "knowledge_base"

    # ---- JWT ----
    JWT_SECRET_KEY: str = "insecure-default-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ---- Redis / Celery（M6 使用）----
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = ""      # 留空回落到 REDIS_URL
    CELERY_RESULT_BACKEND: str = ""

    # ---- Chat：DeepSeek ----
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT_SECONDS: int = 30

    # ---- Embedding：硅基流动（向量列维度与 EMBEDDING_DIM 保持一致）----
    SILICONFLOW_API_KEY: str
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024

    # ---- 退款业务规则（M3 使用）----
    REFUND_WINDOW_DAYS: int = 7                    # 发货后可退款的天数窗口
    REFUND_AUTO_APPROVE_MAX_AMOUNT: float = 100.0   # ≤ 此金额自动批准，否则转人工

    # ---------- 派生 URL ----------

    @property
    def database_url_sync(self) -> str:
        """Alembic 迁移 / seed 脚本 / Celery 使用。"""
        auth = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{auth}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_async(self) -> str:
        """FastAPI 运行时使用。"""
        auth = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{auth}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
