"""管理员 API：待审退款任务列表 + 决策（批准/拒绝）。

状态机（与 M3/M4 约定一致）：
    approve → refund: PENDING → AUTO_APPROVED（M6 挂 Celery 支付任务）
    reject  → refund: PENDING → REJECTED；订单恢复 SHIPPED
              （演示简化：未记录退款前状态，统一按已发货恢复）
重复决策 → 409。决策完成后向所有在线管理员 WS 广播。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from app.api.v1.schemas import AuditTaskOut, DecisionRequest, DecisionResponse
from app.core.database import sync_engine
from app.core.security import get_current_admin
from app.models import (
    AuditAction,
    AuditLog,
    AuditStatus,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
    User,
    utc_now,
)
from app.websocket.manager import manager

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])


@router.get("/audits", response_model=list[AuditTaskOut])
def list_pending_audits():
    """待审任务列表（同步端点 → FastAPI 自动丢线程池）。"""
    with Session(sync_engine) as session:
        rows = session.exec(
            select(AuditLog, Refund, Order, User)
            .join(Refund, AuditLog.refund_id == Refund.id)
            .join(Order, Refund.order_id == Order.id)
            .join(User, Refund.user_id == User.id)
            .where(AuditLog.status == AuditStatus.PENDING)
            .order_by(AuditLog.id)
        ).all()
    return [
        AuditTaskOut(
            audit_id=audit.id,
            refund_no=refund.refund_no,
            order_no=order.order_no,
            product_name=order.product_name,
            username=user.username,
            reason=refund.reason,
            refund_amount=refund.refund_amount,
            requested_at=refund.requested_at,
            status=audit.status.value,
        )
        for audit, refund, order, user in rows
    ]


@router.post("/audits/{audit_id}/decision", response_model=DecisionResponse)
async def decide(audit_id: int, req: DecisionRequest, admin: User = Depends(get_current_admin)):
    def _apply() -> tuple[str, str | None]:
        with Session(sync_engine) as session:
            audit = session.get(AuditLog, audit_id)
            if audit is None:
                return "not_found", None
            if audit.status != AuditStatus.PENDING:
                return "conflict", None

            refund = audit.refund
            order = refund.order

            if req.action == "approve":
                audit.action = AuditAction.APPROVE
                refund.status = RefundStatus.AUTO_APPROVED
                # M6：在此派发 Celery 退款支付任务
            else:
                audit.action = AuditAction.REJECT
                refund.status = RefundStatus.REJECTED
                order.status = OrderStatus.SHIPPED  # 演示简化（见 docstring）

            refund.processed_at = utc_now()
            audit.status = AuditStatus.RESOLVED
            audit.admin_id = admin.id
            audit.comment = req.comment
            audit.resolved_at = utc_now()

            refund_no = refund.refund_no
            session.add(audit)
            session.add(refund)
            session.add(order)
            session.commit()
            return "ok", refund_no

    outcome, refund_no = await run_in_threadpool(_apply)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="审核任务不存在")
    if outcome == "conflict":
        raise HTTPException(status_code=409, detail="该审核任务已处理")

    await manager.broadcast_admins({
        "type": "audit_resolved",
        "audit_id": audit_id,
        "action": req.action,
        "refund_no": refund_no,
    })
    return DecisionResponse(action=req.action, refund_no=refund_no or "")
