"""M3：退款服务层单测 —— 穷举规则引擎每一个分支。

分支矩阵（对应 seed_orders 的 9 笔订单）：
    eligible           : shipped_recent / paid / threshold
    beyond_window      : shipped_old
    already_refunded   : refunded
    not_refundable     : pending_payment / closed
    pending_application: in_progress
    order_not_found    : 不存在的订单号 / lisi_order（越权）
金额分流：59 → 自动批准；1280 → 人工审核；100（=阈值）→ 自动批准。
"""
import re
from decimal import Decimal

from sqlmodel import select

from app.models import (
    AuditLog,
    AuditStatus,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
)
from app.services.refund_service import (
    RefundCheckCode,
    check_refund_eligibility,
    create_refund_application,
    query_refund_status,
)

REFUND_NO_RE = re.compile(r"^RF-\d{14}-[0-9A-F]{6}$")


class TestCheckRefundEligibility:
    def test_shipped_within_window_is_eligible(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["shipped_recent"].order_no, seed_users["zhangsan"].id
        )
        assert res.eligible is True
        assert res.code == RefundCheckCode.ELIGIBLE
        assert res.refund_amount == Decimal("59.00")
        assert res.order is not None and res.order.product_name == "蓝牙键盘"

    def test_paid_before_shipment_is_eligible(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["paid"].order_no, seed_users["zhangsan"].id
        )
        assert res.eligible is True
        assert res.code == RefundCheckCode.ELIGIBLE

    def test_shipped_beyond_window_rejected(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["shipped_old"].order_no, seed_users["zhangsan"].id
        )
        assert res.eligible is False
        assert res.code == RefundCheckCode.BEYOND_WINDOW
        assert res.order is not None          # 拒绝时仍返回订单摘要供展示
        assert res.refund_amount is None

    def test_already_refunded_rejected(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["refunded"].order_no, seed_users["zhangsan"].id
        )
        assert res.code == RefundCheckCode.ALREADY_REFUNDED

    def test_unpaid_rejected(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["pending_payment"].order_no, seed_users["zhangsan"].id
        )
        assert res.code == RefundCheckCode.NOT_REFUNDABLE_STATUS

    def test_in_progress_rejected(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["in_progress"].order_no, seed_users["zhangsan"].id
        )
        assert res.code == RefundCheckCode.PENDING_APPLICATION

    def test_closed_rejected(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, seed_orders["closed"].order_no, seed_users["zhangsan"].id
        )
        assert res.code == RefundCheckCode.NOT_REFUNDABLE_STATUS

    def test_order_not_found(self, db_session, seed_users, seed_orders):
        res = check_refund_eligibility(
            db_session, "T-NOPE-404", seed_users["zhangsan"].id
        )
        assert res.code == RefundCheckCode.ORDER_NOT_FOUND
        assert res.order is None

    def test_other_users_order_is_hidden(self, db_session, seed_users, seed_orders):
        # 越权查询与他人订单：与"不存在"返回同一文案，防止订单号枚举
        res_other = check_refund_eligibility(
            db_session, seed_orders["lisi_order"].order_no, seed_users["zhangsan"].id
        )
        res_missing = check_refund_eligibility(
            db_session, "T-NOPE-404", seed_users["zhangsan"].id
        )
        assert res_other.code == RefundCheckCode.ORDER_NOT_FOUND
        assert res_other.reason == res_missing.reason


class TestCreateRefundApplication:
    def test_small_amount_auto_approved(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        order_no = seed_orders["shipped_recent"].order_no
        res = create_refund_application(db_session, order_no, uid, "质量不佳")

        assert res.success is True
        assert res.auto_approved is True and res.needs_manual_review is False
        assert res.status == RefundStatus.AUTO_APPROVED
        assert REFUND_NO_RE.match(res.refund_no)

        refund = db_session.exec(
            select(Refund).where(Refund.refund_no == res.refund_no)
        ).one()
        assert refund.refund_amount == Decimal("59.00")
        assert refund.reason == "质量不佳"
        assert refund.user_id == uid

        order = db_session.exec(select(Order).where(Order.order_no == order_no)).one()
        assert order.status == OrderStatus.REFUND_REQUESTED

        # 自动批准：不产生人工审核任务
        assert db_session.exec(select(AuditLog)).all() == []

    def test_large_amount_requires_manual_review(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        order_no = seed_orders["paid"].order_no  # 1280 元、未发货、可退
        res = create_refund_application(db_session, order_no, uid, "不想要了")

        assert res.success is True
        assert res.needs_manual_review is True and res.auto_approved is False
        assert res.status == RefundStatus.PENDING

        refund = db_session.exec(
            select(Refund).where(Refund.refund_no == res.refund_no)
        ).one()
        audits = db_session.exec(select(AuditLog)).all()
        assert len(audits) == 1
        assert audits[0].status == AuditStatus.PENDING
        assert audits[0].refund_id == refund.id

        order = db_session.exec(select(Order).where(Order.order_no == order_no)).one()
        assert order.status == OrderStatus.REFUND_REQUESTED

    def test_amount_equal_threshold_auto_approved(self, db_session, seed_users, seed_orders):
        res = create_refund_application(
            db_session, seed_orders["threshold"].order_no, seed_users["zhangsan"].id, "x"
        )
        assert res.auto_approved is True  # ≤ 阈值（含等于）

    def test_ineligible_creates_nothing(self, db_session, seed_users, seed_orders):
        order_no = seed_orders["shipped_old"].order_no
        res = create_refund_application(
            db_session, order_no, seed_users["zhangsan"].id, "超期也想试"
        )
        assert res.success is False
        assert res.refund_no is None
        assert db_session.exec(select(Refund)).all() == []     # 无退款落库
        order = db_session.exec(select(Order).where(Order.order_no == order_no)).one()
        assert order.status == OrderStatus.SHIPPED              # 订单状态未被篡改

    def test_duplicate_application_blocked(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        order_no = seed_orders["shipped_recent"].order_no
        first = create_refund_application(db_session, order_no, uid, "第一次")
        second = create_refund_application(db_session, order_no, uid, "第二次")

        assert first.success is True
        assert second.success is False
        assert "正在处理" in second.message
        assert len(db_session.exec(select(Refund)).all()) == 1  # 只有一笔

    def test_blank_reason_gets_default(self, db_session, seed_users, seed_orders):
        res = create_refund_application(
            db_session, seed_orders["shipped_recent"].order_no,
            seed_users["zhangsan"].id, "   ",
        )
        refund = db_session.exec(
            select(Refund).where(Refund.refund_no == res.refund_no)
        ).one()
        assert refund.reason == "未填写原因"


class TestQueryRefundStatus:
    def test_query_by_refund_no(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        created = create_refund_application(
            db_session, seed_orders["shipped_recent"].order_no, uid, "质量不佳"
        )
        info = query_refund_status(db_session, uid, refund_no=created.refund_no)

        assert info is not None
        assert info.status == RefundStatus.AUTO_APPROVED
        assert info.order_no == seed_orders["shipped_recent"].order_no
        assert info.product_name == "蓝牙键盘"
        assert info.amount == Decimal("59.00")
        assert info.processed_at is None

    def test_query_by_order_no_returns_latest(self, db_session, seed_users, seed_orders):
        uid = seed_users["zhangsan"].id
        order_no = seed_orders["shipped_recent"].order_no
        created = create_refund_application(db_session, order_no, uid, "质量不佳")
        info = query_refund_status(db_session, uid, order_no=order_no)
        assert info is not None and info.refund_no == created.refund_no

    def test_query_missing_returns_none(self, db_session, seed_users, seed_orders):
        assert query_refund_status(
            db_session, seed_users["zhangsan"].id, refund_no="RF-20990101000000-000000"
        ) is None

    def test_other_users_refund_hidden(self, db_session, seed_users, seed_orders):
        created = create_refund_application(
            db_session, seed_orders["shipped_recent"].order_no,
            seed_users["zhangsan"].id, "质量不佳",
        )
        assert query_refund_status(
            db_session, seed_users["lisi"].id, refund_no=created.refund_no
        ) is None
