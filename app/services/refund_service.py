"""退款业务服务层：资格校验、申请创建、状态查询。

分层约定（项目级"宪法"）：
1. 本层只做【数据库读写 + 业务规则计算】，不 import Celery / LLM / FastAPI，
   因此可被三层复用：FastAPI 路由、Celery 任务、LangGraph 工具，也可脱离外部依赖单测。
2. 金额一律 Decimal；阈值从配置读取并显式转 Decimal 再比较（禁 Decimal 与 float 混算）。
3. 时间一律 tz-aware UTC（utc_now）。
4. 会话由调用方注入；本层在业务事务完成处 commit。
5. 订单不存在与"不属于当前用户"返回同一文案，防止订单号枚举探测。

退款状态机（M3 覆盖前半段）：
    PENDING ──(管理员批准, M5)──> AUTO_APPROVED ──(Celery 支付, M6)──> PROCESSING ──> REFUNDED
       └──(管理员拒绝, M5)──> REJECTED
    金额 ≤ REFUND_AUTO_APPROVE_MAX_AMOUNT 的申请直接置为 AUTO_APPROVED（本层实现）。
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AuditLog,
    AuditStatus,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
    utc_now,
)

# ---------- 对外结果 DTO（M4 工具 / M5 API 会复用） ----------


class RefundCheckCode(str, Enum):
    """机器可读的校验结论码，Agent / 前端据此分支。"""

    ELIGIBLE = "eligible"
    ORDER_NOT_FOUND = "order_not_found"        # 含"订单不属于当前用户"（安全合并）
    NOT_REFUNDABLE_STATUS = "not_refundable_status"
    BEYOND_WINDOW = "beyond_window"
    ALREADY_REFUNDED = "already_refunded"
    PENDING_APPLICATION = "pending_application"


class OrderSnapshot(BaseModel):
    """订单摘要：用于消息卡片 / Agent 上下文。"""

    order_no: str
    product_name: str
    amount: Decimal
    status: str
    created_at: datetime


class EligibilityResult(BaseModel):
    eligible: bool
    code: RefundCheckCode
    reason: str                                   # 面向用户的中文结论
    order: Optional[OrderSnapshot] = None
    refund_amount: Optional[Decimal] = None       # 可退金额（当前简化为全额退）


class RefundCreateResult(BaseModel):
    success: bool
    message: str
    refund_no: Optional[str] = None
    status: Optional[RefundStatus] = None
    auto_approved: bool = False                   # True → M6 派发 Celery 支付任务
    needs_manual_review: bool = False             # True → 已生成待审 AuditLog


class RefundStatusInfo(BaseModel):
    refund_no: str
    order_no: str
    product_name: str
    amount: Decimal
    status: RefundStatus
    reason: str
    requested_at: datetime
    processed_at: Optional[datetime] = None


# ---------- 内部工具 ----------

_NOT_FOUND_MSG = "未找到该订单"

# 状态分流：未发货随时可退；已发货/已完成需在窗口期内
_PRE_SHIPMENT_REFUNDABLE = {OrderStatus.PAID}
_WINDOW_REFUNDABLE = {OrderStatus.SHIPPED, OrderStatus.COMPLETED}


def _as_utc(dt: datetime) -> datetime:
    """防御性归一：万一读到 naive 值按 UTC 解释（M1 之后不应出现）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _load_order(session: Session, order_no: str, user_id: int) -> Optional[Order]:
    """加载属于该用户的订单；不存在或不属于该用户统一返回 None。"""
    order = session.exec(select(Order).where(Order.order_no == order_no)).first()
    if order is None or order.user_id != user_id:
        return None
    return order


def _snapshot(order: Order) -> OrderSnapshot:
    status_value = (
        order.status.value if isinstance(order.status, OrderStatus) else str(order.status)
    )
    return OrderSnapshot(
        order_no=order.order_no,
        product_name=order.product_name,
        amount=order.amount,
        status=status_value,
        created_at=_as_utc(order.created_at),
    )


def _evaluate(order: Order) -> EligibilityResult:
    """纯规则函数：不碰数据库，订单进 → 结论出（便于单测穷举所有分支）。"""
    snap = _snapshot(order)

    # ---- 不可退状态（逐一给出针对性文案） ----
    if order.status == OrderStatus.PENDING_PAYMENT:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.NOT_REFUNDABLE_STATUS,
            reason="订单尚未支付，无需申请退款", order=snap,
        )
    if order.status == OrderStatus.REFUNDED:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.ALREADY_REFUNDED,
            reason="该订单已完成退款，请勿重复申请", order=snap,
        )
    if order.status == OrderStatus.REFUND_REQUESTED:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.PENDING_APPLICATION,
            reason="该订单已有退款申请正在处理中，请勿重复提交", order=snap,
        )
    if order.status == OrderStatus.CLOSED:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.NOT_REFUNDABLE_STATUS,
            reason="订单已关闭，无法申请退款", order=snap,
        )

    # ---- 可退状态 ----
    if order.status in _PRE_SHIPMENT_REFUNDABLE:
        return EligibilityResult(
            eligible=True, code=RefundCheckCode.ELIGIBLE,
            reason="订单尚未发货，符合全额退款条件",
            order=snap, refund_amount=order.amount,
        )

    # SHIPPED / COMPLETED：校验退货窗口
    age = utc_now() - _as_utc(order.created_at)
    window = timedelta(days=settings.REFUND_WINDOW_DAYS)
    if age > window:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.BEYOND_WINDOW,
            reason=(
                f"已超过 {settings.REFUND_WINDOW_DAYS} 天退货期"
                f"（下单至今 {age.days} 天），无法退款"
            ),
            order=snap,
        )
    return EligibilityResult(
        eligible=True, code=RefundCheckCode.ELIGIBLE,
        reason="订单在退货期内，符合退款条件",
        order=snap, refund_amount=order.amount,
    )


def _generate_refund_no() -> str:
    """RF-<UTC时间戳14位>-<6位随机十六进制>，同秒碰撞概率约 1/1670 万。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"RF-{ts}-{uuid4().hex[:6].upper()}"


# ---------- 对外服务 API ----------


def check_refund_eligibility(
    session: Session, order_no: str, user_id: int
) -> EligibilityResult:
    """退款资格校验：LangGraph 工具 / API 共用入口（只读，无副作用）。"""
    order = _load_order(session, order_no, user_id)
    if order is None:
        return EligibilityResult(
            eligible=False, code=RefundCheckCode.ORDER_NOT_FOUND, reason=_NOT_FOUND_MSG
        )
    return _evaluate(order)


def create_refund_application(
    session: Session, order_no: str, user_id: int, reason: str
) -> RefundCreateResult:
    """创建退款申请：规则校验 → 落库 → 金额阈值分流（自动批准 / 转人工）。"""
    order = _load_order(session, order_no, user_id)
    if order is None:
        return RefundCreateResult(success=False, message=_NOT_FOUND_MSG)

    verdict = _evaluate(order)
    if not verdict.eligible:
        return RefundCreateResult(success=False, message=verdict.reason)

    clean_reason = ((reason or "").strip() or "未填写原因")[:500]

    refund = Refund(
        refund_no=_generate_refund_no(),
        order_id=order.id,
        user_id=user_id,
        reason=clean_reason,
        refund_amount=order.amount,
        status=RefundStatus.PENDING,
    )
    session.add(refund)
    session.flush()  # 拿到 refund.id，供 AuditLog 外键使用

    # 金额阈值分流（≤ 阈值自动批准；> 阈值生成人工审核任务）
    threshold = Decimal(str(settings.REFUND_AUTO_APPROVE_MAX_AMOUNT))
    if order.amount <= threshold:
        refund.status = RefundStatus.AUTO_APPROVED
        auto_approved, needs_manual = True, False
        message = "退款申请已自动通过，退款金额将原路退回（预计 1-3 个工作日到账）"
    else:
        session.add(AuditLog(refund_id=refund.id, status=AuditStatus.PENDING))
        auto_approved, needs_manual = False, True
        message = "退款金额需人工审核，已为你提交审核，结果将通过消息通知你"

    order.status = OrderStatus.REFUND_REQUESTED
    order.updated_at = utc_now()

    # 先取值再 commit（避免 expire_on_commit 后触发重复查询）
    result = RefundCreateResult(
        success=True,
        message=message,
        refund_no=refund.refund_no,
        status=refund.status,
        auto_approved=auto_approved,
        needs_manual_review=needs_manual,
    )
    session.commit()
    return result


def query_refund_status(
    session: Session,
    user_id: int,
    refund_no: Optional[str] = None,
    order_no: Optional[str] = None,
) -> Optional[RefundStatusInfo]:
    """按退款单号或订单号查询当前用户最新退款进度；未找到/越权统一返回 None。"""
    if refund_no:
        refund = session.exec(
            select(Refund).where(Refund.refund_no == refund_no)
        ).first()
    elif order_no:
        order = _load_order(session, order_no, user_id)
        if order is None:
            return None
        refund = session.exec(
            select(Refund)
            .where(Refund.order_id == order.id)
            .order_by(Refund.id.desc())
        ).first()
    else:
        return None

    if refund is None or refund.user_id != user_id:
        return None

    refund_order = refund.order  # selectin 关系，会话内直接可用
    return RefundStatusInfo(
        refund_no=refund.refund_no,
        order_no=refund_order.order_no,
        product_name=refund_order.product_name,
        amount=refund.refund_amount,
        status=refund.status,
        reason=refund.reason,
        requested_at=_as_utc(refund.requested_at),
        processed_at=(
            _as_utc(refund.processed_at) if refund.processed_at is not None else None
        ),
    )
