"""事件路由：把 pub/sub 事件翻译成 WS 推送（策略层，transport 在 core.pubsub）。"""
import logging

from app.websocket.manager import manager

logger = logging.getLogger(__name__)


async def handle_event(event: dict) -> None:
    etype = event.get("type")
    data = event.get("data") or {}

    if etype == "refund.completed":
        try:
            user_id = int(data.get("user_id"))
        except (TypeError, ValueError):
            logger.warning("refund.completed 事件缺少合法 user_id: %s", data)
            return
        await manager.send_to_user(user_id, {"type": "refund.completed", **data})

    elif etype == "audit.pending":
        await manager.broadcast_admins({"type": "audit.pending", **data})

    else:
        logger.debug("忽略未知事件类型: %s", etype)
