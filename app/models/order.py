from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlmodel import Field, Relationship, SQLModel
from app.models.base import utc_now

class OrderStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"    # 待支付
    PAID = "paid"                          # 已支付未发货
    SHIPPED = "shipped"                    # 已发货
    COMPLETED = "completed"                # 已完成
    REFUND_REQUESTED = "refund_requested"  # 退款申请中
    REFUNDED = "refunded"                  # 已退款
    CLOSED = "closed"                      # 已关闭


class Order(SQLModel, table=True):
    __tablename__ = "orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_no: str = Field(index=True, unique=True, max_length=32)
    user_id: int = Field(foreign_key="users.id", index=True)
    product_name: str = Field(max_length=200)
    quantity: int = Field(default=1)
    amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    status: OrderStatus = Field(default=OrderStatus.PENDING_PAYMENT, index=True)
    created_at: datetime = Field(default_factory=utc_now)   # 退款资格校验依据
    updated_at: datetime = Field(default_factory=utc_now)

    user: Optional["User"] = Relationship(
        back_populates="orders", sa_relationship_kwargs={"lazy": "selectin"}
    )
    refunds: list["Refund"] = Relationship(
        back_populates="order", sa_relationship_kwargs={"lazy": "selectin"}
    )
