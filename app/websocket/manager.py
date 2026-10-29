"""WebSocket 连接管理器（M5：单进程内存版）。

M6 桥接预告：Celery worker 与 API 是不同进程，无法直接调用本管理器。
届时 worker 通过 Redis PUBLISH 发布事件，API 进程在 lifespan 里起
监听任务转发到 broadcast_* —— 仅需扩展本文件与 main.lifespan。
"""
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, set[WebSocket]] = defaultdict(set)
        self._admin_sessions: set[str] = set()

    def register(self, session_id: str, ws: WebSocket, is_admin: bool = False) -> None:
        self._sessions[session_id].add(ws)
        if is_admin:
            self._admin_sessions.add(session_id)

    def unregister(self, session_id: str, ws: WebSocket) -> None:
        self._sessions[session_id].discard(ws)
        if not self._sessions.get(session_id):
            self._sessions.pop(session_id, None)
            self._admin_sessions.discard(session_id)

    async def send_to_session(self, session_id: str, payload: dict) -> None:
        for ws in list(self._sessions.get(session_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.unregister(session_id, ws)

    async def broadcast_admins(self, payload: dict) -> None:
        for sid in list(self._admin_sessions):
            await self.send_to_session(sid, payload)


manager = ConnectionManager()
