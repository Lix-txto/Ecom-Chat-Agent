"""M4a：工具层测试 —— 通过 LangChain tool.invoke 全链路验证。

复用 M3 的 db_session / seed_users / seed_orders 夹具：
工具内部自建会话读测试库（conftest 已把 POSTGRES_DB 指向 knowledge_base_test），
夹具 commit 过的种子数据对工具可见 —— 这本身验证了"会话不入 state、
每次调用独立开库"的设计。
"""
import json
import re
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlmodel import select

from app.graph.tools import (
    check_refund_eligibility,
    extract_order_no,
    extract_refund_no,
    query_refund_status,
    submit_refund_application,
)
from app.models import AuditLog, Order, OrderStatus, Refund

REFUND_NO_RE = re.compile(r"^RF-\d{14}-[0-9A-F]{6}$")


class TestToolRegistration:
    def test_tool_metadata(self):
        assert check_refund_eligibility.name == "check_refund_eligibility"
        assert submit_refund_application.name == "submit_refund_application"
        assert query_refund_status.name == "query_refund_status"
        assert "退款资格" in check_refund_eligibility.description
        assert "退款申请" in submit_refund_application.description


class TestCheckRefundEligibilityTool:
    def test_eligible_returns_json_safe_dict(self, db_session, seed_users, seed_orders):
        out = check_refund_eligibility.invoke({
            "order_no": seed_orders["shipped_recent"].order_no,
            "user_id": seed_users["zhangsan"].id,
        })
        assert isinstance(out, dict)
        json.dumps(out)  # 不抛异常 = JSON 安全（Checkpointer / JSONB 依赖此性质）
        assert out["eligible"] is True
        assert out["code"] == "eligible"
        assert Decimal(str(out["refund_amount"])) == Decimal("59.00")
        assert out["order"]["order_no"] == "T-SHIP-RECENT"
        assert out["reason"]

    def test_beyond_window(self, db_session, seed_users, seed_orders):
        out = check_refund_eligibility.invoke({
            "order_no": seed_orders["shipped_old"].order_no,
            "user_id": seed_users["zhangsan"].id,
        })
        assert out["eligible"] is False
        assert out["code"] == "beyond_window"

    def test_order_not_found(self, db_session, seed_users, seed_orders):
        out = check_refund_eligibility.invoke({
            "order_no": "T-NOPE-404", "user_id": seed_users["zhangsan"].id,
        })
        assert out["code"] == "order_not_found"
        assert out["order"] is None

    def test_other_users_order_hidden(self, db_session, seed_users, seed_orders):
        out = check_refund_eligibility.invoke({
            "order_no": seed_orders["lisi_order"].order_no,
            "user_id": seed_users["zhangsan"].id,
        })
        assert out["code"] == "order_not_found"

    def test_missing_user_id_rejected(self, db_session, seed_users, seed_orders):
        # 工具 schema 强制校验参数 —— user_id 缺失直接被 pydantic 拦截
        with pytest.raises(ValidationError):
            check_refund_eligibility.invoke({"order_no": "T-SHIP-RECENT"})


class TestSubmitRefundApplicationTool:
    def test_auto_approved(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        out = submit_refund_application.invoke({
            "order_no": seed_orders["shipped_recent"].order_no,
            "user_id": uid, "reason": "质量不佳",
        })
        assert out["success"] is True
        assert out["auto_approved"] is True
        assert out["needs_manual_review"] is False
        assert out["status"] == "auto_approved"
        assert REFUND_NO_RE.match(out["refund_no"])

        db_session.expire_all()  # 工具在独立会话提交过，强制刷新本会话视图
        assert db_session.exec(select(AuditLog)).all() == []
        order = db_session.exec(
            select(Order).where(Order.order_no == seed_orders["shipped_recent"].order_no)
        ).one()
        assert order.status == OrderStatus.REFUND_REQUESTED

    def test_manual_review(self, db_session, seed_users, seed_orders):
        out = submit_refund_application.invoke({
            "order_no": seed_orders["paid"].order_no,  # 1280 元，超过阈值
            "user_id": seed_users["zhangsan"].id, "reason": "不想要了",
        })
        assert out["success"] is True
        assert out["needs_manual_review"] is True
        assert out["auto_approved"] is False
        assert out["status"] == "pending"

        db_session.expire_all()
        assert len(db_session.exec(select(AuditLog)).all()) == 1

    def test_ineligible_creates_nothing(self, db_session, seed_users, seed_orders):
        out = submit_refund_application.invoke({
            "order_no": seed_orders["shipped_old"].order_no,
            "user_id": seed_users["zhangsan"].id, "reason": "超期也想试",
        })
        assert out["success"] is False
        assert db_session.exec(select(Refund)).all() == []


class TestQueryRefundStatusTool:
    def test_by_refund_no(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        created = submit_refund_application.invoke({
            "order_no": seed_orders["shipped_recent"].order_no,
            "user_id": uid, "reason": "质量不佳",
        })
        out = query_refund_status.invoke({"user_id": uid, "refund_no": created["refund_no"]})
        assert out["found"] is True
        assert out["status"] == "auto_approved"
        assert out["order_no"] == "T-SHIP-RECENT"
        assert out["reason"] == "质量不佳"

    def test_by_order_no(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        created = submit_refund_application.invoke({
            "order_no": seed_orders["shipped_recent"].order_no,
            "user_id": uid, "reason": "质量不佳",
        })
        out = query_refund_status.invoke({"user_id": uid, "order_no": "T-SHIP-RECENT"})
        assert out["found"] is True
        assert out["refund_no"] == created["refund_no"]

    def test_not_found(self, db_session, seed_users, seed_orders):
        out = query_refund_status.invoke({
            "user_id": seed_users["zhangsan"].id,
            "refund_no": "RF-20990101000000-000000",
        })
        assert out["found"] is False

    def test_other_users_refund_hidden(self, db_session, seed_users, seed_orders):
        created = submit_refund_application.invoke({
            "order_no": seed_orders["shipped_recent"].order_no,
            "user_id": seed_users["zhangsan"].id, "reason": "质量不佳",
        })
        out = query_refund_status.invoke({
            "user_id": seed_users["lisi"].id, "refund_no": created["refund_no"],
        })
        assert out["found"] is False


class TestEntityExtraction:
    def test_extract_dev_format(self):
        assert extract_order_no("我想退 ORD-20261025-0001 这个订单") == "ORD-20261025-0001"

    def test_extract_test_format(self):
        assert extract_order_no("T-SHIP-RECENT 还能退吗") == "T-SHIP-RECENT"

    def test_ignores_refund_no(self):
        assert extract_order_no("我的退款单 RF-20261028120000-ABC123 到哪了") is None

    def test_prefers_order_over_refund(self):
        text = "查一下 ORD-20261025-0001 的退款 RF-20261028120000-ABC123"
        assert extract_order_no(text) == "ORD-20261025-0001"

    def test_no_match(self):
        assert extract_order_no("你好，请问退货政策是什么") is None
        assert extract_order_no("") is None

    def test_extract_refund_no(self):
        text = "退款单号是 RF-20261028120000-ABC123"
        assert extract_refund_no(text) == "RF-20261028120000-ABC123"
        assert extract_order_no(text) is None

    def test_extract_refund_no_none(self):
        assert extract_refund_no("没有单号") is None
