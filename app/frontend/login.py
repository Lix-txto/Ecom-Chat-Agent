"""登录视图：调用 FastAPI OAuth2 端点；组件在此创建，事件在 app.py 统一接线。"""
from types import SimpleNamespace
from typing import Optional

import gradio as gr
import requests


def do_login(api_base: str, username: str, password: str) -> tuple[Optional[dict], Optional[str]]:
    """返回 (登录数据, 错误信息)，二者必居其一。"""
    if not username.strip() or not password.strip():
        return None, "请输入用户名和密码"
    try:
        resp = requests.post(
            f"{api_base}/auth/login",
            data={"username": username, "password": password},
            timeout=10,
        )
    except requests.RequestException:
        return None, "无法连接后端服务，请确认 API 已启动（http://localhost:8000）"
    if resp.status_code != 200:
        try:
            return None, resp.json().get("detail", "登录失败")
        except ValueError:
            return None, "登录失败"
    return resp.json(), None


def auth_headers(auth: dict | None) -> dict:
    token = (auth or {}).get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def build_login() -> SimpleNamespace:
    with gr.Group(visible=True) as view:
        gr.Markdown(
            "### 🔐 ABot 智能客服 · 登录\n\n"
            "演示账号：`zhangsan / zhangsan123`（用户）· `admin / admin123`（管理员）"
        )
        username = gr.Textbox(label="用户名", placeholder="zhangsan")
        password = gr.Textbox(label="密码", type="password", placeholder="zhangsan123")
        login_btn = gr.Button("登 录", variant="primary")
        login_msg = gr.Markdown("")
    return SimpleNamespace(view=view, username=username, password=password,
                           login_btn=login_btn, login_msg=login_msg)
