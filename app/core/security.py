"""JWT 认证与授权：密码哈希、令牌签发/校验、FastAPI 用户依赖链。

依赖链设计：
    oauth2_scheme      (从请求头提取 Bearer token)
      -> decode_token  (校验签名 / 有效期)
      -> get_current_user (回查数据库，确认用户存在且活跃)
      -> get_current_admin (校验管理员角色)

安全决策：token 里的 role 仅供展示；鉴权时总是回查数据库取最新角色，
这样角色变更 / 封禁能即时生效，token 只承担"我是谁"的证明。
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models import User, UserRole

# ---------- 密码 ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode())


# ---------- JWT ----------

# tokenUrl 指向 M5 将实现的登录端点；在此之前 Swagger 的 Authorize 按钮不可用（属预期）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _credentials_exception(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(
    subject: str,
    role: str | None = None,
    expires_minutes: int | None = None,
) -> str:
    """签发 JWT。sub 存 username。时间统一使用 tz-aware UTC（M1 宪法）。"""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=(
            expires_minutes
            if expires_minutes is not None
            else settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": expire}
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """校验并解析 JWT；任何失败统一抛 401。"""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise _credentials_exception("Token 已过期") from None
    except jwt.InvalidTokenError:  # 签名错误/格式错误/sub 非法等统一入口
        raise _credentials_exception("无法校验的 Token") from None

    if not isinstance(payload.get("sub"), str):
        raise _credentials_exception("Token 缺少有效 subject")
    return payload


# ---------- FastAPI 依赖 ----------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """解析 Bearer token 并返回当前活跃用户。"""
    payload = decode_token(token)
    username = payload["sub"]

    user = (
        await session.exec(select(User).where(User.username == username))
    ).first()
    if user is None:
        raise _credentials_exception("用户不存在")
    if not user.is_active:
        raise _credentials_exception("用户已被禁用")
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员角色，否则 403。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要管理员权限",
        )
    return current_user
