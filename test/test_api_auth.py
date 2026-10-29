"""M5：认证 API。"""
import pytest


def _login(client, username, password):
    return client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}
    )


class TestLogin:
    def test_success(self, client, seed_users):
        r = _login(client, "zhangsan", "test-password-123")
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["role"] == "customer"
        assert body["access_token"]

    def test_admin_role(self, client, seed_users):
        assert _login(client, "admin", "test-password-123").json()["role"] == "admin"

    def test_wrong_password_401(self, client, seed_users):
        assert _login(client, "zhangsan", "wrong").status_code == 401

    def test_unknown_user_same_message(self, client, seed_users):
        # 用户不存在与密码错误统一文案（防用户名枚举）
        r_missing = _login(client, "nobody", "x")
        r_wrong = _login(client, "zhangsan", "wrong")
        assert r_missing.status_code == r_wrong.status_code == 401
        assert r_missing.json()["detail"] == r_wrong.json()["detail"]


class TestMe:
    def test_with_token(self, client, seed_users):
        token = _login(client, "zhangsan", "test-password-123").json()["access_token"]
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["username"] == "zhangsan"

    def test_without_token_403(self, client, seed_users):
        assert client.get("/api/v1/auth/me").status_code == 403
