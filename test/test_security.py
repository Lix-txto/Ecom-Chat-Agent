from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPassword:
    def test_hash_roundtrip(self):
        raw = "s3cret-P@ss"
        hashed = hash_password(raw)
        assert hashed != raw
        assert verify_password(raw, hashed)

    def test_wrong_password_rejected(self):
        assert not verify_password("wrong", hash_password("correct"))

    def test_bcrypt_salting(self):
        # 相同明文两次哈希不同（bcrypt 自带随机盐）
        assert hash_password("same") != hash_password("same")


class TestJWT:
    def test_roundtrip(self):
        token = create_access_token("zhangsan")
        payload = decode_token(token)
        assert payload["sub"] == "zhangsan"
        assert "exp" in payload and "iat" in payload

    def test_custom_expiry(self):
        token = create_access_token("zhangsan", expires_minutes=5)
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)

    def test_role_claim(self):
        payload = decode_token(create_access_token("admin", role="admin"))
        assert payload.get("role") == "admin"

    def test_expired_token_rejected(self):
        token = create_access_token("zhangsan", expires_minutes=-1)
        with pytest.raises(HTTPException) as exc:
            decode_token(token)
        assert exc.value.status_code == 401

    def test_garbage_token_rejected(self):
        with pytest.raises(HTTPException) as exc:
            decode_token("not-a-jwt")
        assert exc.value.status_code == 401

    def test_forged_signature_rejected(self):
        # 攻击者用别的 secret 伪造的 token 必须被拒绝
        forged = pyjwt.encode(
            {"sub": "zhangsan", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "attacker-secret-"+"x"*32,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            decode_token(forged)
        assert exc.value.status_code == 401
