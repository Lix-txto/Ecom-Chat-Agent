from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import utc_now


class AuditStatus(str, Enum):
    PENDING = "pending"    # 待管理员处理
    RESOLVED = "resolved"  # 已处理


class AuditAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    refund_id: int = Field(foreign_key="refunds.id", index=True)
    admin_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    status: AuditStatus = Field(default=AuditStatus.PENDING, index=True)
    action: Optional[AuditAction] = Field(default=None)
    comment: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: Optional[datetime] = Field(default=None)

    refund: Optional["Refund"] = Relationship(
        back_populates="audit_logs", sa_relationship_kwargs={"lazy": "selectin"}
    )
