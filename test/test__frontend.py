"""M7：前端包冒烟 + 状态标签与后端枚举对齐（防 UI 渲染漏态）。"""
import importlib

from app.models import OrderStatus, RefundStatus
from app.frontend.labels import ORDER_STATUS_LABELS, REFUND_STATUS_LABELS


def test_frontend_modules_importable():
    # app 导入时会构建 Blocks（不 launch），顺带冒烟全部 UI 构造
    for name in ("app.frontend.labels", "app.frontend.login",
                 "app.frontend.user_chat", "app.frontend.admin_dashboard", "app.frontend.app"):
        assert importlib.import_module(name) is not None


def test_order_status_labels_cover_all():
    assert set(ORDER_STATUS_LABELS) == {s.value for s in OrderStatus}


def test_refund_status_labels_cover_all():
    assert set(REFUND_STATUS_LABELS) == {s.value for s in RefundStatus}
