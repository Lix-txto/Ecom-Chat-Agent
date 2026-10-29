"""M6：Celery 任务体、派发器、事件路由、节点接线。

策略：任务体直接当普通函数调用（决策③），全程不依赖 broker。
conftest 已设 CELERY_ENABLED=false / PAYMENT_SIMULATION_SECONDS=0。
"""
from types import SimpleNamespace

from sqlmodel import select

from app.graph.nodes import audit_check_node
from app.models import AuditLog, AuditStatus, Order, OrderStatus, Refund, RefundStatus
from app.services.refund_service import create_refund_application
from app.tasks.dispatcher import dispatch_refund_payment
from app.tasks.refund_tasks import (
    notify_admins_new_audit,
    process_refund_payment,
    send_refund_sms,
)
from app.websocket import events


class TestProcessRefundPayment:
    def test_auto_approved_flows_to_refunded(self, db_session, seed_users, seed_orders):
        res = create_refund_application(
            db_session, "T-SHIP-RECENT", seed_users["zhangsan"].id, "质量不佳"
        )
        out = process_refund_payment(res.refund_no)

        assert out["success"] is True
        db_session.expire_all()
        refund = db_session.exec(select(Refund)).one()
        assert refund.status == RefundStatus.REFUNDED
        assert refund.processed_at is not None
        order = db_session.exec(select(Order).where(Order.order_no == "T-SHIP-RECENT")).one()
        assert order.status == OrderStatus.REFUNDED

    def test_idempotent_second_run_skipped(self, db_session, seed_users, seed_orders):
        res = create_refund_application(
            db_session, "T-SHIP-RECENT", seed_users["zhangsan"].id, "x"
        )
        assert process_refund_payment(res.refund_no)["success"] is True
        db_session.expire_all()
        first_processed_at = db_session.exec(select(Refund)).one().processed_at

        second = process_refund_payment(res.refund_no)   # 重复执行
        assert second["success"] is False
        db_session.expire_all()
        refund = db_session.exec(select(Refund)).one()
        assert refund.status == RefundStatus.REFUNDED
        assert refund.processed_at == first_processed_at  # 无二次副作用

    def test_refuses_pending_manual_review(self, db_session, seed_users, seed_orders):
        res = create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "x")
        assert res.needs_manual_review is True
        out = process_refund_payment(res.refund_no)
        assert out["success"] is False and "待人工审核" in out["message"]
        db_session.expire_all()
        assert db_session.exec(select(Refund)).one().status == RefundStatus.PENDING

    def test_refuses_rejected(self, db_session, seed_users, seed_orders):
        res = create_refund_application(
            db_session, "T-SHIP-RECENT", seed_users["zhangsan"].id, "x"
        )
        refund = db_session.exec(select(Refund)).one()
        refund.status = RefundStatus.REJECTED
        db_session.add(refund)
        db_session.commit()

        out = process_refund_payment(res.refund_no)
        assert out["success"] is False and "拒绝" in out["message"]

    def test_unknown_refund_no(self, db_session, seed_users, seed_orders):
        out = process_refund_payment("RF-20990101000000-000000")
        assert out["success"] is False and "不存在" in out["message"]


class TestNotificationTasks:
    def test_send_refund_sms_simulated(self, db_session, seed_users, seed_orders):
        out = send_refund_sms(seed_users["zhangsan"].id, "RF-20261029120000-ABC123", True)
        assert out["success"] is True and out["simulated"] is True

    def test_notify_admins_publishes_for_pending(self, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "不想要了")
        out = notify_admins_new_audit(
            db_session.exec(select(Refund)).one().refund_no
        )
        assert out["success"] is True

    def test_notify_admins_skips_when_resolved(self, db_session, seed_users, seed_orders):
        create_refund_application(db_session, "T-PAID", seed_users["zhangsan"].id, "x")
        refund = db_session.exec(select(Refund)).one()
        audit = db_session.exec(select(AuditLog)).one()
        audit.status = AuditStatus.RESOLVED   # 已处理 → 不应再通知
        db_session.add(audit)
        db_session.commit()
        assert notify_admins_new_audit(refund.refund_no)["success"] is False


class TestDispatcher:
    def test_disabled_noop(self, db_session, seed_users):
        # conftest 默认 CELERY_ENABLED=false：不碰 broker，返回 False
        assert dispatch_refund_payment("RF-20261029120000-ABC123") is False

    def test_enabled_calls_delay(self, monkeypatch):
        calls = []
        monkeypatch.setattr("app.tasks.dispatcher.settings.CELERY_ENABLED", True)
        monkeypatch.setattr(
            "app.tasks.dispatcher.process_refund_payment",
            SimpleNamespace(delay=lambda *a: calls.append(a)),
        )
        assert dispatch_refund_payment("RF-X") is True
        assert calls == [("RF-X",)]

    def test_broker_failure_graceful(self, monkeypatch):
        def boom(*a):
            raise RuntimeError("broker down")
        monkeypatch.setattr("app.tasks.dispatcher.settings.CELERY_ENABLED", True)
        monkeypatch.setattr(
            "app.tasks.dispatcher.process_refund_payment",
            SimpleNamespace(delay=boom),
        )
        assert dispatch_refund_payment("RF-X") is False  # 不抛异常


class TestEventRouting:
    async def _collect(self, monkeypatch, event):
        sent = []
        async def fake_user(uid, payload): sent.append(("user", uid, payload))
        async def fake_admins(payload): sent.append(("admins", payload))
        monkeypatch.setattr(events.manager, "send_to_user", fake_user)
        monkeypatch.setattr(events.manager, "broadcast_admins", fake_admins)
        await events.handle_event(event)
        return sent

    def test_refund_completed_routed_to_user(self, monkeypatch):
        import asyncio
        sent = asyncio.run(self._collect(monkeypatch, {
            "type": "refund.completed",
            "data": {"user_id": 7, "refund_no": "RF-X", "amount": "59.00"},
        }))
        assert sent == [("user", 7, {"type": "refund.completed", "user_id": 7,
                                     "refund_no": "RF-X", "amount": "59.00"})]

    def test_audit_pending_routed_to_admins(self, monkeypatch):
        import asyncio
        sent = asyncio.run(self._collect(monkeypatch, {
            "type": "audit.pending",
            "data": {"refund_no": "RF-X", "amount": "1280.00"},
        }))
        assert sent == [("admins", {"type": "audit.pending",
                                    "refund_no": "RF-X", "amount": "1280.00"})]

    def test_unknown_type_ignored(self, monkeypatch):
        import asyncio
        sent = asyncio.run(self._collect(monkeypatch, {"type": "nonsense", "data": {}}))
        assert sent == []


class TestNodeWiring:
    def test_auto_approved_dispatches_payment(self, monkeypatch):
        calls = []
        monkeypatch.setattr("app.graph.nodes.dispatch_refund_payment",
                            lambda refund_no: calls.append(("pay", refund_no)))
        monkeypatch.setattr("app.graph.nodes.dispatch_admin_notification",
                            lambda refund_no: calls.append(("admin", refund_no)))
        upd = audit_check_node({"refund_application": {
            "success": True, "auto_approved": True,
            "needs_manual_review": False, "refund_no": "RF-AUTO",
        }})
        assert upd["needs_audit"] is False
        assert calls == [("pay", "RF-AUTO")]

    def test_manual_review_dispatches_admin_notify(self, monkeypatch):
        calls = []
        monkeypatch.setattr("app.graph.nodes.dispatch_refund_payment",
                            lambda refund_no: calls.append(("pay", refund_no)))
        monkeypatch.setattr("app.graph.nodes.dispatch_admin_notification",
                            lambda refund_no: calls.append(("admin", refund_no)))
        audit_check_node({"refund_application": {
            "success": True, "auto_approved": False,
            "needs_manual_review": True, "refund_no": "RF-MANUAL",
        }})
        assert calls == [("admin", "RF-MANUAL")]   # 未批准前绝不派发支付
