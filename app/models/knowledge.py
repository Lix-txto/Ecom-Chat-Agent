from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.config import settings
from app.models.base import utc_now


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("source", "chunk_index"),)  # ETL 防重

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True, max_length=200)      # 如 shipping_policy.md
    chunk_index: int = Field(default=0)                   # 块在源文件中的序号
    content: str                                          # 原文块内容
    embedding: Optional[list[float]] = Field(
        default=None, sa_column=Column(Vector(settings.EMBEDDING_DIM))
    )
    meta: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB)
    )
    created_at: datetime = Field(default_factory=utc_now)
