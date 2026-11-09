"""Gradio 前端入口（M7b 视觉升级版）。

运行：uv run python -m frontend.app
配置：API_BASE_URL（默认 http://localhost:8000/api/v1）、FRONTEND_PORT（默认 7860）
"""
import os
import tempfile
from pathlib import Path

import gradio as gr
import requests

from .admin_dashboard import build_admin
from .login import auth_headers, build_login, do_login
from .user_chat import build_user_chat

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
_EMPTY_AUTH = {"token": None, "role": None, "username": None}
_BADGE_LOGGED_OUT = '<div class="badge">🔒 未登录</div>'

# ---------- 自定义 CSS ----------

CSS = """
.app-header{background:linear-gradient(90deg,#eef2ff,#e0e7ff);border-radius:14px;
  padding:10px 18px;margin-bottom:10px;align-items:center}
.app-header .brand{font-size:1.35rem;font-weight:800;color:#3730a3}
.badge{display:inline-flex;align-items:center;gap:6px;background:#fff;
  border:1px solid #c7d2fe;color:#3730a3;font-weight:600;
  padding:6px 14px;border-radius:999px;box-shadow:0 1px 2px rgba(0,0,0,.05)}
.main-chat{border:1px solid #e5e7eb;border-radius:14px;background:#fafafa}
.side-title{font-weight:700;color:#374151;margin:4px 0 8px}
.sidebar .tool-btn{width:100%;margin:3px 0;justify-content:center}
.sidebar .note{font-size:.8rem;color:#9ca3af;margin:6px 0 2px}
.statusbar{margin-top:8px}
.status-chip{display:inline-flex;gap:6px;align-items:center;background:#ecfdf5;
  border:1px solid #a7f3d0;color:#047857;font-weight:600;
  padding:4px 12px;border-radius:999px;font-size:.85rem}
.login-card{max-width:430px;margin:40px auto;background:#fff;border:1px solid #e5e7eb;
  border-radius:16px;padding:26px;box-shadow:0 4px 14px rgba(0,0,0,.06)}
"""



# ① Blocks 构造器删掉 theme、css 两个参数
with gr.Blocks(title="ABot 智能客服") as demo:
    auth = gr.State(dict(_EMPTY_AUTH))
    """
    # ② launch() 接管，值原样照抄
    demo.queue(max_size=32).launch(
    server_name="0.0.0.0",
    server_port=int(os.getenv("FRONTEND_PORT", "7860")),
    theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="blue",
                         font=["system-ui", "-apple-system", "sans-serif"]),
    css=CSS,
    )
    """
    # ---- 顶部品牌栏 ----
    with gr.Row(elem_classes=["app-header"]):
        gr.HTML('<div class="brand">🛍️ ABot 智能客服助手</div>')
        user_badge = gr.HTML(_BADGE_LOGGED_OUT)

    login_ui = build_login()
    chat_ui = build_user_chat(API_BASE, auth, login_ui, user_badge)
    admin_ui = build_admin(API_BASE, auth, login_ui, user_badge)

    # ---- 底部状态条 ----
    with gr.Row(elem_classes=["statusbar"]):
        gr.HTML('<span class="status-chip">🟢 Ready</span>')
        gr.HTML('<span class="note">API: :8000 · 前端 :7860</span>')

    # ---- 登录事件（需要引用全部视图 → 唯一在 app.py 接线）----
    GREETING = (
        "👋 您好！我是 ABot 智能客服助手。\n\n"
        "可以帮我：**查询订单 / 办理退款 / 查退款进度 / 解答退货政策**。\n"
        "💡 点击右侧快捷指令可一键体验，或直接在下方输入。"
    )

    def _on_login(username, password, sid, auth_val):
        data, err = do_login(API_BASE, username or "", password or "")
        if err:
            return (auth_val, gr.update(visible=True), gr.update(visible=False),
                    gr.update(visible=False), f"❌ {err}", "", "", [],
                    _BADGE_LOGGED_OUT)
        token, role = data["access_token"], data["role"]
        new_auth = {"token": token, "role": role, "username": username}
        label = "管理员" if role == "admin" else "用户"
        badge = f'<div class="badge">👤 {username}（{label}）</div>'
        greet = f"### 👋 欢迎，**{username}**（{label}）"

        history: list = []
        if role == "customer" and sid:
            try:
                resp = requests.get(f"{API_BASE}/chat/history/{sid}",
                                    headers=auth_headers(new_auth), timeout=10)
                if resp.status_code == 200:
                    history = [{"role": it["role"], "content": it["content"]}
                               for it in resp.json()]
            except requests.RequestException:
                history = []
        if role == "customer" and not history:
            history = [{"role": "assistant", "content": GREETING}]

        return (new_auth, gr.update(visible=False),
                gr.update(visible=role == "customer"),
                gr.update(visible=role == "admin"),
                "✅ 登录成功", greet, greet, history, badge)

    login_ui.login_btn.click(
        _on_login,
        [login_ui.username, login_ui.password, chat_ui.session_id, auth],
        [auth, login_ui.view, chat_ui.view, admin_ui.view,
         login_ui.login_msg, chat_ui.welcome, admin_ui.welcome,
         chat_ui.chatbot, user_badge],
    )
"""
if __name__ == "__main__":
    demo.queue(max_size=32).launch(
        server_name="0.0.0.0", server_port=int(os.getenv("FRONTEND_PORT", "7860"))
    )
"""
if __name__ == "__main__":
    demo.queue(max_size=32).launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("FRONTEND_PORT", "7860")),
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="blue",
                             font=["system-ui", "-apple-system", "sans-serif"]),
        css=CSS,
    )
