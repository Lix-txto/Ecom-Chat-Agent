"""Redis pub/sub 事件总线：worker 进程 ⇄ API 进程的事件桥。

- publish_event：同步（worker 任务内 / API 进程内均可调），失败仅告警
- listen_events：异步常驻协程（main.lifespan 启动），断线自动重连
消息格式：{"type": str, "data": {...}}，JSON 序列化。
"""
import asyncio
import json
import logging
from functools import lru_cache

import redis as redis_lib

from app.core.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "Ecom-Chat-Agent:events"
_RECONNECT_DELAY_SECONDS = 5


@lru_cache
def _sync_client() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def publish_event(event_type: str, data: dict) -> bool:
    """发布事件；任何失败（Redis 不可用等）降级为告警，不抛出。"""
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
    try:
        _sync_client().publish(CHANNEL, payload)
        return True
    except Exception as exc:
        logger.warning("事件发布失败（%s）: %s", event_type, exc)
        return False


async def listen_events(handler) -> None:
    """订阅事件并逐条交给 handler；取消安全，断线重连。"""
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        while True:
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        event = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await handler(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("事件监听断开，%ss 后重连: %s", _RECONNECT_DELAY_SECONDS, exc)
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
            finally:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
    finally:
        await client.aclose()
