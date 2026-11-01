"""前端展示用的状态中文标签。

刻意与 app 包解耦（前端是纯 HTTP 客户端）。test_frontend.py 有对齐测试：
后端枚举新增成员时，本表必须同步补齐，否则测试红 —— 防 UI 渲染漏态。
"""

ORDER_STATUS_LABELS = {
    "pending_payment": "待支付",
    "paid": "已支付（待发货）",
    "shipped": "已发货",
    "completed": "已完成",
    "refund_requested": "退款处理中",
    "refunded": "已退款",
    "closed": "已关闭",
}

REFUND_STATUS_LABELS = {
    "pending": "待人工审核",
    "auto_approved": "已自动通过",
    "processing": "退款处理中",
    "refunded": "已退款",
    "rejected": "已拒绝",
}
