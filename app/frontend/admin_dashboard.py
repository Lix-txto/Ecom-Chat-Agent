"""管理员审核视图：待审任务列表 + 批准/拒绝决策（决策后自动刷新列表）。"""
from types import SimpleNamespace

import gradio as gr
import requests

from .login import auth_headers

_EMPTY_AUTH = {"token": None, "role": None, "username": None}
_TABLE_HEADERS = ["审核ID", "退款单号", "订单号", "商品", "用户", "金额", "原因", "申请时间"]


def build_admin(api_base: str, auth: gr.State, login_ui: SimpleNamespace) -> SimpleNamespace:
    with gr.Group(visible=False) as view:
        welcome = gr.Markdown("")
        refresh_btn = gr.Button("🔄 刷新待审任务")
        audits = gr.DataFrame(headers=_TABLE_HEADERS, value=[], interactive=False, wrap=True)
        with gr.Row():
            audit_id = gr.Number(label="审核 ID", precision=0)
            action = gr.Radio(choices=["approve", "reject"], value="approve", label="决策")
        comment = gr.Textbox(label="备注（可选）", placeholder="例如：情况属实")
        decide_btn = gr.Button("提交决策", variant="primary")
        decide_msg = gr.Markdown("")
        logout_btn = gr.Button("退出登录")

    def _fetch(auth_val) -> list[list]:
        if (auth_val or {}).get("role") != "admin":
            return []
        try:
            resp = requests.get(f"{api_base}/admin/audits",
                                headers=auth_headers(auth_val), timeout=10)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        return [
            [t["audit_id"], t["refund_no"], t["order_no"], t["product_name"],
             t["username"], f"¥{t['refund_amount']}", t["reason"],
             t["requested_at"][:19].replace("T", " ")]
            for t in resp.json()
        ]

    refresh_btn.click(_fetch, auth, audits)

    def _decide(aid, act, cmt, auth_val):
        if (auth_val or {}).get("role") != "admin":
            return "需要管理员权限登录", []
        try:
            resp = requests.post(
                f"{api_base}/admin/audits/{int(aid)}/decision",
                json={"action": act, "comment": (cmt or None)},
                headers=auth_headers(auth_val), timeout=15,
            )
        except (requests.RequestException, TypeError, ValueError):
            return "网络异常或审核 ID 非法", _fetch(auth_val)
        if resp.status_code == 200:
            no = resp.json()["refund_no"]
            msg = f"✅ 已{'批准' if act == 'approve' else '拒绝'}退款 `{no}`，异步打款/通知已派发。"
        elif resp.status_code == 409:
            msg = "⚠️ 该任务已被处理（重复决策被拒绝）"
        elif resp.status_code == 404:
            msg = "审核任务不存在"
        elif resp.status_code == 401:
            msg = "登录已过期，请重新登录"
        else:
            msg = f"决策失败（{resp.status_code}）"
        return msg, _fetch(auth_val)  # 决策后自动刷新

    decide_btn.click(_decide, [audit_id, action, comment, auth], [decide_msg, audits])

    def _logout():
        return dict(_EMPTY_AUTH), gr.update(visible=True), gr.update(visible=False), ""

    logout_btn.click(_logout, None, [auth, login_ui.view, view, login_ui.login_msg])

    return SimpleNamespace(view=view, welcome=welcome, audits=audits)
