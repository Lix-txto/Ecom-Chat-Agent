"""认证 API：登录签发 JWT + 当前用户信息。

bcrypt 校验较慢（故意的），放线程池避免阻塞事件循环。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.api.v1.schemas import TokenResponse
from app.core.database import get_session, sync_engine
from app.core.security import create_access_token, get_current_user, verify_password
from app.models import User, UserRole

router = APIRouter(tags=["auth"])


def _authenticate(username: str, password: str) -> User | None:
    """线程池内执行：独立同步会话查库 + bcrypt 校验。"""
    with Session(sync_engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user and verify_password(password, user.hashed_password):
            return user
    return None


@router.post("/auth/login", response_model=TokenResponse)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = await run_in_threadpool(_authenticate, form.username, form.password)
    # 用户不存在与密码错误统一文案，防用户名枚举
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.username, role=user.role.value)
    return TokenResponse(access_token=token, role=user.role.value)


@router.get("/auth/me")
async def me(current_user: User = Depends(get_current_user)):
    """M2 临时 /me 的正式归宿。"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role.value,
    }
