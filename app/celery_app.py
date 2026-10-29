"""Celery 应用实例。

- broker/backend 复用 config 的回落逻辑（未单独配置时都走 REDIS_URL）
- include 在 worker 启动时注册任务模块
- 早 ack（默认）：失败不重投 —— 支付任务靠"状态机防护 + 幂等"保证安全，
  而不是依赖重复投递（重复投递对支付场景反而危险）
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "abot",
    broker=settings.celery_broker,
    backend=settings.celery_result_backend,
    include=["app.tasks.refund_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,               # 任务可见 STARTED 状态，便于排查
    worker_prefetch_multiplier=1,          # 公平分发，避免单 worker 囤积任务
    broker_connection_retry_on_startup=True,
)
