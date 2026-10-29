"""退款相关 Celery 任务：支付（模拟）、用户短信（模拟）、管理员通知。

任务纪律：
1. 任务体是普通函数 —— 直接调用即可测试（本项目测试策略，不用 eager 模式）。
2. 幂等：按 refund_no 定位 + 状态机防护，重复执行不产生二次副作用。
3. 金额/时间纪律沿袭全项目宪法：Decimal / tz-aware UTC。
4. 对外事件经 core.pubsub 发布 —— worker 与 API 是不同进程，
   这是结果实时触达用户 WebSocket 的唯一桥。
"""
import logging
import time

from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import sync_engine
from app.core.pubsub import publish_event
from app.models import AuditStatus, Order, OrderStatus, Refund, RefundStatus, utc_now
from app.celery_app import celery_app   # ← 必须 import 这份实例

logger = logging.getLogger(__name__)


def _load_refund(session: Session, refund_no: str) -> Refund | None:
    return session.exec(select(Refund).where(Refund.refund_no == refund_no)).first()

@celery_app.task
def process_refund_payment(refund_no: str) -> dict:
    """退款支付任务（模拟打款网关）。

    状态机防护：
        AUTO_APPROVED / PROCESSING → 可推进
        REFUNDED                  → 幂等跳过（重复投递/重试安全）
        PENDING                   → 拒绝（尚未批准，人工流程未完成）
        REJECTED                  → 拒绝
    成功后：refund → REFUNDED，order → REFUNDED，并发布 refund.completed 事件。
    """
    with Session(sync_engine) as session:
        refund = _load_refund(session, refund_no)
        if refund is None:
            return {"success": False, "refund_no": refund_no, "message": "退款单不存在"}

        if refund.status == RefundStatus.REFUNDED:
            return {"success": False, "refund_no": refund_no,
                    "message": "该退款已完成，幂等跳过（防重复打款）"}
        if refund.status == RefundStatus.PENDING:
            return {"success": False, "refund_no": refund_no,
                    "message": "退款尚待人工审核，拒绝支付"}
        if refund.status == RefundStatus.REJECTED:
            return {"success": False, "refund_no": refund_no,
                    "message": "退款已被拒绝，拒绝支付"}
        # AUTO_APPROVED / PROCESSING → 继续

        refund.status = RefundStatus.PROCESSING
        session.add(refund)
        session.commit()

        # ---- 模拟第三方支付网关调用 ----
        logger.info("[Payment] 开始处理退款 %s（¥%s）...", refund_no, refund.refund_amount)
        time.sleep(settings.PAYMENT_SIMULATION_SECONDS)
        logger.info("[Payment] 退款 %s 打款成功", refund_no)

        refund.status = RefundStatus.REFUNDED
        refund.processed_at = utc_now()
        order = refund.order
        order.status = OrderStatus.REFUNDED
        order.updated_at = utc_now()
        session.add(refund)
        session.add(order)
        session.commit()

        publish_event("refund.completed", {
            "user_id": refund.user_id,
            "refund_no": refund.refund_no,
            "order_no": order.order_no,
            "amount": str(refund.refund_amount),
        })
        return {"success": True, "refund_no": refund_no,
                "status": RefundStatus.REFUNDED.value}

@celery_app.task
def send_refund_sms(user_id: int, refund_no: str, success: bool = True) -> dict:
    """用户通知任务（模拟短信网关）：真实项目在此接入短信/推送服务商。"""
    outcome = "已原路退回，请注意查收" if success else "审核未通过，如有疑问请联系人工客服"
    logger.info("[SMS 模拟] → 用户 %s：您的退款 %s %s", user_id, refund_no, outcome)
    return {"success": True, "simulated": True, "user_id": user_id, "refund_no": refund_no}

@celery_app.task
def notify_admins_new_audit(refund_no: str) -> dict:
    """管理员通知任务：有大额退款进入人工审核时提醒（模拟渠道 + WS 事件）。"""
    with Session(sync_engine) as session:
        refund = _load_refund(session, refund_no)
        if refund is None or refund.status != RefundStatus.PENDING:
            return {"success": False, "message": "无待审退款或退款单不存在"}
        # 仅当仍存在待审 AuditLog 时提醒（防止拒绝后再通知）
        if not any(a.status == AuditStatus.PENDING for a in refund.audit_logs):
            return {"success": False, "message": "审核任务已处理，跳过通知"}
        order = refund.order
        logger.info("[AdminNotify 模拟] 新退款审核任务：%s（¥%s，订单 %s）",
                    refund_no, refund.refund_amount, order.order_no)
        publish_event("audit.pending", {
            "refund_no": refund_no,
            "order_no": order.order_no,
            "amount": str(refund.refund_amount),
            "reason": refund.reason,
        })
    return {"success": True, "simulated": True, "refund_no": refund_no}
