"""
Локальный HTTP API + раздача UI NeoRender Pro.

Мультитенантность (задел под SaaS):
  - Заголовок X-Tenant-ID — изоляция данных в SQLite и папках uploads/rendered.
  - Без заголовка: NEORENDER_TENANT_ID в окружении или tenant \"default\".

Запуск: py run_server.py (порт 8765 или следующий свободный) либо uvicorn api_server:app --host 127.0.0.1 --port 8765
UI: http://127.0.0.1:8765/ui/ — React из web/dist (обязательно `npm run build` в frontend/ после правок исходников; иначе отдаётся старая сборка). Без dist — классический UI из web/legacy.

Старт: загрузка .env из корня проекта, затем data/neo_settings.json (ключи из UI).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from core import adspower_sync
from core import adspower_profiles
from core import analytics_advisor
from core import ai_copywriter
from core import adspower_launcher
from core import persisted_config as persisted_cfg
from core import analytics_scraper
from core import database as dbmod
from core import ffmpeg_runner
from core import luxury_engine
from core import overlay_paths
from core import profile_job_runner
from core import storage as storage_mod
from core import content_scraper
from core import ubt_detector
from core import subtitle_generator
from core import auth as auth_core
from core.main_loop import AutomationPipeline
from core.tenancy import normalize_tenant_id, tenant_id_from_environ

logging.basicConfig(level=logging.INFO, encoding="utf-8")
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
from typing import Any

ROOT = Path(__file__).resolve().parent
_UPLOADS_ROOT = ROOT / "data" / "uploads"
_ARBITRAGE_ALERT_STATE_FILE = ROOT / "data" / "arbitrage_alert_state.json"
_RISK_LABELS_FILE = ROOT / "data" / "risk_labels.json"

# Кэш результата `ffmpeg -version` — обновляется раз в 60 секунд.
_ffmpeg_version_cache: dict[str, Any] = {}
_FFMPEG_CACHE_TTL = 60.0
WEB_ROOT = ROOT / "web"
WEB_DIST = WEB_ROOT / "dist"
WEB_LEGACY = WEB_ROOT / "legacy"
_UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
_UPLOAD_RATE_LIMIT = 30
_TASK_CREATE_RATE_LIMIT = 120
_RATE_WINDOW_SEC = 60.0
_rate_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        persisted_cfg.load_dotenv_if_present()
        persisted_cfg.apply_persisted_settings()
        persisted_cfg.load_dotenv_override_if_present()
        r = await dbmod.init_db()
        if r.get("status") != "ok":
            logger.warning("init_db: %s", r)
    except Exception as exc:
        logger.exception("startup db: %s", exc)
    try:
        await _ensure_demo_auth_users()
    except Exception as exc:
        logger.warning("startup demo users: %s", exc)
    # Инициализация реестра антидетект-браузеров + health-check
    try:
        from core.antidetect_registry import init_registry, get_registry
        registry = await init_registry()
        logger.info("antidetect_registry: loaded")
        # Проверить доступность всех зарегистрированных браузеров
        if registry.count() > 0:
            try:
                health = await registry.verify_all()
                results = health.get("results") or []
                for r in results:
                    aid = r.get("antidetect_id")
                    btype = r.get("browser_type", "?")
                    if r.get("status") == "ok":
                        logger.info("antidetect id=%s (%s): online ✓", aid, btype)
                    else:
                        logger.warning(
                            "antidetect id=%s (%s): OFFLINE — %s "
                            "(убедитесь что приложение запущено)",
                            aid, btype, r.get("message", "no response"),
                        )
            except Exception as exc:
                logger.warning("antidetect health-check: %s", exc)
        else:
            logger.info("antidetect_registry: нет зарегистрированных браузеров (добавьте в Profiles → Antidetect Browsers)")
    except Exception as exc:
        logger.warning("antidetect_registry startup: %s", exc)
    # Запуск MediaScanQueue (воркеры + предзагрузка Whisper)
    try:
        from core.media_scanner import get_media_scan_queue
        await get_media_scan_queue().start()
        logger.info("media_scanner: queue started")
    except Exception as exc:
        logger.warning("media_scanner startup: %s", exc)
    yield
    # Остановка MediaScanQueue при shutdown
    try:
        from core.media_scanner import get_media_scan_queue
        await get_media_scan_queue().stop()
    except Exception as exc:
        logger.warning("media_scanner shutdown: %s", exc)


app = FastAPI(title="NeoRender Pro API", version="0.3", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _ui_trailing_slash_redirect(request: Request, call_next):
    """Без слэша StaticFiles / браузер кладёт ассеты неверно; редирект на канонический URL."""
    p = request.scope.get("path") or ""
    if p == "/ui":
        return RedirectResponse(url="/ui/", status_code=307)
    if p == "/ui/legacy":
        return RedirectResponse(url="/ui/legacy/", status_code=307)
    return await call_next(request)


@app.middleware("http")
async def _ui_entry_no_cache(request: Request, call_next):
    """Чтобы после `npm run build` сразу подхватывался новый index.html, а не закэшированный."""
    response = await call_next(request)
    if request.method != "GET":
        return response
    p = request.scope.get("path") or ""
    if p in ("/ui", "/ui/", "/ui/index.html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# Отдельный пайплайн на tenant (очередь не смешивается между клиентами).
_pipelines: dict[str, AutomationPipeline] = {}


_bearer_scheme_optional = HTTPBearer(auto_error=False)


async def get_tenant_id(
    request: Request,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme_optional)] = None,
) -> str:
    """
    Приоритет tenant_id:
    1. JWT токен (Bearer или cookie) — нельзя подделать заголовком
    2. X-Tenant-ID заголовок — только для публичных/dev эндпоинтов
    3. ENV переменная NEORENDER_TENANT_ID
    """
    # 1. Попытка извлечь из JWT (Bearer или cookie)
    token: str | None = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("neo_token")

    if token:
        try:
            payload = auth_core.decode_token(token)
            tid = str(payload.get("tenant_id") or "").strip()
            if tid:
                return normalize_tenant_id(tid)
        except Exception:
            pass  # невалидный токен — продолжаем к fallback

    # 2. X-Tenant-ID заголовок (публичные эндпоинты / локальный запуск)
    if x_tenant_id and str(x_tenant_id).strip():
        return normalize_tenant_id(x_tenant_id)

    # 3. ENV
    return tenant_id_from_environ()


TenantDep = Annotated[str, Depends(get_tenant_id)]


def _auth_user_or_401(user: dict[str, Any] | None) -> JSONResponse | None:
    if not user:
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=401)
    return None


class AuthRegisterBody(BaseModel):
    email: str
    password: str
    name: str = ""


class AuthLoginBody(BaseModel):
    email: str
    password: str


class AuthUpdateBody(BaseModel):
    name: str = ""


class AuthChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


class AdminPlanBody(BaseModel):
    plan: str


class AdminRoleBody(BaseModel):
    role: str


class AdminBulkUsersBody(BaseModel):
    user_ids: list[int]
    action: str
    value: str | None = None


@app.get("/api/auth/ping")
async def auth_ping():
    return _json_ok({"auth": "real"})


@app.post("/api/auth/register")
async def auth_register(body: AuthRegisterBody, tenant_id: TenantDep):
    email = (body.email or "").strip().lower()
    pwd = str(body.password or "")
    if not email:
        return JSONResponse({"status": "error", "message": "Email обязателен."}, status_code=400)
    if len(pwd) < 6:
        return JSONResponse({"status": "error", "message": "Слишком короткий пароль."}, status_code=400)
    created = await dbmod.create_user(
        email=email,
        password_hash=auth_core.hash_password(pwd),
        name=(body.name or "").strip(),
        role="user",
        plan="free",
        tenant_id=tenant_id,
    )
    if created.get("status") != "ok":
        return JSONResponse(created, status_code=400)
    user = created.get("user") or {}
    token = auth_core.create_access_token(int(user.get("id") or 0), email, "user", tenant_id)
    return _json_ok({"token": token, "user": user})


@app.post("/api/auth/login")
async def auth_login(body: AuthLoginBody, tenant_id: TenantDep):
    email = (body.email or "").strip().lower()
    pwd = str(body.password or "")
    row = await dbmod.get_user_by_email(email, tenant_id=tenant_id)
    if row.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Неверный email или пароль."}, status_code=401)
    user = row.get("user") or {}
    if not auth_core.verify_password(pwd, str(user.get("password_hash") or "")):
        return JSONResponse({"status": "error", "message": "Неверный email или пароль."}, status_code=401)
    if str(user.get("status") or "active") == "banned":
        return JSONResponse({"status": "error", "message": "Пользователь заблокирован."}, status_code=403)
    token = auth_core.create_access_token(int(user.get("id") or 0), email, str(user.get("role") or "user"), tenant_id)
    safe = await dbmod.get_user_by_id(int(user.get("id") or 0), tenant_id=tenant_id)
    return _json_ok({"token": token, "user": safe.get("user")})


@app.get("/api/auth/me")
async def auth_me(tenant_id: TenantDep, current: auth_core.CurrentUser):
    safe = await dbmod.get_user_by_id(current.user_id, tenant_id=tenant_id)
    if safe.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=401)
    return _json_ok({"user": safe.get("user")})


@app.patch("/api/auth/me")
async def auth_update_me(body: AuthUpdateBody, tenant_id: TenantDep, current: auth_core.CurrentUser):
    upd = await dbmod.update_user(current.user_id, name=(body.name or "").strip(), tenant_id=tenant_id)
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    return _json_ok({"user": upd.get("user")})


@app.post("/api/auth/change-password")
async def auth_change_password(
    body: AuthChangePasswordBody,
    tenant_id: TenantDep,
    current: auth_core.CurrentUser,
):
    user_res = await dbmod.get_user_by_email(current.email, tenant_id=tenant_id)
    if user_res.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=401)
    user = user_res.get("user") or {}
    if not auth_core.verify_password(str(body.old_password or ""), str(user.get("password_hash") or "")):
        return JSONResponse({"status": "error", "message": "Старый пароль неверен."}, status_code=400)
    if len(str(body.new_password or "")) < 6:
        return JSONResponse({"status": "error", "message": "Новый пароль слишком короткий."}, status_code=400)
    upd = await dbmod.update_user(
        current.user_id,
        password_hash=auth_core.hash_password(str(body.new_password)),
        tenant_id=tenant_id,
    )
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    return _json_ok({"changed": True})


@app.post("/api/auth/logout")
async def auth_logout():
    return _json_ok({"logged_out": True})


@app.get("/api/admin/users")
async def admin_list_users(tenant_id: TenantDep, _admin: auth_core.AdminUser):
    out = await dbmod.list_users(tenant_id=tenant_id, limit=1000, offset=0)
    if out.get("status") != "ok":
        return JSONResponse(out, status_code=400)
    users = out.get("users") or []
    return _json_ok({"users": users, "total": len(users)})


@app.post("/api/admin/users/{user_id}/ban")
async def admin_ban_user(user_id: int, tenant_id: TenantDep, admin: auth_core.AdminUser):
    if int(user_id) == int(admin.user_id):
        return JSONResponse({"status": "error", "message": "Нельзя заблокировать самого себя."}, status_code=400)
    check = await dbmod.get_user_by_id(user_id, tenant_id=tenant_id)
    if check.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=404)
    upd = await dbmod.update_user(user_id, status="banned", tenant_id=tenant_id)
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    await dbmod.record_admin_user_event(
        admin_user_id=admin.user_id,
        target_user_id=user_id,
        action="status",
        old_value=str((check.get("user") or {}).get("status") or ""),
        new_value="banned",
        tenant_id=tenant_id,
    )
    return _json_ok({"user": upd.get("user")})


@app.post("/api/admin/users/{user_id}/unban")
async def admin_unban_user(user_id: int, tenant_id: TenantDep, _admin: auth_core.AdminUser):
    check = await dbmod.get_user_by_id(user_id, tenant_id=tenant_id)
    if check.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=404)
    old_status = str((check.get("user") or {}).get("status") or "")
    upd = await dbmod.update_user(user_id, status="active", tenant_id=tenant_id)
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    await dbmod.record_admin_user_event(
        admin_user_id=_admin.user_id,
        target_user_id=user_id,
        action="status",
        old_value=old_status,
        new_value="active",
        tenant_id=tenant_id,
    )
    return _json_ok({"user": upd.get("user")})


@app.post("/api/admin/users/{user_id}/plan")
async def admin_change_plan(user_id: int, body: AdminPlanBody, tenant_id: TenantDep, _admin: auth_core.AdminUser):
    check = await dbmod.get_user_by_id(user_id, tenant_id=tenant_id)
    if check.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=404)
    old_plan = str((check.get("user") or {}).get("plan") or "")
    new_plan = str(body.plan or "").lower()
    upd = await dbmod.update_user(user_id, plan=new_plan, tenant_id=tenant_id)
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    await dbmod.record_admin_user_event(
        admin_user_id=_admin.user_id,
        target_user_id=user_id,
        action="plan",
        old_value=old_plan,
        new_value=new_plan,
        tenant_id=tenant_id,
    )
    return _json_ok({"user": upd.get("user")})


@app.post("/api/admin/users/{user_id}/role")
async def admin_change_role(user_id: int, body: AdminRoleBody, tenant_id: TenantDep, admin: auth_core.AdminUser):
    if int(user_id) == int(admin.user_id):
        return JSONResponse({"status": "error", "message": "Нельзя изменить роль самому себе."}, status_code=400)
    role = str(body.role or "").strip().lower()
    if role not in ("user", "admin"):
        return JSONResponse({"status": "error", "message": "Недопустимая роль. Используйте user/admin."}, status_code=400)
    check = await dbmod.get_user_by_id(user_id, tenant_id=tenant_id)
    if check.get("status") != "ok":
        return JSONResponse({"status": "error", "message": "Пользователь не найден."}, status_code=404)
    old_role = str((check.get("user") or {}).get("role") or "")
    upd = await dbmod.update_user(user_id, role=role, tenant_id=tenant_id)
    if upd.get("status") != "ok":
        return JSONResponse(upd, status_code=400)
    await dbmod.record_admin_user_event(
        admin_user_id=admin.user_id,
        target_user_id=user_id,
        action="role",
        old_value=old_role,
        new_value=role,
        tenant_id=tenant_id,
    )
    return _json_ok({"user": upd.get("user")})


@app.post("/api/admin/users/bulk")
async def admin_bulk_users(body: AdminBulkUsersBody, tenant_id: TenantDep, admin: auth_core.AdminUser):
    ids = sorted({int(x) for x in (body.user_ids or []) if int(x) > 0})
    if not ids:
        return JSONResponse({"status": "error", "message": "Выберите пользователей."}, status_code=400)
    action = str(body.action or "").strip().lower()
    if action not in {"ban", "unban", "plan", "role"}:
        return JSONResponse({"status": "error", "message": "Недопустимое действие bulk."}, status_code=400)
    if action in {"plan", "role"} and not str(body.value or "").strip():
        return JSONResponse({"status": "error", "message": "Для этого действия нужно значение value."}, status_code=400)

    changed = 0
    skipped = 0
    for uid in ids:
        if uid == int(admin.user_id):
            skipped += 1
            continue
        check = await dbmod.get_user_by_id(uid, tenant_id=tenant_id)
        if check.get("status") != "ok":
            skipped += 1
            continue
        user = check.get("user") or {}
        old_val = ""
        upd = {"status": "error"}
        if action == "ban":
            old_val = str(user.get("status") or "")
            upd = await dbmod.update_user(uid, status="banned", tenant_id=tenant_id)
            if upd.get("status") == "ok":
                await dbmod.record_admin_user_event(admin.user_id, uid, "status", old_val, "banned", tenant_id=tenant_id)
        elif action == "unban":
            old_val = str(user.get("status") or "")
            upd = await dbmod.update_user(uid, status="active", tenant_id=tenant_id)
            if upd.get("status") == "ok":
                await dbmod.record_admin_user_event(admin.user_id, uid, "status", old_val, "active", tenant_id=tenant_id)
        elif action == "plan":
            new_plan = str(body.value or "").strip().lower()
            old_val = str(user.get("plan") or "")
            upd = await dbmod.update_user(uid, plan=new_plan, tenant_id=tenant_id)
            if upd.get("status") == "ok":
                await dbmod.record_admin_user_event(admin.user_id, uid, "plan", old_val, new_plan, tenant_id=tenant_id)
        elif action == "role":
            new_role = str(body.value or "").strip().lower()
            old_val = str(user.get("role") or "")
            upd = await dbmod.update_user(uid, role=new_role, tenant_id=tenant_id)
            if upd.get("status") == "ok":
                await dbmod.record_admin_user_event(admin.user_id, uid, "role", old_val, new_role, tenant_id=tenant_id)
        if upd.get("status") == "ok":
            changed += 1
        else:
            skipped += 1
    return _json_ok({"changed": changed, "skipped": skipped})


@app.get("/api/admin/users/audit")
async def admin_users_audit(tenant_id: TenantDep, _admin: auth_core.AdminUser, limit: int = 100, offset: int = 0):
    out = await dbmod.list_admin_user_events(tenant_id=tenant_id, limit=limit, offset=offset)
    if out.get("status") != "ok":
        return JSONResponse(out, status_code=400)
    return _json_ok({"events": out.get("events") or [], "count": out.get("count", 0)})


@app.get("/api/admin/stats")
async def admin_stats(tenant_id: TenantDep, _admin: auth_core.AdminUser):
    st = await dbmod.user_stats(tenant_id=tenant_id)
    if st.get("status") != "ok":
        return JSONResponse(st, status_code=400)
    return _json_ok(
        {
            "total_users": st.get("total_users", 0),
            "by_plan": st.get("by_plan", {}),
            "by_status": st.get("by_status", {}),
        }
    )


def _load_arbitrage_monitor_cfg() -> dict[str, Any]:
    """Read optional arbitrage monitor settings from neo_settings.json."""
    try:
        path = persisted_cfg.settings_file_path()
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        cfg = raw.get("arbitrage_monitor")
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _load_arbitrage_alert_state() -> dict[str, Any]:
    try:
        if not _ARBITRAGE_ALERT_STATE_FILE.is_file():
            return {"sent_ids": []}
        raw = json.loads(_ARBITRAGE_ALERT_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            sent = raw.get("sent_ids")
            if isinstance(sent, list):
                return {"sent_ids": [str(x) for x in sent if str(x).strip()]}
        return {"sent_ids": []}
    except Exception:
        return {"sent_ids": []}


def _save_arbitrage_alert_state(state: dict[str, Any]) -> None:
    try:
        _ARBITRAGE_ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ARBITRAGE_ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("save_arbitrage_alert_state: %s", exc)


def _load_risk_labels() -> list[dict[str, Any]]:
    try:
        if not _RISK_LABELS_FILE.is_file():
            return []
        raw = json.loads(_RISK_LABELS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save_risk_labels(rows: list[dict[str, Any]]) -> None:
    try:
        _RISK_LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RISK_LABELS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("save_risk_labels: %s", exc)


async def _send_arbitrage_alerts(
    *,
    results: dict[str, list[dict[str, Any]]],
    score_threshold: int,
    max_items: int,
) -> int:
    """Send Telegram alerts for newly found high-score / watchlist videos."""
    from core import notifier as _notifier

    if not _notifier.is_configured():
        return 0

    state = _load_arbitrage_alert_state()
    sent_ids = {str(x) for x in state.get("sent_ids", []) if str(x).strip()}
    candidates: list[dict[str, Any]] = []
    for rows in results.values():
        for v in rows:
            vid = str(v.get("id") or "").strip()
            if not vid or vid in sent_ids:
                continue
            score = int(v.get("arb_score") or 0)
            if bool(v.get("watchlist_hit")) or score >= score_threshold:
                candidates.append(v)

    if not candidates:
        return 0

    candidates.sort(
        key=lambda v: (
            int(v.get("watchlist_hit") is True),
            int(v.get("arb_score") or 0),
            int(v.get("view_count") or 0),
        ),
        reverse=True,
    )
    selected = candidates[: max(1, min(max_items, 10))]

    lines = ["⚡ <b>Arbitrage monitor: новые заливы</b>"]
    for v in selected:
        title = str(v.get("title") or "—").replace("<", "&lt;").replace(">", "&gt;")
        url = str(v.get("url") or "").strip()
        game = str(v.get("game_label") or v.get("game") or "")
        score = int(v.get("arb_score") or 0)
        views = int(v.get("view_count") or 0)
        wl = " · 👥 watchlist" if bool(v.get("watchlist_hit")) else ""
        if url:
            lines.append(f"• <b>{game}</b> · {score}/100 · {views:,} views{wl}\n<a href=\"{url}\">{title[:140]}</a>")
        else:
            lines.append(f"• <b>{game}</b> · {score}/100 · {views:,} views{wl}\n{title[:140]}")

    sent = await _notifier.send_text("\n".join(lines))
    if not sent:
        return 0

    sent_ids.update(str(v.get("id") or "") for v in selected if str(v.get("id") or "").strip())
    keep = list(sent_ids)[-4000:]
    _save_arbitrage_alert_state({"sent_ids": keep})
    return len(selected)


async def _ensure_demo_auth_users() -> None:
    """
    Локальные demo-аккаунты для страницы логина (не трогаем существующие записи).
    Создаются только при NEORENDER_DEV_SEED=1 — никогда в production.
    """
    if os.environ.get("NEORENDER_DEV_SEED", "").strip() != "1":
        return
    try:
        demo_users = [
            {
                "email": "admin@neorender.pro",
                "password": "admin123",
                "name": "Admin",
                "role": "admin",
                "plan": "enterprise",
            },
            {
                "email": "user@neorender.pro",
                "password": "user123",
                "name": "Demo User",
                "role": "user",
                "plan": "pro",
            },
        ]
        for du in demo_users:
            existing = await dbmod.get_user_by_email(du["email"], tenant_id="default")
            if existing.get("status") == "ok":
                continue
            await dbmod.create_user(
                email=du["email"],
                password_hash=auth_core.hash_password(du["password"]),
                name=du["name"],
                role=du["role"],
                plan=du["plan"],
                tenant_id="default",
            )
    except Exception as exc:
        logger.warning("ensure_demo_auth_users: %s", exc)


def _tenant_for_media_stream(
    x_tenant_id: str | None,
    tenant_query: str | None,
) -> str:
    """Для <video src> без кастомных заголовков — tenant в query; иначе X-Tenant-ID."""
    if x_tenant_id and str(x_tenant_id).strip():
        return normalize_tenant_id(x_tenant_id)
    if tenant_query and str(tenant_query).strip():
        return normalize_tenant_id(tenant_query)
    return tenant_id_from_environ()


def _pipeline_for(tenant_id: str) -> AutomationPipeline:
    tid = normalize_tenant_id(tenant_id)
    if tid not in _pipelines:
        pipe = AutomationPipeline(
            tenant_id=tid,
            groq_api_key=os.environ.get("GROQ_API_KEY"),
        )
        # Восстанавливаем сохранённые настройки уникализатора из neo_settings.json.
        saved = persisted_cfg.load_uniqualizer_settings()
        if saved:
            try:
                pipe.update_uniqualizer_settings(**{k: v for k, v in saved.items()})
            except Exception as exc:
                logger.warning("_pipeline_for: не удалось применить сохранённые настройки: %s", exc)
        _pipelines[tid] = pipe
    return _pipelines[tid]


def _json_ok(data: dict | None = None):
    out = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _is_rate_limited(scope: str, tenant_id: str, limit: int) -> bool:
    now = time.monotonic()
    key = (scope, normalize_tenant_id(tenant_id))
    q = _rate_buckets[key]
    while q and (now - q[0]) > _RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _schedule_profile_job_execution(
    background_tasks: BackgroundTasks | None,
    *,
    job_id: int,
    tenant_id: str,
    db_path: str | None = None,
) -> None:
    async def _runner() -> None:
        await profile_job_runner.run_profile_job(job_id, tenant_id=tenant_id, db_path=db_path)

    if background_tasks is not None:
        background_tasks.add_task(_runner)
        return
    asyncio.create_task(_runner())




@app.get("/api/health")
async def health(tenant_id: TenantDep, _user: auth_core.CurrentUser):
    pipe = _pipeline_for(tenant_id)
    try:
        disk = shutil.disk_usage(Path("."))
        disk_free_gb = round(disk.free / (1024 ** 3), 2)
        disk_total_gb = round(disk.total / (1024 ** 3), 2)
    except OSError:
        disk_free_gb = None
        disk_total_gb = None
    return _json_ok(
        {
            "service": "NeoRender Pro",
            "tenant_id": tenant_id,
            "pipeline_running": bool(pipe.is_running),
            "workers": {
                "scheduler": bool(getattr(pipe, "scheduler", None) and pipe.scheduler.is_running),
                "analytics_poller": bool(getattr(pipe, "analytics_poller", None) and pipe.analytics_poller.is_running),
            },
            "disk": {
                "free_gb": disk_free_gb,
                "total_gb": disk_total_gb,
            },
        }
    )


@app.get("/api/health/workers")
async def health_workers(tenant_id: TenantDep, _user: auth_core.CurrentUser):
    pipe = _pipeline_for(tenant_id)
    return _json_ok(
        {
            "tenant_id": tenant_id,
            "pipeline_running": bool(pipe.is_running),
            "scheduler_running": bool(getattr(pipe, "scheduler", None) and pipe.scheduler.is_running),
            "analytics_poller_running": bool(
                getattr(pipe, "analytics_poller", None) and pipe.analytics_poller.is_running
            ),
            "queue_size": int(pipe.queue.qsize()),
            "metrics": pipe.get_metrics_snapshot() if hasattr(pipe, "get_metrics_snapshot") else {},
            "hot_folder": pipe.hot_folder.get_status() if hasattr(pipe, "hot_folder") else {},
        }
    )


@app.get("/api/system/status")
async def system_status(tenant_id: TenantDep, _user: auth_core.CurrentUser):
    """
    Сводный статус для UI: ключи, overlay, ffmpeg, API AdsPower.
    Не выполняет тяжёлых действий, только быстрые проверки.
    """
    try:
        pipe_ov = _pipeline_for(tenant_id).overlay_media_path
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        ff_cmd = (os.environ.get("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"
        ffmpeg_resolvable = (
            bool(shutil.which(ff_cmd)) if ff_cmd == "ffmpeg" else Path(ff_cmd).is_file()
        )
        import time as _time
        _cache = _ffmpeg_version_cache
        if _cache.get("bin") != ff_cmd or _time.monotonic() - _cache.get("ts", 0) > _FFMPEG_CACHE_TTL:
            ffmpeg_runs, ffmpeg_version = await ffmpeg_runner.probe_ffmpeg_runs(ff_cmd)
            _cache.update({"bin": ff_cmd, "runs": ffmpeg_runs, "version": ffmpeg_version, "ts": _time.monotonic()})
        else:
            ffmpeg_runs, ffmpeg_version = _cache["runs"], _cache["version"]
        return _json_ok(
            {
                "tenant_id": tenant_id,
                "overlay_exists": pipe_ov.is_file(),
                "overlay_path": str(pipe_ov.resolve()),
                "groq_configured": bool(groq_key),
                "adspower_api_base": adspower_sync.get_adspower_base(),
                "adspower_use_auth": adspower_sync.is_adspower_auth_enabled(),
                "adspower_api_key_configured": bool(adspower_sync.get_adspower_api_key()),
                "ffmpeg_found": ffmpeg_resolvable,
                "ffmpeg_runs": ffmpeg_runs,
                "ffmpeg_version": ffmpeg_version,
                "ffmpeg_bin": ff_cmd,
            }
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось получить системный статус."}


@app.get("/api/system/ffmpeg-config")
async def ffmpeg_config(_user: auth_core.CurrentUser):
    """Текущая конфигурация FFmpeg пайплайна (для диагностики в UI)."""
    try:
        ffmpeg_bin_cfg = (os.environ.get("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"
        ffprobe_bin_cfg = (os.environ.get("FFPROBE_PATH") or "").strip() or "auto(ffprobe рядом с ffmpeg)"
        timeout_cfg = (os.environ.get("NEORENDER_FFMPEG_TIMEOUT_SEC") or "").strip() or "default(14400)"
        vsync_mode = (os.environ.get("NEORENDER_VSYNC_MODE") or "").strip() or "off"
        disable_nvenc = (os.environ.get("NEORENDER_DISABLE_NVENC") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        return _json_ok(
            {
                "ffmpeg_bin": ffmpeg_bin_cfg,
                "ffprobe_bin": ffprobe_bin_cfg,
                "ffmpeg_timeout_sec": timeout_cfg,
                "vsync_mode": vsync_mode,
                "nvenc_disabled": disable_nvenc,
                "hardened_builder": True,
            }
        )
    except Exception as exc:
        logger.exception("ffmpeg_config: %s", exc)
        return {"status": "error", "message": "Не удалось получить FFmpeg-конфиг."}


@app.get("/api/integrations/ping")
async def integrations_ping(tenant_id: TenantDep):
    """
    Живая проверка Groq (GET /v1/models) и AdsPower (локальный API).
    Проверки независимы: сбой антидетекта не ломает статус Groq и наоборот.
    """
    pipe = _pipeline_for(tenant_id)
    groq_key = (pipe.groq_api_key or os.environ.get("GROQ_API_KEY") or "").strip()

    async def _ping_groq() -> dict:
        try:
            r = await ai_copywriter.ping_groq_api(groq_key)
            return {
                "live": bool(r.get("live")),
                "message": str(r.get("message") or ""),
            }
        except Exception as exc:
            logger.warning("integrations_ping groq: %s", exc)
            return {
                "live": False,
                "message": "Не удалось связаться с Groq (сеть или таймаут)",
            }

    async def _ping_adspower() -> dict:
        try:
            ads = await adspower_sync.verify_connection()
            ads_ok = ads.get("status") == "ok"
            return {
                "live": ads_ok,
                "message": str(ads.get("message") or ("Связь OK" if ads_ok else "Нет ответа")),
                "profiles_count": ads.get("profiles_count") if ads_ok else None,
            }
        except Exception as exc:
            logger.warning("integrations_ping adspower: %s", exc)
            return {
                "live": False,
                "message": "AdsPower не отвечает (клиент запущен? верный порт в настройках?)",
                "profiles_count": None,
            }

    groq_out, ads_out = await asyncio.gather(_ping_groq(), _ping_adspower())
    return _json_ok({"groq": groq_out, "adspower": ads_out})


class AdsPowerConfigBody(BaseModel):
    """Настройки Local API AdsPower."""

    api_base: str = ""
    api_key: str = ""
    use_auth: bool = False


@app.get("/api/adspower/status")
async def adspower_status(_user: auth_core.CurrentUser):
    """Текущие настройки API AdsPower (без проверки сети)."""
    try:
        return adspower_sync.get_api_settings_status()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось прочитать настройки."}


@app.post("/api/adspower/settings")
async def adspower_save_settings(body: AdsPowerConfigBody, _user: auth_core.AdminUser):
    """Сохранить адрес API, ключ и режим Bearer-авторизации для Local API AdsPower."""
    try:
        r = adspower_sync.configure_api_settings(
            url=body.api_base.strip() or None,
            api_key=body.api_key,
            use_auth=body.use_auth,
        )
        if r.get("status") == "ok":
            persisted_cfg.persist_current_settings()
        return r
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка сохранения настроек AdsPower."}


@app.get("/api/adspower/verify")
async def adspower_verify(tenant_id: TenantDep, sync_db: bool = False):
    """
    Проверка связи с AdsPower. sync_db=true — дополнительно записать профили в SQLite.
    Ответ: status, message, profiles_count, api_base, synced_to_db.
    """
    try:
        if sync_db:
            return await adspower_sync.verify_and_sync_db(tenant_id=tenant_id)
        return await adspower_sync.verify_connection()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось выполнить проверку AdsPower."}


@app.post("/api/profiles/sync")
async def profiles_sync(tenant_id: TenantDep):
    try:
        return await adspower_sync.fetch_profiles_and_sync_db(tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("%s", exc)
        return JSONResponse(
            {"status": "error", "message": "Не удалось синхронизировать профили."},
            status_code=500,
        )


@app.get("/api/profiles")
async def profiles_list(tenant_id: TenantDep):
    try:
        return await dbmod.list_profiles(tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка чтения профилей."}


class WarmupRunBody(BaseModel):
    profile_id: str
    intensity: str = "medium"          # light | medium | deep
    niche_keywords: list[str] = []
    shorts_retention_mode: str = "mixed"  # mixed | looper | engaged | casual | bouncer


class AdsPowerProfilePatchBody(BaseModel):
    profile_name: str | None = None
    geo: str | None = None
    language: str | None = None
    tags_json: str | None = None
    notes: str | None = None
    platform: str | None = None
    status: str | None = None


class ProfileLinkBody(BaseModel):
    adspower_profile_id: str
    youtube_channel_id: str | None = None
    youtube_channel_handle: str | None = None
    geo: str | None = None
    offer_name: str | None = None
    operator_label: str | None = None
    is_active: bool | None = None


class ProfileJobBody(BaseModel):
    adspower_profile_id: str
    job_type: str
    scheduled_at: str | None = None
    payload: dict[str, object] = {}
    run_now: bool = True


class PublishJobBody(BaseModel):
    task_id: int
    adspower_profile_id: str
    scheduled_at: str | None = None
    title: str = ""
    description: str = ""
    comment: str = ""
    tags: list[str] = []
    thumbnail_path: str | None = None
    run_now: bool = True


# ---------------------------------------------------------------------------
# In-memory store for background warmup jobs.
# Each entry: {status, profile_id, intensity, tenant_id, stats, actions_log,
#              message, started_at, finished_at, cancel_event, task}
# ---------------------------------------------------------------------------
_WARMUP_JOBS: dict[str, dict] = {}


@app.post("/api/warmup/start")
async def warmup_start(tenant_id: TenantDep, body: WarmupRunBody):
    """Запустить прогрев в фоне. Возвращает job_id для опроса статуса."""
    import uuid as _uuid
    import time as _time

    job_id = str(_uuid.uuid4())
    cancel_event = asyncio.Event()

    _WARMUP_JOBS[job_id] = {
        "status": "running",
        "profile_id": body.profile_id,
        "intensity": body.intensity,
        "tenant_id": tenant_id,
        "stats": {},
        "actions_log": [],
        "message": None,
        "started_at": _time.time(),
        "finished_at": None,
        "cancel_event": cancel_event,
    }

    async def _run() -> None:
        try:
            from core import warmup_automator as _wu
            result = await _wu.run_warmup_for_profile(
                profile_id=body.profile_id,
                intensity=body.intensity,
                niche_keywords=body.niche_keywords or None,
                tenant_id=tenant_id,
                cancel_event=cancel_event,
                shorts_retention_mode=body.shorts_retention_mode,
            )
        except Exception as exc:
            logger.exception("warmup background job %s: %s", job_id, exc)
            result = {"status": "error", "message": str(exc)}

        job = _WARMUP_JOBS.get(job_id)
        if job is None:
            return
        cancelled = cancel_event.is_set()
        job["status"] = "cancelled" if cancelled else result.get("status", "error")
        job["stats"] = result.get("stats") or {}
        job["actions_log"] = result.get("actions_log") or []
        job["message"] = result.get("message")
        job["finished_at"] = _time.time()

    asyncio.create_task(_run())
    return _json_ok({"job_id": job_id, "status": "running"})


@app.get("/api/warmup/status/{job_id}")
async def warmup_status(job_id: str, tenant_id: TenantDep):
    """Текущий статус / частичные результаты фонового прогрева."""
    job = _WARMUP_JOBS.get(job_id)
    if job is None:
        return JSONResponse({"status": "error", "message": "Задача не найдена."}, status_code=404)
    if job["tenant_id"] != tenant_id:
        return JSONResponse({"status": "error", "message": "Нет доступа."}, status_code=403)
    return _json_ok({
        "job_id":       job_id,
        "status":       job["status"],
        "profile_id":   job["profile_id"],
        "intensity":    job["intensity"],
        "stats":        job["stats"],
        "actions_log":  job["actions_log"],
        "message":      job["message"],
        "started_at":   job["started_at"],
        "finished_at":  job["finished_at"],
    })


@app.delete("/api/warmup/cancel/{job_id}")
async def warmup_cancel(job_id: str, tenant_id: TenantDep):
    """Отменить фоновый прогрев."""
    job = _WARMUP_JOBS.get(job_id)
    if job is None:
        return JSONResponse({"status": "error", "message": "Задача не найдена."}, status_code=404)
    if job["tenant_id"] != tenant_id:
        return JSONResponse({"status": "error", "message": "Нет доступа."}, status_code=403)
    if job["status"] == "running":
        job["cancel_event"].set()
        job["status"] = "cancelling"
    return _json_ok({"job_id": job_id, "status": job["status"]})


@app.get("/api/warmup/history")
async def warmup_history(
    tenant_id: TenantDep,
    profile_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """История сессий прогрева из БД."""
    try:
        result = await dbmod.list_warmup_sessions(
            profile_id=profile_id,
            limit=limit,
            tenant_id=tenant_id,
        )
        return result
    except Exception as exc:
        logger.exception("warmup_history: %s", exc)
        return {"status": "error", "message": "Ошибка получения истории прогрева."}


# Keep the old blocking endpoint as an alias for backwards compatibility.
@app.post("/api/warmup/run")
async def warmup_run(tenant_id: TenantDep, body: WarmupRunBody):
    """[Устарело] Блокирующий запуск прогрева. Используйте /api/warmup/start."""
    try:
        from core import warmup_automator as _wu
        result = await _wu.run_warmup_for_profile(
            profile_id=body.profile_id,
            intensity=body.intensity,
            niche_keywords=body.niche_keywords or None,
            tenant_id=tenant_id,
            shorts_retention_mode=body.shorts_retention_mode,
        )
        return result
    except Exception as exc:
        logger.exception("warmup_run: %s", exc)
        return {"status": "error", "message": "Ошибка запуска прогрева."}


@app.get("/api/warmup/intensities")
async def warmup_intensities():
    """Список доступных уровней интенсивности прогрева."""
    return {
        "status": "ok",
        "intensities": [
            {"key": "light",  "label": "Лёгкий",   "desc": "2–4 видео, 1–2 поиска, ~15 мин"},
            {"key": "medium", "label": "Средний",   "desc": "4–7 видео, 2–4 поиска, ~30 мин"},
            {"key": "deep",   "label": "Глубокий",  "desc": "8–14 видео, 4–7 поисков, ~60 мин"},
        ],
    }


@app.get("/api/adspower/profiles")
async def adspower_profiles_list(tenant_id: TenantDep, status: str | None = None):
    try:
        pipe = _pipeline_for(tenant_id)
        return await adspower_profiles.list_profiles(tenant_id=tenant_id, status_filter=status, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profiles_list: %s", exc)
        return {"status": "error", "message": "Не удалось загрузить реестр профилей AdsPower."}


@app.post("/api/adspower/profiles/sync")
async def adspower_profiles_sync(tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await adspower_profiles.sync_profiles_from_adspower(tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profiles_sync: %s", exc)
        return {"status": "error", "message": "Не удалось синхронизировать профили AdsPower."}


@app.patch("/api/adspower/profiles/{profile_id}")
async def adspower_profile_patch(profile_id: str, tenant_id: TenantDep, body: AdsPowerProfilePatchBody):
    try:
        pipe = _pipeline_for(tenant_id)
        fields = body.model_dump(exclude_none=True)
        return await adspower_profiles.assign_profile_metadata(
            profile_id,
            tenant_id=tenant_id,
            db_path=pipe.db_path,
            **fields,
        )
    except Exception as exc:
        logger.exception("adspower_profile_patch: %s", exc)
        return {"status": "error", "message": "Не удалось обновить профиль AdsPower."}


@app.post("/api/adspower/profiles/{profile_id}/pause")
async def adspower_profile_pause(profile_id: str, tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await adspower_profiles.update_profile_status(profile_id, "paused", tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profile_pause: %s", exc)
        return {"status": "error", "message": "Не удалось поставить профиль на паузу."}


@app.post("/api/adspower/profiles/{profile_id}/resume")
async def adspower_profile_resume(profile_id: str, tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await adspower_profiles.update_profile_status(profile_id, "ready", tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profile_resume: %s", exc)
        return {"status": "error", "message": "Не удалось вернуть профиль в ready."}


@app.post("/api/adspower/profiles/{profile_id}/launch-test")
async def adspower_profile_launch_test(profile_id: str, tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        health = await adspower_launcher.check_profile_health(profile_id, tenant_id=tenant_id)
        if health.get("status") == "ok":
            await dbmod.update_adspower_profile_launch(profile_id, tenant_id=tenant_id, db_path=pipe.db_path)
            await adspower_profiles.record_profile_event(
                profile_id,
                "launch_test",
                message="Тест запуска профиля выполнен успешно.",
                payload=health.get("data") if isinstance(health.get("data"), dict) else {},
                tenant_id=tenant_id,
                db_path=pipe.db_path,
            )
        return health
    except Exception as exc:
        logger.exception("adspower_profile_launch_test: %s", exc)
        return {"status": "error", "message": "Не удалось выполнить launch-test профиля."}


@app.get("/api/adspower/profiles/{profile_id}/events")
async def adspower_profile_events(profile_id: str, tenant_id: TenantDep, limit: int = 50):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.list_profile_events(profile_id, tenant_id=tenant_id, limit=limit, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profile_events: %s", exc)
        return {"status": "error", "message": "Не удалось загрузить события профиля."}


@app.get("/api/adspower/profile-links")
async def adspower_profile_links_list(tenant_id: TenantDep, adspower_profile_id: str | None = None):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.list_profile_channel_links(tenant_id=tenant_id, adspower_profile_id=adspower_profile_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profile_links_list: %s", exc)
        return {"status": "error", "message": "Не удалось загрузить привязки профилей."}


@app.post("/api/adspower/profile-links")
async def adspower_profile_links_create(tenant_id: TenantDep, body: ProfileLinkBody):
    try:
        pipe = _pipeline_for(tenant_id)
        created = await dbmod.create_profile_channel_link(
            body.adspower_profile_id,
            youtube_channel_id=body.youtube_channel_id,
            youtube_channel_handle=body.youtube_channel_handle,
            geo=body.geo,
            offer_name=body.offer_name,
            operator_label=body.operator_label,
            tenant_id=tenant_id,
            db_path=pipe.db_path,
        )
        if created.get("status") == "ok":
            await adspower_profiles.record_profile_event(
                body.adspower_profile_id,
                "link_created",
                message="Добавлена привязка профиля к каналу/гео.",
                payload=body.model_dump(exclude_none=True),
                tenant_id=tenant_id,
                db_path=pipe.db_path,
            )
        return created
    except Exception as exc:
        logger.exception("adspower_profile_links_create: %s", exc)
        return {"status": "error", "message": "Не удалось создать привязку профиля."}


@app.patch("/api/adspower/profile-links/{link_id}")
async def adspower_profile_links_patch(link_id: int, tenant_id: TenantDep, body: ProfileLinkBody):
    try:
        pipe = _pipeline_for(tenant_id)
        fields = body.model_dump(exclude_none=True)
        fields.pop("adspower_profile_id", None)
        return await dbmod.patch_profile_channel_link(link_id, tenant_id=tenant_id, db_path=pipe.db_path, **fields)
    except Exception as exc:
        logger.exception("adspower_profile_links_patch: %s", exc)
        return {"status": "error", "message": "Не удалось обновить привязку профиля."}


@app.get("/api/adspower/profile-jobs")
async def adspower_profile_jobs_list(
    tenant_id: TenantDep,
    job_type: str | None = None,
    status: str | None = None,
    adspower_profile_id: str | None = None,
    limit: int = 100,
):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.list_profile_jobs(
            tenant_id=tenant_id,
            job_type=job_type,
            status=status,
            adspower_profile_id=adspower_profile_id,
            limit=limit,
            db_path=pipe.db_path,
        )
    except Exception as exc:
        logger.exception("adspower_profile_jobs_list: %s", exc)
        return {"status": "error", "message": "Не удалось загрузить задачи профилей."}


@app.post("/api/adspower/profile-jobs")
async def adspower_profile_jobs_create(
    tenant_id: TenantDep,
    body: ProfileJobBody,
    background_tasks: BackgroundTasks,
):
    try:
        pipe = _pipeline_for(tenant_id)
        created = await dbmod.create_profile_job(
            body.adspower_profile_id,
            body.job_type,
            payload_json=json.dumps(body.payload, ensure_ascii=False),
            scheduled_at=body.scheduled_at,
            tenant_id=tenant_id,
            db_path=pipe.db_path,
        )
        if created.get("status") != "ok":
            return created
        job_id = int(created.get("id") or 0)
        await adspower_profiles.record_profile_event(
            body.adspower_profile_id,
            "job_created",
                message=f"Создана задача профиля {body.job_type}.",
                payload={"job_id": job_id, "job_type": body.job_type, "scheduled_at": body.scheduled_at},
                tenant_id=tenant_id,
                db_path=pipe.db_path,
            )
        if body.run_now and not body.scheduled_at and job_id > 0:
            _schedule_profile_job_execution(
                background_tasks,
                job_id=job_id,
                tenant_id=tenant_id,
                db_path=str(pipe.db_path) if pipe.db_path else None,
            )
        return _json_ok({"id": job_id, "job_status": created.get("job_status")})
    except Exception as exc:
        logger.exception("adspower_profile_jobs_create: %s", exc)
        return {"status": "error", "message": "Не удалось создать задачу профиля."}


@app.post("/api/adspower/profile-jobs/{job_id}/retry")
async def adspower_profile_jobs_retry(job_id: int, tenant_id: TenantDep, background_tasks: BackgroundTasks):
    try:
        pipe = _pipeline_for(tenant_id)
        retried = await dbmod.retry_profile_job(job_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if retried.get("status") == "ok":
            _schedule_profile_job_execution(
                background_tasks,
                job_id=job_id,
                tenant_id=tenant_id,
                db_path=str(pipe.db_path) if pipe.db_path else None,
            )
        return retried
    except Exception as exc:
        logger.exception("adspower_profile_jobs_retry: %s", exc)
        return {"status": "error", "message": "Не удалось повторить задачу профиля."}


@app.post("/api/adspower/profile-jobs/{job_id}/cancel")
async def adspower_profile_jobs_cancel(job_id: int, tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.cancel_profile_job(job_id, tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profile_jobs_cancel: %s", exc)
        return {"status": "error", "message": "Не удалось отменить задачу профиля."}


@app.post("/api/publish/jobs")
async def publish_jobs_create(
    tenant_id: TenantDep,
    body: PublishJobBody,
    background_tasks: BackgroundTasks,
):
    try:
        pipe = _pipeline_for(tenant_id)
        task = await dbmod.get_task_by_id(body.task_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if task.get("status") != "ok":
            return JSONResponse({"status": "error", "message": "Задача рендера не найдена."}, status_code=404)
        row = task.get("task") or {}
        if str(row.get("status") or "") != "success":
            return JSONResponse(
                {"status": "error", "message": "Publish job можно создавать только для успешно отрендеренной задачи."},
                status_code=400,
            )
        payload = {
            "task_id": body.task_id,
            "title": body.title,
            "description": body.description,
            "comment": body.comment,
            "tags": body.tags,
            "thumbnail_path": body.thumbnail_path,
        }
        created = await dbmod.create_profile_job(
            body.adspower_profile_id,
            "publish",
            payload_json=json.dumps(payload, ensure_ascii=False),
            scheduled_at=body.scheduled_at,
            tenant_id=tenant_id,
            db_path=pipe.db_path,
        )
        if created.get("status") != "ok":
            return created
        job_id = int(created.get("id") or 0)
        await adspower_profiles.record_profile_event(
            body.adspower_profile_id,
            "publish_job_created",
            message=f"Создана publish-задача для task #{body.task_id}.",
            payload={"job_id": job_id, "task_id": body.task_id},
            tenant_id=tenant_id,
            db_path=pipe.db_path,
        )
        if body.run_now and not body.scheduled_at and job_id > 0:
            _schedule_profile_job_execution(
                background_tasks,
                job_id=job_id,
                tenant_id=tenant_id,
                db_path=str(pipe.db_path) if pipe.db_path else None,
            )
        return _json_ok({"id": job_id, "job_status": created.get("job_status")})
    except Exception as exc:
        logger.exception("publish_jobs_create: %s", exc)
        return {"status": "error", "message": "Не удалось создать publish job."}


@app.get("/api/publish/jobs")
async def publish_jobs_list(
    tenant_id: TenantDep,
    status: str | None = None,
    adspower_profile_id: str | None = None,
    limit: int = 100,
):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.list_profile_jobs(
            tenant_id=tenant_id,
            job_type="publish",
            status=status,
            adspower_profile_id=adspower_profile_id,
            limit=limit,
            db_path=pipe.db_path,
        )
    except Exception as exc:
        logger.exception("publish_jobs_list: %s", exc)
        return {"status": "error", "message": "Не удалось загрузить publish jobs."}


@app.post("/api/publish/jobs/{job_id}/retry")
async def publish_jobs_retry(job_id: int, tenant_id: TenantDep, background_tasks: BackgroundTasks):
    try:
        pipe = _pipeline_for(tenant_id)
        retried = await dbmod.retry_profile_job(job_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if retried.get("status") == "ok":
            _schedule_profile_job_execution(
                background_tasks,
                job_id=job_id,
                tenant_id=tenant_id,
                db_path=str(pipe.db_path) if pipe.db_path else None,
            )
        return retried
    except Exception as exc:
        logger.exception("publish_jobs_retry: %s", exc)
        return {"status": "error", "message": "Не удалось повторить publish job."}


@app.post("/api/publish/jobs/{job_id}/cancel")
async def publish_jobs_cancel(job_id: int, tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.cancel_profile_job(job_id, tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("publish_jobs_cancel: %s", exc)
        return {"status": "error", "message": "Не удалось отменить publish job."}


@app.get("/api/system/adspower-sync-status")
async def adspower_sync_status(tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.get_adspower_sync_status(tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_sync_status: %s", exc)
        return {"status": "error", "message": "Не удалось получить статус синхронизации AdsPower."}


@app.get("/api/system/profiles-health")
async def adspower_profiles_health(tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.get_profiles_health(tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("adspower_profiles_health: %s", exc)
        return {"status": "error", "message": "Не удалось получить статистику профилей."}


@app.get("/api/tasks")
async def tasks_list(tenant_id: TenantDep, limit: int = 100):
    try:
        pipe = _pipeline_for(tenant_id)
        return await dbmod.list_tasks(limit=limit, tenant_id=tenant_id, db_path=pipe.db_path)
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка чтения задач."}


class CreateTaskBody(BaseModel):
    original_video: str
    target_profile: str = ""
    render_only: bool = False
    # Если задан — вшивается в эту задачу; иначе берётся из настроек пайплайна.
    subtitle: str | None = None
    template: str | None = None


@app.post("/api/tasks")
async def tasks_create(tenant_id: TenantDep, body: CreateTaskBody):
    try:
        if _is_rate_limited("tasks_create", tenant_id, _TASK_CREATE_RATE_LIMIT):
            return JSONResponse(
                {"status": "error", "message": "Слишком много запросов на создание задач. Повторите позже."},
                status_code=429,
            )
        raw_path = str(body.original_video or "").strip()
        if not raw_path:
            return JSONResponse(
                {"status": "error", "message": "Не указан путь к исходному видео."},
                status_code=400,
            )
        vp = Path(raw_path)
        try:
            vp = vp.resolve()
        except OSError:
            return JSONResponse(
                {"status": "error", "message": "Некорректный путь к исходному видео."},
                status_code=400,
            )
        if not vp.is_file():
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Исходный файл видео не найден. Укажите путь после загрузки или проверьте диск.",
                },
                status_code=400,
            )
        # Защита от path traversal: файл должен находиться внутри data/ проекта.
        _data_root = ROOT / "data"
        try:
            vp.relative_to(_data_root)
        except ValueError:
            return JSONResponse(
                {"status": "error", "message": "Доступ к файлу за пределами папки data/ запрещён."},
                status_code=400,
            )
        pipe = _pipeline_for(tenant_id)
        return await dbmod.create_task(
            str(vp),
            body.target_profile,
            render_only=body.render_only,
            subtitle=body.subtitle,
            template=body.template,
            tenant_id=tenant_id,
            db_path=pipe.db_path,
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось создать задачу."}


class VariantsGenerateBody(BaseModel):
    """
    Пакетный генератор задач из одного исходника:
      - создаёт count задач в БД;
      - опционально сразу ставит их в очередь (и запускает пайплайн).
    Поля subtitle / subtitles: один CTA на весь пакет или ровно count строк (свой на задачу).
    randomize_effects: для каждой задачи — случайный набор эффектов и уровень интенсивности.
    """

    source_video: str
    target_profile: str = ""
    render_only: bool = True
    count: int = 10
    enqueue: bool = True
    auto_start_pipeline: bool = True
    subtitle: str | None = None
    subtitles: list[str] | None = None
    rotate_templates: bool = False
    template: str | None = None
    randomize_effects: bool = False
    randomize_device_geo: bool = False
    priority: int = 0


@app.post("/api/variants/generate")
async def variants_generate(tenant_id: TenantDep, body: VariantsGenerateBody):
    try:
        src = str(body.source_video or "").strip()
        if not src:
            return JSONResponse(
                {"status": "error", "message": "Не указан source_video."},
                status_code=400,
            )
        src_path = Path(src)
        if not src_path.is_file():
            return JSONResponse(
                {"status": "error", "message": "Исходный файл source_video не найден."},
                status_code=400,
            )
        cnt = int(body.count)
        if cnt < 1 or cnt > 50:
            return JSONResponse(
                {"status": "error", "message": "count должен быть в диапазоне 1..50."},
                status_code=400,
            )
        target_profile = str(body.target_profile or "").strip()
        if not body.render_only and not target_profile:
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Для render_only=false укажите target_profile.",
                },
                status_code=400,
            )

        if body.subtitles is not None and len(body.subtitles) != cnt:
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"subtitles: ожидается ровно {cnt} строк (сейчас {len(body.subtitles)}).",
                },
                status_code=400,
            )

        pipe = _pipeline_for(tenant_id)
        batch_subtitle = (body.subtitle or "").strip() or None
        tmpl_ids = luxury_engine.get_montage_template_ids()
        batch_tpl = (body.template or "").strip() or None

        import random as _rnd
        import json as _json
        _ALL_EFFECTS = ["mirror", "noise", "speed", "gamma_jitter", "crop_reframe", "audio_tone"]
        _INTENSITIES = ["low", "med", "high"]
        _LEVEL_OPTS = ["low", "med", "high"]
        _DEVICE_MODELS = list(luxury_engine.DEVICE_MODEL_FINGERPRINTS.keys())
        _GEO_PROFILES = list(luxury_engine._GEO_PROFILES.keys())

        # Собираем строки пакета и делаем один batch INSERT.
        batch_rows: list[dict] = []
        for i in range(cnt):
            one_sub: str | None = None
            if body.subtitles is not None:
                raw_i = body.subtitles[i]
                one_sub = (str(raw_i).strip() if raw_i is not None else "") or None
            elif batch_subtitle:
                one_sub = batch_subtitle
            one_tpl: str | None = None
            if body.rotate_templates and tmpl_ids:
                one_tpl = tmpl_ids[i % len(tmpl_ids)]
            elif batch_tpl:
                one_tpl = batch_tpl
            one_effects_json: str | None = None
            if body.randomize_effects:
                # Случайный набор 1–4 эффектов + уровни + интенсивность.
                k = _rnd.randint(1, min(4, len(_ALL_EFFECTS)))
                chosen = _rnd.sample(_ALL_EFFECTS, k)
                eff = {e: True for e in chosen}
                eff_lvls = {e: _rnd.choice(_LEVEL_OPTS) for e in chosen}
                intensity = _rnd.choice(_INTENSITIES)
                one_effects_json = _json.dumps({
                    "effects": eff,
                    "effect_levels": eff_lvls,
                    "intensity": intensity,
                }, ensure_ascii=False)
            one_device: str | None = None
            one_geo: str | None = None
            if body.randomize_device_geo:
                one_device = _rnd.choice(_DEVICE_MODELS)
                one_geo = _rnd.choice(_GEO_PROFILES)

            batch_rows.append({
                "original_video": str(src_path.resolve()),
                "target_profile": target_profile,
                "render_only": bool(body.render_only),
                "subtitle": one_sub,
                "template": one_tpl,
                "effects_json": one_effects_json,
                "priority": int(body.priority),
                "device_model": one_device,
                "geo_profile": one_geo,
            })

        cr = await dbmod.create_tasks_batch(batch_rows, tenant_id=tenant_id, db_path=pipe.db_path)
        if cr.get("status") != "ok":
            return JSONResponse(
                {"status": "error", "message": cr.get("message", "Не удалось создать задачи.")},
                status_code=500,
            )
        created_ids: list[int] = cr.get("ids") or []

        enqueued = 0
        if body.enqueue:
            if body.auto_start_pipeline:
                st = await pipe.start()
                if st.get("status") != "ok":
                    return JSONResponse(
                        {
                            "status": "error",
                            "message": str(st.get("message") or "Не удалось запустить очередь."),
                            "created_ids": created_ids,
                        },
                        status_code=500,
                    )
            for tid in created_ids:
                await pipe.enqueue(tid)
                enqueued += 1

        return _json_ok(
            {
                "created": len(created_ids),
                "created_ids": created_ids,
                "enqueued": enqueued,
                "render_only": bool(body.render_only),
                "message": "Пакет задач создан.",
            }
        )
    except Exception as exc:
        logger.exception("variants_generate: %s", exc)
        return JSONResponse(
            {"status": "error", "message": "Не удалось создать пакет задач."},
            status_code=500,
        )


@app.get("/api/tasks/{task_id}/download")
async def task_download(task_id: int, tenant_id: TenantDep):
    """
    Скачать уникализированный файл задачи.
    Доступно только для задач со статусом success и заполненным unique_video.
    """
    try:
        pipe = _pipeline_for(tenant_id)
        got = await dbmod.get_task_by_id(task_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if got.get("status") != "ok":
            return JSONResponse({"status": "error", "message": "Задача не найдена."}, status_code=404)
        task = got.get("task") or {}
        if task.get("status") != "success":
            return JSONResponse(
                {"status": "error", "message": "Файл ещё не готов. Дождитесь завершения рендера."},
                status_code=400,
            )
        unique_video = task.get("unique_video")
        if not unique_video:
            return JSONResponse(
                {"status": "error", "message": "Путь к файлу не найден в задаче."},
                status_code=404,
            )
        file_path = Path(unique_video)
        if not file_path.is_file():
            return JSONResponse(
                {"status": "error", "message": "Файл не найден на диске. Возможно, был удалён."},
                status_code=404,
            )
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="video/mp4",
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return JSONResponse(
            {"status": "error", "message": "Не удалось отдать файл."},
            status_code=500,
        )


@app.post("/api/tasks/{task_id}/cancel")
async def task_cancel(task_id: int, tenant_id: TenantDep):
    """
    Отмена: pending — сразу error в БД; rendering/uploading — сигнал воркеру (FFmpeg / этапы после рендера).
    """
    try:
        pipe = _pipeline_for(tenant_id)
        got = await dbmod.get_task_by_id(task_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if got.get("status") != "ok":
            return JSONResponse(
                {"status": "error", "message": "Задача не найдена."},
                status_code=404,
            )
        task = got.get("task") or {}
        st = str(task.get("status") or "")
        if st == "pending":
            ur = await dbmod.update_task_status(
                task_id,
                "error",
                error_message="Отменено пользователем до начала обработки.",
                tenant_id=tenant_id,
                db_path=pipe.db_path,
            )
            if ur.get("status") != "ok":
                return JSONResponse(
                    {"status": "error", "message": "Не удалось отменить задачу в очереди."},
                    status_code=500,
                )
            return _json_ok({"message": "Задача снята с ожидания."})
        if st == "success":
            return JSONResponse(
                {"status": "error", "message": "Задача уже успешно завершена."},
                status_code=400,
            )
        if st == "error":
            return JSONResponse(
                {"status": "error", "message": "Задача уже в статусе ошибки."},
                status_code=400,
            )
        if st not in ("rendering", "uploading"):
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Отмена недоступна для статуса «{st or 'неизвестно'}».",
                },
                status_code=400,
            )
        if not pipe.cancel_task_request(task_id):
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Эта задача сейчас не обрабатывается воркером (или уже завершилась).",
                },
                status_code=400,
            )
        return _json_ok({"message": "Запрос на отмену отправлен. Статус обновится через несколько секунд."})
    except Exception as exc:
        logger.exception("task_cancel %s: %s", task_id, exc)
        return JSONResponse(
            {"status": "error", "message": "Не удалось отменить задачу."},
            status_code=500,
        )


@app.post("/api/tasks/{task_id}/retry")
async def task_retry(task_id: int, tenant_id: TenantDep):
    """
    Повторить задачу в статусе error: сброс в pending и постановка в очередь.
    """
    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.retry_task(task_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if res.get("status") != "ok":
            return JSONResponse({"status": "error", "message": res.get("message", "Не удалось сбросить задачу.")}, status_code=400)
        st = await pipe.start()
        if st.get("status") != "ok":
            return JSONResponse({"status": "error", "message": st.get("message", "Не удалось запустить пайплайн.")}, status_code=500)
        await pipe.enqueue(task_id)
        return _json_ok({"message": "Задача поставлена в очередь повторно.", "task_id": task_id})
    except Exception as exc:
        logger.exception("task_retry %s: %s", task_id, exc)
        return JSONResponse({"status": "error", "message": "Не удалось повторить задачу."}, status_code=500)


class PriorityBody(BaseModel):
    priority: int = 0  # 1=высокий, 0=обычный, -1=низкий


@app.post("/api/tasks/{task_id}/priority")
async def task_set_priority(task_id: int, tenant_id: TenantDep, body: PriorityBody):
    """Изменить приоритет задачи (влияет на порядок в очереди)."""
    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.set_task_priority(
            task_id, body.priority, tenant_id=tenant_id, db_path=pipe.db_path
        )
        if res.get("status") != "ok":
            return JSONResponse(res, status_code=400)
        return _json_ok({"task_id": task_id, "priority": body.priority})
    except Exception as exc:
        logger.exception("task_set_priority %s: %s", task_id, exc)
        return JSONResponse({"status": "error", "message": "Не удалось изменить приоритет."}, status_code=500)


class ScheduleBody(BaseModel):
    """ISO 8601 datetime с timezone: '2026-04-10T14:00:00Z' или '+09:00'."""
    scheduled_at: str


@app.post("/api/tasks/{task_id}/schedule")
async def task_schedule(task_id: int, tenant_id: TenantDep, body: ScheduleBody):
    """Назначить время публикации задачи. Планировщик сам поставит её в очередь когда наступит время."""
    try:
        pipe = _pipeline_for(tenant_id)
        raw = (body.scheduled_at or "").strip()
        if not raw:
            return JSONResponse(
                {"status": "error", "message": "Укажите дату в ISO 8601 с timezone (например 2026-04-10T14:00:00Z)."},
                status_code=400,
            )
        raw_norm = raw.replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(raw_norm)
        except ValueError:
            return JSONResponse(
                {"status": "error", "message": "Некорректная дата. Используйте ISO 8601 с timezone."},
                status_code=400,
            )
        if parsed.tzinfo is None:
            return JSONResponse(
                {"status": "error", "message": "Требуется timezone offset (например Z или +03:00)."},
                status_code=400,
            )
        normalized = parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        res = await dbmod.schedule_task(
            task_id, normalized, tenant_id=tenant_id, db_path=pipe.db_path
        )
        if res.get("status") != "ok":
            return JSONResponse(res, status_code=400)
        return _json_ok({"task_id": task_id, "scheduled_at": normalized})
    except Exception as exc:
        logger.exception("task_schedule %s: %s", task_id, exc)
        return JSONResponse({"status": "error", "message": "Не удалось назначить расписание."}, status_code=500)


@app.delete("/api/tasks/{task_id}/schedule")
async def task_unschedule(task_id: int, tenant_id: TenantDep):
    """Снять расписание — задача запустится при следующем тике очереди."""
    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.schedule_task(task_id, None, tenant_id=tenant_id, db_path=pipe.db_path)
        if res.get("status") != "ok":
            return JSONResponse(res, status_code=400)
        # Сразу ставим в очередь
        await pipe.enqueue(task_id)
        return _json_ok({"task_id": task_id, "message": "Расписание снято, задача поставлена в очередь."})
    except Exception as exc:
        logger.exception("task_unschedule %s: %s", task_id, exc)
        return JSONResponse({"status": "error", "message": "Не удалось снять расписание."}, status_code=500)


@app.get("/api/tasks/scheduled")
async def tasks_scheduled(tenant_id: TenantDep):
    """Список pending-задач с назначенным временем публикации (ещё не наступило)."""
    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.list_tasks(500, tenant_id=tenant_id, db_path=pipe.db_path)
        if res.get("status") != "ok":
            return res
        tasks = [
            t for t in (res.get("tasks") or [])
            if t.get("scheduled_at") and t.get("status") == "pending"
        ]
        tasks.sort(key=lambda t: t.get("scheduled_at") or "")
        return _json_ok({"tasks": tasks, "count": len(tasks)})
    except Exception as exc:
        logger.exception("tasks_scheduled: %s", exc)
        return {"status": "error", "message": "Не удалось получить список запланированных задач."}


@app.get("/api/analytics")
async def analytics_list(tenant_id: TenantDep, limit: int = 200):
    try:
        return await dbmod.list_analytics(limit=limit, tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка аналитики."}


@app.get("/api/dashboard/summary")
async def dashboard_summary(
    tenant_id: TenantDep,
    chart_range: Annotated[str, Query(alias="range", description="24h | 7d | 30d | 90d")] = "30d",
):
    """
    Готовые агрегаты для главного дашборда:
    - KPI
    - ряды за 30 дней
    - здоровье каналов
    - heatmap 7x24
    """
    try:
        pipe = _pipeline_for(tenant_id)
        tasks_res = await dbmod.list_tasks(limit=800, tenant_id=tenant_id, db_path=pipe.db_path)
        analytics_res = await dbmod.list_analytics(limit=1200, tenant_id=tenant_id, db_path=pipe.db_path)
        if tasks_res.get("status") != "ok":
            return tasks_res
        if analytics_res.get("status") != "ok":
            return analytics_res

        tasks = list(tasks_res.get("tasks") or [])
        analytics = list(analytics_res.get("analytics") or [])

        def _parse_dt(raw: Any) -> dt.datetime | None:
            s = str(raw or "").strip()
            if not s:
                return None
            # sqlite datetime('now') хранится как "YYYY-MM-DD HH:MM:SS"
            s = s.replace("Z", "+00:00")
            try:
                return dt.datetime.fromisoformat(s)
            except Exception:
                try:
                    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    return None

        total_videos = len(analytics)
        total_views = sum(int(r.get("views") or 0) for r in analytics)
        total_likes = sum(int(r.get("likes") or 0) for r in analytics)
        like_rate = (total_likes / total_views * 100.0) if total_views > 0 else 0.0

        queue_count = sum(1 for t in tasks if str(t.get("status") or "") == "pending")
        active_tasks = sum(1 for t in tasks if str(t.get("status") or "") in {"rendering", "uploading"})
        success_tasks = sum(1 for t in tasks if str(t.get("status") or "") == "success")
        failed_tasks = sum(1 for t in tasks if str(t.get("status") or "") == "error")

        channels_set = {
            str(t.get("target_profile") or "").strip()
            for t in tasks
            if str(t.get("target_profile") or "").strip()
        }

        healthy = sum(1 for r in analytics if str(r.get("status") or "").lower() not in {"shadowban", "banned"})
        watch = sum(1 for r in analytics if str(r.get("status") or "").lower() == "shadowban")
        banned = sum(1 for r in analytics if str(r.get("status") or "").lower() == "banned")
        health_pct = round((healthy / total_videos) * 100) if total_videos > 0 else 0

        range_key = str(chart_range or "30d").strip().lower()
        if range_key not in {"24h", "7d", "30d", "90d"}:
            range_key = "30d"
        now = dt.datetime.now()
        day_keys: list[str] = []
        for i in range(29, -1, -1):
            d = now - dt.timedelta(days=i)
            day_keys.append(d.strftime("%Y-%m-%d"))

        by_day_views: dict[str, int] = {k: 0 for k in day_keys}
        by_day_uploads: dict[str, int] = {k: 0 for k in day_keys}
        for row in analytics:
            d = _parse_dt(row.get("published_at"))
            if not d:
                continue
            k = d.strftime("%Y-%m-%d")
            if k in by_day_views:
                by_day_views[k] += int(row.get("views") or 0)
                by_day_uploads[k] += 1

        views30 = [by_day_views[k] for k in day_keys]
        uploads30 = [by_day_uploads[k] for k in day_keys]
        views7 = sum(views30[-7:]) if len(views30) >= 7 else sum(views30)
        chart_labels: list[str] = []
        chart_views: list[int] = []
        chart_uploads: list[int] = []
        if range_key == "24h":
            hour_labels: list[str] = []
            by_hour_views: dict[str, int] = {}
            by_hour_uploads: dict[str, int] = {}
            for i in range(23, -1, -1):
                h = now - dt.timedelta(hours=i)
                hk = h.strftime("%Y-%m-%d %H")
                hour_labels.append(hk)
                by_hour_views[hk] = 0
                by_hour_uploads[hk] = 0
            for row in analytics:
                d = _parse_dt(row.get("published_at"))
                if not d:
                    continue
                hk = d.strftime("%Y-%m-%d %H")
                if hk in by_hour_views:
                    by_hour_views[hk] += int(row.get("views") or 0)
                    by_hour_uploads[hk] += 1
            chart_labels = [h.split(" ", 1)[1] for h in hour_labels]  # HH
            chart_views = [by_hour_views[k] for k in hour_labels]
            chart_uploads = [by_hour_uploads[k] for k in hour_labels]
        else:
            days = 7 if range_key == "7d" else 30 if range_key == "30d" else 90
            keys: list[str] = []
            by_views: dict[str, int] = {}
            by_uploads: dict[str, int] = {}
            for i in range(days - 1, -1, -1):
                d = now - dt.timedelta(days=i)
                dk = d.strftime("%Y-%m-%d")
                keys.append(dk)
                by_views[dk] = 0
                by_uploads[dk] = 0
            for row in analytics:
                d = _parse_dt(row.get("published_at"))
                if not d:
                    continue
                dk = d.strftime("%Y-%m-%d")
                if dk in by_views:
                    by_views[dk] += int(row.get("views") or 0)
                    by_uploads[dk] += 1
            chart_labels = [k[5:] for k in keys]  # MM-DD
            chart_views = [by_views[k] for k in keys]
            chart_uploads = [by_uploads[k] for k in keys]

        profile_map: dict[str, dict[str, int]] = {}
        for t in tasks:
            name = str(t.get("target_profile") or "unknown")
            stat = profile_map.setdefault(name, {"total": 0, "success": 0, "error": 0, "active": 0})
            stat["total"] += 1
            st = str(t.get("status") or "")
            if st == "success":
                stat["success"] += 1
            if st == "error":
                stat["error"] += 1
            if st in {"rendering", "uploading"}:
                stat["active"] += 1
        channels = []
        for name, s in profile_map.items():
            total = max(1, s["total"])
            channels.append({
                "name": name,
                "total": s["total"],
                "success": s["success"],
                "error": s["error"],
                "active": s["active"],
                "health": round((s["success"] / total) * 100),
            })
        channels.sort(key=lambda c: c["success"], reverse=True)
        channels = channels[:5]

        alerts = []
        for c in channels:
            if c["error"] > 0 or c["health"] < 40:
                alerts.append({
                    "name": c["name"],
                    "text": f"Низкое здоровье: {c['health']}%" if c["health"] < 40 else f"Ошибок: {c['error']}",
                    "color": "var(--accent-red)" if c["health"] < 40 else "var(--accent-amber)",
                })
        alerts = alerts[:3]

        heat = [[0 for _ in range(24)] for _ in range(7)]
        for row in analytics:
            d = _parse_dt(row.get("published_at"))
            if not d:
                continue
            day = (d.weekday())  # 0..6 already Monday-first
            hour = d.hour
            heat[day][hour] += 1
        max_heat = max(1, max((v for r in heat for v in r), default=0))
        heat_classes = []
        for r in heat:
            out_row = []
            for v in r:
                if v == 0:
                    out_row.append("")
                else:
                    p = v / max_heat
                    if p < 0.25:
                        out_row.append("l1")
                    elif p < 0.5:
                        out_row.append("l2")
                    elif p < 0.75:
                        out_row.append("l3")
                    elif p < 0.92:
                        out_row.append("l4")
                    else:
                        out_row.append("l5")
            heat_classes.append(out_row)

        return _json_ok({
            "summary": {
                "totalVideos": total_videos,
                "totalViews": total_views,
                "views7": views7,
                "likeRate": round(like_rate, 2),
                "queueCount": queue_count,
                "activeTasks": active_tasks,
                "successTasks": success_tasks,
                "failedTasks": failed_tasks,
                "channelsCount": len(channels_set),
                "healthy": healthy,
                "watch": watch,
                "banned": banned,
                "healthPct": health_pct,
                "views30": views30,
                "uploads30": uploads30,
                "range": range_key,
                "chartLabels": chart_labels,
                "chartViews": chart_views,
                "chartUploads": chart_uploads,
                "channels": channels,
                "alerts": alerts,
                "heatClasses": heat_classes,
            }
        })
    except Exception as exc:
        logger.exception("dashboard_summary: %s", exc)
        return {"status": "error", "message": "Не удалось собрать сводку дашборда."}


@app.get("/api/analytics/recommendations")
async def analytics_recommendations(tenant_id: TenantDep, limit: int = 200):
    try:
        data = await dbmod.list_analytics(limit=limit, tenant_id=tenant_id)
        if data.get("status") != "ok":
            return data
        rows = data.get("analytics") or []
        return _json_ok({"recommendations": analytics_advisor.build_recommendations(rows)})
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось собрать рекомендации аналитики."}


class CheckUrlBody(BaseModel):
    url: str


@app.post("/api/analytics/check")
async def analytics_check(body: CheckUrlBody):
    try:
        return await analytics_scraper.check_video(body.url.strip())
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось проверить ссылку."}


class CheckAllBody(BaseModel):
    """Пакетная проверка: до 20 URL за раз с задержкой между запросами."""
    urls: list[str]
    delay_sec: float = 1.5


@app.post("/api/analytics/check-all")
async def analytics_check_all(tenant_id: TenantDep, body: CheckAllBody):
    """
    Проверить несколько URL сразу и сохранить результаты в аналитику.
    Максимум 20 URL; задержка delay_sec между запросами (защита от блокировки).
    """
    try:
        urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
        if not urls:
            return JSONResponse({"status": "error", "message": "Список URL пуст."}, status_code=400)
        if len(urls) > 20:
            return JSONResponse(
                {"status": "error", "message": "Максимум 20 URL за один запрос."},
                status_code=400,
            )
        delay = max(0.0, min(10.0, float(body.delay_sec)))
        results = []
        for i, url in enumerate(urls):
            if i > 0:
                await asyncio.sleep(delay)
            try:
                r = await analytics_scraper.check_video(url)
                if r.get("status") in ("active", "shadowban", "banned"):
                    await dbmod.add_analytics_row(
                        url,
                        views=int(r.get("views") or 0),
                        likes=int(r.get("likes") or 0),
                        status=str(r.get("status") or "active"),
                        tenant_id=tenant_id,
                    )
                results.append({"url": url, **r})
            except Exception as exc:
                logger.warning("check-all %s: %s", url, exc)
                results.append({"url": url, "status": "error", "message": str(exc)})
        ok_count = sum(1 for r in results if r.get("status") in ("active", "shadowban", "banned"))
        return _json_ok({"checked": len(results), "ok": ok_count, "results": results})
    except Exception as exc:
        logger.exception("analytics_check_all: %s", exc)
        return {"status": "error", "message": "Не удалось выполнить пакетную проверку."}


@app.get("/api/tasks/export")
async def tasks_export(tenant_id: TenantDep, limit: int = 500):
    """Экспорт задач в CSV (потоковый ответ)."""
    import csv, io

    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.list_tasks(limit=min(limit, 2000), tenant_id=tenant_id, db_path=pipe.db_path)
        tasks = res.get("tasks") or []

        fields = [
            "id", "status", "error_type", "priority", "retry_count",
            "target_profile", "device_model", "geo_profile",
            "render_only", "template", "subtitle",
            "original_video", "unique_video",
            "error_message", "warning_message",
            "scheduled_at", "created_at", "updated_at",
        ]

        def _generate():
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            yield buf.getvalue()
            for row in tasks:
                buf = io.StringIO()
                w2 = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
                w2.writerow(row)
                yield buf.getvalue()

        return StreamingResponse(
            _generate(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=tasks.csv"},
        )
    except Exception as exc:
        logger.exception("tasks_export: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось экспортировать задачи."}, status_code=500)


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: int, tenant_id: TenantDep):
    """Полные данные задачи по ID — для модального окна в UI."""
    try:
        pipe = _pipeline_for(tenant_id)
        got = await dbmod.get_task_by_id(task_id, tenant_id=tenant_id, db_path=pipe.db_path)
        if got.get("status") != "ok":
            return JSONResponse({"status": "error", "message": "Задача не найдена."}, status_code=404)
        return got
    except Exception as exc:
        logger.exception("task_detail %s: %s", task_id, exc)
        return JSONResponse({"status": "error", "message": "Не удалось загрузить задачу."}, status_code=500)


@app.get("/api/analytics/export")
async def analytics_export(tenant_id: TenantDep, limit: int = 500):
    """Экспорт аналитики в CSV."""
    import csv, io

    try:
        pipe = _pipeline_for(tenant_id)
        res = await dbmod.list_analytics(limit=min(limit, 2000), tenant_id=tenant_id, db_path=pipe.db_path)
        items = res.get("analytics") or []

        fields = ["id", "video_url", "views", "likes", "status", "checked_at", "published_at"]

        def _generate():
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            yield buf.getvalue()
            for row in items:
                buf = io.StringIO()
                w2 = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
                w2.writerow(row)
                yield buf.getvalue()

        return StreamingResponse(
            _generate(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=analytics.csv"},
        )
    except Exception as exc:
        logger.exception("analytics_export: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось экспортировать аналитику."}, status_code=500)



class DistributeTasksBody(BaseModel):
    original_video: str
    target_profiles: list[str]
    start_time: str | None = None
    interval_minutes: int = 15
    render_only: bool = False
    subtitle: str | None = None
    template: str | None = None
    randomize_effects: bool = True
    randomize_device_geo: bool = True
    priority: int = 0
    enqueue: bool = True
    auto_start_pipeline: bool = True

@app.post("/api/tasks/distribute")
async def tasks_distribute(tenant_id: TenantDep, body: DistributeTasksBody):
    try:
        src = str(body.original_video or "").strip()
        if not src:
            return JSONResponse({"status": "error", "message": "Не указан original_video."}, status_code=400)
        src_path = Path(src)
        if not src_path.is_file():
            return JSONResponse({"status": "error", "message": "Исходный файл видео не найден."}, status_code=400)
        
        target_profiles = [p.strip() for p in body.target_profiles if p.strip()]
        if not target_profiles:
            return JSONResponse({"status": "error", "message": "Не указаны профили target_profiles."}, status_code=400)

        pipe = _pipeline_for(tenant_id)
        
        from datetime import datetime, timezone, timedelta
        if body.start_time:
            try:
                start_dt = datetime.fromisoformat(body.start_time.replace("Z", "+00:00"))
            except ValueError:
                return JSONResponse({"status": "error", "message": "Неверный формат start_time (ISO 8601)."}, status_code=400)
        else:
            start_dt = datetime.now(timezone.utc)
            
        import random as _rnd
        import json as _json
        _ALL_EFFECTS = ["mirror", "noise", "speed", "gamma_jitter", "crop_reframe", "audio_tone"]
        _INTENSITIES = ["low", "med", "high"]
        _LEVEL_OPTS = ["low", "med", "high"]
        _DEVICE_MODELS = list(luxury_engine.DEVICE_MODEL_FINGERPRINTS.keys())
        _GEO_PROFILES = list(luxury_engine._GEO_PROFILES.keys())

        batch_rows: list[dict] = []
        for i, target_profile in enumerate(target_profiles):
            scheduled_dt = start_dt + timedelta(minutes=body.interval_minutes * i)
            scheduled_str = scheduled_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            
            one_effects_json: str | None = None
            if body.randomize_effects:
                k = _rnd.randint(1, min(4, len(_ALL_EFFECTS)))
                chosen = _rnd.sample(_ALL_EFFECTS, k)
                eff = {e: True for e in chosen}
                eff_lvls = {e: _rnd.choice(_LEVEL_OPTS) for e in chosen}
                intensity = _rnd.choice(_INTENSITIES)
                one_effects_json = _json.dumps({
                    "effects": eff,
                    "effect_levels": eff_lvls,
                    "intensity": intensity,
                }, ensure_ascii=False)
                
            one_device: str | None = None
            one_geo: str | None = None
            if body.randomize_device_geo:
                one_device = _rnd.choice(_DEVICE_MODELS)
                one_geo = _rnd.choice(_GEO_PROFILES)

            batch_rows.append({
                "original_video": str(src_path.resolve()),
                "target_profile": target_profile,
                "render_only": bool(body.render_only),
                "subtitle": body.subtitle,
                "template": body.template,
                "effects_json": one_effects_json,
                "priority": int(body.priority),
                "device_model": one_device,
                "geo_profile": one_geo,
                "scheduled_at": scheduled_str
            })

        cr = await dbmod.create_tasks_batch(batch_rows, tenant_id=tenant_id, db_path=pipe.db_path)
        if cr.get("status") != "ok":
            return JSONResponse({"status": "error", "message": cr.get("message", "Не удалось создать задачи.")}, status_code=500)
            
        created_ids: list[int] = cr.get("ids") or []
        
        if body.enqueue and body.auto_start_pipeline:
            await pipe.start()

        return _json_ok({
            "created": len(created_ids),
            "created_ids": created_ids,
            "render_only": bool(body.render_only),
            "message": "Пакет задач распределён."
        })
    except Exception as exc:
        logger.exception("tasks_distribute: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось распределить задачи."}, status_code=500)

class PreviewRenderBody(BaseModel):

    source_video: str
    duration_sec: float = 5.0


@app.post("/api/render/preview")
async def render_preview(tenant_id: TenantDep, body: PreviewRenderBody):
    """
    Dry-run: рендер первых duration_sec секунд с текущими настройками.
    Возвращает путь к preview-файлу в data/rendered/{tenant}/preview_*.mp4.
    """
    try:
        src = str(body.source_video or "").strip()
        dur = max(1.0, min(30.0, float(body.duration_sec)))
        if not src:
            return JSONResponse({"status": "error", "message": "Не указан source_video."}, status_code=400)
        src_path = Path(src)
        if not src_path.is_file():
            return JSONResponse({"status": "error", "message": "Файл source_video не найден."}, status_code=400)

        pipe = _pipeline_for(tenant_id)
        import uuid as _uuid
        out_dir = ROOT / "data" / "rendered" / tenant_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"preview_{_uuid.uuid4().hex[:8]}.mp4"

        res = await luxury_engine.render_unique_video(
            str(src_path.resolve()),
            str(pipe.overlay_media_path),
            str(out_file),
            preset=pipe.preset,
            template=pipe.template,
            subtitle=pipe.subtitle or None,
            srt_path=pipe.subtitle_srt_path,
            overlay_mode=pipe.overlay_mode,
            overlay_position=pipe.overlay_position,
            overlay_blend_mode=pipe.overlay_blend_mode,
            overlay_opacity=pipe.overlay_opacity,
            subtitle_style=pipe.subtitle_style,
            subtitle_font=pipe.subtitle_font or None,
            subtitle_font_size=pipe.subtitle_font_size or None,
            effects=pipe.effects,
            effect_levels=pipe.effect_levels,
            uniqualize_intensity=pipe.uniqualize_intensity,
            geo_enabled=pipe.geo_enabled,
            geo_profile=pipe.geo_profile,
            geo_jitter=pipe.geo_jitter,
            device_model=pipe.device_model,
            auto_trim_lead_tail=False,
            perceptual_hash_check=False,
            preview_duration_sec=dur,
        )
        if res.get("status") != "ok":
            return JSONResponse(res, status_code=500)
        return _json_ok({
            "preview_path": res.get("output_path"),
            "duration_sec": dur,
            "message": f"Preview готов: первые {dur:.0f} сек с текущими настройками.",
        })
    except Exception as exc:
        logger.exception("render_preview: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось создать preview."}, status_code=500)


_SCREENSHOTS_DIR = ROOT / "data" / "screenshots"


@app.get("/api/screenshots")
async def screenshots_list():
    """Список скриншотов Google-верификации из data/screenshots/."""
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            _SCREENSHOTS_DIR.glob("*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        items = [
            {
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "url": f"/api/screenshots/{p.name}",
            }
            for p in files
        ]
        return _json_ok({"screenshots": items, "count": len(items)})
    except Exception as exc:
        logger.exception("screenshots_list: %s", exc)
        return {"status": "error", "message": "Не удалось получить список скриншотов."}


@app.get("/api/screenshots/{filename}")
async def screenshot_download(filename: str):
    """Скачать/открыть конкретный скриншот верификации Google."""
    try:
        # Защита от path traversal
        safe_name = Path(filename).name
        if not safe_name.endswith(".png") or safe_name != filename:
            return JSONResponse({"status": "error", "message": "Некорректное имя файла."}, status_code=400)
        path = _SCREENSHOTS_DIR / safe_name
        if not path.is_file():
            return JSONResponse({"status": "error", "message": "Скриншот не найден."}, status_code=404)
        return FileResponse(path=str(path), media_type="image/png", filename=safe_name)
    except Exception as exc:
        logger.exception("screenshot_download: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось отдать скриншот."}, status_code=500)


async def _handle_overlay_upload(
    tenant_id: str, data: bytes, filename: str | None
) -> dict:
    """Сохранить картинку или видео как слой; обновить overlay_media_path пайплайна."""
    if not data:
        return {"status": "error", "message": "Пустой файл."}
    ext = Path(filename or "layer.mp4").suffix.lower()
    if ext not in overlay_paths.ALLOWED_OVERLAY_SUFFIXES:
        return {
            "status": "error",
            "message": "Неподдерживаемый формат слоя. Используйте PNG, JPG, WebP, GIF или видео MP4/MOV/WebM/MKV.",
        }
    if len(data) < 16:
        return {
            "status": "error",
            "message": f"Файл слишком мал ({len(data)} байт) — загрузка не завершилась. Попробуйте снова.",
        }
    saved = await storage_mod.get_default_storage().save_upload(
        tenant_id,
        f"overlay_layer{ext}",
        data,
        allowed_ext=overlay_paths.ALLOWED_OVERLAY_SUFFIXES,
    )
    if saved.get("status") != "ok":
        return saved
    path = saved.get("path")
    if not path:
        return {"status": "error", "message": "Не удалось сохранить слой."}
    # Проверяем что FFmpeg реально может прочитать загруженный файл.
    from core import ffmpeg_runner as _ff_check
    dims = await _ff_check.probe_video_dimensions(Path(path))
    if dims is None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "status": "error",
            "message": "Файл повреждён или не является корректным изображением/видео. "
                       "Загрузите PNG, JPG, WebP или MP4.",
        }
    pipe = _pipeline_for(tenant_id)
    abs_path = str(Path(path).resolve())
    upd = pipe.update_uniqualizer_settings(overlay_media_path=abs_path)
    if upd.get("status") != "ok":
        # Валидация не пропустила путь — ставим напрямую (файл только что сохранён в uploads/).
        logger.warning("overlay upload: update_uniqualizer_settings отклонил путь, прямое присвоение: %s", upd)
        pipe.overlay_media_path = Path(abs_path)
    else:
        # Также сохраняем в neo_settings.json.
        persisted_cfg.save_uniqualizer_settings(upd)
    return _json_ok(
        {
            "path": abs_path,
            "overlay_media_path": abs_path,
            "message": "Слой загружен и применён к пайплайну (путь совпадает с сохранением настроек).",
        }
    )


@app.get("/api/uploads/video/{filename}")
async def stream_uploaded_video(
    filename: str,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    tenant: Annotated[
        str | None,
        Query(description="Идентификатор арендатора для превью в <video> (без заголовка X-Tenant-ID)"),
    ] = None,
):
    tid = _tenant_for_media_stream(x_tenant_id, tenant)
    path = storage_mod.resolve_uploaded_video_file(tid, filename)
    if path is None:
        return JSONResponse({"status": "error", "message": "Файл не найден"}, status_code=404)
    ext = path.suffix.lower()
    media_type = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/upload")
async def upload_video(
    tenant_id: TenantDep,
    file: UploadFile = File(...),
    purpose: str = Form(default="video"),
):
    try:
        if _is_rate_limited("upload_video", tenant_id, _UPLOAD_RATE_LIMIT):
            return JSONResponse(
                {"status": "error", "message": "Слишком много загрузок. Подождите минуту."},
                status_code=429,
            )
        pur = (purpose or "video").strip().lower()

        # overlay и srt — обычно небольшие файлы, читаем целиком.
        if pur in ("overlay", "srt"):
            data = await file.read()
            if pur == "overlay":
                return await _handle_overlay_upload(tenant_id, data, file.filename)
            # srt
            fn_hint = file.filename or "subs.srt"
            if Path(fn_hint).suffix.lower() != ".srt":
                return JSONResponse(
                    {
                        "status": "error",
                        "message": "Для таймкодных субтитров нужен файл с расширением .srt.",
                    },
                    status_code=400,
                )
            res = await storage_mod.get_default_storage().save_upload(
                tenant_id,
                fn_hint,
                data,
                allowed_ext=frozenset({".srt"}),
            )
            if res.get("status") != "ok":
                return JSONResponse(res, status_code=400)
            p = str(res.get("path") or "")
            try:
                abs_srt = str(Path(p).resolve())
            except OSError:
                abs_srt = p
            pipe = _pipeline_for(tenant_id)
            srt_upd = pipe.update_uniqualizer_settings(subtitle_srt_path=abs_srt)
            if not pipe.subtitle_srt_path and Path(abs_srt).is_file():
                pipe.subtitle_srt_path = abs_srt
            if srt_upd.get("status") != "ok":
                logger.warning("srt upload: update_uniqualizer_settings: %s", srt_upd)
            return _json_ok(
                {
                    "path": abs_srt,
                    "subtitle_srt_path": abs_srt,
                    "filename": res.get("filename"),
                }
            )

        # Видео — потоковая запись чанками (не держим весь файл в RAM).
        async def _chunks():
            total = 0
            while True:
                chunk = await file.read(1 << 20)  # 1 МБ
                if not chunk:
                    break
                total += len(chunk)
                if total > _UPLOAD_MAX_BYTES:
                    raise ValueError("Файл слишком большой")
                yield chunk

        try:
            return await storage_mod.get_default_storage().save_upload_stream(
                tenant_id,
                file.filename or "video.mp4",
                _chunks(),
            )
        except ValueError:
            return JSONResponse(
                {"status": "error", "message": "Размер файла превышает лимит 2 GB."},
                status_code=413,
            )
    except Exception as exc:
        logger.exception("%s", exc)
        return JSONResponse(
            {"status": "error", "message": "Не удалось сохранить файл."},
            status_code=500,
        )


class GroqBody(BaseModel):
    key: str = ""


@app.post("/api/settings/groq")
async def settings_groq(tenant_id: TenantDep, body: GroqBody):
    try:
        k = (body.key or "").strip()
        if k:
            os.environ["GROQ_API_KEY"] = k
            _pipeline_for(tenant_id).groq_api_key = k
            persisted_cfg.persist_current_settings()
            return _json_ok({"saved": True, "cleared": False})
        os.environ.pop("GROQ_API_KEY", None)
        _pipeline_for(tenant_id).groq_api_key = None
        persisted_cfg.persist_current_settings(clear_groq=True)
        return _json_ok({"saved": False, "cleared": True})
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось сохранить настройки."}


@app.get("/api/settings/groq")
async def settings_groq_status():
    k = os.environ.get("GROQ_API_KEY", "").strip()
    masked = ""
    if k:
        masked = k[:4] + "••••" + k[-2:] if len(k) > 6 else "••••"
    return _json_ok({"configured": bool(k), "masked": masked})


class GroqPingBody(BaseModel):
    """Пустой key — проверить ключ, уже сохранённый на сервере для tenant."""

    key: str = ""


@app.post("/api/settings/groq/ping")
async def settings_groq_ping(tenant_id: TenantDep, body: GroqPingBody):
    """Проверка ключа Groq (GET /v1/models). Можно передать ключ из поля без сохранения."""
    try:
        pipe = _pipeline_for(tenant_id)
        trial = (body.key or "").strip()
        k = trial or (pipe.groq_api_key or os.environ.get("GROQ_API_KEY") or "").strip()
        r = await ai_copywriter.ping_groq_api(k)
        return _json_ok(
            {
                "live": bool(r.get("live")),
                "message": str(r.get("message") or ""),
                "used_trial_key": bool(trial),
            }
        )
    except Exception as exc:
        logger.exception("settings_groq_ping: %s", exc)
        return {"status": "error", "message": "Не удалось проверить ключ Groq."}


class UniqualizerSettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Важно: принимаем частичные апдейты. Раньше отсутствующие поля заполнялись
    # дефолтами pydantic и при POST сбрасывали текущие настройки пайплайна.
    geo_enabled: bool | None = None
    geo_profile: str | None = None
    geo_jitter: float | None = None
    device_model: str | None = None
    niche: str | None = None
    preset: str | None = None
    template: str | None = None
    subtitle: str | None = None
    subtitle_srt_path: str | None = None
    overlay_mode: str | None = None
    overlay_position: str | None = None
    subtitle_style: str | None = None
    subtitle_font: str | None = None
    subtitle_font_size: int | None = None
    overlay_media_path: str | None = None
    overlay_blend_mode: str | None = None
    overlay_opacity: float | None = None
    effects: dict[str, bool] | None = None
    effect_levels: dict[str, str] | None = None
    uniqualize_intensity: str | None = None
    auto_trim_lead_tail: bool | None = None
    perceptual_hash_check: bool | None = None
    tags: list[str] | None = None
    thumbnail_path: str | None = None
    shorts_loop: bool | None = None
    shorts_loop_fade_sec: float | None = None
    # Системные настройки: переключают env vars и сохраняются в neo_settings.json.
    disable_nvenc: bool | None = None
    groq_model: str | None = None


@app.get("/api/uniqualizer/settings")
async def uniqualizer_settings_status(tenant_id: TenantDep):
    try:
        pipe = _pipeline_for(tenant_id)
        return _json_ok(
            {
                "geo_enabled": pipe.geo_enabled,
                "geo_profile": pipe.geo_profile,
                "geo_jitter": pipe.geo_jitter,
                "device_model": pipe.device_model,
                "niche": pipe.niche,
                "preset": pipe.preset,
                "template": pipe.template,
                "subtitle": pipe.subtitle,
                "subtitle_srt_path": pipe.subtitle_srt_path or "",
                "overlay_mode": pipe.overlay_mode,
                "overlay_position": pipe.overlay_position,
                "subtitle_style": pipe.subtitle_style,
                "subtitle_font": getattr(pipe, "subtitle_font", ""),
                "subtitle_font_size": getattr(pipe, "subtitle_font_size", 0),
                "overlay_media_path": str(pipe.overlay_media_path.resolve()),
                "overlay_blend_mode": pipe.overlay_blend_mode,
                "overlay_opacity": pipe.overlay_opacity,
                "effects": dict(getattr(pipe, "effects", {}) or {}),
                "effect_levels": dict(getattr(pipe, "effect_levels", {}) or {}),
                "uniqualize_intensity": getattr(pipe, "uniqualize_intensity", "med"),
                "auto_trim_lead_tail": getattr(pipe, "auto_trim_lead_tail", True),
                "perceptual_hash_check": getattr(pipe, "perceptual_hash_check", True),
                "tags": list(getattr(pipe, "tags", []) or []),
                "thumbnail_path": getattr(pipe, "thumbnail_path", "") or "",
                "shorts_loop": getattr(pipe, "shorts_loop", False),
                "shorts_loop_fade_sec": getattr(pipe, "shorts_loop_fade_sec", 0.5),
                "disable_nvenc": os.environ.get("NEORENDER_DISABLE_NVENC", "").strip().lower() in ("1", "true", "yes", "on"),
                "groq_model": os.environ.get("GROQ_MODEL", ""),
                "available_presets": luxury_engine.get_render_presets(),
                "available_templates": luxury_engine.get_montage_templates(),
                "available_overlay_blends": luxury_engine.get_overlay_blend_modes(),
                "available_geo_profiles": luxury_engine.get_geo_profiles(),
                "available_device_models": luxury_engine.get_device_model_presets(),
                "available_effects": {
                    "mirror": "Mirror (hflip)",
                    "noise": "Noise / grain",
                    "speed": "Speed tweak",
                    "crop_reframe": "Micro crop + reframe",
                    "gamma_jitter": "Gamma jitter",
                    "audio_tone": "Audio tone profile",
                },
                "available_effect_levels": {
                    "low": "Low",
                    "med": "Med",
                    "high": "High",
                },
                "available_uniqualize_intensity": luxury_engine.get_uniqualize_intensity_modes(),
            }
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось получить настройки уникализатора."}


@app.post("/api/uniqualizer/settings")
async def uniqualizer_settings_save(tenant_id: TenantDep, body: UniqualizerSettingsBody):
    try:
        # Применяем системные переключатели до вызова update_uniqualizer_settings.
        if body.disable_nvenc is not None:
            if body.disable_nvenc:
                os.environ["NEORENDER_DISABLE_NVENC"] = "1"
            else:
                os.environ.pop("NEORENDER_DISABLE_NVENC", None)
        if body.groq_model is not None:
            gm = body.groq_model.strip()
            if gm:
                os.environ["GROQ_MODEL"] = gm
            else:
                os.environ.pop("GROQ_MODEL", None)

        result = _pipeline_for(tenant_id).update_uniqualizer_settings(
            geo_enabled=body.geo_enabled,
            geo_profile=body.geo_profile,
            geo_jitter=body.geo_jitter,
            device_model=body.device_model,
            niche=body.niche,
            preset=body.preset,
            template=body.template,
            subtitle=body.subtitle,
            subtitle_srt_path=body.subtitle_srt_path,
            overlay_mode=body.overlay_mode,
            overlay_position=body.overlay_position,
            subtitle_style=body.subtitle_style,
            subtitle_font=body.subtitle_font,
            subtitle_font_size=body.subtitle_font_size,
            overlay_media_path=body.overlay_media_path,
            overlay_blend_mode=body.overlay_blend_mode,
            overlay_opacity=body.overlay_opacity,
            effects=body.effects,
            effect_levels=body.effect_levels,
            uniqualize_intensity=body.uniqualize_intensity,
            auto_trim_lead_tail=body.auto_trim_lead_tail,
            perceptual_hash_check=body.perceptual_hash_check,
            tags=body.tags,
            thumbnail_path=body.thumbnail_path,
            shorts_loop=body.shorts_loop,
            shorts_loop_fade_sec=body.shorts_loop_fade_sec,
        )
        if result.get("status") != "ok":
            return result
        # Добавляем системные поля в результат перед сохранением.
        result["disable_nvenc"] = os.environ.get("NEORENDER_DISABLE_NVENC", "").strip().lower() in ("1", "true", "yes", "on")
        result["groq_model"] = os.environ.get("GROQ_MODEL", "")
        # Сохраняем настройки на диск — переживут рестарт сервера.
        persisted_cfg.save_uniqualizer_settings(result)
        persisted_cfg.persist_current_settings()
        result["available_geo_profiles"] = luxury_engine.get_geo_profiles()
        result["available_device_models"] = luxury_engine.get_device_model_presets()
        result["available_presets"] = luxury_engine.get_render_presets()
        result["available_templates"] = luxury_engine.get_montage_templates()
        result["available_overlay_blends"] = luxury_engine.get_overlay_blend_modes()
        result["available_effect_levels"] = {"low": "Low", "med": "Med", "high": "High"}
        result["available_uniqualize_intensity"] = luxury_engine.get_uniqualize_intensity_modes()
        return result
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось сохранить настройки уникализатора."}


@app.get("/api/pipeline/render-progress")
async def pipeline_render_progress(tenant_id: TenantDep):
    """Прогресс рендера / заливки для модального окна в UI."""
    try:
        pipe = _pipeline_for(tenant_id)
        enc = pipe.get_encode_progress_snapshot()
        tr = await dbmod.list_tasks(80, tenant_id, pipe.db_path)
        if tr.get("status") != "ok":
            return _json_ok(
                {
                    "visible": False,
                    "encoding": False,
                    "percent": 0,
                    "title": "",
                    "detail": "",
                    "task_id": None,
                    "queue_total": 0,
                    "queue_done": 0,
                }
            )
        tasks = tr.get("tasks") or []
        busy = [t for t in tasks if t.get("status") in ("rendering", "uploading")]
        pending_left = sum(1 for t in tasks if t.get("status") == "pending")
        in_flight = sum(1 for t in tasks if t.get("status") in ("pending", "rendering", "uploading"))
        done = sum(1 for t in tasks if t.get("status") in ("success", "error"))
        # В БД «рендер/залив», но воркеры не запущены — иначе вечные 4% в UI
        if busy and not enc.get("active") and not pipe.is_running():
            return _json_ok(
                {
                    "visible": False,
                    "encoding": False,
                    "percent": 0,
                    "title": "",
                    "detail": "",
                    "task_id": None,
                    "queue_total": in_flight,
                    "queue_done": done,
                }
            )
        if not busy and not enc.get("active"):
            if pending_left > 0 and pipe.is_running():
                return _json_ok(
                    {
                        "visible": True,
                        "encoding": False,
                        "percent": 3.0,
                        "title": "Очередь",
                        "detail": f"Ожидание: в очереди ещё {pending_left} задач(а/и)…",
                        "task_id": None,
                        "queue_total": in_flight,
                        "queue_done": done,
                    }
                )
            return _json_ok(
                {
                    "visible": False,
                    "encoding": False,
                    "percent": 0,
                    "title": "",
                    "detail": "",
                    "task_id": None,
                    "queue_total": in_flight,
                    "queue_done": done,
                }
            )

        t0 = busy[0] if busy else None
        tid = (t0.get("id") if t0 else None) or enc.get("task_id")
        st = str(t0.get("status") or "") if t0 else "rendering"

        fps = 0.0
        speed = 0.0
        eta_sec = 0.0
        if enc.get("active"):
            pct = float(enc.get("percent") or 0)
            detail = str(enc.get("label") or "Кодирование…")
            title = "Идёт рендер"
            m = enc.get("metrics") or {}
            try:
                fps = float(m.get("fps") or 0.0)
            except Exception:
                fps = 0.0
            try:
                speed = float(m.get("speed") or 0.0)
            except Exception:
                speed = 0.0
            try:
                out_time = float(m.get("out_time_sec") or 0.0)
            except Exception:
                out_time = 0.0
            if speed > 0.01 and pct > 0.5 and pct < 99.5:
                dur = out_time / max(0.01, pct / 100.0)
                eta_sec = max(0.0, (dur - out_time) / max(0.05, speed))
        elif st == "uploading":
            pct = 92.0
            title = "Загрузка"
            detail = "Отправка видео на YouTube…"
        else:
            uv = t0.get("unique_video") if t0 else None
            if uv:
                pct = 82.0
                detail = "Подготовка к публикации (AI, браузер)…"
            else:
                pct = 4.0
                detail = "Подготовка к кодированию…"
            title = "Идёт обработка"

        pct = min(100.0, max(0.0, pct))
        return _json_ok(
            {
                "visible": True,
                "percent": round(pct, 1),
                "title": title,
                "detail": detail,
                "task_id": tid,
                "encoding": bool(enc.get("active")),
                "fps": fps,
                "speed": speed,
                "eta_sec": eta_sec,
                "queue_total": in_flight,
                "queue_done": done,
            }
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return _json_ok(
            {
                "visible": False,
                "encoding": False,
                "percent": 0,
                "title": "",
                "detail": "",
                "task_id": None,
                "queue_total": 0,
                "queue_done": 0,
            }
        )


@app.get("/api/pipeline/events")
async def pipeline_events(
    request: Request,
    tenant_id: Annotated[str | None, Query(alias="tenant_id")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
):
    """
    SSE-стрим прогресса рендера (обновление раз в 1.5 сек).
    EventSource не поддерживает кастомные заголовки — tenant_id передаётся в query.
    """
    import json as _json

    tid = _tenant_for_media_stream(x_tenant_id, tenant_id)

    async def _snapshot() -> dict:
        try:
            pipe = _pipeline_for(tid)
            enc = pipe.get_encode_progress_snapshot()
            tr = await dbmod.list_tasks(80, tid, pipe.db_path)
            tasks = tr.get("tasks") or [] if tr.get("status") == "ok" else []
            busy = [t for t in tasks if t.get("status") in ("rendering", "uploading")]
            pending_left = sum(1 for t in tasks if t.get("status") == "pending")
            in_flight = sum(1 for t in tasks if t.get("status") in ("pending", "rendering", "uploading"))
            done = sum(1 for t in tasks if t.get("status") in ("success", "error"))

            if busy and not enc.get("active") and not pipe.is_running():
                return {"visible": False, "encoding": False, "percent": 0, "title": "", "detail": "", "task_id": None, "queue_total": in_flight, "queue_done": done}

            if not busy and not enc.get("active"):
                if pending_left > 0 and pipe.is_running():
                    return {"visible": True, "encoding": False, "percent": 3.0, "title": "Очередь", "detail": f"Ожидание: {pending_left} задач(а/и)…", "task_id": None, "queue_total": in_flight, "queue_done": done}
                return {"visible": False, "encoding": False, "percent": 0, "title": "", "detail": "", "task_id": None, "queue_total": in_flight, "queue_done": done}

            t0 = busy[0] if busy else None
            task_id_val = (t0.get("id") if t0 else None) or enc.get("task_id")
            st = str(t0.get("status") or "") if t0 else "rendering"

            fps = speed = eta_sec = 0.0
            if enc.get("active"):
                pct = float(enc.get("percent") or 0)
                detail = str(enc.get("label") or "Кодирование…")
                title = "Идёт рендер"
                m = enc.get("metrics") or {}
                try:
                    fps = float(m.get("fps") or 0.0)
                except Exception:
                    fps = 0.0
                try:
                    speed = float(m.get("speed") or 0.0)
                except Exception:
                    speed = 0.0
                try:
                    out_time = float(m.get("out_time_sec") or 0.0)
                except Exception:
                    out_time = 0.0
                if speed > 0.01 and 0.5 < pct < 99.5:
                    dur = out_time / max(0.01, pct / 100.0)
                    eta_sec = max(0.0, (dur - out_time) / max(0.05, speed))
            elif st == "uploading":
                pct = 92.0
                title = "Загрузка"
                detail = "Отправка видео на YouTube…"
            else:
                uv = t0.get("unique_video") if t0 else None
                pct = 82.0 if uv else 4.0
                detail = "Подготовка к публикации (AI, браузер)…" if uv else "Подготовка к кодированию…"
                title = "Идёт обработка"

            return {
                "visible": True,
                "encoding": bool(enc.get("active")),
                "percent": round(min(100.0, max(0.0, pct)), 1),
                "title": title,
                "detail": detail,
                "task_id": task_id_val,
                "fps": fps,
                "speed": speed,
                "eta_sec": eta_sec,
                "queue_total": in_flight,
                "queue_done": done,
            }
        except Exception as exc:
            logger.exception("pipeline_events snapshot: %s", exc)
            return {"visible": False, "encoding": False, "percent": 0, "title": "", "detail": "", "task_id": None, "queue_total": 0, "queue_done": 0}

    async def _generate():
        while True:
            if await request.is_disconnected():
                break
            data = await _snapshot()
            yield f"data: {_json.dumps(data)}\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/pipeline/start")
async def pipeline_start(tenant_id: TenantDep):
    try:
        return await _pipeline_for(tenant_id).start()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось запустить пайплайн."}


@app.post("/api/pipeline/stop")
async def pipeline_stop(tenant_id: TenantDep):
    try:
        return await _pipeline_for(tenant_id).stop()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось остановить пайплайн."}


@app.post("/api/pipeline/enqueue-pending")
async def pipeline_enqueue_pending(tenant_id: TenantDep):
    try:
        return await _pipeline_for(tenant_id).enqueue_pending_from_db()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка очереди."}


class EnqueueIdBody(BaseModel):
    task_id: int


@app.post("/api/pipeline/enqueue")
async def pipeline_enqueue_one(tenant_id: TenantDep, body: EnqueueIdBody):
    try:
        await _pipeline_for(tenant_id).enqueue(body.task_id)
        return _json_ok()
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Не удалось поставить задачу в очередь."}


class TelegramSettingsBody(BaseModel):
    bot_token: str = ""
    chat_id: str = ""


class ArbitrageMonitorSettingsBody(BaseModel):
    alerts_enabled: bool = True
    score_threshold: int = 72
    alert_max_items: int = 5
    watchlist_channels: list[str] = []


def _save_arbitrage_monitor_cfg(cfg: dict[str, Any]) -> None:
    path = persisted_cfg.settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["arbitrage_monitor"] = cfg
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/settings/arbitrage-monitor")
async def arbitrage_monitor_settings_status():
    cfg = _load_arbitrage_monitor_cfg()
    watchlist = cfg.get("watchlist_channels")
    if not isinstance(watchlist, list):
        watchlist = []
    return _json_ok({
        "alerts_enabled": bool(cfg.get("alerts_enabled", True)),
        "score_threshold": max(1, min(int(cfg.get("score_threshold") or 72), 100)),
        "alert_max_items": max(1, min(int(cfg.get("alert_max_items") or 5), 10)),
        "watchlist_channels": [str(x).strip() for x in watchlist if str(x).strip()],
    })


@app.post("/api/settings/arbitrage-monitor")
async def arbitrage_monitor_settings_save(body: ArbitrageMonitorSettingsBody):
    try:
        watchlist = [str(x).strip() for x in body.watchlist_channels if str(x).strip()]
        clean = {
            "alerts_enabled": bool(body.alerts_enabled),
            "score_threshold": max(1, min(int(body.score_threshold), 100)),
            "alert_max_items": max(1, min(int(body.alert_max_items), 10)),
            "watchlist_channels": watchlist[:300],
        }
        _save_arbitrage_monitor_cfg(clean)
        return _json_ok(clean)
    except Exception as exc:
        logger.exception("arbitrage_monitor_settings_save: %s", exc)
        return {"status": "error", "message": "Не удалось сохранить настройки мониторинга."}


@app.get("/api/settings/telegram")
async def telegram_settings_status():
    """Текущие настройки Telegram (токен замаскирован, chat_id виден полностью)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    masked = ""
    if token:
        masked = token[:4] + "••••" + token[-4:] if len(token) > 8 else "••••"
    from core import notifier as _notifier
    return _json_ok({
        "configured": bool(token and chat_id),
        "token_masked": masked,
        "chat_id": chat_id,
        "notifier_ready": _notifier.is_configured(),
    })


@app.post("/api/settings/telegram")
async def telegram_settings_save(body: TelegramSettingsBody):
    """Сохранить токен бота и chat_id Telegram."""
    try:
        token = body.bot_token.strip()
        chat_id = body.chat_id.strip()
        if token:
            os.environ["TELEGRAM_BOT_TOKEN"] = token
        else:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        if chat_id:
            os.environ["TELEGRAM_CHAT_ID"] = chat_id
        else:
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        persisted_cfg.persist_current_settings()
        from core import notifier as _notifier
        return _json_ok({
            "saved": bool(token and chat_id),
            "notifier_ready": _notifier.is_configured(),
        })
    except Exception as exc:
        logger.exception("telegram_settings_save: %s", exc)
        return {"status": "error", "message": "Не удалось сохранить настройки Telegram."}


@app.post("/api/settings/telegram/ping")
async def telegram_ping():
    """Отправить тестовое сообщение в Telegram для проверки настроек."""
    try:
        from core import notifier as _notifier
        if not _notifier.is_configured():
            return {"status": "error", "message": "Telegram не настроен (нет токена или chat_id)."}
        import httpx
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": "NeoRender Pro: тест уведомлений ✓"})
            data = r.json()
            if r.is_success and data.get("ok"):
                return _json_ok({"message": "Тестовое сообщение отправлено."})
            return {"status": "error", "message": str(data.get("description") or f"HTTP {r.status_code}")}
    except Exception as exc:
        logger.exception("telegram_ping: %s", exc)
        return {"status": "error", "message": f"Ошибка проверки: {exc}"}


@app.post("/api/ai/preview")
async def ai_preview(tenant_id: TenantDep, body: dict):
    """
    Генерация метаданных. Поддерживает расширенный режим:
      hook_pattern  : "curiosity" | "number" | "interrupt" | "auto"
      n_variants    : 1–10 (сколько вариантов заголовка вернуть)
      competitor_examples : [{title, view_count}] — из /api/research/search
    """
    try:
        niche = str(body.get("niche") or "YouTube Shorts")
        hook_pattern = str(body.get("hook_pattern") or "auto")
        n_variants = max(1, min(10, int(body.get("n_variants") or 5)))
        competitor_examples = body.get("competitor_examples") or []
        if not isinstance(competitor_examples, list):
            competitor_examples = []
        return await ai_copywriter.generate_viral_metadata(
            api_key=_pipeline_for(tenant_id).groq_api_key,
            niche=niche,
            competitor_examples=competitor_examples,
            hook_pattern=hook_pattern,
            n_variants=n_variants,
        )
    except Exception as exc:
        logger.exception("%s", exc)
        return {"status": "error", "message": "Ошибка AI."}


@app.post("/api/ai/caption-sequence")
async def ai_caption_sequence(tenant_id: TenantDep, body: dict):
    """
    Генерирует 3-фазную caption-последовательность для Shorts.
    Возвращает SRT-строку готовую к использованию в уникализаторе.

    Body: {niche, duration_sec, competitor_examples?}
    """
    try:
        niche = str(body.get("niche") or "YouTube Shorts")
        duration_sec = max(5.0, float(body.get("duration_sec") or 30.0))
        competitor_examples = body.get("competitor_examples") or []
        if not isinstance(competitor_examples, list):
            competitor_examples = []
        return await ai_copywriter.generate_caption_sequence(
            api_key=_pipeline_for(tenant_id).groq_api_key,
            niche=niche,
            duration_sec=duration_sec,
            competitor_examples=competitor_examples,
        )
    except Exception as exc:
        logger.exception("ai_caption_sequence: %s", exc)
        return {"status": "error", "message": "Ошибка генерации captions."}


# ──────────────────────────── Content Research ────────────────────────────────

@app.post("/api/research/search")
async def research_search(tenant_id: TenantDep, body: dict):
    """Search for trending videos by niche and source."""
    try:
        niche = str(body.get("niche") or "").strip()
        use_ubt_seeds = bool(body.get("use_ubt_seeds", True))
        if not niche and not use_ubt_seeds:
            return JSONResponse({"status": "error", "message": "Укажите нишу или включите режим UBT-сидов"}, status_code=400)
        source = str(body.get("source") or "youtube").lower()
        period_days = int(body.get("period_days") or 7)
        limit = max(1, min(int(body.get("limit") or 12), 25))
        region = str(body.get("region") or "KR").upper()
        shorts_only = bool(body.get("shorts_only", True))
        fetch_multiplier = max(1, min(6, int(body.get("fetch_multiplier") or 3)))
        rm_raw = body.get("recent_max_hours")
        recent_max_hours: float | None = None
        if rm_raw is not None and str(rm_raw).strip() != "":
            try:
                recent_max_hours = float(rm_raw)
            except (TypeError, ValueError):
                recent_max_hours = None
        if recent_max_hours is not None and recent_max_hours <= 0:
            recent_max_hours = None
        results = await content_scraper.search_videos(
            niche=niche,
            source=source,
            period_days=period_days,
            limit=limit,
            region=region,
            shorts_only=shorts_only,
            fetch_multiplier=fetch_multiplier,
            use_ubt_seed_queries=use_ubt_seeds,
            recent_max_hours=recent_max_hours,
        )
        return {"status": "ok", "results": results, "total": len(results)}
    except RuntimeError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=503)
    except Exception as exc:
        logger.exception("research_search: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/trending-audio")
async def research_trending_audio(tenant_id: TenantDep, body: dict):
    """
    Возвращает топ трендовых аудио-треков по нише за последние 14 дней.
    Использует yt-dlp метаданные track/artist из топ Shorts.

    Body: {niche, top_n?, region?}
    """
    try:
        niche = str(body.get("niche") or "")
        if not niche.strip():
            return JSONResponse({"status": "error", "message": "Укажите нишу"}, status_code=400)
        top_n = max(5, min(30, int(body.get("top_n") or 20)))
        region = str(body.get("region") or "KR").upper()
        result = await content_scraper.get_trending_audio(
            niche=niche,
            top_n=top_n,
            region=region,
        )
        return result
    except Exception as exc:
        logger.exception("research_trending_audio: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/download")
async def research_download(tenant_id: TenantDep, body: dict):
    """Download a video URL via yt-dlp into uploads folder."""
    url = str(body.get("url") or "")
    if not url.strip():
        return JSONResponse({"status": "error", "message": "URL не указан"}, status_code=400)
    uploads_dir = _UPLOADS_ROOT / normalize_tenant_id(tenant_id)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    result = await content_scraper.download_video(url, uploads_dir)
    logger.info("research download %s → %s", url, result)
    if result.get("status") != "ok":
        return JSONResponse(
            {"status": "error", "message": str(result.get("error") or "Не удалось скачать видео")},
            status_code=500,
        )
    return {
        "status": "ok",
        "message": "Видео скачано",
        "url": url,
        "filename": result.get("filename"),
        "path": result.get("path"),
    }


@app.post("/api/research/arbitrage-scan")
async def research_arbitrage_scan(tenant_id: TenantDep, body: dict):
    """
    UBT stealth scan (2026) — finds arbitrage videos by behavioral patterns,
    not game/casino names (those get blocked by YouTube).

    mode = "stealth" (default) — behavioral categories:
        shock-reaction / secret-method / new-app / multiplier /
        lifestyle / urgency / withdrawal-proof / phone-screen
    mode = "legacy" — old game-name based scan (still supported)

    Body: { mode?, categories?, region?, period_days?, limit_per_query?,
            shorts_only?, fetch_multiplier? }
    Returns: { status, results, labels, colors, monitor }
    """
    try:
        monitor_cfg = _load_arbitrage_monitor_cfg()
        watchlist_channels = monitor_cfg.get("watchlist_channels")
        if not isinstance(watchlist_channels, list):
            watchlist_channels = []
        score_threshold = max(1, min(int(monitor_cfg.get("score_threshold") or 60), 100))
        alerts_enabled = bool(monitor_cfg.get("alerts_enabled", True))
        alert_max_items = max(1, min(int(monitor_cfg.get("alert_max_items") or 5), 10))

        mode = str(body.get("mode") or "stealth").strip().lower()
        raw_region = body.get("region", None)
        region = None if (raw_region is None or str(raw_region).strip() == "") else str(raw_region).strip().upper()
        period_days     = max(1, min(int(body.get("period_days") or 7), 30))
        limit_per_query = max(1, min(int(body.get("limit_per_query") or 4), 10))
        shorts_only     = bool(body.get("shorts_only", True))
        fetch_multiplier = max(1, min(8, int(body.get("fetch_multiplier") or 5)))

        if mode == "legacy":
            # Old game-name based scan (for backward compatibility)
            games = body.get("games") or None
            results = await content_scraper.scan_arbitrage_videos(
                games=games,
                region=region,
                period_days=period_days,
                limit_per_query=limit_per_query,
                shorts_only=shorts_only,
                fetch_multiplier=fetch_multiplier,
                watchlist_channels=watchlist_channels,
            )
            labels = content_scraper.ARBITRAGE_GAME_LABELS
            colors = content_scraper.ARBITRAGE_GAME_COLORS
        else:
            # 2026 stealth behavioral scan
            categories = body.get("categories") or None
            results = await content_scraper.scan_stealth_videos(
                categories=categories,
                region=region,
                period_days=period_days,
                limit_per_query=limit_per_query,
                shorts_only=shorts_only,
                fetch_multiplier=fetch_multiplier,
                watchlist_channels=watchlist_channels,
            )
            labels = content_scraper.STEALTH_CATEGORY_LABELS
            colors = content_scraper.STEALTH_CATEGORY_COLORS

        alerted = 0
        if alerts_enabled:
            alerted = await _send_arbitrage_alerts(
                results=results,
                score_threshold=score_threshold,
                max_items=alert_max_items,
            )
        return _json_ok({
            "results": results,
            "labels": labels,
            "colors": colors,
            "mode": mode,
            "monitor": {
                "watchlist_size": len(watchlist_channels),
                "score_threshold": score_threshold,
                "alerts_enabled": alerts_enabled,
                "alerts_sent": alerted,
            },
        })
    except Exception as exc:
        logger.exception("arbitrage_scan: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/media-scan")
async def research_media_scan(tenant_id: TenantDep, body: dict):
    """
    Запускает мультимодальный анализ видео (OpenCV + faster-whisper).
    Неблокирующий: ставит задачу в очередь и возвращает сразу.

    Body: { "video_id": "abc123", "url": "https://...", "duration": 30.0 }

    Response (pending):  { status, state: "pending",  video_id }
    Response (ready):    { status, state: "ready",    video_id, result: MediaScanResult }
    Response (error):    { status, state: "error",    video_id, error: str }
    """
    try:
        from core.media_scanner import get_media_scan_queue

        video_id = str(body.get("video_id") or "").strip()
        url      = str(body.get("url")      or "").strip()
        duration = float(body.get("duration") or 0)

        if not video_id:
            return JSONResponse({"status": "error", "message": "video_id обязателен"}, status_code=400)
        if not url or not url.startswith("http"):
            return JSONResponse({"status": "error", "message": "url невалидный"}, status_code=400)

        queue  = get_media_scan_queue()
        future = await queue.submit(video_id=video_id, url=url, duration=duration)

        # Если результат уже готов — возвращаем сразу
        if future.done():
            if future.cancelled():
                return _json_ok({"state": "error", "video_id": video_id, "error": "cancelled"})
            exc = future.exception()
            if exc:
                return _json_ok({"state": "error", "video_id": video_id, "error": str(exc)})
            return _json_ok({"state": "ready", "video_id": video_id, "result": future.result().to_dict()})

        return _json_ok({
            "state":    "pending",
            "video_id": video_id,
            "queue_size": queue.queue_size(),
        })

    except Exception as exc:
        logger.exception("media_scan: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.get("/api/research/media-scan/{video_id}")
async def research_media_scan_poll(tenant_id: TenantDep, video_id: str):
    """
    Polling-эндпоинт: проверить готовность результата медиа-скана.

    Response (pending): { status, state: "pending" }
    Response (ready):   { status, state: "ready",  result: MediaScanResult }
    Response (unknown): { status, state: "unknown" } — не было submit()
    """
    try:
        from core.media_scanner import get_media_scan_queue

        queue = get_media_scan_queue()

        if queue.is_pending(video_id):
            return _json_ok({"state": "pending", "video_id": video_id, "queue_size": queue.queue_size()})

        result = queue.get_result(video_id)
        if result is None:
            return _json_ok({"state": "unknown", "video_id": video_id})

        if result.error:
            return _json_ok({"state": "error", "video_id": video_id, "error": result.error})

        return _json_ok({"state": "ready", "video_id": video_id, "result": result.to_dict()})

    except Exception as exc:
        logger.exception("media_scan_poll %s: %s", video_id, exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/resolve-funnel")
async def research_resolve_funnel(tenant_id: TenantDep, body: dict):
    """
    Раскрутить цепочку редиректов от одного или нескольких URL.

    Body:
        { "url": "https://bit.ly/..." }           — один URL
        { "urls": ["https://...", "https://..."] } — пакет до 5 URL
        { "text": "описание видео с bit.ly/..." } — извлечь URL из текста

    Response:
        { status, results: [FunnelResult, ...], count: int }
    """
    try:
        from core.funnel_resolver import resolve_funnel, resolve_urls_in_text

        results_raw = []

        # Режим: текст (описание/теги видео)
        if "text" in body:
            text = str(body["text"] or "")[:4000]
            funnels = await resolve_urls_in_text(text, max_urls=5)
            results_raw = [f.to_dict() for f in funnels]

        # Режим: пакет URL
        elif "urls" in body:
            raw_urls = [str(u).strip() for u in (body["urls"] or []) if str(u).strip()][:5]
            if not raw_urls:
                return JSONResponse(
                    {"status": "error", "message": "Список urls пуст"}, status_code=400
                )
            gathered = await asyncio.gather(
                *[resolve_funnel(u) for u in raw_urls],
                return_exceptions=True,
            )
            results_raw = [
                f.to_dict() if not isinstance(f, Exception)
                else {"error": str(f), "source_url": raw_urls[i]}
                for i, f in enumerate(gathered)
            ]

        # Режим: одиночный URL
        elif "url" in body:
            url = str(body["url"] or "").strip()
            if not url:
                return JSONResponse(
                    {"status": "error", "message": "url не задан"}, status_code=400
                )
            funnel = await resolve_funnel(url)
            results_raw = [funnel.to_dict()]

        else:
            return JSONResponse(
                {"status": "error", "message": "Нужен один из параметров: url / urls / text"},
                status_code=400,
            )

        return _json_ok({"results": results_raw, "count": len(results_raw)})

    except Exception as exc:
        logger.exception("resolve_funnel: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/channel-risk")
async def research_channel_risk(tenant_id: TenantDep, body: dict):
    """
    Риск-анализ YouTube-канала по channel_id или channel_url.

    Body:
        { "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxxxxx" }
        { "channel_url": "https://www.youtube.com/channel/UCxxxxx" }

    Response:
        { status, channel: ChannelRiskResult }

    Требует YOUTUBE_API_KEY в .env или neo_settings.json.
    """
    try:
        from core.channel_analyzer import analyze_channel_risk, extract_channel_id

        # Получаем channel_id из параметров
        channel_id = str(body.get("channel_id") or "").strip()
        if not channel_id:
            ch_url = str(body.get("channel_url") or "").strip()
            if ch_url:
                channel_id = extract_channel_id(ch_url) or ""

        if not channel_id:
            return JSONResponse(
                {
                    "status": "error",
                    "message": (
                        "Нужен channel_id (UCxxxxxxx) или channel_url. "
                        "Канал по handle (@name) требует предварительного API-поиска."
                    ),
                },
                status_code=400,
            )

        # API-ключ: env → neo_settings.json
        api_key = (os.environ.get("YOUTUBE_API_KEY") or "").strip()
        if not api_key:
            try:
                _settings_path = persisted_cfg.settings_file_path()
                if _settings_path.is_file():
                    _raw_cfg = json.loads(_settings_path.read_text(encoding="utf-8"))
                    api_key = str((_raw_cfg or {}).get("youtube_api_key") or "").strip()
            except Exception:
                pass

        result = await analyze_channel_risk(channel_id, api_key=api_key or None)

        if result.error:
            return JSONResponse({"status": "error", "message": result.error}, status_code=400)

        return _json_ok({"channel": result.to_dict()})

    except Exception as exc:
        logger.exception("channel_risk: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


_SUBTITLES_JOBS: dict[str, dict[str, Any]] = {}
_SUBTITLES_DIR = ROOT / "data" / "subtitles"


@app.post("/api/subtitles/generate")
async def subtitles_generate(tenant_id: TenantDep, background_tasks: BackgroundTasks, body: dict):
    """
    Start subtitle generation job.
    Body: { url?, file_path?, source_lang?, target_lang?, burn? }
    """
    import uuid, time
    url        = str(body.get("url") or "").strip()
    file_path  = str(body.get("file_path") or "").strip()
    source_lang = str(body.get("source_lang") or "").strip() or None
    target_lang = str(body.get("target_lang") or "").strip() or None
    burn       = bool(body.get("burn") or False)

    if not url and not file_path:
        return JSONResponse({"status": "error", "message": "Укажите url или file_path"}, status_code=400)

    pipe     = _pipeline_for(tenant_id)
    # Сначала окружение (.env после override на старте) — не даём устаревшему pipe.groq_api_key ломать Whisper.
    api_key  = (os.environ.get("GROQ_API_KEY") or pipe.groq_api_key or "").strip()
    if not api_key:
        return JSONResponse({"status": "error", "message": "GROQ_API_KEY не задан в настройках"}, status_code=400)

    job_id = str(uuid.uuid4())
    out_dir = _SUBTITLES_DIR / normalize_tenant_id(tenant_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    _SUBTITLES_JOBS[job_id] = {
        "status": "pending",
        "step": "Ожидание",
        "created_at": time.time(),
        "tenant_id": tenant_id,
    }

    async def _run():
        import time as _time
        job = _SUBTITLES_JOBS[job_id]
        try:
            video_path: str | None = None

            # ── Download if URL ──
            if url:
                job.update({"status": "running", "step": "Скачивание видео"})
                uploads_dir = _UPLOADS_ROOT / normalize_tenant_id(tenant_id)
                uploads_dir.mkdir(parents=True, exist_ok=True)
                dl = await content_scraper.download_video(url, uploads_dir)
                if dl.get("status") != "ok":
                    raise RuntimeError(str(dl.get("error") or "Не удалось скачать видео"))
                video_path = str(dl.get("path") or "")
            else:
                job.update({"status": "running", "step": "Транскрипция (Whisper)"})
                video_path = file_path

            if not video_path or not Path(video_path).exists():
                raise RuntimeError("Видео файл не найден")

            job.update({"step": "Транскрипция (Whisper)"})
            result = await subtitle_generator.generate_subtitles(
                video_path  = video_path,
                output_dir  = out_dir,
                api_key     = api_key,
                source_lang = source_lang,
                target_lang = target_lang,
                burn        = burn,
                on_step     = lambda s: job.update({"step": s}),
            )

            if result.get("status") != "ok":
                raise RuntimeError(str(result.get("message") or "Ошибка генерации"))

            job.update({
                "status":         "done",
                "step":           "Готово",
                "srt_path":       result.get("srt_path"),
                "srt_filename":   result.get("srt_filename"),
                "ass_path":       result.get("ass_path"),
                "ass_filename":   result.get("ass_filename"),
                "burned_path":    result.get("burned_path"),
                "burned_filename":result.get("burned_filename"),
                "segment_count":  result.get("segment_count"),
                "source_lang":    result.get("source_lang"),
                "target_lang":    result.get("target_lang"),
                "finished_at":    _time.time(),
            })
        except Exception as exc:
            logger.exception("subtitles job %s: %s", job_id, exc)
            job.update({"status": "error", "step": "Ошибка", "message": str(exc)})

    background_tasks.add_task(_run)
    return _json_ok({"job_id": job_id, "status": "pending"})


@app.get("/api/subtitles/{job_id}")
async def subtitles_status(job_id: str, tenant_id: TenantDep):
    """Poll job status."""
    job = _SUBTITLES_JOBS.get(job_id)
    if not job:
        return JSONResponse({"status": "error", "message": "Job не найден"}, status_code=404)
    if job.get("tenant_id") != tenant_id:
        return JSONResponse({"status": "error", "message": "Нет доступа"}, status_code=403)
    return _json_ok({"job": job})


@app.get("/api/subtitles/{job_id}/download/srt")
async def subtitles_download_srt(job_id: str, tenant_id: TenantDep):
    """Download the generated .srt file."""
    job = _SUBTITLES_JOBS.get(job_id)
    if not job or job.get("tenant_id") != tenant_id:
        return JSONResponse({"status": "error", "message": "Job не найден"}, status_code=404)
    srt = str(job.get("srt_path") or "")
    if not srt or not Path(srt).exists():
        return JSONResponse({"status": "error", "message": ".srt файл не найден"}, status_code=404)
    return FileResponse(path=srt, filename=Path(srt).name, media_type="text/plain")


@app.get("/api/subtitles/{job_id}/download/ass")
async def subtitles_download_ass(job_id: str, tenant_id: TenantDep):
    """Download the generated .ass file (with fade animations)."""
    job = _SUBTITLES_JOBS.get(job_id)
    if not job or job.get("tenant_id") != tenant_id:
        return JSONResponse({"status": "error", "message": "Job не найден"}, status_code=404)
    ass = str(job.get("ass_path") or "")
    if not ass or not Path(ass).exists():
        # fall back to SRT if ASS not available
        srt = str(job.get("srt_path") or "")
        if srt and Path(srt).exists():
            return FileResponse(path=srt, filename=Path(srt).name, media_type="text/plain")
        return JSONResponse({"status": "error", "message": ".ass файл не найден"}, status_code=404)
    return FileResponse(path=ass, filename=Path(ass).name, media_type="text/plain")


@app.get("/api/subtitles/{job_id}/download/video")
async def subtitles_download_video(job_id: str, tenant_id: TenantDep):
    """Download video with burned-in subtitles."""
    job = _SUBTITLES_JOBS.get(job_id)
    if not job or job.get("tenant_id") != tenant_id:
        return JSONResponse({"status": "error", "message": "Job не найден"}, status_code=404)
    burned = str(job.get("burned_path") or "")
    if not burned or not Path(burned).exists():
        return JSONResponse({"status": "error", "message": "Видео с субтитрами не найдено"}, status_code=404)
    return FileResponse(path=burned, filename=Path(burned).name, media_type="application/octet-stream")


@app.post("/api/research/download/browser")
async def research_download_browser(tenant_id: TenantDep, body: dict):
    """Download video and return it as browser attachment."""
    url = str(body.get("url") or "")
    if not url.strip():
        return JSONResponse({"status": "error", "message": "URL не указан"}, status_code=400)
    uploads_dir = _UPLOADS_ROOT / normalize_tenant_id(tenant_id)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    result = await content_scraper.download_video(url, uploads_dir)
    logger.info("research browser download %s → %s", url, result)
    if result.get("status") != "ok":
        return JSONResponse(
            {"status": "error", "message": str(result.get("error") or "Не удалось скачать видео")},
            status_code=500,
        )
    path = Path(str(result.get("path") or ""))
    if not path.exists() or not path.is_file():
        return JSONResponse({"status": "error", "message": "Файл не найден"}, status_code=500)
    filename = str(result.get("filename") or path.name)
    fn_low = filename.lower()
    media = (
        "video/webm"
        if fn_low.endswith(".webm")
        else "video/quicktime"
        if fn_low.endswith(".mov")
        else "video/x-matroska"
        if fn_low.endswith(".mkv")
        else "video/mp4"
    )
    return FileResponse(path=str(path), filename=filename, media_type=media)


@app.get("/api/research/queue")
async def research_queue(tenant_id: TenantDep):
    """List downloaded videos ready for uniqualizer."""
    uploads_dir = _UPLOADS_ROOT / normalize_tenant_id(tenant_id)
    videos = content_scraper.get_queued_videos(uploads_dir)
    return {"status": "ok", "videos": videos, "total": len(videos)}


@app.post("/api/research/advice")
async def research_advice(tenant_id: TenantDep, body: dict):
    """
    AI advice for a discovered video candidate.
    Input: { title, channel, url, source, view_count, duration, niche? }
    """
    try:
        title = str(body.get("title") or "").strip()
        channel = str(body.get("channel") or "").strip()
        source = str(body.get("source") or "youtube").strip()
        url = str(body.get("url") or "").strip()
        niche = str(body.get("niche") or "").strip()
        view_count = int(body.get("view_count") or 0)
        duration = int(body.get("duration") or 0)

        like_count = int(body.get("like_count") or 0)
        comment_count = int(body.get("comment_count") or 0)

        prompt_niche = niche or f"{source} trend"
        if title:
            prompt_niche = f"{prompt_niche}: {title[:120]}"

        groq_key = _pipeline_for(tenant_id).groq_api_key
        ai_meta, ubt_result = await asyncio.gather(
            ai_copywriter.generate_metadata(groq_key, prompt_niche),
            ubt_detector.classify_video(body, api_key=groq_key),
            return_exceptions=True,
        )
        if isinstance(ai_meta, Exception):
            ai_meta = {}
        if isinstance(ubt_result, Exception):
            ubt_result = {"status": "ERROR", "message": str(ubt_result)}

        # ── Detailed scoring engine ──────────────────────────────────────────
        score = 50
        reasons: list[str] = []
        breakdown: dict = {}

        # 1. Views score (0–30 pts)
        if view_count >= 5_000_000:
            pts = 30; reasons.append("Мега-вирусное видео (5M+ просмотров)")
        elif view_count >= 1_000_000:
            pts = 25; reasons.append("Очень высокий трафик (1M+ просмотров)")
        elif view_count >= 500_000:
            pts = 20; reasons.append("Высокий органический охват (500K+)")
        elif view_count >= 100_000:
            pts = 15; reasons.append("Хороший объём просмотров (100K+)")
        elif view_count >= 20_000:
            pts = 8;  reasons.append("Подтверждённый спрос (20K+)")
        elif view_count >= 5_000:
            pts = 3;  reasons.append("Малый охват, проверьте нишу")
        else:
            pts = -5; reasons.append("Очень низкие просмотры — риск")
        score += pts
        breakdown["views"] = {"pts": pts, "value": view_count}

        # 2. Engagement rate score (0–20 pts)
        engagement_rate = 0.0
        if view_count > 0 and (like_count > 0 or comment_count > 0):
            engagement_rate = round((like_count + comment_count * 3) / view_count * 100, 2)
        if engagement_rate >= 10:
            pts = 20; reasons.append(f"Отличный engagement rate {engagement_rate:.1f}% (10%+)")
        elif engagement_rate >= 5:
            pts = 14; reasons.append(f"Хороший engagement rate {engagement_rate:.1f}%")
        elif engagement_rate >= 2:
            pts = 8;  reasons.append(f"Средний engagement rate {engagement_rate:.1f}%")
        elif engagement_rate > 0:
            pts = 2
        else:
            pts = 0
        score += pts
        breakdown["engagement"] = {"pts": pts, "rate": engagement_rate, "likes": like_count, "comments": comment_count}

        # 3. Duration score for Shorts UBT (0–15 pts)
        if 15 <= duration <= 45:
            pts = 15; reasons.append("Идеальная длина для Shorts (15–45с)")
        elif 45 < duration <= 60:
            pts = 10; reasons.append("Хорошая длина (45–60с)")
        elif 8 <= duration < 15:
            pts = 7;  reasons.append("Короткий формат — хук под вопросом")
        elif 60 < duration <= 90:
            pts = 5;  reasons.append("Длинновато для Shorts, нужно обрезать")
        elif duration > 90:
            pts = -8; reasons.append("Слишком длинный контент (>90с)")
        else:
            pts = 0
        score += pts
        breakdown["duration"] = {"pts": pts, "seconds": duration}

        # 4. Keyword / topic virality (0–10 pts)
        viral_keywords = {
            "casino": 10, "казино": 10, "slots": 10, "слоты": 10,
            "reaction": 8, "реакция": 8, "drama": 7, "дорама": 7,
            "prank": 9, "pranks": 9, "viral": 9, "вирус": 7,
            "win": 6, "winning": 6, "jackpot": 10, "money": 6,
            "тайланд": 7, "korea": 6, "malaysia": 6, "asian": 6,
        }
        title_lower = title.lower()
        kw_pts = max((v for k, v in viral_keywords.items() if k in title_lower), default=0)
        score += kw_pts
        breakdown["keywords"] = {"pts": kw_pts}
        if kw_pts >= 9:
            reasons.append("Горячий вирусный тег в названии")
        elif kw_pts >= 6:
            reasons.append("Умеренно вирусная тема")

        # 5. Source bonus (0–5 pts)
        src_bonus = {"youtube": 5, "tiktok": 4, "instagram": 3}.get(source, 2)
        score += src_bonus
        breakdown["source"] = {"pts": src_bonus, "platform": source}

        score = max(1, min(99, score))
        risk = "low" if score >= 70 else ("medium" if score >= 45 else "high")

        # Preset recommendation based on score + risk
        if score >= 80:
            preset = "Aggressive MAX"
        elif score >= 70:
            preset = "Aggressive"
        elif score >= 60:
            preset = "Balanced+"
        elif score >= 50:
            preset = "Balanced"
        elif score >= 40:
            preset = "Subtle+"
        else:
            preset = "Subtle"

        # Action plan based on score
        if score >= 70:
            action_plan = [
                "Запустить 5–8 уникализаций немедленно, пока тренд горячий",
                "Использовать preset Aggressive с Mirror + Color Shift",
                "Прайм-слоты: 19:00–22:00 по целевому региону",
                "Мониторить метрики через 1ч — если CTR >8%, масштабировать",
                "Добавить overlay-текст для усиления hook в первые 2 сек",
            ]
        elif score >= 50:
            action_plan = [
                "Сделать 3–5 вариаций с разными пресетами эффектов",
                "Проверить дублирование перед заливом на каждый канал",
                "Тестировать в 2 слота: 12:00 и 20:00",
                "Сравнить метрики 6h — оставить лучший вариант для масштаба",
            ]
        else:
            action_plan = [
                "Осторожно — спрос не подтверждён, тест 1–2 каналов",
                "Использовать Subtle пресет, минимальные изменения",
                "Мониторить вручную первые 24ч перед масштабом",
            ]

        # Viral coefficient estimate
        viral_coeff = round(engagement_rate * (view_count / 10_000 if view_count < 1_000_000 else 100), 1)

        recommendation = {
            "score": score,
            "risk": risk,
            "preset": preset,
            "reasons": reasons[:5],
            "action_plan": action_plan,
            "breakdown": breakdown,
            "engagement_rate": engagement_rate,
            "viral_coeff": min(viral_coeff, 9999),
            "ai_title": ai_meta.get("title"),
            "ai_description": ai_meta.get("description"),
            "ai_comment": ai_meta.get("comment"),
            "overlay_text": ai_meta.get("overlay_text"),
            "used_fallback": bool(ai_meta.get("used_fallback")),
            "ubt": ubt_result,
            "input": {
                "title": title,
                "channel": channel,
                "url": url,
                "source": source,
                "view_count": view_count,
                "like_count": like_count,
                "comment_count": comment_count,
                "duration": duration,
            },
        }
        return {"status": "ok", "advice": recommendation}
    except Exception as exc:
        logger.exception("research_advice: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/risk-label")
async def research_risk_label(tenant_id: TenantDep, body: dict):
    try:
        video_id = str(body.get("video_id") or "").strip()
        url = str(body.get("url") or "").strip()
        source = str(body.get("source") or "youtube").strip()
        label = str(body.get("label") or "").strip()
        score = int(body.get("risk_score") or 0)
        if not video_id and not url:
            return JSONResponse({"status": "error", "message": "video_id или url обязательны."}, status_code=400)
        rows = _load_risk_labels()
        rows.append(
            {
                "tenant_id": normalize_tenant_id(tenant_id),
                "video_id": video_id,
                "url": url,
                "source": source,
                "label": label,
                "risk_score": score,
                "created_at": dt.datetime.utcnow().isoformat() + "Z",
            }
        )
        _save_risk_labels(rows[-5000:])
        return _json_ok({"saved": True})
    except Exception as exc:
        logger.exception("research_risk_label: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось сохранить метку риска."}, status_code=500)


@app.get("/api/research/risk-telemetry")
async def research_risk_telemetry(tenant_id: TenantDep):
    try:
        tid = normalize_tenant_id(tenant_id)
        rows = [r for r in _load_risk_labels() if str(r.get("tenant_id") or "default") == tid]
        tier_counts = {"low": 0, "medium": 0, "high": 0}
        label_counts: dict[str, int] = {}
        signal_counts: dict[str, int] = {}

        for r in rows:
            score = int(r.get("risk_score") or 0)
            tier = "high" if score >= 65 else ("medium" if score >= 35 else "low")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            label = str(r.get("label") or "").strip()
            if label:
                label_counts[label] = label_counts.get(label, 0) + 1
                signal_counts[label] = signal_counts.get(label, 0) + 1

        top_signals = [
            {"signal": k, "count": v}
            for k, v in sorted(signal_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        return _json_ok(
            {
                "tier_counts": tier_counts,
                "top_signals": top_signals,
                "label_counts": label_counts,
                "total": len(rows),
            }
        )
    except Exception as exc:
        logger.exception("research_risk_telemetry: %s", exc)
        return JSONResponse({"status": "error", "message": "Не удалось получить телеметрию риска."}, status_code=500)


@app.post("/api/research/ubt-classify")
async def research_ubt_classify(tenant_id: TenantDep, body: dict):
    """
    LLM-классификатор UBT/арбитражного контента.
    Body: { title, description?, tags?, ocr_text?, transcript?, pinned_comment?, url? }
    """
    try:
        api_key = _pipeline_for(tenant_id).groq_api_key
        result = await ubt_detector.classify_video(body, api_key=api_key)
        return _json_ok(result)
    except Exception as exc:
        logger.exception("research_ubt_classify: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@app.post("/api/research/ubt-batch")
async def research_ubt_batch(tenant_id: TenantDep, body: dict):
    """
    Пакетная LLM-классификация списка видео.
    Body: { videos: [...], concurrency?: 3 }
    """
    try:
        videos = body.get("videos") or []
        if not isinstance(videos, list) or not videos:
            return JSONResponse({"status": "error", "message": "videos must be a non-empty list"}, status_code=400)
        concurrency = max(1, min(int(body.get("concurrency") or 3), 5))
        api_key = _pipeline_for(tenant_id).groq_api_key
        results = await ubt_detector.batch_classify(videos, api_key=api_key, concurrency=concurrency)
        ubt_count = sum(1 for r in results if r.get("status") == "UBT_FOUND")
        return _json_ok({"results": results, "total": len(results), "ubt_found": ubt_count})
    except Exception as exc:
        logger.exception("research_ubt_batch: %s", exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


# ──────────────────────────── Campaigns ───────────────────────────────────────

@app.get("/api/campaigns")
async def campaigns_list(tenant_id: TenantDep):
    return await dbmod.list_campaigns(tenant_id)


@app.post("/api/campaigns")
async def campaigns_create(tenant_id: TenantDep, body: dict):
    name = str(body.get("name") or "").strip()
    if not name:
        return JSONResponse({"status": "error", "message": "Укажите название кампании"}, status_code=400)
    return await dbmod.create_campaign(
        tenant_id=tenant_id,
        name=name,
        niche=str(body.get("niche") or ""),
        profile_ids=body.get("profile_ids") or [],
        preset=str(body.get("preset") or ""),
        template=str(body.get("template") or ""),
        effects=body.get("effects") or [],
        proxy_group=str(body.get("proxy_group") or ""),
    )


@app.patch("/api/campaigns/{campaign_id}")
async def campaigns_update(campaign_id: int, tenant_id: TenantDep, body: dict):
    return await dbmod.update_campaign(campaign_id, tenant_id, patch=body)


@app.delete("/api/campaigns/{campaign_id}")
async def campaigns_delete(campaign_id: int, tenant_id: TenantDep):
    return await dbmod.delete_campaign(campaign_id, tenant_id)


@app.get("/api/campaigns/{campaign_id}/stats")
async def campaigns_stats(campaign_id: int, tenant_id: TenantDep):
    return await dbmod.get_campaign_stats(campaign_id, tenant_id)


# ──────────────────────────── Cookie Backup ───────────────────────────────────

_COOKIE_BACKUPS_DIR = ROOT / "data" / "cookie_backups"


@app.get("/api/cookies/backups")
async def cookies_list_backups(tenant_id: TenantDep):
    """List all cookie backup files."""
    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    backups = []
    if backup_dir.exists():
        for f in sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix == ".json":
                stat = f.stat()
                backups.append({
                    "filename": f.name,
                    "profile_id": f.stem.split("_backup_")[0] if "_backup_" in f.stem else f.stem,
                    "created_at": f.stem.split("_backup_")[-1] if "_backup_" in f.stem else "",
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": stat.st_mtime,
                })
    return {"status": "ok", "backups": backups}


@app.post("/api/cookies/backup/{profile_id}")
async def cookies_backup(profile_id: str, tenant_id: TenantDep):
    """
    Backup cookies for the given AdsPower profile.
    Calls AdsPower API to export cookies and stores them as JSON.
    """
    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    backup_dir.mkdir(parents=True, exist_ok=True)

    try:
        import datetime
        import httpx

        pipeline = _pipeline_for(tenant_id)
        adspower_url = getattr(pipeline, "adspower_api_url", None) or os.environ.get("ADSPOWER_API_URL", "http://local.adspower.net:50325")

        async with httpx.AsyncClient(timeout=15) as client:
            # AdsPower supports /api/v1/browser/cookies/export (some versions)
            resp = await client.get(
                f"{adspower_url}/api/v1/browser/cookies",
                params={"user_id": profile_id},
            )
            data = resp.json()

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{profile_id}_backup_{ts}.json"
        backup_file.write_text(
            json.dumps({"profile_id": profile_id, "cookies": data, "backed_up_at": ts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"status": "ok", "filename": backup_file.name, "profile_id": profile_id}
    except Exception as exc:
        logger.exception("cookie_backup %s: %s", profile_id, exc)
        # Create a placeholder backup with metadata
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{profile_id}_backup_{ts}.json"
        backup_file.write_text(
            json.dumps({"profile_id": profile_id, "cookies": [], "backed_up_at": ts, "error": str(exc)}, indent=2),
            encoding="utf-8",
        )
        return {"status": "partial", "filename": backup_file.name, "message": f"Бэкап создан с ошибкой: {exc}"}


@app.post("/api/cookies/restore/{profile_id}")
async def cookies_restore(profile_id: str, tenant_id: TenantDep, body: dict):
    """
    Restore cookies for a profile from the latest (or specified) backup file.
    """
    backup_dir = _COOKIE_BACKUPS_DIR / normalize_tenant_id(tenant_id)
    filename = body.get("filename")
    if filename:
        backup_root = backup_dir.resolve()
        backup_file = (backup_dir / str(filename)).resolve()
        try:
            backup_file.relative_to(backup_root)
        except ValueError:
            return JSONResponse({"status": "error", "message": "Некорректный путь к файлу бэкапа."}, status_code=400)
        if backup_file.suffix.lower() != ".json":
            return JSONResponse({"status": "error", "message": "Разрешены только .json бэкапы."}, status_code=400)
    else:
        # Find latest backup for this profile
        candidates = sorted(
            [f for f in backup_dir.iterdir() if f.stem.startswith(f"{profile_id}_backup_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ) if backup_dir.exists() else []
        if not candidates:
            return JSONResponse({"status": "error", "message": "Бэкап не найден"}, status_code=404)
        backup_file = candidates[0]

    if not backup_file.exists():
        return JSONResponse({"status": "error", "message": "Файл бэкапа не найден"}, status_code=404)

    try:
        import httpx
        backup_data = json.loads(backup_file.read_text(encoding="utf-8"))
        cookies = backup_data.get("cookies", [])

        pipeline = _pipeline_for(tenant_id)
        adspower_url = getattr(pipeline, "adspower_api_url", None) or os.environ.get("ADSPOWER_API_URL", "http://local.adspower.net:50325")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{adspower_url}/api/v1/browser/cookies/import",
                json={"user_id": profile_id, "cookies": cookies},
            )
            result = resp.json()

        return {"status": "ok", "profile_id": profile_id, "filename": backup_file.name, "adspower_response": result}
    except Exception as exc:
        logger.exception("cookie_restore %s: %s", profile_id, exc)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


# ─── KST Scheduler endpoints ──────────────────────────────────────────────────


@app.get("/api/kst/status")
async def kst_status():
    """
    Текущее время KST, статус активного окна (09:00–22:00 KST) и минуты до открытия.
    Использовать в UI как индикатор «сейчас можно заливать».
    """
    from core.kst_scheduler import kst_status_summary
    return _json_ok(kst_status_summary())


class DailyLimitBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limit: int


@app.get("/api/profiles/{profile_id}/daily-limit")
async def get_daily_limit(profile_id: str, tenant_id: TenantDep):
    """
    Лимит заливок на аккаунт + сколько уже залито сегодня (по KST).
    Поле can_upload = True если ещё есть слоты.
    """
    limit_res = await dbmod.get_profile_daily_limit(profile_id, tenant_id=tenant_id)
    count_res = await dbmod.get_profile_daily_upload_count(profile_id, tenant_id=tenant_id)
    if limit_res.get("status") != "ok":
        return JSONResponse(limit_res, status_code=400)
    if count_res.get("status") != "ok":
        return JSONResponse(count_res, status_code=400)
    daily_limit = int(limit_res["daily_upload_limit"])
    used_today  = int(count_res["count"])
    return _json_ok({
        "profile_id":         profile_id,
        "daily_upload_limit": daily_limit,
        "used_today":         used_today,
        "remaining":          max(0, daily_limit - used_today),
        "can_upload":         used_today < daily_limit,
        "day_start_utc":      count_res["day_start_utc"],
        "day_end_utc":        count_res["day_end_utc"],
    })


@app.post("/api/profiles/{profile_id}/daily-limit")
async def set_daily_limit(profile_id: str, body: DailyLimitBody, tenant_id: TenantDep):
    """
    Установить дневной лимит заливок для аккаунта. Диапазон: 1–20.
    Рекомендуемые значения: новый аккаунт — 1–2, прогретый — 3–5.
    """
    res = await dbmod.set_profile_daily_limit(profile_id, body.limit, tenant_id=tenant_id)
    if res.get("status") != "ok":
        return JSONResponse(res, status_code=400)
    return _json_ok(res)


class DistributeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    profile_ids:    list[str]
    task_id:        int
    title:          str = ""
    description:    str = ""
    comment:        str | None = None
    tags:           list[str] | None = None
    thumbnail_path: str | None = None
    start_hour:     int = 9
    end_hour:       int = 22
    jitter_minutes: int = 8
    skip_over_limit: bool = True   # не создавать job для аккаунтов, достигших лимита


@app.post("/api/schedule/distribute")
async def schedule_distribute(
    body: DistributeBody,
    background_tasks: BackgroundTasks,
    tenant_id: TenantDep,
):
    """
    Разместить одну заливку на каждый аккаунт из списка, распределив задачи
    по активному окну 09:00–22:00 KST с рандомным jitter.

    Автоматически пропускает аккаунты, исчерпавшие дневной лимит (если skip_over_limit=True).
    Создаёт profile_job с типом 'publish' и scheduled_at в UTC.

    Возвращает: список созданных job'ов с временем KST, список пропущенных аккаунтов.
    """
    from core.kst_scheduler import distribute_uploads_kst

    if not body.profile_ids:
        return JSONResponse({"status": "error", "message": "profile_ids не может быть пустым."}, status_code=400)

    # Фильтруем аккаунты, достигшие лимита.
    eligible: list[str] = []
    skipped:  list[dict] = []

    for pid in body.profile_ids:
        if body.skip_over_limit:
            limit_res = await dbmod.get_profile_daily_limit(pid, tenant_id=tenant_id)
            count_res = await dbmod.get_profile_daily_upload_count(pid, tenant_id=tenant_id)
            used  = int(count_res.get("count") or 0) if count_res.get("status") == "ok" else 0
            limit = int(limit_res.get("daily_upload_limit") or 3) if limit_res.get("status") == "ok" else 3
            if used >= limit:
                skipped.append({"profile_id": pid, "reason": f"лимит исчерпан ({used}/{limit})"})
                continue
        eligible.append(pid)

    if not eligible:
        return _json_ok({
            "scheduled": [],
            "skipped":   skipped,
            "message":   "Все аккаунты исчерпали дневной лимит.",
        })

    # Распределяем слоты по KST-окну.
    slots = distribute_uploads_kst(
        eligible,
        start_hour=body.start_hour,
        end_hour=body.end_hour,
        jitter_minutes=body.jitter_minutes,
    )

    payload = {
        "task_id":        body.task_id,
        "title":          body.title,
        "description":    body.description,
        "comment":        body.comment,
        "tags":           body.tags,
        "thumbnail_path": body.thumbnail_path,
    }

    scheduled: list[dict] = []
    for slot in slots:
        job_res = await dbmod.create_profile_job(
            adspower_profile_id=slot["profile_id"],
            job_type="publish",
            scheduled_at=slot["scheduled_at_utc"],
            payload_json=__import__("json").dumps(payload, ensure_ascii=False),
            tenant_id=tenant_id,
        )
        if job_res.get("status") == "ok":
            scheduled.append({
                "profile_id":       slot["profile_id"],
                "job_id":           job_res.get("id"),
                "scheduled_at_utc": slot["scheduled_at_utc"],
                "scheduled_at_kst": slot["scheduled_at_kst"],
            })
        else:
            skipped.append({"profile_id": slot["profile_id"], "reason": job_res.get("message", "ошибка создания job")})

    return _json_ok({
        "scheduled": scheduled,
        "skipped":   skipped,
        "total_scheduled": len(scheduled),
        "total_skipped":   len(skipped),
    })


# ── Campaign Runner ───────────────────────────────────────────────────────────

from core import campaign_runner as _cr
from core.campaign_runner import CampaignRunConfig


class CampaignRunBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str                              # warmup_only / farm_cookies / upload_only / full
    profile_ids: list[str]                   # AdsPower profile IDs
    video_path: str | None = None            # абсолютный путь к видео
    niche: str = ""                          # ниша (запятые как разделитель)
    warmup_intensity: str = "medium"         # light / medium / deep
    concurrency: int = 3                     # профилей одновременно (1–10)
    campaign_id: int | None = None           # необязательная ссылка на campaigns.id
    adspower_api_url: str = "http://local.adspower.net:50325"


@app.post("/api/campaign-runs")
async def start_campaign_run(body: CampaignRunBody, tenant_id: TenantDep):
    """
    Запустить кампанию: прогрев, уникализация, загрузка, куки — за один вызов.

    Пресеты:
      - `warmup_only`  — только прогрев профиля
      - `farm_cookies` — прогрев + сохранение cookies
      - `upload_only`  — только загрузка видео (требует video_path)
      - `full`         — прогрев → загрузка → аналитика (требует video_path)
    """
    cfg = CampaignRunConfig(
        preset=body.preset,
        profile_ids=body.profile_ids,
        tenant_id=tenant_id,
        video_path=body.video_path,
        niche=body.niche,
        warmup_intensity=body.warmup_intensity,
        concurrency=max(1, min(10, body.concurrency)),
        campaign_id=body.campaign_id,
        adspower_api_url=body.adspower_api_url,
    )
    res = await _cr.start_campaign_run(cfg)
    if res.get("status") != "ok":
        return JSONResponse(res, status_code=400)
    return _json_ok(res)


@app.get("/api/campaign-runs")
async def list_campaign_runs(tenant_id: TenantDep, limit: int = Query(50, ge=1, le=200)):
    """Список запусков кампаний (последние N, по убыванию даты)."""
    res = await dbmod.list_campaign_runs(tenant_id=tenant_id, limit=limit)
    if res.get("status") != "ok":
        return JSONResponse(res, status_code=500)
    active = _cr.get_active_runs()
    return _json_ok({**res, "active_run_ids": active})


@app.get("/api/campaign-runs/{run_id}")
async def get_campaign_run(run_id: int, tenant_id: TenantDep):
    """Детали конкретного запуска, включая per-profile результаты."""
    res = await dbmod.get_campaign_run(run_id, tenant_id=tenant_id)
    if res.get("status") != "ok":
        return JSONResponse(res, status_code=404)
    run = res["run"]
    run["is_active"] = run_id in _cr.get_active_runs()
    return _json_ok({"run": run})


@app.post("/api/campaign-runs/{run_id}/cancel")
async def cancel_campaign_run(run_id: int, tenant_id: TenantDep):
    """Отменить запущенный воркер (или пометить завершённый как cancelled)."""
    res = await _cr.cancel_campaign_run(run_id, tenant_id=tenant_id)
    return _json_ok(res)


class CookieFarmerBody(BaseModel):
    interval_sec: int = 1800
    batch_size: int = 5
    warmup_intensity: str = "light"
    niche: str = "general"
    adspower_api_url: str = "http://127.0.0.1:50325"


@app.post("/api/cookie-farmer/start")
async def start_cookie_farmer(body: CookieFarmerBody, tenant_id: TenantDep):
    from core import cookie_farmer

    cfg = cookie_farmer.CookieFarmerConfig(
        tenant_id=tenant_id,
        interval_sec=max(30, body.interval_sec),
        batch_size=max(1, min(20, body.batch_size)),
        warmup_intensity=body.warmup_intensity,
        niche=body.niche,
        adspower_api_url=body.adspower_api_url,
    )
    res = await cookie_farmer.start(cfg)
    return _json_ok(res)


@app.post("/api/cookie-farmer/stop")
async def stop_cookie_farmer(tenant_id: TenantDep):
    from core import cookie_farmer

    res = await cookie_farmer.stop(tenant_id=tenant_id)
    return _json_ok(res)


@app.get("/api/cookie-farmer/status")
async def cookie_farmer_status(tenant_id: TenantDep):
    from core import cookie_farmer

    return _json_ok(cookie_farmer.get_status(tenant_id=tenant_id))


@app.get("/api/cookie-farmer/profiles")
async def cookie_farmer_profiles(tenant_id: TenantDep):
    """Per-profile farming status (last farmed time, total cycles, errors)."""
    from core import cookie_farmer

    profiles = cookie_farmer.get_profiles_status(tenant_id=tenant_id)
    return _json_ok({"profiles": profiles})


class CookieFarmerRunNowBody(BaseModel):
    profile_id: str
    warmup_intensity: str = "light"
    niche: str = "general"
    adspower_api_url: str = "http://127.0.0.1:50325"


@app.post("/api/cookie-farmer/run-now")
async def cookie_farmer_run_now(body: CookieFarmerRunNowBody, tenant_id: TenantDep):
    """Запустить немедленный фарминг для конкретного профиля (без шедулера)."""
    from core import cookie_farmer

    res = await cookie_farmer.farm_now(
        profile_id=body.profile_id,
        tenant_id=tenant_id,
        warmup_intensity=body.warmup_intensity,
        niche=body.niche,
        adspower_api_url=body.adspower_api_url,
    )
    return _json_ok(res)


@app.delete("/api/cookie-farmer/run-now/{profile_id}")
async def cookie_farmer_cancel_run_now(profile_id: str, tenant_id: TenantDep):
    """Отменить ручной фарминг профиля."""
    from core import cookie_farmer

    res = cookie_farmer.cancel_farm_now(profile_id=profile_id)
    return _json_ok(res)


# ── Antidetect Browsers ───────────────────────────────────────────────────────

class AntidetectBrowserBody(BaseModel):
    name: str
    browser_type: str = "adspower"
    api_url: str = ""
    api_key: str = ""
    use_auth: bool = False
    is_active: bool = True
    notes: str = ""


@app.get("/api/antidetect")
async def list_antidetect_browsers(tenant_id: TenantDep):
    """Список всех антидетект-браузеров."""
    res = await dbmod.list_antidetect_browsers(tenant_id=tenant_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/antidetect")
async def create_antidetect_browser(body: AntidetectBrowserBody, tenant_id: TenantDep):
    """Зарегистрировать новый антидетект-браузер."""
    from core.antidetect_client import SUPPORTED_BROWSER_TYPES, default_url
    url = body.api_url.strip() or default_url(body.browser_type)
    res = await dbmod.upsert_antidetect_browser(
        name=body.name,
        browser_type=body.browser_type,
        api_url=url,
        api_key=body.api_key,
        use_auth=body.use_auth,
        is_active=body.is_active,
        notes=body.notes,
        tenant_id=tenant_id,
    )
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("message"))
    # Перезагрузить реестр
    try:
        from core.antidetect_registry import get_registry
        await get_registry().reload()
    except Exception:
        pass
    return _json_ok(res)


@app.get("/api/antidetect/{browser_id}")
async def get_antidetect_browser(browser_id: int, tenant_id: TenantDep):
    res = await dbmod.get_antidetect_browser(browser_id, tenant_id=tenant_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return _json_ok(res)


@app.put("/api/antidetect/{browser_id}")
async def update_antidetect_browser(browser_id: int, body: AntidetectBrowserBody, tenant_id: TenantDep):
    """Обновить параметры антидетекта (по имени внутри тенанта)."""
    from core.antidetect_client import default_url
    url = body.api_url.strip() or default_url(body.browser_type)
    res = await dbmod.upsert_antidetect_browser(
        name=body.name,
        browser_type=body.browser_type,
        api_url=url,
        api_key=body.api_key,
        use_auth=body.use_auth,
        is_active=body.is_active,
        notes=body.notes,
        tenant_id=tenant_id,
    )
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("message"))
    try:
        from core.antidetect_registry import get_registry
        await get_registry().reload()
    except Exception:
        pass
    return _json_ok(res)


@app.delete("/api/antidetect/{browser_id}")
async def delete_antidetect_browser(browser_id: int, tenant_id: TenantDep):
    res = await dbmod.delete_antidetect_browser(browser_id, tenant_id=tenant_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=404, detail=res.get("message"))
    try:
        from core.antidetect_registry import get_registry
        await get_registry().reload()
    except Exception:
        pass
    return _json_ok(res)


@app.post("/api/antidetect/{browser_id}/verify")
async def verify_antidetect(browser_id: int, tenant_id: TenantDep):
    """Проверить связь с конкретным антидетектом."""
    from core.antidetect_registry import get_registry
    registry = get_registry()
    client = registry.get_client(browser_id)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Антидетект id={browser_id} не загружен в реестр.")
    res = await client.verify_connection()
    return _json_ok(res)


@app.post("/api/antidetect/{browser_id}/sync")
async def sync_antidetect_profiles(browser_id: int, tenant_id: TenantDep):
    """Синхронизировать профили из конкретного антидетекта в БД."""
    from core.antidetect_registry import get_registry
    registry = get_registry()
    res = await registry.sync_profiles(browser_id, tenant_id=tenant_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/antidetect/sync-all")
async def sync_all_antidetect_profiles(tenant_id: TenantDep):
    """Синхронизировать профили из ВСЕХ антидетектов."""
    from core.antidetect_registry import get_registry
    registry = get_registry()
    res = await registry.sync_all_profiles(tenant_id=tenant_id)
    return _json_ok(res)


@app.get("/api/antidetect/status/all")
async def antidetect_status_all():
    """Статус всех антидетектов в реестре (ping без sync)."""
    from core.antidetect_registry import get_registry
    registry = get_registry()
    res = await registry.verify_all()
    return _json_ok(res)


@app.post("/api/antidetect/reload")
async def reload_antidetect_registry(tenant_id: TenantDep):
    """Перезагрузить реестр (после ручного изменения в БД)."""
    from core.antidetect_registry import get_registry
    await get_registry().reload()
    count = get_registry().count()
    return _json_ok({"reloaded": True, "clients_count": count})


# ── Proxy Management ─────────────────────────────────────────────────────────

class ProxyBody(BaseModel):
    host: str
    port: int
    protocol: str = "http"
    username: str = ""
    password: str = ""
    name: str = ""
    group_name: str = ""
    notes: str = ""


class ProxyBulkBody(BaseModel):
    lines: str          # raw text, one proxy per line
    protocol: str = "http"
    group_name: str = ""


class ProxyAssignBody(BaseModel):
    proxy_id: int | None = None   # None = unassign


@app.get("/api/proxies")
async def list_proxies(tenant_id: TenantDep, group: str | None = None, status: str | None = None):
    res = await dbmod.list_proxies(tenant_id=tenant_id, group_name=group, status_filter=status)
    if res.get("status") != "ok":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/proxies")
async def create_proxy(body: ProxyBody, tenant_id: TenantDep):
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.upsert_proxy(
        host=body.host, port=body.port, protocol=body.protocol,
        username=body.username, password=body.password,
        name=body.name, group_name=body.group_name, notes=body.notes,
        tenant_id=tenant_id, db_path=pipe.db_path,
    )
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/proxies/bulk")
async def create_proxies_bulk(body: ProxyBulkBody, tenant_id: TenantDep):
    """Массовый импорт прокси (host:port:user:pass или protocol://user:pass@host:port)."""
    from core.proxy_checker import parse_proxy_line
    pipe = _pipeline_for(tenant_id)
    added = 0
    errors = []
    for raw_line in body.lines.splitlines():
        parsed = parse_proxy_line(raw_line)
        if not parsed:
            continue
        res = await dbmod.upsert_proxy(
            host=parsed["host"], port=parsed["port"],
            protocol=parsed.get("protocol") or body.protocol,
            username=parsed.get("username") or "",
            password=parsed.get("password") or "",
            group_name=body.group_name,
            tenant_id=tenant_id, db_path=pipe.db_path,
        )
        if res.get("status") == "ok":
            added += 1
        else:
            errors.append({"line": raw_line, "error": res.get("message")})
    return _json_ok({"added": added, "errors": errors})


@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int, tenant_id: TenantDep):
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.delete_proxy(proxy_id, tenant_id=tenant_id, db_path=pipe.db_path)
    if res.get("status") != "ok":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/proxies/{proxy_id}/check")
async def check_proxy_single(proxy_id: int, tenant_id: TenantDep):
    """Проверить одну прокси и сохранить результат."""
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.list_proxies(tenant_id=tenant_id, db_path=pipe.db_path)
    proxies = res.get("proxies") or []
    proxy = next((p for p in proxies if p["id"] == proxy_id), None)
    if not proxy:
        raise HTTPException(status_code=404, detail="Прокси не найден.")
    from core.proxy_checker import check_proxy
    result = await check_proxy(
        proxy_id=proxy_id, host=proxy["host"], port=proxy["port"],
        protocol=proxy.get("protocol") or "http",
        username=proxy.get("username") or "",
        password=proxy.get("password") or "",
        db_path=str(pipe.db_path),
    )
    return _json_ok(result)


@app.post("/api/proxies/check-all")
async def check_all_proxies_ep(tenant_id: TenantDep):
    """Проверить все прокси параллельно (фоновая задача)."""
    pipe = _pipeline_for(tenant_id)
    from core.proxy_checker import check_all_proxies
    result = await check_all_proxies(tenant_id=tenant_id, db_path=str(pipe.db_path))
    return _json_ok(result)


@app.post("/api/proxies/{proxy_id}/assign/{profile_id}")
async def assign_proxy(proxy_id: int, profile_id: str, tenant_id: TenantDep):
    """Привязать прокси к профилю."""
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.assign_proxy_to_profile(
        profile_id=profile_id, proxy_id=proxy_id,
        tenant_id=tenant_id, db_path=pipe.db_path,
    )
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return _json_ok(res)


@app.delete("/api/proxies/assign/{profile_id}")
async def unassign_proxy(profile_id: str, tenant_id: TenantDep):
    """Снять прокси с профиля."""
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.assign_proxy_to_profile(
        profile_id=profile_id, proxy_id=None,
        tenant_id=tenant_id, db_path=pipe.db_path,
    )
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return _json_ok(res)


@app.post("/api/proxies/rotate/{profile_id}")
async def rotate_proxy(profile_id: str, tenant_id: TenantDep):
    """Ротация: назначить следующую живую прокси из той же группы."""
    pipe = _pipeline_for(tenant_id)
    from core.proxy_checker import rotate_proxy_for_profile
    res = await rotate_proxy_for_profile(
        profile_id=profile_id, tenant_id=tenant_id, db_path=str(pipe.db_path)
    )
    return _json_ok(res)


@app.get("/api/proxies/profile/{profile_id}")
async def get_profile_proxy_ep(profile_id: str, tenant_id: TenantDep):
    """Прокси, привязанный к профилю."""
    pipe = _pipeline_for(tenant_id)
    res = await dbmod.get_profile_proxy(
        profile_id=profile_id, tenant_id=tenant_id, db_path=pipe.db_path
    )
    return _json_ok(res)


def _mount_static_ui() -> None:
    """
    React-сборка: web/dist → /ui, классический UI → /ui/legacy (iframe).
    Без сборки: только legacy → /ui (как раньше).
    """
    has_dist = WEB_DIST.is_dir() and (WEB_DIST / "index.html").is_file()
    has_legacy = WEB_LEGACY.is_dir() and (WEB_LEGACY / "index.html").is_file()

    if not has_dist and not has_legacy:
        logger.warning(
            "UI не смонтирован: нет web/dist (npm run build в frontend/) и нет web/legacy/index.html"
        )
        return

    if has_legacy:
        app.mount(
            "/ui/legacy",
            StaticFiles(directory=str(WEB_LEGACY), html=True),
            name="ui_legacy",
        )
    if has_dist:
        app.mount("/ui", StaticFiles(directory=str(WEB_DIST), html=True), name="ui")
    elif has_legacy:
        app.mount("/ui", StaticFiles(directory=str(WEB_LEGACY), html=True), name="ui")


_mount_static_ui()


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/ui/")
