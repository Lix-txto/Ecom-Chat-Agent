from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, Relationship, SQLModel
from app.models.base import utc_now


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    email: str = Field(index=True, unique=True, max_length=120)
    hashed_password: str = Field(max_length=255)
    role: UserRole = Field(default=UserRole.CUSTOMER, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)

    # 字符串引用 Order，避免模块间导入（与原仓库做法一致）
    orders: list["Order"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"lazy": "selectin"}
    )
