"""
Тесты DB-слоя аутентификации (core/database.py — функции users).

Используют реальную SQLite в temp-файле — никаких моков ORM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import database as db
from core.auth import hash_password, verify_password


# ── Вспомогательная фикстура ──────────────────────────────────────────────────


@pytest.fixture
async def ready_db(temp_db_path: Path) -> Path:
    """Инициализированная БД, готова к работе."""
    result = await db.init_db(temp_db_path)
    assert result["status"] == "ok"
    return temp_db_path


# ── create_user ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_returns_ok(ready_db: Path):
    r = await db.create_user(
        email="alice@example.com",
        password_hash=hash_password("pass1"),
        name="Alice",
        db_path=ready_db,
    )
    assert r["status"] == "ok"
    u = r["user"]
    assert u["email"] == "alice@example.com"
    assert u["name"] == "Alice"
    assert u["role"] == "user"
    assert u["plan"] == "free"


@pytest.mark.asyncio
async def test_create_user_password_hash_not_in_response(ready_db: Path):
    """Хеш пароля никогда не должен утекать через create_user."""
    r = await db.create_user(
        email="bob@example.com",
        password_hash=hash_password("secret"),
        db_path=ready_db,
    )
    assert "password_hash" not in r["user"]


@pytest.mark.asyncio
async def test_create_user_sets_avatar_initials(ready_db: Path):
    r = await db.create_user(
        email="carol@x.com",
        password_hash="h",
        name="Carol King",
        db_path=ready_db,
    )
    assert r["user"]["avatar_initials"] == "CK"


@pytest.mark.asyncio
async def test_create_user_fills_plan_limits(ready_db: Path):
    r = await db.create_user(
        email="d@x.com",
        password_hash="h",
        plan="pro",
        db_path=ready_db,
    )
    limits = r["user"]["plan_limits"]
    assert limits["tasks_per_day"] == 100
    assert limits["profiles"] == 20


@pytest.mark.asyncio
async def test_create_user_fills_usage_zeros(ready_db: Path):
    r = await db.create_user(
        email="e@x.com",
        password_hash="h",
        db_path=ready_db,
    )
    usage = r["user"]["usage"]
    assert usage["tasks_today"] == 0
    assert usage["storage_used_gb"] == 0


@pytest.mark.asyncio
async def test_create_user_duplicate_email_returns_error(ready_db: Path):
    await db.create_user(email="dup@x.com", password_hash="h", db_path=ready_db)
    r2 = await db.create_user(email="dup@x.com", password_hash="h2", db_path=ready_db)
    assert r2["status"] == "error"
    assert "зарегистрирован" in r2["message"].lower() or "unique" in r2["message"].lower()


@pytest.mark.asyncio
async def test_create_user_email_stored_lowercase(ready_db: Path):
    r = await db.create_user(email="UPPER@CASE.COM", password_hash="h", db_path=ready_db)
    assert r["user"]["email"] == "upper@case.com"


@pytest.mark.asyncio
async def test_create_user_admin_role(ready_db: Path):
    r = await db.create_user(
        email="adm@x.com",
        password_hash="h",
        role="admin",
        plan="enterprise",
        db_path=ready_db,
    )
    assert r["user"]["role"] == "admin"
    assert r["user"]["plan"] == "enterprise"
    assert r["user"]["plan_limits"]["tasks_per_day"] == 9999


# ── get_user_by_email ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_email_found(ready_db: Path):
    await db.create_user(email="find@x.com", password_hash="h", name="Find Me", db_path=ready_db)
    r = await db.get_user_by_email("find@x.com", db_path=ready_db)
    assert r["status"] == "ok"
    assert r["user"]["name"] == "Find Me"


@pytest.mark.asyncio
async def test_get_user_by_email_case_insensitive(ready_db: Path):
    await db.create_user(email="ci@x.com", password_hash="h", db_path=ready_db)
    r = await db.get_user_by_email("CI@X.COM", db_path=ready_db)
    assert r["status"] == "ok"


@pytest.mark.asyncio
async def test_get_user_by_email_returns_password_hash_for_verification(ready_db: Path):
    """Login нуждается в хеше — он должен быть в ответе get_user_by_email."""
    original_hash = hash_password("mypass")
    await db.create_user(email="verify@x.com", password_hash=original_hash, db_path=ready_db)
    r = await db.get_user_by_email("verify@x.com", db_path=ready_db)
    assert "password_hash" in r["user"]
    assert verify_password("mypass", r["user"]["password_hash"]) is True


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(ready_db: Path):
    r = await db.get_user_by_email("nobody@x.com", db_path=ready_db)
    assert r["status"] == "error"


# ── get_user_by_id ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_id_found(ready_db: Path):
    created = await db.create_user(email="byid@x.com", password_hash="h", db_path=ready_db)
    uid = created["user"]["id"]
    r = await db.get_user_by_id(uid, db_path=ready_db)
    assert r["status"] == "ok"
    assert r["user"]["id"] == uid


@pytest.mark.asyncio
async def test_get_user_by_id_no_password_hash(ready_db: Path):
    """get_user_by_id не должен возвращать пароль — используется для /api/auth/me."""
    created = await db.create_user(email="secure@x.com", password_hash="h", db_path=ready_db)
    uid = created["user"]["id"]
    r = await db.get_user_by_id(uid, db_path=ready_db)
    assert "password_hash" not in r["user"]


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(ready_db: Path):
    r = await db.get_user_by_id(99999, db_path=ready_db)
    assert r["status"] == "error"


# ── update_user ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_user_name(ready_db: Path):
    c = await db.create_user(email="upd@x.com", password_hash="h", name="Old Name", db_path=ready_db)
    uid = c["user"]["id"]
    r = await db.update_user(uid, name="New Name", db_path=ready_db)
    assert r["status"] == "ok"
    assert r["user"]["name"] == "New Name"
    assert r["user"]["avatar_initials"] == "NN"


@pytest.mark.asyncio
async def test_update_user_plan_refreshes_limits(ready_db: Path):
    c = await db.create_user(email="plan@x.com", password_hash="h", plan="free", db_path=ready_db)
    uid = c["user"]["id"]
    r = await db.update_user(uid, plan="enterprise", db_path=ready_db)
    assert r["user"]["plan"] == "enterprise"
    assert r["user"]["plan_limits"]["tasks_per_day"] == 9999


@pytest.mark.asyncio
async def test_update_user_status_ban(ready_db: Path):
    c = await db.create_user(email="ban@x.com", password_hash="h", db_path=ready_db)
    uid = c["user"]["id"]
    r = await db.update_user(uid, status="banned", db_path=ready_db)
    assert r["user"]["status"] == "banned"


@pytest.mark.asyncio
async def test_update_user_password_hash(ready_db: Path):
    old_hash = hash_password("old_pass")
    c = await db.create_user(email="chpw@x.com", password_hash=old_hash, db_path=ready_db)
    uid = c["user"]["id"]
    new_hash = hash_password("new_pass")
    await db.update_user(uid, password_hash=new_hash, db_path=ready_db)
    # Читаем через get_user_by_email — там есть хеш
    row = await db.get_user_by_email("chpw@x.com", db_path=ready_db)
    assert verify_password("new_pass", row["user"]["password_hash"]) is True
    assert verify_password("old_pass", row["user"]["password_hash"]) is False


@pytest.mark.asyncio
async def test_update_nonexistent_user_returns_error(ready_db: Path):
    r = await db.update_user(99999, name="Ghost", db_path=ready_db)
    assert r["status"] == "error"


@pytest.mark.asyncio
async def test_update_user_no_fields_is_noop(ready_db: Path):
    c = await db.create_user(email="noop@x.com", password_hash="h", name="Orig", db_path=ready_db)
    uid = c["user"]["id"]
    r = await db.update_user(uid, db_path=ready_db)
    assert r["status"] == "ok"
    assert r["user"]["name"] == "Orig"


# ── list_users ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_users_empty(ready_db: Path):
    r = await db.list_users(db_path=ready_db)
    assert r["status"] == "ok"
    assert r["users"] == []


@pytest.mark.asyncio
async def test_list_users_returns_all(ready_db: Path):
    for i in range(3):
        await db.create_user(email=f"u{i}@x.com", password_hash="h", db_path=ready_db)
    r = await db.list_users(db_path=ready_db)
    assert len(r["users"]) == 3


@pytest.mark.asyncio
async def test_list_users_limit(ready_db: Path):
    for i in range(5):
        await db.create_user(email=f"lim{i}@x.com", password_hash="h", db_path=ready_db)
    r = await db.list_users(limit=2, db_path=ready_db)
    assert len(r["users"]) == 2


@pytest.mark.asyncio
async def test_list_users_offset(ready_db: Path):
    for i in range(4):
        await db.create_user(email=f"off{i}@x.com", password_hash="h", db_path=ready_db)
    r_all = await db.list_users(db_path=ready_db)
    r_offset = await db.list_users(limit=10, offset=2, db_path=ready_db)
    assert len(r_offset["users"]) == len(r_all["users"]) - 2


@pytest.mark.asyncio
async def test_list_users_no_password_hash(ready_db: Path):
    await db.create_user(email="safe@x.com", password_hash="h", db_path=ready_db)
    r = await db.list_users(db_path=ready_db)
    for u in r["users"]:
        assert "password_hash" not in u


# ── ensure_default_admin ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_default_admin_creates_if_missing(ready_db: Path):
    await db.ensure_default_admin(
        email="root@x.com",
        password_hash=hash_password("rootpass"),
        db_path=ready_db,
    )
    r = await db.get_user_by_email("root@x.com", db_path=ready_db)
    assert r["status"] == "ok"
    assert r["user"]["role"] == "admin"
    assert r["user"]["plan"] == "enterprise"


@pytest.mark.asyncio
async def test_ensure_default_admin_idempotent(ready_db: Path):
    """Вызов дважды не должен создавать второй admin-аккаунт."""
    h = hash_password("pass")
    await db.ensure_default_admin(email="admin@x.com", password_hash=h, db_path=ready_db)
    await db.ensure_default_admin(email="admin@x.com", password_hash=h, db_path=ready_db)
    r = await db.list_users(db_path=ready_db)
    admins = [u for u in r["users"] if u["role"] == "admin"]
    assert len(admins) == 1


@pytest.mark.asyncio
async def test_ensure_default_admin_no_hash_skips(ready_db: Path):
    """Если password_hash пустой — не создаём пустого admin."""
    await db.ensure_default_admin(email="empty@x.com", password_hash="", db_path=ready_db)
    r = await db.list_users(db_path=ready_db)
    assert r["users"] == []


@pytest.mark.asyncio
async def test_ensure_default_admin_skips_if_admin_exists(ready_db: Path):
    """Если admin уже есть — не создаёт нового с другим email."""
    await db.create_user(
        email="existing_admin@x.com",
        password_hash=hash_password("p"),
        role="admin",
        plan="enterprise",
        db_path=ready_db,
    )
    await db.ensure_default_admin(
        email="another_admin@x.com",
        password_hash=hash_password("p2"),
        db_path=ready_db,
    )
    r = await db.list_users(db_path=ready_db)
    admins = [u for u in r["users"] if u["role"] == "admin"]
    assert len(admins) == 1
    assert admins[0]["email"] == "existing_admin@x.com"
