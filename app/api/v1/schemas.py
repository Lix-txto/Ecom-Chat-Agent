"""API 请求/响应 Pydantic 模型（契约层）。"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---- auth ----

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ---- chat ----

class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: str
    order_no: Optional[str] = None
    refund_no: Optional[str] = None
    needs_audit: bool = False


class ChatHistoryItem(BaseModel):
    role: str
    content: str
    card_type: Optional[str] = None
    card_payload: Optional[dict[str, Any]] = None
    created_at: datetime


# ---- admin ----

class AuditTaskOut(BaseModel):
    audit_id: int
    refund_no: str
    order_no: str
    product_name: str
    username: str
    reason: str
    refund_amount: Decimal
    requested_at: datetime
    status: str


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = Field(default=None, max_length=500)


class DecisionResponse(BaseModel):
    status: str = "ok"
    action: str
    refund_no: str
