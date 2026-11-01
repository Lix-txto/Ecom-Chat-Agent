"""Gradio 前端入口：登录 → 用户聊天 / 管理员审核。

运行：uv run python -m frontend.app
配置：API_BASE_URL（默认 http://localhost:8000/api/v1）、FRONTEND_PORT（默认 7860）
"""
import os

import gradio as gr
import requests

from .admin_dashboard import build_admin
from .login import auth_headers, build_login, do_login
from .user_chat import build_user_chat

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
_EMPTY_AUTH = {"token": None, "role": None, "username": None}

with gr.Blocks(title="ABot 智能客服") as demo:
    auth = gr.State(dict(_EMPTY_AUTH))

    login_ui = build_login()
    chat_ui = build_user_chat(API_BASE, auth, login_ui)
    admin_ui = build_admin(API_BASE, auth, login_ui)

    # 登录事件需要引用全部三个视图 → 唯一放在 app.py 接线的 event
    def _on_login(username, password, sid, auth_val):
        data, err = do_login(API_BASE, username or "", password or "")
        if err:
            return (auth_val, gr.update(visible=True), gr.update(visible=False),
                    gr.update(visible=False), f"❌ {err}", "", "", [])
        token, role = data["access_token"], data["role"]
        new_auth = {"token": token, "role": role, "username": username}
        greet = f"👋 欢迎，**{username}**（{'管理员' if role == 'admin' else '用户'}）"

        history: list = []  # 用户登录即恢复该会话历史
        if role == "customer" and sid:
            try:
                resp = requests.get(f"{API_BASE}/chat/history/{sid}",
                                    headers=auth_headers(new_auth), timeout=10)
                if resp.status_code == 200:
                    history = [{"role": it["role"], "content": it["content"]}
                               for it in resp.json()]
            except requests.RequestException:
                history = []

        return (new_auth, gr.update(visible=False),
                gr.update(visible=role == "customer"),
                gr.update(visible=role == "admin"),
                "✅ 登录成功",
                greet if role == "customer" else "",
                greet if role == "admin" else "",
                history)

    login_ui.login_btn.click(
        _on_login,
        [login_ui.username, login_ui.password, chat_ui.session_id, auth],
        [auth, login_ui.view, chat_ui.view, admin_ui.view,
         login_ui.login_msg, chat_ui.welcome, admin_ui.welcome, chat_ui.chatbot],
    )

if __name__ == "__main__":
    demo.queue(max_size=32).launch(
        server_name="0.0.0.0", server_port=int(os.getenv("FRONTEND_PORT", "7860"))
    )
