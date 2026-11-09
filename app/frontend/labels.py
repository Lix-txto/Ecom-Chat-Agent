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

_BADGE_LOGGED_OUT = "🔒 未登录"

# labels.py 顶部
import tempfile
from pathlib import Path

# labels.py 末尾（原样粘贴函数体）
def _emoji_avatar(emoji: str, bg: str) -> str:
    d = Path(tempfile.gettempdir()) / "Ecom-Chat-Agent_avatars"
    d.mkdir(exist_ok=True)
    p = d / f"{emoji}_{bg.strip('#')}.svg"
    p.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72">'
        f'<rect width="72" height="72" rx="36" fill="{bg}"/>'
        f'<text x="36" y="47" font-size="36" text-anchor="middle">{emoji}</text></svg>',
        encoding="utf-8",
    )
    return str(p)
