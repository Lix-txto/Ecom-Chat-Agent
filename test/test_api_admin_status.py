"""M5：管理员审核 + 状态轮询。"""
from sqlmodel import select

from app.models import AuditLog, AuditStatus, Order, OrderStatus, RefundStatus
from app.services.refund_service import create_refund_application
from test.test_api_auth import _login


def _admin_h(client):
    token = _login(client, "admin", "test-password-123").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_h(client):
    token = _login(client, "zhangsan", "test-password-123").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAdminAudits:
    def test_customer_forbidden(self, client, seed_users):
        r = client.get("/api/v1/admin/audits", headers=_user_h(client))
        assert r.status_code == 403

    def test_list_pending(self, client, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "不想要了")
        r = client.get("/api/v1/admin/audits", headers=_admin_h(client))
        tasks = r.json()
        assert len(tasks) == 1
        assert tasks[0]["refund_amount"] == "1280.00"
        assert tasks[0]["username"] == "zhangsan"
        assert tasks[0]["status"] == "pending"

    def test_approve(self, client, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "不想要了")
        audit_id = db_session.exec(select(AuditLog)).one().id

        r = client.post(f"/api/v1/admin/audits/{audit_id}/decision",
                        json={"action": "approve"}, headers=_admin_h(client))
        assert r.status_code == 200
        assert r.json()["action"] == "approve"

        db_session.expire_all()
        audit = db_session.exec(select(AuditLog)).one()
        assert audit.status == AuditStatus.RESOLVED
        assert audit.action.value == "approve"
        assert audit.admin_id == seed_users["admin"].id
        assert audit.resolved_at is not None
        refund = audit.refund
        assert refund.status == RefundStatus.AUTO_APPROVED
        assert refund.processed_at is not None

    def test_reject_restores_order(self, client, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "不想要了")
        audit_id = db_session.exec(select(AuditLog)).one().id

        r = client.post(f"/api/v1/admin/audits/{audit_id}/decision",
                        json={"action": "reject", "comment": "凭证不足"},
                        headers=_admin_h(client))
        assert r.status_code == 200

        db_session.expire_all()
        refund = db_session.exec(select(AuditLog)).one().refund
        assert refund.status == RefundStatus.REJECTED
        order = db_session.exec(select(Order).where(Order.order_no == "T-PAID")).one()
        assert order.status == OrderStatus.SHIPPED  # 简化恢复

    def test_double_decision_conflict(self, client, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "x")
        audit_id = db_session.exec(select(AuditLog)).one().id
        url = f"/api/v1/admin/audits/{audit_id}/decision"
        assert client.post(url, json={"action": "approve"}, headers=_admin_h(client)).status_code == 200
        assert client.post(url, json={"action": "reject"}, headers=_admin_h(client)).status_code == 409

    def test_decision_unknown_404(self, client, seed_users):
        r = client.post("/api/v1/admin/audits/99999/decision",
                        json={"action": "approve"}, headers=_admin_h(client))
        assert r.status_code == 404


class TestStatus:
    def test_found(self, client, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-SHIP-RECENT", seed_users["zhangsan"].id, "x")
        r = client.get("/api/v1/status/refunds/T-SHIP-RECENT", headers=_user_h(client))
        assert r.status_code == 200
        assert r.json()["status"] == "auto_approved"

    def test_404_when_no_refund(self, client, seed_users, seed_orders):
        r = client.get("/api/v1/status/refunds/T-SHIP-OLD", headers=_user_h(client))
        assert r.status_code == 404

    def test_requires_auth(self, client, seed_users):
        assert client.get("/api/v1/status/refunds/T-SHIP-RECENT").status_code == 403
