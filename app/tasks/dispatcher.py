"""任务派发器：外层（graph 节点 / API 端点）与 Celery 的唯一通道。

三重职责：
1. CELERY_ENABLED 开关 —— false 时全部 no-op（测试/离线环境零 broker 依赖）
2. broker 故障优雅降级 —— 派发失败仅告警，不炸用户请求（支付可用管理员重试兜底）
3. 测试替换点 —— monkeypatch 本模块的名字即可拦截派发
"""
import logging

from app.core.config import settings
from app.tasks.refund_tasks import (
    notify_admins_new_audit,
    process_refund_payment,
    send_refund_sms,
)

logger = logging.getLogger(__name__)


def _send(task, *args) -> bool:
    if not settings.CELERY_ENABLED:
        return False
    try:
        task.delay(*args)
        return True
    except Exception:  # broker 宕机 / 连接超时等
        logger.warning("Celery 派发失败 task=%s args=%s",
                       getattr(task, "name", "unknown"), args)
        return False


def dispatch_refund_payment(refund_no: str) -> bool:
    return _send(process_refund_payment, refund_no)


def dispatch_refund_sms(user_id: int, refund_no: str, success: bool = True) -> bool:
    return _send(send_refund_sms, user_id, refund_no, success)


def dispatch_admin_notification(refund_no: str) -> bool:
    return _send(notify_admins_new_audit, refund_no)
