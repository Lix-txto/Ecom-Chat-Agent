"""M5：聊天 API（离线确定性路径）。"""
import re
from sqlmodel import select

from app.models import MessageCard, Order, OrderStatus, Refund, RefundStatus

REFUND_NO_RE = re.compile(r"^RF-\d{14}-[0-9A-F]{6}$")


def _h(client, username="zhangsan"):
    from test.test_api_auth import _login
    token = _login(client, username, "test-password-123").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestChat:
    def test_general_chat(self, client, seed_users):
        r = client.post("/api/v1/chat", json={"session_id": "c1", "message": "你好"},
                        headers=_h(client))
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "general_chat"
        assert "智能客服" in body["reply"]
        assert body["needs_audit"] is False

    def test_refund_auto_approved(self, client, db_session, seed_users, seed_orders):
        r = client.post(
            "/api/v1/chat",
            json={"session_id": "c2", "message": "帮我退掉 T-SHIP-RECENT，质量有问题"},
            headers=_h(client),
        )
        body = r.json()
        assert body["intent"] == "refund_request"
        assert body["needs_audit"] is False
        assert REFUND_NO_RE.match(body["refund_no"])

        db_session.expire_all()
        refund = db_session.exec(select(Refund)).one()
        assert refund.status == RefundStatus.AUTO_APPROVED
        order = db_session.exec(select(Order).where(Order.order_no == "T-SHIP-RECENT")).one()
        assert order.status == OrderStatus.REFUND_REQUESTED

    def test_refund_manual_review(self, client, seed_users, seed_orders):
        r = client.post(
            "/api/v1/chat",
            json={"session_id": "c3", "message": "T-PAID 不想要了，帮我退款"},
            headers=_h(client),
        )
        assert r.json()["needs_audit"] is True

    def test_order_query(self, client, seed_users, seed_orders):
        r = client.post(
            "/api/v1/chat",
            json={"session_id": "c4", "message": "T-SHIP-RECENT 到哪了"},
            headers=_h(client),
        )
        body = r.json()
        assert body["intent"] == "order_query"
        assert "蓝牙键盘" in body["reply"]

    def test_policy_qa(self, client, seed_users, seed_knowledge):
        r = client.post(
            "/api/v1/chat",
            json={"session_id": "c5", "message": "退货政策是什么"},
            headers=_h(client),
        )
        assert "退货政策" in r.json()["reply"]

    def test_unauthorized_403(self, client, seed_users):
        r = client.post("/api/v1/chat", json={"session_id": "x", "message": "hi"})
        assert r.status_code == 403

    def test_message_validation(self, client, seed_users):
        r = client.post("/api/v1/chat", json={"session_id": "x", "message": ""},
                        headers=_h(client))
        assert r.status_code == 422

    def test_history_persisted(self, client, db_session, seed_users):
        client.post("/api/v1/chat", json={"session_id": "h1", "message": "你好"},
                    headers=_h(client))
        r = client.get("/api/v1/chat/history/h1", headers=_h(client))
        items = r.json()
        assert len(items) == 2
        assert items[0]["role"] == "user"
        assert items[1]["role"] == "assistant"

    def test_history_isolated_between_users(self, client, seed_users):
        client.post("/api/v1/chat", json={"session_id": "h2", "message": "你好"},
                    headers=_h(client, "zhangsan"))
        r = client.get("/api/v1/chat/history/h2", headers=_h(client, "lisi"))
        assert r.json() == []  # 他人会话历史不可见
