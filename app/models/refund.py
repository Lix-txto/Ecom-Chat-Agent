from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.order import utc_now


class RefundStatus(str, Enum):
    PENDING = "pending"              # 已提交，待规则/人工裁决
    AUTO_APPROVED = "auto_approved"  # 自动通过，进入支付流程
    PROCESSING = "processing"        # Celery 执行退款支付中
    REFUNDED = "refunded"            # 已到账
    REJECTED = "rejected"            # 已拒绝


class Refund(SQLModel, table=True):
    __tablename__ = "refunds"

    id: Optional[int] = Field(default=None, primary_key=True)
    refund_no: str = Field(index=True, unique=True, max_length=32)
    order_id: int = Field(foreign_key="orders.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    reason: str = Field(max_length=500)
    refund_amount: Decimal = Field(max_digits=12, decimal_places=2)
    status: RefundStatus = Field(default=RefundStatus.PENDING, index=True)
    requested_at: datetime = Field(default_factory=utc_now)
    processed_at: Optional[datetime] = Field(default=None)

    order: Optional["Order"] = Relationship(
        back_populates="refunds", sa_relationship_kwargs={"lazy": "selectin"}
    )
    audit_logs: list["AuditLog"] = Relationship(
        back_populates="refund", sa_relationship_kwargs={"lazy": "selectin"}
    )

