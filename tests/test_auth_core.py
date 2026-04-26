"""
Тесты core/auth.py — хеширование паролей, JWT, FastAPI dependencies.

Все тесты изолированы: не трогают БД и не поднимают HTTP сервер.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from jose import jwt

from core.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


# ── Пароли ────────────────────────────────────────────────────────────────────


def test_hash_returns_non_empty_string():
    h = hash_password("secret")
    assert isinstance(h, str)
    assert len(h) > 20


def test_hash_is_different_from_plain():
    plain = "mypassword"
    assert hash_password(plain) != plain


def test_two_hashes_of_same_password_differ():
    """bcrypt использует случайную соль — два хеша одного пароля не равны."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


def test_verify_correct_password():
    h = hash_password("hello123")
    assert verify_password("hello123", h) is True


def test_verify_wrong_password():
    h = hash_password("hello123")
    assert verify_password("wrongpass", h) is False


def test_verify_empty_password_against_hash():
    h = hash_password("not_empty")
    assert verify_password("", h) is False


def test_verify_invalid_hash_does_not_raise():
    """Гарантия: битый хеш не бросает исключение наружу, возвращает False."""
    assert verify_password("password", "not_a_real_hash") is False


def test_verify_empty_hash_does_not_raise():
    assert verify_password("password", "") is False


# ── JWT создание ──────────────────────────────────────────────────────────────


def test_create_token_returns_string():
    token = create_access_token(1, "a@b.com", "user", "default")
    assert isinstance(token, str)
    assert len(token) > 10


def test_create_token_payload_fields():
    token = create_access_token(42, "admin@x.com", "admin", "tenant_x")
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "42"
    assert payload["email"] == "admin@x.com"
    assert payload["role"] == "admin"
    assert payload["tenant_id"] == "tenant_x"


def test_create_token_has_expiry():
    token = create_access_token(1, "a@b.com", "user", "default")
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert "exp" in payload
    assert payload["exp"] > time.time()


def test_create_token_custom_expiry():
    """Токен с expires_minutes=1 должен иметь exp ≈ now + 60s."""
    before = time.time()
    token = create_access_token(1, "a@b.com", "user", "default", expires_minutes=1)
    after = time.time()
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert before + 50 < payload["exp"] < after + 70  # ±10s погрешность


# ── JWT декодирование ─────────────────────────────────────────────────────────


def test_decode_valid_token():
    token = create_access_token(7, "u@u.com", "user", "t1")
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "user"


def test_decode_tampered_token_raises_401():
    token = create_access_token(1, "a@b.com", "user", "default")
    bad_token = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_token(bad_token)
    assert exc_info.value.status_code == 401


def test_decode_garbage_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        decode_token("totally.not.a.jwt")
    assert exc_info.value.status_code == 401


def test_decode_wrong_secret_raises_401():
    """Токен, подписанный другим секретом, должен отклоняться."""
    other_token = jwt.encode(
        {"sub": "1", "email": "a@b.com", "role": "user", "tenant_id": "x",
         "exp": int(time.time()) + 3600},
        "WRONG_SECRET",
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_token(other_token)
    assert exc_info.value.status_code == 401


def test_decode_expired_token_raises_401():
    expired = jwt.encode(
        {"sub": "1", "email": "a@b.com", "role": "user", "tenant_id": "x",
         "exp": int(time.time()) - 10},   # уже истёк
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired)
    assert exc_info.value.status_code == 401


# ── TokenData ─────────────────────────────────────────────────────────────────


def test_decode_populates_token_data_fields():
    from core.auth import TokenData
    token = create_access_token(99, "me@me.me", "admin", "workspace_1")
    payload = decode_token(token)
    td = TokenData(payload)
    assert td.user_id == 99
    assert td.email == "me@me.me"
    assert td.role == "admin"
    assert td.tenant_id == "workspace_1"


def test_token_data_default_role():
    from core.auth import TokenData
    td = TokenData({"sub": "5", "email": "x@x.com", "tenant_id": "d"})
    assert td.role == "user"


def test_token_data_default_tenant():
    from core.auth import TokenData
    td = TokenData({"sub": "5", "email": "x@x.com"})
    assert td.tenant_id == "default"
