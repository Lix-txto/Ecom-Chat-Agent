"""数据库引擎与会话管理。
 sync_engine / get_sync_session : Alembic、seed 脚本、Celery 任务用
 async_engine / get_session     : FastAPI 运行时用（每请求一个会话）
"""
from collections.abc import AsyncGenerator,Generator

from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.config import settings

# Alembic / seed / Celery 用
sync_engine = create_engine(
    settings.database_url_sync, echo=False, pool_pre_ping=True
)
# FastAPI 运行时用（M2 提供 AsyncSession 依赖）
async_engine = create_async_engine(
    settings.database_url_async,
    pool_pre_ping=True,
    poolclass=NullPool,   # 连接即用即弃：每次 checkout 都在当前循环新建
)

async_session_factory = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


def get_sync_session() -> Generator[Session, None, None]:
    """同步会话（Celery / 脚本用）。"""
    with Session(sync_engine) as session:
        yield session

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """异步会话（FastAPI 运行时用）。"""
    async with async_session_factory() as session:
        yield session
