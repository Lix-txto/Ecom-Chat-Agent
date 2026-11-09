"""用户聊天视图：REST /chat + 会话历史 + 退款进度查询。"""
"""用户聊天视图（M7b）：双栏布局 = 左聊天 + 右快捷工具箱。"""
import uuid
from types import SimpleNamespace

import gradio as gr
import requests
from .labels import _emoji_avatar
from .labels import _BADGE_LOGGED_OUT
from .labels import REFUND_STATUS_LABELS
from .login import auth_headers

_EMPTY_AUTH = {"token": None, "role": None, "username": None}

_INTENT_ICON = {"order_query": "📦", "refund_request": "💸",
                "refund_status": "📊", "policy_qa": "📜"}

# 示例指令（绑定开发库种子数据，一键复现演示剧本）
_ORDER_ACTIONS = [
    ("我的订单", "查询订单 ORD-20261025-0001"),
    ("订单不存在（反馈测试）", "查询订单 ORD-20991231-9999"),
    ("他人订单（越权测试）", "查询订单 ORD-20261026-0002"),
]
_AFTER_SALES_ACTIONS = [
    ("退货政策", "退货政策是什么"),
    ("模拟：小额退款（自动批准）", "帮我退掉 ORD-20261029-0059，尺码不合适"),
    ("模拟：大额退款（转人工审核）", "帮我退掉 ORD-20261027-0001，不想要了"),
]


def build_user_chat(api_base: str, auth: gr.State, login_ui: SimpleNamespace,
                    user_badge: gr.HTML) -> SimpleNamespace:
    with gr.Group(visible=False) as view:
        welcome = gr.Markdown("")
        with gr.Row():
            # ===== 左栏：聊天 =====
            with gr.Column(scale=4, elem_classes=["main-col"]):
                with gr.Row():
                    session_id = gr.Textbox(
                        label="会话 ID（可自定义，用于恢复历史会话）",
                        value=f"web-{uuid.uuid4().hex[:8]}",
                    )
                    load_btn = gr.Button("🔄 加载该会话历史")
                chatbot = gr.Chatbot(
                    label="智能客服", 
                    height=520,
                    elem_classes=["main-chat"], 
                    show_label=False,
                    # bubble_full_width=False, 
                    # show_copy_button=True,
                    avatar_images=(_emoji_avatar("🧑", "#e0e7ff"),
                             _emoji_avatar("🤖", "#c7d2fe")),
                    placeholder=(
                        "<div style='text-align:center;color:#9ca3af;padding-top:40px'>"
                        "<h3>开始你的第一条对话吧</h3>"
                        "<p>试试右侧快捷指令，或输入：查询订单 ORD-20261025-0001</p></div>"
                    ),
                )
                with gr.Row():
                    msg = gr.Textbox(label="", show_label=False,
                                     placeholder="请输入消息... (Enter 发送)", scale=5)
                    send_btn = gr.Button("发送", variant="primary", scale=1, size="lg")

            # ===== 右栏：快捷工具箱 =====
            with gr.Column(scale=1, elem_classes=["sidebar"]):
                gr.Markdown('<div class="side-title">⚡ 快捷工具箱</div>')
                with gr.Accordion("🧾 订单查询", open=True):
                    order_btns = [gr.Button(l, elem_classes=["tool-btn"], size="sm")
                                  for l, _ in _ORDER_ACTIONS]
                with gr.Accordion("🛠 售后服务", open=True):
                    after_btns = [gr.Button(l, elem_classes=["tool-btn"], size="sm")
                                  for l, _ in _AFTER_SALES_ACTIONS]
                gr.Markdown('<div class="note">💡 示例基于开发库种子数据，可直接改写输入框内容</div>')
                clear_btn = gr.Button("🗑 清空历史", variant="stop", size="sm")

        with gr.Accordion("📊 退款进度查询", open=False):
            with gr.Row():
                order_no = gr.Textbox(label="订单号", placeholder="ORD-20261025-0001")
                status_btn = gr.Button("查询")
            status_md = gr.Markdown("")

        logout_btn = gr.Button("退出登录")

    # ---- 发送（生成器：先上屏用户消息 → 再追加回复，营造“打字中”反馈）----
    def _send(text, history, sid, auth_val):
        text = (text or "").strip()
        if not text:
            yield history, ""
            return
        history = history + [{"role": "user", "content": text}]
        if not (auth_val or {}).get("token"):
            yield history + [{"role": "assistant", "content": "请先登录后再发送消息"}], ""
            return
        yield history + [{"role": "assistant", "content": "正在思考…"}], ""
        try:
            resp = requests.post(f"{api_base}/chat",
                                 json={"session_id": sid, "message": text},
                                 headers=auth_headers(auth_val), timeout=60)
        except requests.RequestException:
            yield history + [{"role": "assistant", "content": "网络异常：无法连接后端服务"}], ""
            return
        if resp.status_code == 401:
            yield history + [{"role": "assistant", "content": "登录已过期，请重新登录"}], ""
            return
        if resp.status_code != 200:
            yield history + [{"role": "assistant", "content": f"请求失败（{resp.status_code}）"}], ""
            return
        body = resp.json()
        icon = _INTENT_ICON.get(body.get("intent", ""), "💬")
        reply = f"**{icon} {body['reply']}**" if icon != "💬" else body["reply"]
        yield history + [{"role": "assistant", "content": reply}], ""

    send_btn.click(_send, [msg, chatbot, session_id, auth], [chatbot, msg])
    msg.submit(_send, [msg, chatbot, session_id, auth], [chatbot, msg])

    # ---- 快捷指令绑定（闭包捕获示例文本，走同一发送管线）----
    def _bind_quick(btn, text):
        def _quick(history, sid, auth_val):
            yield from _send(text, history, sid, auth_val)
        btn.click(_quick, [chatbot, session_id, auth], [chatbot, msg])
    for btn, (_, text) in zip(order_btns, _ORDER_ACTIONS):
        _bind_quick(btn, text)
    for btn, (_, text) in zip(after_btns, _AFTER_SALES_ACTIONS):
        _bind_quick(btn, text)
    

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
            return f"ℹ️ 订单 `{order_no_val}` 暂无退款记录。"
        if resp.status_code == 401:
            return "登录已过期，请重新登录"
        if resp.status_code != 200:
            return f"查询失败（{resp.status_code}）"
        d = resp.json()
        label = REFUND_STATUS_LABELS.get(d["status"], d["status"])
        return (
            "### 💳 退款进度卡片\n\n"
            f"| 项目 | 内容 |\n|---|---|\n"
            f"| 订单 | `{d['order_no']}` |\n"
            f"| 商品 | {d['product_name']} |\n"
            f"| 退款单 | `{d['refund_no']}` |\n"
            f"| 状态 | **{label}** |\n"
            f"| 金额 | ¥{d['amount']} |\n"
            f"| 申请时间 | {d['requested_at'][:19].replace('T', ' ')} |"
        )

    status_btn.click(_check_status, [order_no, auth], [status_md])

    # ---- 退出登录 ----
    def _logout():
        return (dict(_EMPTY_AUTH), gr.update(visible=True),
                gr.update(visible=False), "", _BADGE_LOGGED_OUT)

    logout_btn.click(_logout, None,
                     [auth, login_ui.view, view, login_ui.login_msg, user_badge])

    return SimpleNamespace(view=view, welcome=welcome, chatbot=chatbot,
                           session_id=session_id, logout_btn=logout_btn)
