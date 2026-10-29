"""M5：WebSocket 端点。"""
import pytest
from starlette.testclient import WebSocketDisconnect

from app.core.security import create_access_token


class TestWebSocket:
    def test_invalid_token_rejected(self, client, seed_users):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/ws/s1?token=bad-token"):
                pass

    def test_missing_token_rejected(self, client, seed_users):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/ws/s1"):
                pass

    def test_connect_welcome(self, client, seed_users):
        token = create_access_token("zhangsan")
        with client.websocket_connect(f"/api/v1/ws/s2?token={token}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["role"] == "customer"
            assert msg["session_id"] == "s2"

    def test_admin_role_recognized(self, client, seed_users):
        token = create_access_token("admin")
        with client.websocket_connect(f"/api/v1/ws/s3?token={token}") as ws:
            assert ws.receive_json()["role"] == "admin"
