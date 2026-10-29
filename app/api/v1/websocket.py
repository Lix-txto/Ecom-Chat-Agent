"""WebSocket 端点：/api/v1/ws/{session_id}?token=<JWT>

浏览器 WS API 无法携带 Authorization 头 → token 走 query param（业界惯例）。
连接即验证：token 非法/用户不存在/已禁用 → close(1008)。
角色回查数据库（不信 token 内 claim）。
"""
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import async_session_factory
from app.core.security import decode_token
from app.models import User, UserRole
from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


async def _authenticate_ws(token: str) -> User | None:
    try:
        payload = decode_token(token)
    except Exception:
        return None
    async with async_session_factory() as session:
        user = (
            await session.exec(select(User).where(User.username == payload["sub"]))
        ).first()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/{session_id}")
async def ws_endpoint(
    ws: WebSocket, session_id: str, token: str = Query(default="")
):
    user = await _authenticate_ws(token)
    if user is None:
        await ws.close(code=1008)  # policy violation：认证失败
        return

    is_admin = user.role == UserRole.ADMIN
    manager.register(session_id, ws, user_id=user.id, is_admin=is_admin)
    await ws.accept()
    await ws.send_json({
        "type": "connected",
        "session_id": session_id,
        "role": user.role.value,
    })

    try:
        while True:
            # M5：客户端消息仅作心跳占位；M6 起可扩展双向指令
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.unregister(session_id, ws)
