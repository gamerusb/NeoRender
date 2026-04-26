"""
HTTP-тесты auth + admin эндпоинтов через FastAPI TestClient.

Каждый тест получает свежую изолированную БД — никакого разделения состояния.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from core import database as dbmod
from core.auth import create_access_token, hash_password


# ── Фикстуры ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client(temp_db_path: Path) -> TestClient:
    """TestClient с изолированной БД на temp_db_path."""
    # Патчим путь ДО init_db — все функции работают с temp-файлом
    original = dbmod._DEFAULT_DB_PATH
    dbmod._DEFAULT_DB_PATH = temp_db_path
    asyncio.run(dbmod.init_db(temp_db_path))
    yield TestClient(api_server.app, raise_server_exceptions=False)
    dbmod._DEFAULT_DB_PATH = original


def _register(client: TestClient, email: str = "u@test.com",
               password: str = "pass123", name: str = "Test User") -> dict:
    r = client.post("/api/auth/register", json={
        "email": email, "password": password, "name": name,
    })
    return r.json()


def _login(client: TestClient, email: str = "u@test.com",
           password: str = "pass123") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.json()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_token(user_id: int = 9999) -> str:
    """Токен с ролью admin и id, который заведомо не совпадает с тестовыми пользователями."""
    return create_access_token(user_id, "admin@test.com", "admin", "default")


# ── /api/auth/ping ────────────────────────────────────────────────────────────


def test_ping_returns_ok(client: TestClient):
    r = client.get("/api/auth/ping")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["auth"] == "real"


# ── /api/auth/register ────────────────────────────────────────────────────────


def test_register_success(client: TestClient):
    r = client.post("/api/auth/register", json={
        "email": "new@test.com", "password": "abcdef", "name": "New User",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "token" in body
    assert body["user"]["email"] == "new@test.com"
    assert body["user"]["name"] == "New User"
    assert body["user"]["role"] == "user"
    assert "password_hash" not in body["user"]


def test_register_short_password_rejected(client: TestClient):
    r = client.post("/api/auth/register", json={
        "email": "x@x.com", "password": "12", "name": "X",
    })
    assert r.status_code == 400
    assert r.json()["status"] == "error"


def test_register_duplicate_email_rejected(client: TestClient):
    _register(client, email="dup@test.com")
    r = client.post("/api/auth/register", json={
        "email": "dup@test.com", "password": "pass123", "name": "Dup",
    })
    assert r.status_code == 400
    assert r.json()["status"] == "error"


def test_register_default_plan_is_free(client: TestClient):
    body = _register(client)
    assert body["user"]["plan"] == "free"


def test_register_sets_plan_limits(client: TestClient):
    body = _register(client)
    assert body["user"]["plan_limits"]["tasks_per_day"] == 10


def test_register_token_is_valid_jwt(client: TestClient):
    from core.auth import decode_token
    body = _register(client)
    payload = decode_token(body["token"])
    assert payload["email"] == "u@test.com"
    assert payload["role"] == "user"


# ── /api/auth/login ───────────────────────────────────────────────────────────


def test_login_success(client: TestClient):
    _register(client, email="login@test.com", password="mypass")
    r = client.post("/api/auth/login", json={
        "email": "login@test.com", "password": "mypass",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "token" in body
    assert body["user"]["email"] == "login@test.com"


def test_login_wrong_password(client: TestClient):
    _register(client, email="wp@test.com", password="correct")
    r = client.post("/api/auth/login", json={
        "email": "wp@test.com", "password": "wrong",
    })
    assert r.status_code == 401
    assert r.json()["status"] == "error"


def test_login_unknown_email(client: TestClient):
    r = client.post("/api/auth/login", json={
        "email": "nobody@test.com", "password": "pass123",
    })
    assert r.status_code == 401


def test_login_case_insensitive_email(client: TestClient):
    _register(client, email="ci@test.com", password="pass123")
    r = client.post("/api/auth/login", json={
        "email": "CI@TEST.COM", "password": "pass123",
    })
    assert r.status_code == 200


def test_login_banned_user_gets_403(client: TestClient):
    body = _register(client, email="banned@test.com")
    uid = body["user"]["id"]
    asyncio.run(dbmod.update_user(uid, status="banned"))
    r = client.post("/api/auth/login", json={
        "email": "banned@test.com", "password": "pass123",
    })
    assert r.status_code == 403


def test_login_no_password_hash_in_response(client: TestClient):
    _register(client, email="safe@test.com")
    body = _login(client, email="safe@test.com")
    assert "password_hash" not in body.get("user", {})


# ── /api/auth/me ──────────────────────────────────────────────────────────────


def test_me_returns_user(client: TestClient):
    reg = _register(client, email="me@test.com")
    token = reg["token"]
    r = client.get("/api/auth/me", headers=_auth_header(token))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "me@test.com"
    assert "password_hash" not in body["user"]


def test_me_without_token_returns_401(client: TestClient):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_invalid_token_returns_401(client: TestClient):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer totally_fake"})
    assert r.status_code == 401


def test_me_with_tampered_token_returns_401(client: TestClient):
    reg = _register(client)
    bad = reg["token"][:-5] + "XXXXX"
    r = client.get("/api/auth/me", headers=_auth_header(bad))
    assert r.status_code == 401


# ── PATCH /api/auth/me ────────────────────────────────────────────────────────


def test_update_me_name(client: TestClient):
    reg = _register(client, name="Old Name")
    token = reg["token"]
    r = client.patch("/api/auth/me",
                     json={"name": "New Name"},
                     headers=_auth_header(token))
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "New Name"


def test_update_me_requires_auth(client: TestClient):
    r = client.patch("/api/auth/me", json={"name": "X"})
    assert r.status_code == 401


# ── /api/auth/change-password ─────────────────────────────────────────────────


def test_change_password_success(client: TestClient):
    reg = _register(client, password="oldpass1")
    token = reg["token"]
    r = client.post("/api/auth/change-password",
                    json={"old_password": "oldpass1", "new_password": "newpass9"},
                    headers=_auth_header(token))
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # Теперь логин со старым паролем не работает
    bad_login = _login(client, email="u@test.com", password="oldpass1")
    assert bad_login.get("status") == "error" or "token" not in bad_login
    # А с новым — работает
    ok_login = _login(client, email="u@test.com", password="newpass9")
    assert ok_login["status"] == "ok"


def test_change_password_wrong_old(client: TestClient):
    reg = _register(client, password="correct")
    r = client.post("/api/auth/change-password",
                    json={"old_password": "wrong", "new_password": "newpass9"},
                    headers=_auth_header(reg["token"]))
    assert r.status_code == 400
    assert r.json()["status"] == "error"


def test_change_password_too_short(client: TestClient):
    reg = _register(client, password="correct")
    r = client.post("/api/auth/change-password",
                    json={"old_password": "correct", "new_password": "123"},
                    headers=_auth_header(reg["token"]))
    assert r.status_code == 400


def test_change_password_requires_auth(client: TestClient):
    r = client.post("/api/auth/change-password",
                    json={"old_password": "x", "new_password": "newpass9"})
    assert r.status_code == 401


# ── /api/auth/logout ──────────────────────────────────────────────────────────


def test_logout_returns_ok(client: TestClient):
    reg = _register(client)
    r = client.post("/api/auth/logout", headers=_auth_header(reg["token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_logout_without_token_still_ok(client: TestClient):
    """Logout stateless — принимает и без токена."""
    r = client.post("/api/auth/logout")
    assert r.status_code == 200


# ── /api/admin/users ──────────────────────────────────────────────────────────


def test_admin_list_users_requires_auth(client: TestClient):
    r = client.get("/api/admin/users")
    assert r.status_code == 401


def test_admin_list_users_requires_admin_role(client: TestClient):
    reg = _register(client)  # role=user
    r = client.get("/api/admin/users", headers=_auth_header(reg["token"]))
    assert r.status_code == 403


def test_admin_list_users_success(client: TestClient):
    _register(client, email="u1@test.com")
    _register(client, email="u2@test.com")
    # Создаём admin напрямую через DB
    asyncio.run(dbmod.create_user(
        email="adm@test.com",
        password_hash=hash_password("adminpass"),
        role="admin",
        plan="enterprise",
    ))
    admin_token = create_access_token(999, "adm@test.com", "admin", "default")
    r = client.get("/api/admin/users", headers=_auth_header(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "users" in body
    assert body["total"] >= 2


def test_admin_list_users_no_password_hash(client: TestClient):
    _register(client, email="sec@test.com")
    admin_token = _admin_token()
    r = client.get("/api/admin/users", headers=_auth_header(admin_token))
    for u in r.json().get("users", []):
        assert "password_hash" not in u


# ── /api/admin/users/{id}/ban и unban ────────────────────────────────────────


def test_admin_ban_user(client: TestClient):
    reg = _register(client, email="victim@test.com")
    uid = reg["user"]["id"]
    admin_token = _admin_token()
    r = client.post(f"/api/admin/users/{uid}/ban", headers=_auth_header(admin_token))
    assert r.status_code == 200
    assert r.json()["user"]["status"] == "banned"


def test_admin_unban_user(client: TestClient):
    reg = _register(client, email="pardoned@test.com")
    uid = reg["user"]["id"]
    admin_token = _admin_token()
    client.post(f"/api/admin/users/{uid}/ban", headers=_auth_header(admin_token))
    r = client.post(f"/api/admin/users/{uid}/unban", headers=_auth_header(admin_token))
    assert r.status_code == 200
    assert r.json()["user"]["status"] == "active"


def test_admin_ban_requires_admin(client: TestClient):
    reg = _register(client, email="t@t.com")
    uid = reg["user"]["id"]
    r = client.post(f"/api/admin/users/{uid}/ban", headers=_auth_header(reg["token"]))
    assert r.status_code == 403


def test_admin_cannot_ban_self(client: TestClient):
    """Admin не должен иметь возможность заблокировать себя."""
    # Создаём admin в БД с реальным id
    created = asyncio.run(dbmod.create_user(
        email="self_admin@test.com",
        password_hash=hash_password("p"),
        role="admin",
        plan="enterprise",
    ))
    admin_uid = created["user"]["id"]
    admin_token = create_access_token(admin_uid, "self_admin@test.com", "admin", "default")
    r = client.post(f"/api/admin/users/{admin_uid}/ban", headers=_auth_header(admin_token))
    assert r.status_code == 400


def test_admin_ban_nonexistent_user(client: TestClient):
    admin_token = _admin_token()
    r = client.post("/api/admin/users/99999/ban", headers=_auth_header(admin_token))
    assert r.status_code == 404


# ── /api/admin/users/{id}/plan ────────────────────────────────────────────────


def test_admin_change_plan(client: TestClient):
    reg = _register(client, email="upgrade@test.com")
    uid = reg["user"]["id"]
    admin_token = _admin_token()
    r = client.post(f"/api/admin/users/{uid}/plan",
                    json={"plan": "pro"},
                    headers=_auth_header(admin_token))
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["plan"] == "pro"
    assert user["plan_limits"]["tasks_per_day"] == 100


def test_admin_change_plan_invalid(client: TestClient):
    reg = _register(client, email="inv@test.com")
    uid = reg["user"]["id"]
    admin_token = _admin_token()
    r = client.post(f"/api/admin/users/{uid}/plan",
                    json={"plan": "ultra_premium_x"},
                    headers=_auth_header(admin_token))
    assert r.status_code == 400


def test_admin_change_plan_requires_admin(client: TestClient):
    reg = _register(client, email="nop@test.com")
    uid = reg["user"]["id"]
    r = client.post(f"/api/admin/users/{uid}/plan",
                    json={"plan": "enterprise"},
                    headers=_auth_header(reg["token"]))
    assert r.status_code == 403


# ── /api/admin/stats ──────────────────────────────────────────────────────────


def test_admin_stats_requires_admin(client: TestClient):
    reg = _register(client)
    r = client.get("/api/admin/stats", headers=_auth_header(reg["token"]))
    assert r.status_code == 403


def test_admin_stats_returns_counts(client: TestClient):
    _register(client, email="s1@test.com")
    _register(client, email="s2@test.com")
    admin_token = _admin_token()
    r = client.get("/api/admin/stats", headers=_auth_header(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "total_users" in body
    assert "by_plan" in body
    assert "by_status" in body
    assert body["total_users"] >= 2
