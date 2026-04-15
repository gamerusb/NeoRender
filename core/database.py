"""
Локальная база данных NeoRender Pro (aiosqlite).

Все сущности привязаны к tenant_id (изоляция для будущего SaaS).
MVP: tenant_id = \"default\".

Публичные операции без исключений наружу: {\"status\": \"error\", \"message\": \"...\"}.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

from .luxury_engine import _normalize_template
from .tenancy import DEFAULT_TENANT_ID, normalize_tenant_id

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "neorender.db"

logger = logging.getLogger(__name__)


def _error(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _tid(tenant_id: str | None) -> str:
    if tenant_id is None:
        return DEFAULT_TENANT_ID
    return normalize_tenant_id(tenant_id)


_FRESH_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    adspower_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle',
    UNIQUE(tenant_id, adspower_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    original_video TEXT NOT NULL,
    unique_video TEXT,
    target_profile TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'rendering', 'transcribing', 'uploading',
            'success', 'error'
        )),
    error_message TEXT,
    error_type TEXT,
    warning_message TEXT,
    render_only INTEGER NOT NULL DEFAULT 0,
    subtitle TEXT,
    template TEXT,
    effects_json TEXT,
    scheduled_at TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    device_model TEXT,
    geo_profile TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    video_url TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'shadowban', 'banned')),
    checked_at TEXT,
    published_at TEXT,
    UNIQUE(tenant_id, video_url)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_profiles_tenant ON profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_profiles_adspower ON profiles(tenant_id, adspower_id);
CREATE INDEX IF NOT EXISTS idx_analytics_tenant_url ON analytics(tenant_id, video_url);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(tenant_id, scheduled_at) WHERE scheduled_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(tenant_id, status, priority DESC, id ASC);
"""


_PROFILE_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS antidetect_browsers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    browser_type TEXT NOT NULL DEFAULT 'adspower'
        CHECK (browser_type IN ('adspower', 'dolphin', 'octo', 'multilogin', 'custom')),
    api_url TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    use_auth INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    profiles_count INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_id, name)
);

CREATE TABLE IF NOT EXISTS adspower_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    adspower_profile_id TEXT NOT NULL,
    profile_name TEXT NOT NULL DEFAULT '',
    group_name TEXT,
    proxy_name TEXT,
    platform TEXT NOT NULL DEFAULT 'youtube',
    geo TEXT,
    language TEXT,
    tags_json TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    antidetect_id INTEGER,
    last_sync_at TEXT,
    last_launch_at TEXT,
    last_publish_at TEXT,
    notes TEXT,
    daily_upload_limit INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_id, adspower_profile_id)
);

CREATE TABLE IF NOT EXISTS profile_channel_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    adspower_profile_id TEXT NOT NULL,
    youtube_channel_id TEXT,
    youtube_channel_handle TEXT,
    geo TEXT,
    offer_name TEXT,
    operator_label TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS profile_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    adspower_profile_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    payload_json TEXT,
    result_json TEXT,
    error_type TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS profile_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    adspower_profile_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_adb_tenant ON antidetect_browsers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_adb_active ON antidetect_browsers(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_ap_tenant ON adspower_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ap_status ON adspower_profiles(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_ap_profile_id ON adspower_profiles(tenant_id, adspower_profile_id);
CREATE INDEX IF NOT EXISTS idx_pcl_tenant ON profile_channel_links(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pcl_profile ON profile_channel_links(tenant_id, adspower_profile_id);
CREATE INDEX IF NOT EXISTS idx_pj_tenant ON profile_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pj_status ON profile_jobs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_pj_profile ON profile_jobs(tenant_id, adspower_profile_id);
CREATE INDEX IF NOT EXISTS idx_pj_type ON profile_jobs(tenant_id, job_type);
CREATE INDEX IF NOT EXISTS idx_pj_scheduled ON profile_jobs(tenant_id, scheduled_at) WHERE scheduled_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pe_tenant ON profile_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pe_profile ON profile_events(tenant_id, adspower_profile_id);
"""


_CAMPAIGNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    niche TEXT NOT NULL DEFAULT '',
    profile_ids TEXT NOT NULL DEFAULT '[]',
    preset TEXT NOT NULL DEFAULT '',
    template TEXT NOT NULL DEFAULT '',
    effects_json TEXT NOT NULL DEFAULT '[]',
    proxy_group TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_campaigns_tenant ON campaigns(tenant_id);
"""


async def _migrate_legacy_schema(db: aiosqlite.Connection) -> None:
    """
    Старые БД без tenant_id: перенос в модель (tenant_id, resource) + составные UNIQUE.
    """
    cur = await db.execute("PRAGMA table_info(profiles)")
    cols = {row[1] for row in await cur.fetchall()}
    if "tenant_id" in cols:
        return

    await db.executescript(
        """
        CREATE TABLE profiles_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            adspower_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle',
            UNIQUE(tenant_id, adspower_id)
        );
        INSERT INTO profiles_new (id, tenant_id, adspower_id, name, status)
        SELECT id, 'default', adspower_id, name, status FROM profiles;
        DROP TABLE profiles;
        ALTER TABLE profiles_new RENAME TO profiles;
        """
    )

    cur_t = await db.execute("PRAGMA table_info(tasks)")
    tcols = {row[1] for row in await cur_t.fetchall()}
    if "tenant_id" not in tcols:
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
        )
    if "render_only" not in tcols:
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN render_only INTEGER NOT NULL DEFAULT 0"
        )

    await db.executescript(
        """
        CREATE TABLE analytics_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            video_url TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0,
            likes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'shadowban', 'banned')),
            checked_at TEXT,
            published_at TEXT,
            UNIQUE(tenant_id, video_url)
        );
        INSERT INTO analytics_new (id, tenant_id, video_url, views, likes, status, checked_at, published_at)
        SELECT id, 'default', video_url, views, likes, status, checked_at, published_at FROM analytics;
        DROP TABLE analytics;
        ALTER TABLE analytics_new RENAME TO analytics;
        """
    )

    await db.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_profiles_tenant ON profiles(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_profiles_adspower ON profiles(tenant_id, adspower_id);
        CREATE INDEX IF NOT EXISTS idx_analytics_tenant_url ON analytics(tenant_id, video_url);
        CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant_id);
        """
    )


_CAMPAIGN_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    campaign_id INTEGER,
    preset TEXT NOT NULL DEFAULT 'full',
    profile_ids TEXT NOT NULL DEFAULT '[]',
    video_path TEXT,
    niche TEXT NOT NULL DEFAULT '',
    warmup_intensity TEXT NOT NULL DEFAULT 'medium',
    concurrency INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'done', 'cancelled', 'error')),
    results_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_campaign_runs_tenant ON campaign_runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_campaign_runs_status ON campaign_runs(tenant_id, status);
"""


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
    )
    row = await cur.fetchone()
    if not row:
        await db.executescript(_FRESH_SCHEMA)
        await db.executescript(_PROFILE_REGISTRY_SCHEMA)
        await db.executescript(_CAMPAIGNS_SCHEMA)
        await db.executescript(_CAMPAIGN_RUNS_SCHEMA)
        await db.commit()
        return
    await _migrate_legacy_schema(db)
    # Один запрос PRAGMA — проверяем все нужные колонки сразу.
    cur_t = await db.execute("PRAGMA table_info(tasks)")
    tcols = {r[1] for r in await cur_t.fetchall()}
    altered = False
    if "render_only" not in tcols:
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN render_only INTEGER NOT NULL DEFAULT 0"
        )
        altered = True
    if "subtitle" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN subtitle TEXT")
        altered = True
    if "template" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN template TEXT")
        altered = True
    if "created_at" not in tcols:
        # SQLite ALTER TABLE не поддерживает функции в DEFAULT — используем пустую строку,
        # новые задачи будут получать datetime('now') через явный INSERT.
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"
        )
        altered = True
    if "updated_at" not in tcols:
        await db.execute(
            "ALTER TABLE tasks ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
        altered = True
    if "effects_json" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN effects_json TEXT")
        altered = True
    if "warning_message" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN warning_message TEXT")
        altered = True
    if "scheduled_at" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN scheduled_at TEXT")
        altered = True
    if "priority" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        altered = True
    if "retry_count" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        altered = True
    if "error_type" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN error_type TEXT")
        altered = True
    if "device_model" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN device_model TEXT")
        altered = True
    if "geo_profile" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN geo_profile TEXT")
        altered = True
    if altered:
        await db.commit()
    # Индексы (partial/compound; безопасно повторно выполнять).
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_scheduled"
        " ON tasks(tenant_id, scheduled_at) WHERE scheduled_at IS NOT NULL"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_priority"
        " ON tasks(tenant_id, status, priority DESC, id ASC)"
    )
    await db.commit()
    # Реестр профилей AdsPower — новые таблицы (безопасно для существующих БД).
    await db.executescript(_PROFILE_REGISTRY_SCHEMA)
    # Миграции adspower_profiles (существующие БД без новых колонок).
    cur_ap = await db.execute("PRAGMA table_info(adspower_profiles)")
    apcols = {r[1] for r in await cur_ap.fetchall()}
    ap_altered = False
    if "daily_upload_limit" not in apcols:
        await db.execute(
            "ALTER TABLE adspower_profiles"
            " ADD COLUMN daily_upload_limit INTEGER NOT NULL DEFAULT 3"
        )
        ap_altered = True
    if "antidetect_id" not in apcols:
        await db.execute("ALTER TABLE adspower_profiles ADD COLUMN antidetect_id INTEGER")
        ap_altered = True
    if ap_altered:
        await db.commit()
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ap_antidetect ON adspower_profiles(antidetect_id)"
    )
    await db.executescript(_CAMPAIGNS_SCHEMA)
    await db.executescript(_CAMPAIGN_RUNS_SCHEMA)
    await db.commit()


async def init_db(db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _error("Не удалось создать папку для базы данных. Проверьте права доступа.")

    try:
        async with aiosqlite.connect(path) as db:
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA synchronous = NORMAL;")
            await db.execute("PRAGMA cache_size = -32000;")
            await db.execute("PRAGMA foreign_keys = ON;")
            await _ensure_schema(db)
            await db.commit()
    except Exception as exc:
        logger.exception("init_db failed: %s", exc)
        return _error("Не удалось инициализировать базу данных. Перезапустите приложение.")

    return _ok({"db_path": str(path.resolve())})


def get_default_db_path() -> Path:
    return _DEFAULT_DB_PATH


# --- Профили -----------------------------------------------------------------


async def upsert_profile(
    adspower_id: str,
    name: str = "",
    status: str = "idle",
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                INSERT INTO profiles (tenant_id, adspower_id, name, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, adspower_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status;
                """,
                (tid, adspower_id.strip(), name.strip(), status),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT id FROM profiles WHERE tenant_id = ? AND adspower_id = ?",
                (tid, adspower_id.strip()),
            )
            row = await cur.fetchone()
            pid = row[0] if row else None
    except Exception as exc:
        logger.exception("upsert_profile: %s", exc)
        return _error("Не удалось сохранить профиль.")

    return _ok({"id": pid})


async def list_profiles(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, adspower_id, name, status
                FROM profiles WHERE tenant_id = ? ORDER BY id
                """,
                (tid,),
            )
            rows = await cur.fetchall()
            profiles = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_profiles: %s", exc)
        return _error("Не удалось загрузить список профилей.")

    return _ok({"profiles": profiles})


async def update_profile_status(
    adspower_id: str,
    status: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "UPDATE profiles SET status = ? WHERE tenant_id = ? AND adspower_id = ?",
                (status, tid, adspower_id.strip()),
            )
            await db.commit()
            if cur.rowcount == 0:
                return _error("Профиль не найден в базе.")
    except Exception as exc:
        logger.exception("update_profile_status: %s", exc)
        return _error("Не удалось обновить статус профиля.")

    return _ok()


# --- Задачи ------------------------------------------------------------------


async def create_task(
    original_video: str,
    target_profile: str,
    unique_video: str | None = None,
    render_only: bool = False,
    subtitle: str | None = None,
    template: str | None = None,
    priority: int = 0,
    device_model: str | None = None,
    geo_profile: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    sub: str | None = None
    if subtitle is not None:
        s = str(subtitle).strip()
        sub = s[:5000] if s else None
    tpl: str | None = None
    if template is not None:
        t = str(template).strip()
        tpl = _normalize_template(t) if t else None
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                INSERT INTO tasks
                    (tenant_id, original_video, unique_video, target_profile, status,
                     render_only, subtitle, template, priority, device_model, geo_profile, scheduled_at,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (tid, original_video, unique_video, target_profile, 1 if render_only else 0,
                 sub, tpl, int(priority), device_model or None, geo_profile or None, None),
            )
            await db.commit()
            task_id = cur.lastrowid
    except Exception as exc:
        logger.exception("create_task: %s", exc)
        return _error("Не удалось создать задачу.")

    return _ok({"id": task_id, "render_only": render_only})


async def create_tasks_batch(
    rows: list[dict[str, Any]],
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Массовое создание задач в одной транзакции (быстрее чем N отдельных INSERT).

    Каждый элемент rows должен содержать:
      original_video, target_profile, render_only (bool), subtitle (str|None), template (str|None).
    """
    if not rows:
        return _ok({"ids": [], "created": 0})
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    params: list[tuple] = []
    for r in rows:
        sub_raw = r.get("subtitle")
        sub = (str(sub_raw).strip()[:5000] if sub_raw else None) or None
        tpl_raw = r.get("template")
        tpl_str = str(tpl_raw).strip() if tpl_raw else ""
        tpl = _normalize_template(tpl_str) if tpl_str else None
        efx_raw = r.get("effects_json")
        efx = str(efx_raw).strip() if efx_raw else None
        params.append((
            tid,
            str(r["original_video"]),
            str(r.get("target_profile") or ""),
            1 if r.get("render_only") else 0,
            sub,
            tpl,
            efx,
            int(r.get("priority") or 0),
            r.get("device_model") or None,
            r.get("geo_profile") or None,
            None,
        ))
    try:
        async with aiosqlite.connect(path) as db:
            await db.executemany(
                """
                INSERT INTO tasks
                    (tenant_id, original_video, target_profile, status,
                     render_only, subtitle, template, effects_json,
                     priority, device_model, geo_profile, scheduled_at,
                     created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                params,
            )
            await db.commit()
            # Стабильное получение ID: берём lastrowid первой строки через rowcount.
            cur = await db.execute("SELECT last_insert_rowid()")
            last_id = (await cur.fetchone())[0]
            ids = list(range(last_id - len(rows) + 1, last_id + 1))
    except Exception as exc:
        logger.exception("create_tasks_batch: %s", exc)
        return _error("Не удалось создать пакет задач.")
    return _ok({"ids": ids, "created": len(ids)})


async def get_pending_tasks(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, original_video, unique_video, target_profile,
                       status, error_message, error_type, warning_message, render_only,
                       subtitle, template, effects_json, scheduled_at,
                       priority, retry_count, device_model, geo_profile,
                       created_at, updated_at
                FROM tasks
                WHERE tenant_id = ? AND status = 'pending'
                  AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
                ORDER BY priority DESC, id ASC
                """,
                (tid,),
            )
            rows = await cur.fetchall()
            tasks = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("get_pending_tasks: %s", exc)
        return _error("Не удалось получить очередь задач.")

    return _ok({"tasks": tasks})


async def get_task_by_id(
    task_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, original_video, unique_video, target_profile,
                       status, error_message, error_type, warning_message, render_only,
                       subtitle, template, effects_json, scheduled_at,
                       priority, retry_count, device_model, geo_profile,
                       created_at, updated_at
                FROM tasks WHERE tenant_id = ? AND id = ?
                """,
                (tid, task_id),
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.exception("get_task_by_id: %s", exc)
        return _error("Не удалось загрузить задачу.")

    if not row:
        return _error("Задача не найдена.")
    return _ok({"task": dict(row)})


async def update_task_status(
    task_id: int,
    status: str,
    error_message: str | None = None,
    unique_video: str | None = None,
    error_type: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    allowed = {"pending", "rendering", "transcribing", "uploading", "success", "error"}
    if status not in allowed:
        return _error("Некорректный статус задачи.")

    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            # Собираем SET-фрагмент динамически, чтобы не плодить 8 веток if/elif.
            sets = ["status = ?", "updated_at = datetime('now')"]
            vals: list[Any] = [status]
            if unique_video is not None:
                sets.append("unique_video = ?")
                vals.append(unique_video)
            if error_message is not None:
                sets.append("error_message = ?")
                vals.append(error_message)
            if error_type is not None:
                sets.append("error_type = ?")
                vals.append(error_type)
            vals.extend([tid, task_id])
            await db.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?",
                vals,
            )
            await db.commit()
            cur = await db.execute("SELECT changes()")
            changes_row = await cur.fetchone()
            if not changes_row or changes_row[0] == 0:
                return _error("Задача не найдена.")
    except Exception as exc:
        logger.exception("update_task_status: %s", exc)
        return _error("Не удалось обновить статус задачи.")

    return _ok()


async def schedule_task(
    task_id: int,
    scheduled_at: str | None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Установить или снять расписание для задачи в статусе pending.
    scheduled_at — ISO 8601 строка ('2026-04-10T14:00:00') или None для немедленного запуска.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT status FROM tasks WHERE tenant_id = ? AND id = ?",
                (tid, task_id),
            )
            row = await cur.fetchone()
            if not row:
                return _error("Задача не найдена.")
            if row[0] not in ("pending",):
                return _error(
                    f"Планирование доступно только для задач в статусе pending (сейчас: {row[0]})."
                )
            await db.execute(
                "UPDATE tasks SET scheduled_at = ?, updated_at = datetime('now') WHERE tenant_id = ? AND id = ?",
                (scheduled_at, tid, task_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("schedule_task: %s", exc)
        return _error("Не удалось обновить расписание задачи.")
    return _ok({"id": task_id, "scheduled_at": scheduled_at})


async def get_due_scheduled_tasks(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Вернуть pending-задачи с наступившим scheduled_at (для поллера планировщика)."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, scheduled_at, retry_count FROM tasks
                WHERE tenant_id = ? AND status = 'pending'
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= datetime('now')
                ORDER BY scheduled_at
                """,
                (tid,),
            )
            rows = await cur.fetchall()
            tasks = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("get_due_scheduled_tasks: %s", exc)
        return _error("Не удалось получить запланированные задачи.")
    return _ok({"tasks": tasks})


async def update_task_warning(
    task_id: int,
    warning_message: str | None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Записать предупреждение perceptual hash в задачу (не меняет статус)."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "UPDATE tasks SET warning_message = ?, updated_at = datetime('now') WHERE tenant_id = ? AND id = ?",
                (warning_message, tid, task_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("update_task_warning: %s", exc)
        return _error("Не удалось обновить предупреждение задачи.")
    return _ok()


async def list_tasks(
    limit: int = 100,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, original_video, unique_video, target_profile,
                       status, error_message, error_type, warning_message, render_only,
                       subtitle, template, effects_json, scheduled_at,
                       priority, retry_count, device_model, geo_profile,
                       created_at, updated_at
                FROM tasks WHERE tenant_id = ? ORDER BY id DESC LIMIT ?
                """,
                (tid, max(1, min(limit, 500))),
            )
            rows = await cur.fetchall()
            tasks = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_tasks: %s", exc)
        return _error("Не удалось загрузить список задач.")

    return _ok({"tasks": tasks})


async def reschedule_task_for_retry(
    task_id: int,
    delay_seconds: int = 60,
    error_message: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Автоматический повтор: сбрасывает задачу в pending, инкрементирует retry_count
    и устанавливает scheduled_at на now+delay. Существующий TaskScheduler подберёт её
    когда наступит время — без отдельной инфраструктуры.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                UPDATE tasks
                SET status = 'pending',
                    error_message = ?,
                    error_type = NULL,
                    retry_count = retry_count + 1,
                    scheduled_at = datetime('now', '+' || ? || ' seconds'),
                    updated_at = datetime('now')
                WHERE tenant_id = ? AND id = ?
                """,
                (error_message, str(int(delay_seconds)), tid, task_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("reschedule_task_for_retry %s: %s", task_id, exc)
        return _error("Не удалось запланировать повтор задачи.")
    return _ok({"id": task_id, "retry_in_seconds": delay_seconds})


async def retry_task(
    task_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Сброс задачи в статус pending для повторной обработки.
    Разрешено только для задач в статусе error.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT status FROM tasks WHERE tenant_id = ? AND id = ?",
                (tid, task_id),
            )
            row = await cur.fetchone()
            if not row:
                return _error("Задача не найдена.")
            if row[0] != "error":
                return _error(f"Повтор возможен только для задач в статусе error (сейчас: {row[0]}).")
            await db.execute(
                """
                UPDATE tasks
                SET status = 'pending', error_message = NULL, error_type = NULL,
                    retry_count = retry_count + 1,
                    updated_at = datetime('now')
                WHERE tenant_id = ? AND id = ?
                """,
                (tid, task_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("retry_task %s: %s", task_id, exc)
        return _error("Не удалось сбросить задачу для повтора.")
    return _ok({"id": task_id, "new_status": "pending"})


async def recover_interrupted_tasks(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    После перезапуска сервера в БД могут остаться «сироты» в rendering/uploading.
    Возвращаем их в pending, чтобы очередь могла снова их обработать.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                UPDATE tasks
                SET status = 'pending'
                WHERE tenant_id = ? AND status IN ('rendering', 'transcribing', 'uploading')
                """,
                (tid,),
            )
            await db.commit()
            recovered = int(cur.rowcount or 0)
    except Exception as exc:
        logger.exception("recover_interrupted_tasks: %s", exc)
        return _error("Не удалось восстановить прерванные задачи.")
    return _ok({"recovered": recovered})


# --- Аналитика ---------------------------------------------------------------


async def upsert_analytics(
    video_url: str,
    views: int = 0,
    likes: int = 0,
    status: str = "active",
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if status not in {"active", "shadowban", "banned"}:
        return _error("Некорректный статус аналитики.")

    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                INSERT INTO analytics (tenant_id, video_url, views, likes, status, checked_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(tenant_id, video_url) DO UPDATE SET
                    views = excluded.views,
                    likes = excluded.likes,
                    status = excluded.status,
                    checked_at = datetime('now');
                """,
                (tid, video_url.strip(), views, likes, status),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("upsert_analytics: %s", exc)
        return _error("Не удалось сохранить аналитику.")

    return _ok()


async def add_analytics_row(
    video_url: str,
    views: int = 0,
    likes: int = 0,
    status: str = "active",
    published_at: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if status not in {"active", "shadowban", "banned"}:
        return _error("Некорректный статус аналитики.")

    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT id FROM analytics WHERE tenant_id = ? AND video_url = ?",
                (tid, video_url.strip()),
            )
            row = await cur.fetchone()
            if row:
                await db.execute(
                    """
                    UPDATE analytics
                    SET views = ?, likes = ?, status = ?,
                        checked_at = datetime('now'),
                        published_at = COALESCE(?, published_at)
                    WHERE tenant_id = ? AND video_url = ?
                    """,
                    (views, likes, status, published_at, tid, video_url.strip()),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO analytics (tenant_id, video_url, views, likes, status, checked_at, published_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
                    """,
                    (tid, video_url.strip(), views, likes, status, published_at),
                )
            await db.commit()
    except Exception as exc:
        logger.exception("add_analytics_row: %s", exc)
        return _error("Не удалось записать аналитику.")

    return _ok()


async def get_analytics_by_url(
    video_url: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM analytics WHERE tenant_id = ? AND video_url = ?",
                (tid, video_url.strip()),
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.exception("get_analytics_by_url: %s", exc)
        return _error("Не удалось загрузить аналитику.")

    if not row:
        return _error("Запись не найдена.")
    return _ok({"analytics": dict(row)})


async def list_analytics(
    limit: int = 200,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, video_url, views, likes, status, checked_at, published_at
                FROM analytics WHERE tenant_id = ? ORDER BY id DESC LIMIT ?
                """,
                (tid, max(1, min(limit, 500))),
            )
            rows = await cur.fetchall()
            items = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_analytics: %s", exc)
        return _error("Не удалось загрузить аналитику.")

    return _ok({"analytics": items})


async def set_task_priority(
    task_id: int,
    priority: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Установить приоритет задачи. 1 = высокий, 0 = обычный, -1 = низкий."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "UPDATE tasks SET priority = ?, updated_at = datetime('now')"
                " WHERE tenant_id = ? AND id = ?",
                (int(priority), tid, task_id),
            )
            await db.commit()
            if not cur.rowcount:
                return _error("Задача не найдена.")
    except Exception as exc:
        logger.exception("set_task_priority %s: %s", task_id, exc)
        return _error("Не удалось изменить приоритет задачи.")
    return _ok({"id": task_id, "priority": int(priority)})


async def list_active_analytics(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Вернуть все active-видео для поллера аналитики."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, video_url, views, likes, status, checked_at, published_at
                FROM analytics
                WHERE tenant_id = ? AND status = 'active'
                ORDER BY id
                """,
                (tid,),
            )
            rows = await cur.fetchall()
            items = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_active_analytics: %s", exc)
        return _error("Не удалось загрузить аналитику для поллера.")
    return _ok({"analytics": items})


async def delete_profile(
    adspower_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "DELETE FROM profiles WHERE tenant_id = ? AND adspower_id = ?",
                (tid, adspower_id.strip()),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("delete_profile: %s", exc)
        return _error("Не удалось удалить профиль.")

    return _ok()


# ─── Реестр профилей AdsPower ─────────────────────────────────────────────────

_VALID_PROFILE_STATUSES = frozenset({
    "new", "warmup", "ready", "publishing", "cooldown", "paused", "error", "archived"
})

_VALID_JOB_TYPES = frozenset({"warmup", "publish", "verify", "stats_sync"})

_VALID_JOB_STATUSES = frozenset({
    "pending", "scheduled", "running", "success", "error", "cancelled", "cooldown"
})


async def upsert_adspower_profile(
    adspower_profile_id: str,
    profile_name: str = "",
    group_name: str | None = None,
    proxy_name: str | None = None,
    platform: str = "youtube",
    geo: str | None = None,
    language: str | None = None,
    tags_json: str | None = None,
    antidetect_id: int | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Upsert AdsPower-профиля в локальный реестр.
    При конфликте НЕ сбрасывает status — только обновляет имя/группу/прокси/last_sync_at.
    antidetect_id — привязка к конкретному антидетект-браузеру.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                INSERT INTO adspower_profiles
                    (tenant_id, adspower_profile_id, profile_name, group_name, proxy_name,
                     platform, geo, language, tags_json, antidetect_id,
                     last_sync_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(tenant_id, adspower_profile_id) DO UPDATE SET
                    profile_name  = excluded.profile_name,
                    group_name    = COALESCE(excluded.group_name, group_name),
                    proxy_name    = COALESCE(excluded.proxy_name, proxy_name),
                    antidetect_id = COALESCE(excluded.antidetect_id, antidetect_id),
                    last_sync_at  = datetime('now'),
                    updated_at    = datetime('now');
                """,
                (tid, adspower_profile_id.strip(), profile_name.strip(),
                 group_name, proxy_name, platform, geo, language, tags_json, antidetect_id),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT id FROM adspower_profiles WHERE tenant_id = ? AND adspower_profile_id = ?",
                (tid, adspower_profile_id.strip()),
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.exception("upsert_adspower_profile: %s", exc)
        return _error("Не удалось сохранить профиль AdsPower.")
    return _ok({"id": row[0] if row else None})


async def list_adspower_profiles(
    tenant_id: str | None = None,
    status_filter: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            if status_filter and status_filter in _VALID_PROFILE_STATUSES:
                cur = await db.execute(
                    """
                    SELECT id, tenant_id, adspower_profile_id, profile_name, group_name,
                           proxy_name, platform, geo, language, tags_json, status,
                           last_sync_at, last_launch_at, last_publish_at, notes,
                           created_at, updated_at
                    FROM adspower_profiles WHERE tenant_id = ? AND status = ?
                    ORDER BY id DESC
                    """,
                    (tid, status_filter),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT id, tenant_id, adspower_profile_id, profile_name, group_name,
                           proxy_name, platform, geo, language, tags_json, status,
                           last_sync_at, last_launch_at, last_publish_at, notes,
                           created_at, updated_at
                    FROM adspower_profiles WHERE tenant_id = ?
                    ORDER BY id DESC
                    """,
                    (tid,),
                )
            rows = await cur.fetchall()
            profiles = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_adspower_profiles: %s", exc)
        return _error("Не удалось загрузить список профилей.")
    return _ok({"profiles": profiles})


async def get_adspower_profile(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, adspower_profile_id, profile_name, group_name,
                       proxy_name, platform, geo, language, tags_json, status,
                       antidetect_id, daily_upload_limit,
                       last_sync_at, last_launch_at, last_publish_at, notes,
                       created_at, updated_at
                FROM adspower_profiles WHERE tenant_id = ? AND adspower_profile_id = ?
                """,
                (tid, adspower_profile_id.strip()),
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.exception("get_adspower_profile: %s", exc)
        return _error("Не удалось загрузить профиль.")
    if not row:
        return _error("Профиль не найден.")
    return _ok({"profile": dict(row)})


async def update_adspower_profile_status(
    adspower_profile_id: str,
    new_status: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if new_status not in _VALID_PROFILE_STATUSES:
        return _error(f"Недопустимый статус профиля: {new_status!r}.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "UPDATE adspower_profiles SET status = ?, updated_at = datetime('now')"
                " WHERE tenant_id = ? AND adspower_profile_id = ?",
                (new_status, tid, adspower_profile_id.strip()),
            )
            await db.commit()
            if not cur.rowcount:
                return _error("Профиль не найден.")
    except Exception as exc:
        logger.exception("update_adspower_profile_status: %s", exc)
        return _error("Не удалось обновить статус профиля.")
    return _ok()


async def patch_adspower_profile(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Частичное обновление полей: geo, notes, language, tags_json, status, platform."""
    _PATCHABLE = {
        "profile_name", "geo", "language", "tags_json", "notes",
        "platform", "status", "last_launch_at", "last_publish_at",
    }
    safe = {k: v for k, v in fields.items() if k in _PATCHABLE}
    if not safe:
        return _error("Нет допустимых полей для обновления.")
    if "status" in safe and safe["status"] not in _VALID_PROFILE_STATUSES:
        return _error(f"Недопустимый статус: {safe['status']!r}.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            sets = [f"{k} = ?" for k in safe] + ["updated_at = datetime('now')"]
            vals: list[Any] = list(safe.values()) + [tid, adspower_profile_id.strip()]
            cur = await db.execute(
                f"UPDATE adspower_profiles SET {', '.join(sets)}"
                f" WHERE tenant_id = ? AND adspower_profile_id = ?",
                vals,
            )
            await db.commit()
            if not cur.rowcount:
                return _error("Профиль не найден.")
    except Exception as exc:
        logger.exception("patch_adspower_profile: %s", exc)
        return _error("Не удалось обновить профиль.")
    return _ok()


async def update_adspower_profile_launch(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Обновить last_launch_at после запуска браузера профиля."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "UPDATE adspower_profiles"
                " SET last_launch_at = datetime('now'), updated_at = datetime('now')"
                " WHERE tenant_id = ? AND adspower_profile_id = ?",
                (tid, adspower_profile_id.strip()),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("update_adspower_profile_launch: %s", exc)
        return _error("Не удалось обновить last_launch_at.")
    return _ok()


async def update_adspower_profile_publish(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Обновить last_publish_at после успешной публикации."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "UPDATE adspower_profiles"
                " SET last_publish_at = datetime('now'), updated_at = datetime('now')"
                " WHERE tenant_id = ? AND adspower_profile_id = ?",
                (tid, adspower_profile_id.strip()),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("update_adspower_profile_publish: %s", exc)
        return _error("Не удалось обновить last_publish_at.")
    return _ok()


# ─── Profile Channel Links ─────────────────────────────────────────────────────


async def create_profile_channel_link(
    adspower_profile_id: str,
    youtube_channel_id: str | None = None,
    youtube_channel_handle: str | None = None,
    geo: str | None = None,
    offer_name: str | None = None,
    operator_label: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                INSERT INTO profile_channel_links
                    (tenant_id, adspower_profile_id, youtube_channel_id,
                     youtube_channel_handle, geo, offer_name, operator_label,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (tid, adspower_profile_id.strip(), youtube_channel_id,
                 youtube_channel_handle, geo, offer_name, operator_label),
            )
            await db.commit()
            link_id = cur.lastrowid
    except Exception as exc:
        logger.exception("create_profile_channel_link: %s", exc)
        return _error("Не удалось создать привязку канала.")
    return _ok({"id": link_id})


async def list_profile_channel_links(
    tenant_id: str | None = None,
    adspower_profile_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            if adspower_profile_id:
                cur = await db.execute(
                    "SELECT * FROM profile_channel_links"
                    " WHERE tenant_id = ? AND adspower_profile_id = ? ORDER BY id DESC",
                    (tid, adspower_profile_id.strip()),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM profile_channel_links WHERE tenant_id = ? ORDER BY id DESC",
                    (tid,),
                )
            rows = await cur.fetchall()
            links = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_profile_channel_links: %s", exc)
        return _error("Не удалось загрузить привязки каналов.")
    return _ok({"links": links})


async def patch_profile_channel_link(
    link_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    _PATCHABLE = {
        "youtube_channel_id", "youtube_channel_handle", "geo",
        "offer_name", "operator_label", "is_active",
    }
    safe = {k: v for k, v in fields.items() if k in _PATCHABLE}
    if not safe:
        return _error("Нет допустимых полей для обновления.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            sets = [f"{k} = ?" for k in safe] + ["updated_at = datetime('now')"]
            vals: list[Any] = list(safe.values()) + [tid, link_id]
            cur = await db.execute(
                f"UPDATE profile_channel_links SET {', '.join(sets)}"
                f" WHERE tenant_id = ? AND id = ?",
                vals,
            )
            await db.commit()
            if not cur.rowcount:
                return _error("Привязка не найдена.")
    except Exception as exc:
        logger.exception("patch_profile_channel_link: %s", exc)
        return _error("Не удалось обновить привязку.")
    return _ok()


# ─── Profile Jobs ──────────────────────────────────────────────────────────────


async def create_profile_job(
    adspower_profile_id: str,
    job_type: str,
    payload_json: str | None = None,
    scheduled_at: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if job_type not in _VALID_JOB_TYPES:
        return _error(f"Недопустимый тип задачи: {job_type!r}.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    initial_status = "scheduled" if scheduled_at else "pending"
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                INSERT INTO profile_jobs
                    (tenant_id, adspower_profile_id, job_type, status,
                     scheduled_at, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (tid, adspower_profile_id.strip(), job_type, initial_status,
                 scheduled_at, payload_json),
            )
            await db.commit()
            job_id = cur.lastrowid
    except Exception as exc:
        logger.exception("create_profile_job: %s", exc)
        return _error("Не удалось создать задачу профиля.")
    return _ok({"id": job_id, "job_status": initial_status})


async def list_profile_jobs(
    tenant_id: str | None = None,
    job_type: str | None = None,
    status: str | None = None,
    adspower_profile_id: str | None = None,
    limit: int = 100,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            wheres = ["tenant_id = ?"]
            params: list[Any] = [tid]
            if job_type and job_type in _VALID_JOB_TYPES:
                wheres.append("job_type = ?")
                params.append(job_type)
            if status and status in _VALID_JOB_STATUSES:
                wheres.append("status = ?")
                params.append(status)
            if adspower_profile_id:
                wheres.append("adspower_profile_id = ?")
                params.append(adspower_profile_id.strip())
            params.append(max(1, min(limit, 500)))
            cur = await db.execute(
                f"SELECT * FROM profile_jobs WHERE {' AND '.join(wheres)}"
                f" ORDER BY id DESC LIMIT ?",
                params,
            )
            rows = await cur.fetchall()
            jobs = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_profile_jobs: %s", exc)
        return _error("Не удалось загрузить задачи профиля.")
    return _ok({"jobs": jobs})


async def get_profile_job(
    job_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM profile_jobs WHERE tenant_id = ? AND id = ?",
                (tid, job_id),
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.exception("get_profile_job: %s", exc)
        return _error("Не удалось загрузить задачу.")
    if not row:
        return _error("Задача не найдена.")
    return _ok({"job": dict(row)})


async def update_profile_job_status(
    job_id: int,
    status: str,
    result_json: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if status not in _VALID_JOB_STATUSES:
        return _error(f"Недопустимый статус задачи: {status!r}.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            sets = ["status = ?", "updated_at = datetime('now')"]
            vals: list[Any] = [status]
            if result_json is not None:
                sets.append("result_json = ?")
                vals.append(result_json)
            if error_type is not None:
                sets.append("error_type = ?")
                vals.append(error_type)
            if error_message is not None:
                sets.append("error_message = ?")
                vals.append(error_message)
            if started_at is not None:
                sets.append("started_at = ?")
                vals.append(started_at)
            if finished_at is not None:
                sets.append("finished_at = ?")
                vals.append(finished_at)
            vals.extend([tid, job_id])
            cur = await db.execute(
                f"UPDATE profile_jobs SET {', '.join(sets)} WHERE tenant_id = ? AND id = ?",
                vals,
            )
            await db.commit()
            if not cur.rowcount:
                return _error("Задача не найдена.")
    except Exception as exc:
        logger.exception("update_profile_job_status: %s", exc)
        return _error("Не удалось обновить статус задачи.")
    return _ok()


async def claim_profile_job_for_run(
    job_id: int,
    tenant_id: str | None = None,
    started_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Атомарно перевести задачу pending/scheduled -> running.
    Возвращает claimed=False, если задачу уже забрал другой воркер.
    """
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                UPDATE profile_jobs
                SET status = 'running',
                    started_at = COALESCE(?, started_at),
                    updated_at = datetime('now')
                WHERE tenant_id = ? AND id = ? AND status IN ('pending', 'scheduled')
                """,
                (started_at, tid, job_id),
            )
            await db.commit()
            claimed = bool(cur.rowcount)
    except Exception as exc:
        logger.exception("claim_profile_job_for_run: %s", exc)
        return _error("Не удалось атомарно захватить задачу профиля.")
    return _ok({"id": job_id, "claimed": claimed})


async def retry_profile_job(
    job_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT status FROM profile_jobs WHERE tenant_id = ? AND id = ?",
                (tid, job_id),
            )
            row = await cur.fetchone()
            if not row:
                return _error("Задача не найдена.")
            if row[0] not in ("error", "cancelled"):
                return _error(
                    f"Повтор возможен только для задач в статусе error/cancelled (сейчас: {row[0]})."
                )
            await db.execute(
                """
                UPDATE profile_jobs
                SET status = 'pending', error_message = NULL, error_type = NULL,
                    started_at = NULL, finished_at = NULL,
                    retry_count = retry_count + 1,
                    updated_at = datetime('now')
                WHERE tenant_id = ? AND id = ?
                """,
                (tid, job_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("retry_profile_job: %s", exc)
        return _error("Не удалось повторить задачу.")
    return _ok({"id": job_id, "new_status": "pending"})


async def cancel_profile_job(
    job_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT status FROM profile_jobs WHERE tenant_id = ? AND id = ?",
                (tid, job_id),
            )
            row = await cur.fetchone()
            if not row:
                return _error("Задача не найдена.")
            if row[0] in ("success", "cancelled"):
                return _error(f"Задача уже в статусе {row[0]}.")
            await db.execute(
                "UPDATE profile_jobs SET status = 'cancelled', updated_at = datetime('now')"
                " WHERE tenant_id = ? AND id = ?",
                (tid, job_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("cancel_profile_job: %s", exc)
        return _error("Не удалось отменить задачу.")
    return _ok({"id": job_id, "new_status": "cancelled"})


# ─── Profile Events ────────────────────────────────────────────────────────────


async def record_profile_event(
    adspower_profile_id: str,
    event_type: str,
    message: str = "",
    payload_json: str | None = None,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                INSERT INTO profile_events
                    (tenant_id, adspower_profile_id, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (tid, adspower_profile_id.strip(), event_type, message or "", payload_json),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("record_profile_event: %s", exc)
        return _error("Не удалось записать событие профиля.")
    return _ok()


async def list_profile_events(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    limit: int = 50,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, adspower_profile_id, event_type, message, payload_json, created_at
                FROM profile_events
                WHERE tenant_id = ? AND adspower_profile_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (tid, adspower_profile_id.strip(), max(1, min(limit, 200))),
            )
            rows = await cur.fetchall()
            events = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_profile_events: %s", exc)
        return _error("Не удалось загрузить события профиля.")
    return _ok({"events": events})


# ─── System / Health ───────────────────────────────────────────────────────────


async def get_adspower_sync_status(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Статистика реестра: количество и дата последнего синка."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT COUNT(*), MAX(last_sync_at) FROM adspower_profiles WHERE tenant_id = ?",
                (tid,),
            )
            row = await cur.fetchone()
            total = int(row[0]) if row else 0
            last_sync = row[1] if row else None
    except Exception as exc:
        logger.exception("get_adspower_sync_status: %s", exc)
        return _error("Не удалось получить статус синхронизации.")
    return _ok({"total_profiles": total, "last_sync_at": last_sync})


async def get_profiles_health(
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Статистика по статусам профилей для dashboard."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM adspower_profiles"
                " WHERE tenant_id = ? GROUP BY status",
                (tid,),
            )
            rows = await cur.fetchall()
            by_status = {r["status"]: r["cnt"] for r in rows}
            total = sum(by_status.values())
    except Exception as exc:
        logger.exception("get_profiles_health: %s", exc)
        return _error("Не удалось получить статистику профилей.")
    return _ok({"total": total, "by_status": by_status})


# ───────────────────────── Campaigns CRUD ────────────────────────────────────

async def list_campaigns(
    tenant_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM campaigns WHERE tenant_id = ? ORDER BY created_at DESC",
                (tid,),
            )
            rows = await cur.fetchall()
            return _ok({"campaigns": [dict(r) for r in rows]})
    except Exception as exc:
        logger.exception("list_campaigns: %s", exc)
        return _error(str(exc))


async def create_campaign(
    tenant_id: str = "default",
    name: str = "",
    niche: str = "",
    profile_ids: list | None = None,
    preset: str = "",
    template: str = "",
    effects: list | None = None,
    proxy_group: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """INSERT INTO campaigns
                   (tenant_id, name, niche, profile_ids, preset, template, effects_json, proxy_group)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, name.strip(), niche.strip(),
                 _json.dumps(profile_ids or []),
                 preset, template,
                 _json.dumps(effects or []),
                 proxy_group),
            )
            await db.commit()
            return _ok({"id": cur.lastrowid, "name": name})
    except Exception as exc:
        logger.exception("create_campaign: %s", exc)
        return _error(str(exc))


async def update_campaign(
    campaign_id: int,
    tenant_id: str = "default",
    patch: dict | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    if not patch:
        return _error("Нет данных для обновления")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    allowed = {"name", "niche", "preset", "template", "proxy_group"}
    sets, vals = [], []
    for key, val in patch.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            vals.append(str(val))
        elif key == "profile_ids":
            sets.append("profile_ids = ?")
            vals.append(_json.dumps(val if isinstance(val, list) else []))
        elif key == "effects":
            sets.append("effects_json = ?")
            vals.append(_json.dumps(val if isinstance(val, list) else []))
    if not sets:
        return _error("Нет допустимых полей для обновления")
    sets.append("updated_at = datetime('now')")
    vals.extend([campaign_id, tid])
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                f"UPDATE campaigns SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?",
                vals,
            )
            await db.commit()
            return _ok({"id": campaign_id, "updated": True})
    except Exception as exc:
        logger.exception("update_campaign: %s", exc)
        return _error(str(exc))


async def delete_campaign(
    campaign_id: int,
    tenant_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "DELETE FROM campaigns WHERE id = ? AND tenant_id = ?",
                (campaign_id, tid),
            )
            await db.commit()
            return _ok({"id": campaign_id, "deleted": True})
    except Exception as exc:
        logger.exception("delete_campaign: %s", exc)
        return _error(str(exc))


async def get_campaign_stats(
    campaign_id: int,
    tenant_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?",
                (campaign_id, tid),
            )
            camp = await cur.fetchone()
            if not camp:
                return _error("Кампания не найдена")
            camp_dict = dict(camp)
            try:
                profile_ids = _json.loads(camp_dict.get("profile_ids") or "[]")
            except Exception:
                profile_ids = []
            total_tasks = 0
            success_tasks = 0
            if profile_ids:
                placeholders = ",".join("?" * len(profile_ids))
                cur2 = await db.execute(
                    f"SELECT status, COUNT(*) as cnt FROM tasks WHERE tenant_id = ? AND target_profile IN ({placeholders}) GROUP BY status",
                    [tid, *profile_ids],
                )
                rows = await cur2.fetchall()
                for r in rows:
                    total_tasks += r["cnt"]
                    if r["status"] == "success":
                        success_tasks += r["cnt"]
            return _ok({
                "campaign": camp_dict,
                "stats": {
                    "total_tasks": total_tasks,
                    "success_tasks": success_tasks,
                    "profile_count": len(profile_ids),
                },
            })
    except Exception as exc:
        logger.exception("get_campaign_stats: %s", exc)
        return _error(str(exc))


# ─── KST Daily Upload Limits ──────────────────────────────────────────────────


async def get_profile_daily_upload_count(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Count successful publish jobs for this profile within the current KST calendar day.

    KST midnight = UTC 15:00 of the previous calendar day, so the boundary is
    computed dynamically via kst_scheduler.kst_day_boundary_utc().
    """
    from .kst_scheduler import kst_day_boundary_utc

    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    day_start, day_end = kst_day_boundary_utc()
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                SELECT COUNT(*) FROM profile_jobs
                WHERE tenant_id = ?
                  AND adspower_profile_id = ?
                  AND job_type = 'publish'
                  AND status = 'success'
                  AND finished_at >= ?
                  AND finished_at <  ?
                """,
                (tid, adspower_profile_id.strip(), day_start, day_end),
            )
            row = await cur.fetchone()
            count = int(row[0]) if row else 0
    except Exception as exc:
        logger.exception("get_profile_daily_upload_count: %s", exc)
        return _error("Не удалось получить счётчик заливок.")
    return _ok({"count": count, "day_start_utc": day_start, "day_end_utc": day_end})


async def get_profile_daily_limit(
    adspower_profile_id: str,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the daily_upload_limit for this profile (default 3 if not set)."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "SELECT daily_upload_limit FROM adspower_profiles"
                " WHERE tenant_id = ? AND adspower_profile_id = ?",
                (tid, adspower_profile_id.strip()),
            )
            row = await cur.fetchone()
            limit = int(row[0]) if row else 3
    except Exception as exc:
        logger.exception("get_profile_daily_limit: %s", exc)
        return _error("Не удалось получить лимит заливок.")
    return _ok({"daily_upload_limit": limit})


async def set_profile_daily_limit(
    adspower_profile_id: str,
    daily_limit: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Set the daily upload limit for a profile. Valid range: 1–20."""
    if not (1 <= daily_limit <= 20):
        return _error("Лимит должен быть от 1 до 20.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                "UPDATE adspower_profiles"
                " SET daily_upload_limit = ?, updated_at = datetime('now')"
                " WHERE tenant_id = ? AND adspower_profile_id = ?",
                (daily_limit, tid, adspower_profile_id.strip()),
            )
            await db.commit()
            if cur.rowcount == 0:
                return _error("Профиль не найден в реестре AdsPower.")
    except Exception as exc:
        logger.exception("set_profile_daily_limit: %s", exc)
        return _error("Не удалось установить лимит.")
    return _ok({"adspower_profile_id": adspower_profile_id, "daily_upload_limit": daily_limit})


# ── Antidetect Browser CRUD ───────────────────────────────────────────────────

async def upsert_antidetect_browser(
    name: str,
    browser_type: str,
    api_url: str,
    api_key: str = "",
    use_auth: bool = False,
    is_active: bool = True,
    notes: str = "",
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Создать или обновить запись антидетект-браузера."""
    if not name or not name.strip():
        return _error("Имя антидетекта не может быть пустым.")
    if not api_url or not api_url.strip():
        return _error("URL API не может быть пустым.")
    supported = ("adspower", "dolphin", "octo", "multilogin", "custom")
    if browser_type not in supported:
        return _error(f"Неподдерживаемый тип: {browser_type}. Допустимые: {', '.join(supported)}.")
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """
                INSERT INTO antidetect_browsers
                    (tenant_id, name, browser_type, api_url, api_key,
                     use_auth, is_active, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(tenant_id, name) DO UPDATE SET
                    browser_type = excluded.browser_type,
                    api_url      = excluded.api_url,
                    api_key      = excluded.api_key,
                    use_auth     = excluded.use_auth,
                    is_active    = excluded.is_active,
                    notes        = excluded.notes,
                    updated_at   = datetime('now')
                """,
                (
                    tid, name.strip(), browser_type,
                    api_url.strip().rstrip("/"),
                    api_key.strip(), int(use_auth), int(is_active),
                    notes.strip(),
                ),
            )
            await db.commit()
            aid = cur.lastrowid
            # При UPDATE lastrowid не обновляется — подгружаем id
            if not aid:
                row = await (await db.execute(
                    "SELECT id FROM antidetect_browsers WHERE tenant_id=? AND name=?",
                    (tid, name.strip()),
                )).fetchone()
                aid = row[0] if row else None
    except Exception as exc:
        logger.exception("upsert_antidetect_browser: %s", exc)
        return _error("Не удалось сохранить антидетект-браузер.")
    return _ok({"id": aid, "name": name.strip(), "browser_type": browser_type})


async def list_antidetect_browsers(
    tenant_id: str | None = None,
    active_only: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Список всех антидетект-браузеров тенанта."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE tenant_id = ?"
            params: tuple = (tid,)
            if active_only:
                where += " AND is_active = 1"
            cur = await db.execute(
                f"SELECT * FROM antidetect_browsers {where} ORDER BY id",
                params,
            )
            rows = await cur.fetchall()
            browsers = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("list_antidetect_browsers: %s", exc)
        return _error("Не удалось получить список антидетектов.")
    return _ok({"browsers": browsers, "count": len(browsers)})


async def get_antidetect_browser(
    browser_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Получить антидетект-браузер по id."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM antidetect_browsers WHERE id = ? AND tenant_id = ?",
                (browser_id, tid),
            )
            row = await cur.fetchone()
            if not row:
                return _error(f"Антидетект id={browser_id} не найден.")
    except Exception as exc:
        logger.exception("get_antidetect_browser: %s", exc)
        return _error("Не удалось получить антидетект-браузер.")
    return _ok({"browser": dict(row)})


async def delete_antidetect_browser(
    browser_id: int,
    tenant_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Удалить антидетект-браузер. Профили отвязываются (antidetect_id → NULL)."""
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "UPDATE adspower_profiles SET antidetect_id = NULL, updated_at = datetime('now')"
                " WHERE antidetect_id = ? AND tenant_id = ?",
                (browser_id, tid),
            )
            cur = await db.execute(
                "DELETE FROM antidetect_browsers WHERE id = ? AND tenant_id = ?",
                (browser_id, tid),
            )
            await db.commit()
            if cur.rowcount == 0:
                return _error(f"Антидетект id={browser_id} не найден.")
    except Exception as exc:
        logger.exception("delete_antidetect_browser: %s", exc)
        return _error("Не удалось удалить антидетект-браузер.")
    return _ok({"deleted_id": browser_id})


async def touch_antidetect_browser(
    browser_id: int,
    profiles_count: int = 0,
    db_path: str | Path | None = None,
) -> None:
    """Обновить last_synced_at и profiles_count после синхронизации."""
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                """
                UPDATE antidetect_browsers
                SET last_synced_at = datetime('now'),
                    profiles_count = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (profiles_count, browser_id),
            )
            await db.commit()
    except Exception as exc:
        logger.exception("touch_antidetect_browser: %s", exc)


# ── Campaign Runs ─────────────────────────────────────────────────────────────

async def create_campaign_run(
    tenant_id: str = "default",
    preset: str = "full",
    profile_ids: list | None = None,
    video_path: str | None = None,
    niche: str = "",
    warmup_intensity: str = "medium",
    concurrency: int = 3,
    campaign_id: int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            cur = await db.execute(
                """INSERT INTO campaign_runs
                   (tenant_id, campaign_id, preset, profile_ids, video_path,
                    niche, warmup_intensity, concurrency, status, results_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', '{}')""",
                (tid, campaign_id, preset,
                 _json.dumps(profile_ids or []),
                 video_path, niche, warmup_intensity, concurrency),
            )
            await db.commit()
            return _ok({"id": cur.lastrowid})
    except Exception as exc:
        logger.exception("create_campaign_run: %s", exc)
        return _error(str(exc))


async def update_campaign_run(
    run_id: int,
    tenant_id: str = "default",
    status: str | None = None,
    results: dict | None = None,
    error_message: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    sets: list[str] = []
    vals: list = []
    if status is not None:
        sets.append("status = ?")
        vals.append(status)
        if status != "running":
            sets.append("finished_at = datetime('now')")
    if results is not None:
        sets.append("results_json = ?")
        vals.append(_json.dumps(results))
    if error_message is not None:
        sets.append("error_message = ?")
        vals.append(error_message)
    if not sets:
        return _error("Нет данных для обновления")
    vals.extend([run_id, _tid(tenant_id)])
    try:
        async with aiosqlite.connect(path) as db:
            await db.execute(
                f"UPDATE campaign_runs SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?",
                vals,
            )
            await db.commit()
            return _ok({"id": run_id})
    except Exception as exc:
        logger.exception("update_campaign_run %s: %s", run_id, exc)
        return _error(str(exc))


async def get_campaign_run(
    run_id: int,
    tenant_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM campaign_runs WHERE id = ? AND tenant_id = ?",
                (run_id, tid),
            )
            row = await cur.fetchone()
            if not row:
                return _error(f"Campaign run id={run_id} не найден")
            d = dict(row)
            try:
                d["results"] = _json.loads(d.pop("results_json", "{}") or "{}")
                d["profile_ids"] = _json.loads(d.get("profile_ids", "[]") or "[]")
            except Exception:
                pass
            return _ok({"run": d})
    except Exception as exc:
        logger.exception("get_campaign_run %s: %s", run_id, exc)
        return _error(str(exc))


async def list_campaign_runs(
    tenant_id: str = "default",
    limit: int = 50,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import json as _json
    tid = _tid(tenant_id)
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM campaign_runs WHERE tenant_id = ? ORDER BY started_at DESC LIMIT ?",
                (tid, limit),
            )
            rows = await cur.fetchall()
            runs = []
            for row in rows:
                d = dict(row)
                try:
                    d["results"] = _json.loads(d.pop("results_json", "{}") or "{}")
                    d["profile_ids"] = _json.loads(d.get("profile_ids", "[]") or "[]")
                except Exception:
                    pass
                runs.append(d)
            return _ok({"runs": runs})
    except Exception as exc:
        logger.exception("list_campaign_runs: %s", exc)
        return _error(str(exc))
