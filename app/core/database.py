from collections.abc import Generator

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

# Alembic / seed / Celery 用
sync_engine = create_engine(
    settings.database_url_sync, echo=False, pool_pre_ping=True
)
# FastAPI 运行时用（M2 提供 AsyncSession 依赖）
async_engine = create_async_engine(settings.database_url_async, pool_pre_ping=True)


def get_sync_session() -> Generator[Session, None, None]:
    with Session(sync_engine) as session:
        yield session
