"""用户聊天视图：REST /chat + 会话历史 + 退款进度查询。"""
import uuid
from types import SimpleNamespace

import gradio as gr
import requests

from .labels import REFUND_STATUS_LABELS
from .login import auth_headers

_EMPTY_AUTH = {"token": None, "role": None, "username": None}


def build_user_chat(api_base: str, auth: gr.State, login_ui: SimpleNamespace) -> SimpleNamespace:
    with gr.Group(visible=False) as view:
        welcome = gr.Markdown("")
        with gr.Row():
            session_id = gr.Textbox(
                label="会话 ID（可自定义，用于恢复历史会话）",
                value=f"web-{uuid.uuid4().hex[:8]}",
            )
            load_btn = gr.Button("🔄 加载该会话历史")
        chatbot = gr.Chatbot(label="智能客服", height=420)
        with gr.Row():
            msg = gr.Textbox(label="输入消息",
                             placeholder="例如：帮我退掉 ORD-xxxx，质量有问题", scale=5)
            send_btn = gr.Button("发送", variant="primary", scale=1)
        with gr.Accordion("退款进度查询", open=False):
            order_no = gr.Textbox(label="订单号", placeholder="ORD-20261025-0001")
            status_btn = gr.Button("查询退款状态")
            status_md = gr.Markdown("")
        logout_btn = gr.Button("退出登录")

    # ---- 发送消息 ----
    def _send(text, history, sid, auth_val):
        text = (text or "").strip()
        if not text:
            return history, ""
        history = history + [{"role": "user", "content": text}]
        if not (auth_val or {}).get("token"):
            return history + [{"role": "assistant", "content": "请先登录后再发送消息"}], ""
        try:
            resp = requests.post(
                f"{api_base}/chat",
                json={"session_id": sid, "message": text},
                headers=auth_headers(auth_val), timeout=60,
            )
        except requests.RequestException:
            return history + [{"role": "assistant", "content": "网络异常：无法连接后端服务"}], ""
        if resp.status_code == 401:
            return history + [{"role": "assistant", "content": "登录已过期，请重新登录"}], ""
        if resp.status_code != 200:
            return history + [{"role": "assistant", "content": f"请求失败（{resp.status_code}）"}], ""
        return history + [{"role": "assistant", "content": resp.json()["reply"]}], ""

    send_btn.click(_send, [msg, chatbot, session_id, auth], [chatbot, msg])
    msg.submit(_send, [msg, chatbot, session_id, auth], [chatbot, msg])

    # ---- 加载历史 ----
    def _load_history(sid, auth_val):
        if not (auth_val or {}).get("token"):
            return []
        try:
            resp = requests.get(f"{api_base}/chat/history/{sid}",
                                headers=auth_headers(auth_val), timeout=10)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        return [{"role": it["role"], "content": it["content"]} for it in resp.json()]

    load_btn.click(_load_history, [session_id, auth], [chatbot])

    # ---- 退款进度 ----
    def _check_status(order_no_val, auth_val):
        order_no_val = (order_no_val or "").strip()
        if not order_no_val:
            return "请输入订单号"
        if not (auth_val or {}).get("token"):
            return "请先登录"
        try:
            resp = requests.get(f"{api_base}/status/refunds/{order_no_val}",
                                headers=auth_headers(auth_val), timeout=10)
        except requests.RequestException:
            return "网络异常：无法连接后端服务"
        if resp.status_code == 404:
            return f"订单 `{order_no_val}` 暂无退款记录。"
        if resp.status_code == 401:
            return "登录已过期，请重新登录"
        if resp.status_code != 200:
            return f"查询失败（{resp.status_code}）"
        d = resp.json()
        label = REFUND_STATUS_LABELS.get(d["status"], d["status"])
        return (
            f"**订单** {d['order_no']} · **商品** {d['product_name']}\n\n"
            f"**退款单** `{d['refund_no']}` · **状态** {label} · **金额** ¥{d['amount']}\n\n"
            f"申请时间 {d['requested_at'][:19].replace('T', ' ')}"
        )

    status_btn.click(_check_status, [order_no, auth], [status_md])

    # ---- 退出登录 ----
    def _logout():
        return dict(_EMPTY_AUTH), gr.update(visible=True), gr.update(visible=False), ""

    logout_btn.click(_logout, None,
                     [auth, login_ui.view, view, login_ui.login_msg])

    return SimpleNamespace(view=view, welcome=welcome, chatbot=chatbot,
                           session_id=session_id, logout_btn=logout_btn)
