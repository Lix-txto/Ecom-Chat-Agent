"""Celery worker 启动入口。用法：uv run python celery_worker.py"""
from app.celery_app import celery_app

if __name__ == "__main__":
    celery_app.worker_main(argv=["worker", "--loglevel=info", "--concurrency=2"])
