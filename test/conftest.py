"""pytest 全局配置：在任何 app 模块被导入前固定测试环境变量。

注意：进程环境变量优先级高于 .env 文件，因此这里的 JWT_SECRET_KEY
会覆盖 .env 的真实值 —— 保证测试可重复、不依赖用户本地配置。
服务进程（uvicorn）不受影响，两者互不干扰。
"""
"""
隔离策略（本轮核心设计）：
1. 在导入任何 app 模块【之前】注入测试环境变量 —— 进程环境变量优先级高于 .env，
   Settings 因此指向独立的测试库 knowledge_base_test，绝不触碰开发库。
   （不用 SQLite 内存库的原因：models 里的 pgvector Vector 与 JSONB 列
   只能在 PostgreSQL 上建表，SQLite 会直接报错。）
2. 会话级 fixture：自动创建测试库 + 建表（幂等，可重复运行，第二次起秒级）。
3. 函数级 fixture：每个测试前 TRUNCATE 全部表并重建演示数据；
   订单日期相对"当前时刻"动态生成，测试不会随时间流逝而腐烂。
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote_plus

# ==== 必须在导入 app 之前设置（本文件内 import 顺序即执行顺序） ====
os.environ["JWT_SECRET_KEY"] = "pytest-secret-key-not-for-production"
os.environ["POSTGRES_DB"] = "knowledge_base_test"        # 强制指向测试库
os.environ.setdefault("POSTGRES_PASSWORD", "admin")     # 其余连接参数允许 .env 提供真实值
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlmodel import SQLModel, Session  # noqa: E402

import app.models  # noqa: E402,F401  注册全部表到 SQLModel.metadata
from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Order, OrderStatus, User, UserRole  # noqa: E402

TEST_DB_NAME = settings.POSTGRES_DB  # 即 knowledge_base_test

# bcrypt 很慢（故意的）：整个测试进程只算一次，所有测试用户共用同一哈希
_HASHED_TEST_PW = hash_password("test-password-123")

_TRUNCATE_SQL = (
    "TRUNCATE TABLE audit_logs, refunds, orders, users, "
    "message_cards, knowledge_chunks RESTART IDENTITY CASCADE"
)


def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


@pytest.fixture(scope="session")
def _database():
    """会话级：确保测试库存在且 schema 就绪。"""
    admin_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:"
        f"{quote_plus(settings.POSTGRES_PASSWORD)}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/postgres"
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()

    from app.core.database import sync_engine  # 引擎按测试库配置创建

    with sync_engine.begin() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    SQLModel.metadata.create_all(sync_engine)  # checkfirst：幂等
    yield


@pytest.fixture()
def db_session(_database):
    """函数级：全新会话 + 清空所有表。"""
    from app.core.database import sync_engine

    with Session(sync_engine) as session:
        session.execute(text(_TRUNCATE_SQL))
        session.commit()
        yield session


@pytest.fixture()
def seed_users(db_session):
    zhangsan = User(
        username="zhangsan", email="zhangsan@test.local",
        hashed_password=_HASHED_TEST_PW, role=UserRole.CUSTOMER,
    )
    lisi = User(
        username="lisi", email="lisi@test.local",
        hashed_password=_HASHED_TEST_PW, role=UserRole.CUSTOMER,
    )
    db_session.add(zhangsan)
    db_session.add(lisi)
    db_session.commit()
    return {"zhangsan": zhangsan, "lisi": lisi}


@pytest.fixture()
def seed_orders(db_session, seed_users):
    """覆盖规则引擎全部分支的订单；日期动态生成保证测试不过期。"""
    zid = seed_users["zhangsan"].id
    lid = seed_users["lisi"].id

    spec = [
        # (key, 订单号, 商品, 数量, 金额, 状态, 下单距今天数)
        ("shipped_recent",  "T-SHIP-RECENT", "蓝牙键盘",     1, "59.00",   OrderStatus.SHIPPED, 3),
        ("shipped_old",     "T-SHIP-OLD",    "无线降噪耳机", 1, "299.00",  OrderStatus.SHIPPED, 15),
        ("paid",            "T-PAID",        "4K 显示器",    1, "1280.00", OrderStatus.PAID, 1),
        ("refunded",        "T-REFUNDED",    "机械键盘",     1, "329.00",  OrderStatus.REFUNDED, 40),
        ("pending_payment", "T-UNPAID",      "桌面音箱",     2, "216.00",  OrderStatus.PENDING_PAYMENT, 0),
        ("in_progress",     "T-INPROG",      "智能手环",     1, "199.00",  OrderStatus.REFUND_REQUESTED, 2),
        ("closed",          "T-CLOSED",      "旧款鼠标",     1, "45.00",   OrderStatus.CLOSED, 30),
        ("threshold",       "T-EXACT-100",   "充电宝",       1, "100.00",  OrderStatus.SHIPPED, 2),
        ("lisi_order",      "T-LISI-OWN",    "他人订单商品", 1, "88.00",   OrderStatus.SHIPPED, 3),
    ]
    orders: dict[str, Order] = {}
    for key, order_no, product, qty, amount, status, age in spec:
        owner = lid if key == "lisi_order" else zid
        order = Order(
            order_no=order_no, user_id=owner, product_name=product,
            quantity=qty, amount=Decimal(amount), status=status,
            created_at=days_ago(age), updated_at=days_ago(age),
        )
        db_session.add(order)
        orders[key] = order
    db_session.commit()
    return orders
