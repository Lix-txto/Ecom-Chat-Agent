"""初始化演示数据：管理员 + 普通用户 + 覆盖各退款场景的订单。

运行：uv run python -m scripts.seed_data
重置：uv run alembic downgrade base && uv run alembic upgrade head
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlmodel import Session, select
from app.core.database import sync_engine
from app.core.security import hash_password
from app.models import Order, OrderStatus, User, UserRole

def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


SEED_USERS = [
    ("admin", "admin@example.com", "admin123", UserRole.ADMIN),
    ("zhangsan", "zhangsan@example.com", "zhangsan123", UserRole.CUSTOMER),
]

# 订单特意覆盖退款规则的各分支（M4 会用到）：
#   可退：已发货且 7 天内 / 已支付未发货
#   不可退：超过退货期 / 已退款 / 未支付
SEED_ORDERS = [
    ("ORD-20261025-0001", "无线降噪耳机", 1, "299.00", OrderStatus.SHIPPED, 3),
    ("ORD-20261025-0002", "蓝牙键盘", 1, "59.00", OrderStatus.SHIPPED, 15),
    ("ORD-20261027-0001", "4K 显示器", 1, "1280.00", OrderStatus.PAID, 1),
    ("ORD-20261020-0001", "机械键盘", 1, "329.00", OrderStatus.REFUNDED, 38),
    ("ORD-20261027-0002", "桌面音箱", 2, "216.00", OrderStatus.PENDING_PAYMENT, 0),
]


def main() -> None:
    with Session(sync_engine) as session:
        if session.exec(select(User).where(User.username == "admin")).first():
            print("种子数据已存在，跳过。（如需重跑：alembic downgrade base && alembic upgrade head）")
            return

        users: dict[str, User] = {}
        for username, email, raw_pwd, role in SEED_USERS:
            u = User(
                username=username,
                email=email,
                hashed_password=hash_password(raw_pwd),
                role=role,
            )
            session.add(u)
            users[username] = u
        session.flush()  # 先拿到 user.id

        zhangsan = users["zhangsan"]
        for order_no, product, qty, amount, status, age in SEED_ORDERS:
            session.add(
                Order(
                    order_no=order_no,
                    user_id=zhangsan.id,
                    product_name=product,
                    quantity=qty,
                    amount=Decimal(amount),
                    status=status,
                    created_at=days_ago(age),
                )
            )

        session.commit()

        # 自检：密码哈希可验证
        admin = session.exec(select(User).where(User.username == "admin")).one()
        assert hash_password("admin123") == admin.hashed_password
        assert len(zhangsan.orders) == 5

        print(f"✅ Seed 完成：2 个用户（admin/admin123, zhangsan/zhangsan123），5 笔订单")


if __name__ == "__main__":
    main()
