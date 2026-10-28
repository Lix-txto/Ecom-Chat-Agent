"""聚合所有 ORM 模型：Alembic env 与业务代码统一从这里导入。

注意：跨文件 Relationship 依赖此聚合导入完成注册。
"""
from app.models.base import utc_now
from app.models.user import User, UserRole
from app.models.order import Order, OrderStatus
from app.models.refund import Refund, RefundStatus
from app.models.audit import AuditAction, AuditLog, AuditStatus
from app.models.knowledge import KnowledgeChunk
from app.models.message import MessageCard, MessageRole

__all__ = [
    "Order", "OrderStatus", "User", "UserRole",
    "Refund", "RefundStatus",
    "AuditAction", "AuditLog", "AuditStatus",
    "KnowledgeChunk",
    "MessageCard", "MessageRole",
]
