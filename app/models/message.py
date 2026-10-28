from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import utc_now


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageCard(SQLModel, table=True):
    __tablename__ = "message_cards"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, max_length=64)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    role: MessageRole = Field(index=True)
    content: str                                            # 纯文本内容
    card_type: Optional[str] = Field(default=None, index=True)  # order_info / refund_progress / policy...
    card_payload: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB)
    )
    created_at: datetime = Field(default_factory=utc_now)
