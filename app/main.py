from __future__ import annotations

import base64
import csv
import datetime as dt
import functools
from email.message import EmailMessage
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import signal
import shutil
import stat
import smtplib
import sqlite3
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
    url_for,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - dependency should be installed in container
    Fernet = None
    InvalidToken = Exception

from app import APP_NAME, APP_VERSION

APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))
APP_LOG_DIR = Path(os.environ.get("APP_LOG_DIR", "/app/logs"))
APP_KEYRING_DIR = Path(os.environ.get("APP_KEYRING_DIR", "/app/keyrings"))
APP_BACKUP_DIR = Path(os.environ.get("APP_BACKUP_DIR", "/app/backups"))
IMPORT_SCRIPT_DIR = Path(os.environ.get("IMPORT_SCRIPT_DIR", "/import-scripts"))
USER_SCRIPT_DIR = Path(os.environ.get("USER_SCRIPT_DIR", "/user-scripts"))
MIRROR_BASE = Path(os.environ.get("MIRROR_BASE", "/mirror"))
IMPORT_HOST_MIRROR_PATHS = [
    p.strip() for p in os.environ.get("IMPORT_HOST_MIRROR_PATHS", "/srv/mirror,/mnt/linux-mirror").split(",") if p.strip()
]
DB_PATH = APP_DATA_DIR / "debmirror-manager.sqlite3"
WEBUI_ERROR_LOG = APP_LOG_DIR / "webui-error.log"
SETTINGS_PATH = APP_DATA_DIR / "settings.json"
SCHEDULER_SCAN_SECONDS = int(os.environ.get("SCHEDULER_SCAN_SECONDS", "60"))
JOB_STOP_GRACE_SECONDS = int(os.environ.get("JOB_STOP_GRACE_SECONDS", "20"))
DEFAULT_MAX_PARALLEL_JOBS = int(os.environ.get("MAX_PARALLEL_JOBS", "1"))
DEFAULT_JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", "31"))
DEFAULT_JOB_LIST_LIMIT = int(os.environ.get("JOB_LIST_LIMIT", "100"))
DEFAULT_DASHBOARD_RECENT_JOBS_LIMIT = int(os.environ.get("DASHBOARD_RECENT_JOBS_LIMIT", "10"))
DEFAULT_DASHBOARD_EVENTS_LIMIT = int(os.environ.get("DASHBOARD_EVENTS_LIMIT", "10"))
DEFAULT_SIZE_CACHE_TTL_SECONDS = int(os.environ.get("SIZE_CACHE_TTL_SECONDS", "21600"))
DEFAULT_SIZE_CALC_TIMEOUT_SECONDS = int(os.environ.get("SIZE_CALC_TIMEOUT_SECONDS", "1800"))
DEFAULT_SIZE_CALC_MAX_PARALLEL = int(os.environ.get("SIZE_CALC_MAX_PARALLEL", "2"))
DEFAULT_AUTO_SIZE_RECALC_ENABLED = int(os.environ.get("AUTO_SIZE_RECALC_ENABLED", "1"))
DEFAULT_AUTO_SIZE_IDLE_MINUTES = int(os.environ.get("AUTO_SIZE_IDLE_MINUTES", "120"))
DEFAULT_STORAGE_GUARD_ENABLED = int(os.environ.get("STORAGE_GUARD_ENABLED", "1"))
DEFAULT_STORAGE_GUARD_THRESHOLD_PERCENT = int(os.environ.get("STORAGE_GUARD_THRESHOLD_PERCENT", "95"))
DEFAULT_APP_TIMEZONE = os.environ.get("APP_TIMEZONE", os.environ.get("TZ", "Europe/Berlin")).strip() or "Europe/Berlin"

# Lokale Zeit für Logeinträge und WebUI-Ausgaben. Falls die Zone ungültig ist,
# bleibt die Python-Standardzeit aktiv, aber die Anwendung bricht nicht ab.
try:
    os.environ.setdefault("TZ", DEFAULT_APP_TIMEZONE)
    if hasattr(time, "tzset"):
        time.tzset()
except Exception:
    pass

APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
APP_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
APP_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
USER_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
MIRROR_BASE.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_NAME"] = "debmirror_manager_session"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

RUNNING_PROCESSES: Dict[int, subprocess.Popen] = {}
RUNNING_PROCESSES_LOCK = threading.Lock()
SCHEDULER_LOCK = threading.Lock()
JOB_WORKER_STARTED = False
JOB_WORKER_LOCK = threading.Lock()
SIZE_CALC_RUNNING: set[str] = set()
SIZE_CALC_LOCK = threading.Lock()


def _normalized_size_path(path_value: str) -> str:
    return str(Path((path_value or "").strip())) if (path_value or "").strip() else ""


def is_scheduled_job_source(source: str) -> bool:
    value = (source or "").strip()
    return value.startswith("schedule:") or value == "legacy-scheduler"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    # SQLite wird von WebUI, Scheduler und laufenden Job-Threads parallel genutzt.
    # Ein großzügiger Busy-Timeout verhindert "database is locked" bei kurzen
    # Schreibkollisionen, ohne die Anwendung unnötig komplex zu machen.
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                method TEXT NOT NULL DEFAULT 'rsync',
                host TEXT NOT NULL,
                root_path TEXT NOT NULL DEFAULT 'debian',
                target_path TEXT NOT NULL,
                dists TEXT NOT NULL,
                sections TEXT NOT NULL,
                archs TEXT NOT NULL,
                source_mode TEXT NOT NULL DEFAULT 'nosource',
                keyring TEXT DEFAULT '',
                postcleanup INTEGER NOT NULL DEFAULT 1,
                diff_mode TEXT NOT NULL DEFAULT 'use',
                progress INTEGER NOT NULL DEFAULT 1,
                verbose INTEGER NOT NULL DEFAULT 1,
                getcontents INTEGER NOT NULL DEFAULT 0,
                i18n INTEGER NOT NULL DEFAULT 0,
                timeout_seconds INTEGER DEFAULT NULL,
                rsync_extra TEXT DEFAULT '',
                extra_options TEXT DEFAULT '',
                include_patterns TEXT DEFAULT '',
                exclude_patterns TEXT DEFAULT '',
                schedule_mode TEXT NOT NULL DEFAULT 'manual',
                schedule_time TEXT NOT NULL DEFAULT '22:00',
                schedule_weekday INTEGER NOT NULL DEFAULT 6,
                interval_hours INTEGER NOT NULL DEFAULT 24,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mirror_id INTEGER DEFAULT NULL,
                mirror_name TEXT NOT NULL,
                job_type TEXT NOT NULL DEFAULT 'mirror',
                script_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 0,
                pid INTEGER DEFAULT NULL,
                command TEXT NOT NULL DEFAULT '',
                log_path TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT DEFAULT NULL,
                exit_code INTEGER DEFAULT NULL,
                error_message TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                command_json TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(mirror_id) REFERENCES mirrors(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT DEFAULT '',
                created_by TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS healthchecks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                expected_status INTEGER NOT NULL DEFAULT 200,
                method TEXT NOT NULL DEFAULT 'GET',
                timeout_seconds INTEGER NOT NULL DEFAULT 10,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_check_at TEXT DEFAULT '',
                last_ok INTEGER DEFAULT NULL,
                last_status_code INTEGER DEFAULT NULL,
                last_latency_ms INTEGER DEFAULT NULL,
                last_error TEXT DEFAULT '',
                last_notify_state TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                job_kind TEXT NOT NULL DEFAULT 'mirror',
                mirror_id INTEGER DEFAULT NULL,
                script_name TEXT NOT NULL DEFAULT '',
                script_selection TEXT NOT NULL DEFAULT 'single',
                script_names TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                schedule_type TEXT NOT NULL DEFAULT 'daily',
                times TEXT NOT NULL DEFAULT '22:00',
                weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                interval_hours INTEGER NOT NULL DEFAULT 24,
                dry_run INTEGER NOT NULL DEFAULT 0,
                origin TEXT NOT NULL DEFAULT 'custom',
                last_run_key TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(mirror_id) REFERENCES mirrors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mirror_size_cache (
                path TEXT PRIMARY KEY,
                bytes INTEGER DEFAULT NULL,
                exists_flag INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'unknown',
                error TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                calculated_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in con.execute("PRAGMA table_info(mirrors)").fetchall()}
        if "extra_options" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN extra_options TEXT DEFAULT ''")
        if "keyring_fingerprint" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN keyring_fingerprint TEXT DEFAULT ''")
        # Migration: Ab v0.1.12 darf mirror_id NULL sein, damit auch Benutzerskripte
        # als normale Jobs in derselben Warteschlange laufen können.
        job_info = con.execute("PRAGMA table_info(jobs)").fetchall()
        job_columns = {row["name"] for row in job_info}
        mirror_id_info = next((row for row in job_info if row["name"] == "mirror_id"), None)
        needs_jobs_rebuild = bool(mirror_id_info and int(mirror_id_info["notnull"] or 0) == 1)
        if needs_jobs_rebuild:
            con.executescript("""
                CREATE TABLE jobs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mirror_id INTEGER DEFAULT NULL,
                    mirror_name TEXT NOT NULL,
                    job_type TEXT NOT NULL DEFAULT 'mirror',
                    script_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    pid INTEGER DEFAULT NULL,
                    command TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT DEFAULT NULL,
                    exit_code INTEGER DEFAULT NULL,
                    error_message TEXT DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    command_json TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(mirror_id) REFERENCES mirrors(id) ON DELETE SET NULL
                );
                INSERT INTO jobs_new(id, mirror_id, mirror_name, job_type, script_name, status, dry_run, pid, command, log_path, started_at, finished_at, exit_code, error_message, source, command_json)
                SELECT id, mirror_id, mirror_name, 'mirror', '', status, dry_run, pid, command, log_path, started_at, finished_at, exit_code, error_message, COALESCE(source, 'manual'), COALESCE(command_json, '') FROM jobs;
                DROP TABLE jobs;
                ALTER TABLE jobs_new RENAME TO jobs;
            """)
            job_info = con.execute("PRAGMA table_info(jobs)").fetchall()
            job_columns = {row["name"] for row in job_info}
        if "source" not in job_columns:
            con.execute("ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "command_json" not in job_columns:
            con.execute("ALTER TABLE jobs ADD COLUMN command_json TEXT NOT NULL DEFAULT ''")
        if "job_type" not in job_columns:
            con.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'mirror'")
        if "script_name" not in job_columns:
            con.execute("ALTER TABLE jobs ADD COLUMN script_name TEXT NOT NULL DEFAULT ''")

        schedule_columns = {row["name"] for row in con.execute("PRAGMA table_info(job_schedules)").fetchall()}
        if "job_kind" not in schedule_columns:
            con.execute("ALTER TABLE job_schedules ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'mirror'")
        if "script_name" not in schedule_columns:
            con.execute("ALTER TABLE job_schedules ADD COLUMN script_name TEXT NOT NULL DEFAULT ''")
        if "script_selection" not in schedule_columns:
            con.execute("ALTER TABLE job_schedules ADD COLUMN script_selection TEXT NOT NULL DEFAULT 'single'")
        if "script_names" not in schedule_columns:
            con.execute("ALTER TABLE job_schedules ADD COLUMN script_names TEXT NOT NULL DEFAULT ''")
        if "origin" not in schedule_columns:
            con.execute("ALTER TABLE job_schedules ADD COLUMN origin TEXT NOT NULL DEFAULT 'custom'")

        # Defensive Nachmigration: Bei sehr alten oder während eines Updates geöffneten
        # Datenbanken kann die Tabelle für den Größen-Cache fehlen. Das darf später
        # beim Dashboard-Aufruf niemals den Login blockieren.
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mirror_size_cache (
                path TEXT PRIMARY KEY,
                bytes INTEGER DEFAULT NULL,
                exists_flag INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'unknown',
                error TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                calculated_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )


def app_timezone_name() -> str:
    try:
        settings_tz = str(load_settings().get("app_timezone") or "").strip()
        if settings_tz:
            return settings_tz
    except Exception:
        pass
    return os.environ.get("APP_TIMEZONE", os.environ.get("TZ", DEFAULT_APP_TIMEZONE)).strip() or DEFAULT_APP_TIMEZONE


def local_now() -> dt.datetime:
    name = app_timezone_name()
    if ZoneInfo is not None:
        try:
            return dt.datetime.now(ZoneInfo(name)).replace(tzinfo=None, microsecond=0)
        except Exception:
            pass
    return dt.datetime.now().replace(microsecond=0)


def now_iso() -> str:
    return local_now().isoformat(sep=" ")


@app.template_filter("local_time")
def local_time_filter(value: str) -> str:
    # Für vorhandene naive Zeitwerte bleibt der Wert erhalten; neue Werte werden
    # durch now_iso() bereits in der konfigurierten lokalen Zeitzone erzeugt.
    return str(value or "")


def parse_datetime_flexible(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    text = str(value).strip()
    for parser in (dt.datetime.fromisoformat,):
        try:
            return parser(text)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def format_duration_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    try:
        total = max(0, int(round(float(seconds))))
    except Exception:
        return "-"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_duration_between(started_at: str, finished_at: str = "") -> str:
    start = parse_datetime_flexible(started_at)
    if not start:
        return "-"
    end = parse_datetime_flexible(finished_at) if finished_at else local_now()
    if not end:
        return "-"
    return format_duration_seconds((end - start).total_seconds())


def enrich_job_duration(job: Dict[str, Any]) -> Dict[str, Any]:
    finished = job.get("finished_at") or ""
    status = job.get("status") or ""
    if not finished and status in {"queued", "starting"}:
        job["duration_h"] = "-"
    elif not finished and status in {"running", "stopping"}:
        job["duration_h"] = format_duration_between(job.get("started_at") or "") + " bisher"
    else:
        job["duration_h"] = format_duration_between(job.get("started_at") or "", finished)
    return job


def enrich_jobs_duration(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for job in jobs:
        enrich_job_duration(job)
    return jobs


def add_event(level: str, message: str) -> None:
    try:
        with db() as con:
            con.execute(
                "INSERT INTO app_events(level, message, created_at) VALUES (?, ?, ?)",
                (level, message, now_iso()),
            )
    except sqlite3.OperationalError as exc:
        # Ereignisse sind hilfreich, aber nicht kritisch. Ein kurzer SQLite-Lock
        # darf Speichern/Importieren/Job-Ende nicht abbrechen.
        if "locked" not in str(exc).lower():
            raise


def log_webui_exception(context: str, exc: BaseException) -> None:
    """Schreibt unerwartete WebUI-Fehler in eine Datei, damit sie nach einem
    Internal Server Error direkt im Container/Volume nachvollziehbar sind."""
    try:
        APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with WEBUI_ERROR_LOG.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"\n[{now_iso()}] {context}: {exc}\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass


@app.errorhandler(500)
def internal_error(exc):
    log_webui_exception("HTTP 500", exc)
    # Die Fehlerseite ist absichtlich ohne komplexe Datenbankabfragen gehalten,
    # damit ein DB-/Template-Problem nicht direkt den nächsten Fehler erzeugt.
    return render_template("error.html", title="Internal Server Error", message="In der WebUI ist ein unerwarteter Fehler aufgetreten. Details wurden in webui-error.log gespeichert.", log_path=str(WEBUI_ERROR_LOG)), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

DEFAULT_PASSWORDS = {"", "changeme", "please-change-this-password", "please-change-me"}


def load_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(SETTINGS_PATH)
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass




# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------

SECRET_FIELDS = {"smtp_password", "telegram_bot_token", "discord_webhook_url"}
SECRET_PREFIX = "enc:v1:"


def encryption_available() -> bool:
    return Fernet is not None and bool(app.secret_key)


def fernet_instance() -> Optional[Any]:
    if not encryption_available():
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(str(app.secret_key).encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if value.startswith(SECRET_PREFIX):
        return value
    f = fernet_instance()
    if not f:
        # Fallback only if cryptography is unexpectedly unavailable. The UI does
        # not display secret values, but true encryption requires cryptography.
        return value
    return SECRET_PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if not value.startswith(SECRET_PREFIX):
        return value
    f = fernet_instance()
    if not f:
        return ""
    token = value[len(SECRET_PREFIX):]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def migrate_notification_secret_storage() -> None:
    """Encrypt existing notification secrets and remove legacy admin secrets.

    This keeps settings.json from exposing SMTP passwords, Telegram bot tokens,
    Discord webhooks and legacy admin password hashes. User accounts remain in
    SQLite with hashed passwords.
    """
    try:
        settings = load_settings()
        changed = False
        notify = settings.get("notify")
        if isinstance(notify, dict):
            for field in SECRET_FIELDS:
                value = str(notify.get(field) or "")
                if value and not value.startswith(SECRET_PREFIX):
                    notify[field] = encrypt_secret(value)
                    changed = True
        # Once the users table exists, legacy single-admin values are no longer
        # needed in settings.json. The username in SQLite remains visible because
        # it is the login identifier; passwords are stored only as hashes.
        if settings.get("admin_username") or settings.get("admin_password_hash"):
            try:
                if user_count() > 0:
                    settings.pop("admin_username", None)
                    settings.pop("admin_password_hash", None)
                    settings["legacy_auth_cleaned_at"] = now_iso()
                    changed = True
            except Exception:
                pass
        if changed:
            save_settings(settings)
    except Exception as exc:
        log_webui_exception("migrate_notification_secret_storage", exc)

def get_int_setting(key: str, default: int, minimum: int = 0, maximum: int = 100000) -> int:
    settings = load_settings()
    try:
        value = int(settings.get(key, os.environ.get(key.upper(), default)))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def max_parallel_jobs() -> int:
    return get_int_setting("max_parallel_jobs", DEFAULT_MAX_PARALLEL_JOBS, 1, 16)


def job_retention_days() -> int:
    return get_int_setting("job_retention_days", DEFAULT_JOB_RETENTION_DAYS, 1, 3660)


def job_list_limit() -> int:
    return get_int_setting("job_list_limit", DEFAULT_JOB_LIST_LIMIT, 10, 5000)


def dashboard_recent_jobs_limit() -> int:
    return get_int_setting("dashboard_recent_jobs_limit", DEFAULT_DASHBOARD_RECENT_JOBS_LIMIT, 1, 200)


def dashboard_events_limit() -> int:
    return get_int_setting("dashboard_events_limit", DEFAULT_DASHBOARD_EVENTS_LIMIT, 1, 200)


def size_cache_ttl_seconds() -> int:
    return get_int_setting("size_cache_ttl_seconds", DEFAULT_SIZE_CACHE_TTL_SECONDS, 60, 604800)


def size_calc_timeout_seconds() -> int:
    return get_int_setting("size_calc_timeout_seconds", DEFAULT_SIZE_CALC_TIMEOUT_SECONDS, 60, 86400)


def size_calc_max_parallel() -> int:
    return get_int_setting("size_calc_max_parallel", DEFAULT_SIZE_CALC_MAX_PARALLEL, 1, 8)


def auto_size_recalc_enabled() -> bool:
    return bool(get_int_setting("auto_size_recalc_enabled", DEFAULT_AUTO_SIZE_RECALC_ENABLED, 0, 1))


def auto_size_idle_minutes() -> int:
    return get_int_setting("auto_size_idle_minutes", DEFAULT_AUTO_SIZE_IDLE_MINUTES, 1, 10080)


def storage_guard_enabled() -> bool:
    return bool(get_int_setting("storage_guard_enabled", DEFAULT_STORAGE_GUARD_ENABLED, 0, 1))


def storage_guard_threshold_percent() -> int:
    return get_int_setting("storage_guard_threshold_percent", DEFAULT_STORAGE_GUARD_THRESHOLD_PERCENT, 1, 100)


def mirror_storage_guard_info() -> Dict[str, Any]:
    """Return current mirror storage guard state.

    The guard protects real mirror jobs from filling the target volume. Dry-runs
    and user scripts are intentionally not blocked because they do not normally
    write mirror payload data.
    """
    usage = disk_usage_info(MIRROR_BASE)
    enabled = storage_guard_enabled()
    threshold = storage_guard_threshold_percent()
    try:
        percent = float(usage.get("percent") or 0)
    except Exception:
        percent = 0.0
    blocked = bool(enabled and not usage.get("error") and percent >= threshold)
    return {
        "enabled": enabled,
        "threshold": threshold,
        "blocked": blocked,
        "usage": usage,
        "message": (
            f"Mirror-Speicher zu voll: {percent:.1f}% belegt, Grenzwert {threshold}%. Neue echte Mirror-Jobs werden pausiert, bis der Wert wieder darunter liegt."
            if blocked else ""
        ),
    }


def save_app_setting_values(values: Dict[str, Any]) -> None:
    settings = load_settings()
    settings.update(values)
    settings["settings_updated_at"] = now_iso()
    save_settings(settings)


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(24)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    encoded = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def verify_password_hash(stored: str, password: str) -> bool:
    stored = stored or ""
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_s, salt, encoded = stored.split("$", 3)
            iterations = int(iterations_s)
            expected = base64.b64decode(encoded.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    if stored.startswith(("pbkdf2:", "scrypt:")):
        try:
            return check_password_hash(stored, password)
        except Exception:
            return False
    return hmac.compare_digest(stored, password)


def password_is_default(value: str) -> bool:
    return (value or "").strip() in DEFAULT_PASSWORDS



def user_count() -> int:
    try:
        with db() as con:
            row = con.execute("SELECT COUNT(*) AS n FROM users WHERE enabled=1").fetchone()
            return int(row["n"] if row else 0)
    except Exception:
        return 0


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    try:
        with db() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
            return row_to_dict(row) if row else None
    except Exception:
        return None


def list_users() -> List[Dict[str, Any]]:
    with db() as con:
        return [row_to_dict(r) for r in con.execute("SELECT id, username, role, enabled, created_at, updated_at, last_login_at FROM users ORDER BY username COLLATE NOCASE").fetchall()]


def create_or_update_user(username: str, password: Optional[str], role: str = "admin", enabled: int = 1, user_id: Optional[int] = None) -> int:
    username = (username or "").strip()
    if not username:
        raise ValueError("Benutzername darf nicht leer sein.")
    if role not in {"admin", "user"}:
        raise ValueError("Ungültige Rolle.")
    if password is not None and len(password) < 8:
        raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
    with db() as con:
        if user_id is None:
            if password is None:
                raise ValueError("Passwort fehlt.")
            cur = con.execute(
                "INSERT INTO users(username, password_hash, role, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, hash_password(password), role, enabled, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)
        if password:
            con.execute(
                "UPDATE users SET username=?, password_hash=?, role=?, enabled=?, updated_at=? WHERE id=?",
                (username, hash_password(password), role, enabled, now_iso(), user_id),
            )
        else:
            con.execute(
                "UPDATE users SET username=?, role=?, enabled=?, updated_at=? WHERE id=?",
                (username, role, enabled, now_iso(), user_id),
            )
        return user_id


def ensure_initial_user_from_legacy_config() -> None:
    if user_count() > 0:
        return
    cfg = legacy_admin_config()
    if not cfg:
        return
    try:
        with db() as con:
            con.execute(
                "INSERT OR IGNORE INTO users(username, password_hash, role, enabled, created_at, updated_at) VALUES (?, ?, 'admin', 1, ?, ?)",
                (cfg["username"], cfg["password_hash"], now_iso(), now_iso()),
            )
    except Exception:
        pass


def legacy_admin_config() -> Optional[Dict[str, str]]:
    """Return legacy single-admin auth config from settings.json or .env."""
    settings = load_settings()
    username = str(settings.get("admin_username") or "").strip()
    password_hash = str(settings.get("admin_password_hash") or "").strip()
    if username and password_hash:
        return {"source": "settings.json", "username": username, "password_hash": password_hash}

    env_username = os.environ.get("APP_USERNAME", "").strip()
    env_hash = os.environ.get("APP_PASSWORD_HASH", "").strip()
    env_password = os.environ.get("APP_PASSWORD", "")

    if env_username and env_hash:
        return {"source": ".env APP_PASSWORD_HASH", "username": env_username, "password_hash": env_hash}
    if env_username and env_password and not password_is_default(env_password):
        return {"source": ".env APP_PASSWORD", "username": env_username, "password_hash": env_password}
    return None


def admin_config() -> Optional[Dict[str, str]]:
    """Return current visible auth config. Users table has priority."""
    try:
        username = session.get("username") or ""
    except RuntimeError:
        username = ""
    try:
        with db() as con:
            row = None
            if username:
                row = con.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
            if not row:
                row = con.execute("SELECT * FROM users WHERE enabled=1 ORDER BY role='admin' DESC, id ASC LIMIT 1").fetchone()
            if row:
                return {"source": "Benutzerverwaltung", "username": row["username"], "password_hash": row["password_hash"], "role": row["role"]}
    except Exception:
        pass
    return legacy_admin_config()


def setup_required() -> bool:
    return user_count() == 0 and legacy_admin_config() is None


def auth_enabled() -> bool:
    return not setup_required()


def verify_user_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_username(username)
    if user and int(user.get("enabled") or 0) == 1 and verify_password_hash(user["password_hash"], password):
        with db() as con:
            con.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_iso(), user["id"]))
        return user
    return None


def verify_admin_login(username: str, password: str) -> bool:
    user = verify_user_login(username, password)
    if user:
        return True
    cfg = legacy_admin_config()
    if not cfg:
        return False
    return hmac.compare_digest(username, cfg["username"]) and verify_password_hash(cfg["password_hash"], password)


def current_user() -> Dict[str, Any]:
    username = session.get("username", "")
    if username:
        user = get_user_by_username(username)
        if user:
            return user
    cfg = admin_config() or {}
    return {"username": cfg.get("username", ""), "role": cfg.get("role", "admin"), "enabled": 1}


def is_admin_user() -> bool:
    try:
        return (current_user() or {}).get("role") == "admin"
    except Exception:
        return False


def deny_non_admin(message: str = "Diese Funktion ist nur für Admin-Benutzer verfügbar."):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    flash(message, "danger")
    return redirect(request.referrer or url_for("dashboard"))


def require_admin_write(view):
    """Erlaubt GET/HEAD für angemeldete Benutzer, blockiert schreibende Requests für normale Benutzer."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if setup_required():
            return redirect(url_for("setup", next=request.path))
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not is_admin_user():
            return deny_non_admin("Normale Benutzer haben nur Leserechte. Änderungen, Starts, Stopps und Importe sind Admin-Funktionen.")
        return view(*args, **kwargs)
    return wrapped


def require_admin(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if setup_required():
            return redirect(url_for("setup", next=request.path))
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        if not is_admin_user():
            return deny_non_admin()
        return view(*args, **kwargs)
    return wrapped

def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if setup_required():
            return redirect(url_for("setup", next=request.path))
        if session.get("authenticated"):
            return view(*args, **kwargs)
        return redirect(url_for("login", next=request.path))

    return wrapped


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if not setup_required() and not request.args.get("force"):
        return redirect(url_for("dashboard") if session.get("authenticated") else url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        try:
            if not username:
                raise ValueError("Benutzername darf nicht leer sein.")
            if len(password) < 8:
                raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
            if password != password2:
                raise ValueError("Die Passwort-Wiederholung passt nicht.")
            create_or_update_user(username, password, role="admin", enabled=1)
            settings = load_settings()
            settings.pop("admin_username", None)
            settings.pop("admin_password_hash", None)
            settings["auth_updated_at"] = now_iso()
            save_settings(settings)
            session.clear()
            session["authenticated"] = True
            session["username"] = username
            session["role"] = "admin"
            add_event("info", "Admin-Zugang über Ersteinrichtung gesetzt.")
            flash("Admin-Zugang wurde eingerichtet.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("setup.html", app_name=APP_NAME, app_version=APP_VERSION)


@app.route("/login", methods=["GET", "POST"])
def login():
    if setup_required():
        return redirect(url_for("setup", next=request.args.get("next") or url_for("dashboard")))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = verify_user_login(username, password)
        if user or verify_admin_login(username, password):
            session.clear()
            session["authenticated"] = True
            if user:
                session["username"] = user["username"]
                session["role"] = user["role"]
            else:
                session["username"] = username
                session["role"] = "admin"
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Login fehlgeschlagen. Prüfe Benutzername, Passwort und ob der Container nach .env-Änderungen neu erstellt wurde.", "danger")
    return render_template("login.html", app_name=APP_NAME, app_version=APP_VERSION, auth_source=(admin_config() or {}).get("source", "unbekannt"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/settings", methods=["GET", "POST"])
@require_admin
def settings_page():
    cfg = admin_config() or {}
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "change_password":
                current_password = request.form.get("current_password", "")
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                password2 = request.form.get("password2", "")
                if not verify_admin_login(cfg.get("username", ""), current_password):
                    raise ValueError("Aktuelles Passwort ist falsch.")
                if not username:
                    raise ValueError("Benutzername darf nicht leer sein.")
                if len(password) < 8:
                    raise ValueError("Das neue Passwort muss mindestens 8 Zeichen lang sein.")
                if password != password2:
                    raise ValueError("Die Passwort-Wiederholung passt nicht.")
                user = current_user()
                if user.get("id"):
                    create_or_update_user(username, password, role=user.get("role", "admin"), enabled=1, user_id=int(user["id"]))
                settings = load_settings()
                settings.pop("admin_username", None)
                settings.pop("admin_password_hash", None)
                settings["auth_updated_at"] = now_iso()
                save_settings(settings)
                session.clear()
                flash("Zugang wurde geändert. Bitte neu einloggen.", "success")
                return redirect(url_for("login"))
            if action == "set_appearance":
                appearance = request.form.get("appearance", "light").strip()
                if appearance not in {"light", "dark", "auto"}:
                    raise ValueError("Ungültiger Darstellungsmodus.")
                settings = load_settings()
                settings["appearance"] = appearance
                settings["appearance_updated_at"] = now_iso()
                save_settings(settings)
                flash("Darstellung wurde gespeichert.", "success")
                return redirect(url_for("settings_page"))
            if action == "save_storage_guard":
                storage_enabled = 1 if request.form.get("storage_guard_enabled") == "on" else 0
                storage_threshold = int(request.form.get("storage_guard_threshold_percent", str(DEFAULT_STORAGE_GUARD_THRESHOLD_PERCENT)) or DEFAULT_STORAGE_GUARD_THRESHOLD_PERCENT)
                if storage_threshold < 1 or storage_threshold > 100:
                    raise ValueError("Speicherplatz-Grenzwert muss zwischen 1 und 100 Prozent liegen.")
                save_app_setting_values({
                    "storage_guard_enabled": storage_enabled,
                    "storage_guard_threshold_percent": storage_threshold,
                })
                flash("Mirror-Speicher-Sperre wurde gespeichert.", "success")
                return redirect(url_for("settings_page"))
            if action == "save_system_settings":
                max_jobs = int(request.form.get("max_parallel_jobs", "1") or 1)
                retention = int(request.form.get("job_retention_days", "31") or 31)
                list_limit = int(request.form.get("job_list_limit", "100") or 100)
                dashboard_jobs_limit = int(request.form.get("dashboard_recent_jobs_limit", str(DEFAULT_DASHBOARD_RECENT_JOBS_LIMIT)) or DEFAULT_DASHBOARD_RECENT_JOBS_LIMIT)
                dashboard_events_limit_value = int(request.form.get("dashboard_events_limit", str(DEFAULT_DASHBOARD_EVENTS_LIMIT)) or DEFAULT_DASHBOARD_EVENTS_LIMIT)
                size_ttl = int(request.form.get("size_cache_ttl_seconds", str(DEFAULT_SIZE_CACHE_TTL_SECONDS)) or DEFAULT_SIZE_CACHE_TTL_SECONDS)
                size_timeout = int(request.form.get("size_calc_timeout_seconds", str(DEFAULT_SIZE_CALC_TIMEOUT_SECONDS)) or DEFAULT_SIZE_CALC_TIMEOUT_SECONDS)
                size_parallel = int(request.form.get("size_calc_max_parallel", str(DEFAULT_SIZE_CALC_MAX_PARALLEL)) or DEFAULT_SIZE_CALC_MAX_PARALLEL)
                auto_size_enabled = 1 if request.form.get("auto_size_recalc_enabled") == "on" else 0
                auto_size_idle = int(request.form.get("auto_size_idle_minutes", str(DEFAULT_AUTO_SIZE_IDLE_MINUTES)) or DEFAULT_AUTO_SIZE_IDLE_MINUTES)
                app_tz = (request.form.get("app_timezone", app_timezone_name()) or app_timezone_name()).strip()
                if not app_tz:
                    app_tz = DEFAULT_APP_TIMEZONE
                if ZoneInfo is not None:
                    try:
                        ZoneInfo(app_tz)
                    except Exception:
                        raise ValueError("Ungültige Zeitzone. Beispiel: Europe/Berlin")
                if max_jobs < 1 or max_jobs > 16:
                    raise ValueError("Gleichzeitig laufende Jobs müssen zwischen 1 und 16 liegen.")
                if retention < 1 or retention > 3660:
                    raise ValueError("Job-/Log-Aufbewahrung muss zwischen 1 und 3660 Tagen liegen.")
                if list_limit < 10 or list_limit > 5000:
                    raise ValueError("Anzeige-Limit muss zwischen 10 und 5000 liegen.")
                if dashboard_jobs_limit < 1 or dashboard_jobs_limit > 200:
                    raise ValueError("Dashboard-Limit für letzte Jobs muss zwischen 1 und 200 liegen.")
                if dashboard_events_limit_value < 1 or dashboard_events_limit_value > 200:
                    raise ValueError("Dashboard-Limit für Ereignisse muss zwischen 1 und 200 liegen.")
                if size_ttl < 60 or size_ttl > 604800:
                    raise ValueError("Größen-Cache-TTL muss zwischen 60 Sekunden und 7 Tagen liegen.")
                if size_timeout < 60 or size_timeout > 86400:
                    raise ValueError("Größenberechnungs-Timeout muss zwischen 60 Sekunden und 24 Stunden liegen.")
                if size_parallel < 1 or size_parallel > 8:
                    raise ValueError("Parallele Größenberechnungen müssen zwischen 1 und 8 liegen.")
                if auto_size_idle < 1 or auto_size_idle > 10080:
                    raise ValueError("Ruhefenster für automatische Größenberechnung muss zwischen 1 Minute und 7 Tagen liegen.")
                save_app_setting_values({
                    "max_parallel_jobs": max_jobs,
                    "job_retention_days": retention,
                    "job_list_limit": list_limit,
                    "dashboard_recent_jobs_limit": dashboard_jobs_limit,
                    "dashboard_events_limit": dashboard_events_limit_value,
                    "size_cache_ttl_seconds": size_ttl,
                    "size_calc_timeout_seconds": size_timeout,
                    "size_calc_max_parallel": size_parallel,
                    "auto_size_recalc_enabled": auto_size_enabled,
                    "auto_size_idle_minutes": auto_size_idle,
                    "app_timezone": app_tz,
                })
                cleanup_old_jobs_and_logs()
                flash("Systemeinstellungen wurden gespeichert.", "success")
                return redirect(url_for("settings_page"))
            raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template(
        "settings.html",
        auth_config=cfg,
        settings_path=str(SETTINGS_PATH),
        webui_port=os.environ.get("WEBUI_PORT", "8111"),
        mirror_http_port=os.environ.get("MIRROR_HTTP_PORT", "8110"),
        use_nginx_mirror_http=str(os.environ.get("USE_NGINX_MIRROR_HTTP", "1")).lower() in {"1", "true", "yes", "on"},
        internal_app_port=os.environ.get("APP_PORT", "8080"),
        project_root=str(Path(__file__).resolve().parents[1]),
        package_folder=Path(__file__).resolve().parents[1].name,
        update_dir=os.environ.get("UPDATE_DIR", "updates"),
        import_script_dir=str(IMPORT_SCRIPT_DIR),
        user_script_dir=str(USER_SCRIPT_DIR),
        import_host_mirror_paths=", ".join(IMPORT_HOST_MIRROR_PATHS),
        storage=disk_usage_info(MIRROR_BASE),
        appearance=current_appearance(),
        dependency_checks=runtime_dependency_checks(),
        max_parallel_jobs=max_parallel_jobs(),
        job_retention_days=job_retention_days(),
        job_list_limit=job_list_limit(),
        dashboard_recent_jobs_limit=dashboard_recent_jobs_limit(),
        dashboard_events_limit=dashboard_events_limit(),
        size_cache_ttl_seconds=size_cache_ttl_seconds(),
        size_calc_timeout_seconds=size_calc_timeout_seconds(),
        size_calc_max_parallel=size_calc_max_parallel(),
        auto_size_recalc_enabled=auto_size_recalc_enabled(),
        auto_size_idle_minutes=auto_size_idle_minutes(),
        storage_guard=mirror_storage_guard_info(),
        storage_guard_enabled=storage_guard_enabled(),
        storage_guard_threshold_percent=storage_guard_threshold_percent(),
        app_timezone=app_timezone_name(),
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def csv_to_list(value: str) -> List[str]:
    if not value:
        return []
    reader = csv.reader(io.StringIO(value))
    return [item.strip() for row in reader for item in row if item.strip()]


def bool_from_form(name: str) -> int:
    return 1 if request.form.get(name) in ("on", "1", "true", "yes") else 0


def normalize_target_path(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Zielverzeichnis darf nicht leer sein.")
    path = Path(raw)
    if not path.is_absolute():
        path = MIRROR_BASE / path
    resolved = path.resolve(strict=False)
    base = MIRROR_BASE.resolve(strict=False)
    if base != resolved and base not in resolved.parents:
        raise ValueError(f"Zielverzeichnis muss innerhalb von {base} liegen.")
    return str(resolved)


def normalize_root_path(value: str) -> str:
    """Normalize a debmirror root path without breaking special roots like ':deb/'."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith(":"):
        # Some existing scripts use roots such as ':deb/'. Keep this exact form.
        return raw
    return raw.strip("/")


SAFE_EXTRA_FLAGS = {
    "--passive",
    "--ignore-missing-release",
    "--ignore-small-errors",
    "--checksums",
    "--ignore-release-gpg",
    "--no-check-gpg",
}


def parse_extra_options(value: str) -> List[str]:
    """Parse a small whitelist of additional debmirror flags.

    These are appended without shell=True, so shell injection is avoided. Unknown
    flags are rejected instead of being executed blindly.
    """
    if not (value or "").strip():
        return []
    result: List[str] = []
    for token in shlex_split(value):
        if token in SAFE_EXTRA_FLAGS:
            result.append(token)
        else:
            raise ValueError(f"Zusatzoption ist nicht freigegeben: {token}")
    return result


def allowed_keyring_path(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        path = APP_KEYRING_DIR / path
    resolved = path.resolve(strict=False)
    base = APP_KEYRING_DIR.resolve(strict=False)
    if base != resolved and base not in resolved.parents:
        raise ValueError(f"Keyring muss innerhalb von {base} liegen.")
    return str(resolved)


def get_mirror(mirror_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute("SELECT * FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
        return row_to_dict(row) if row else None


def list_mirrors() -> List[Dict[str, Any]]:
    with db() as con:
        rows = con.execute("SELECT * FROM mirrors ORDER BY name COLLATE NOCASE").fetchall()
        return [row_to_dict(r) for r in rows]


def get_last_job(mirror_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE mirror_id=? ORDER BY id DESC LIMIT 1", (mirror_id,)
        ).fetchone()
        return row_to_dict(row) if row else None


def get_running_job_for_mirror(mirror_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE mirror_id=? AND status IN ('queued','starting','running','stopping') ORDER BY id DESC LIMIT 1",
            (mirror_id,),
        ).fetchone()
        return row_to_dict(row) if row else None


def get_last_job_for_script(script_name: str) -> Optional[Dict[str, Any]]:
    script_name = (script_name or "").strip()
    if not script_name:
        return None
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE job_type='script' AND script_name=? ORDER BY id DESC LIMIT 1",
            (script_name,),
        ).fetchone()
        return row_to_dict(row) if row else None


def get_running_job_for_script(script_name: str) -> Optional[Dict[str, Any]]:
    script_name = (script_name or "").strip()
    if not script_name:
        return None
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE job_type='script' AND script_name=? AND status IN ('queued','starting','running','stopping') ORDER BY id DESC LIMIT 1",
            (script_name,),
        ).fetchone()
        return row_to_dict(row) if row else None


def enrich_user_script_runtime_info(scripts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for script in scripts:
        try:
            last_job = get_last_job_for_script(script.get("name") or "")
            if last_job:
                enrich_job_duration(last_job)
                last_job["source_h"] = job_source_label(last_job.get("source") or "")
            running_job = get_running_job_for_script(script.get("name") or "")
            if running_job:
                enrich_job_duration(running_job)
                running_job["source_h"] = job_source_label(running_job.get("source") or "")
            script["last_job"] = last_job
            script["running_job"] = running_job
            script["schedule_display"] = schedule_display_for_script(script.get("name") or "")
        except Exception as exc:
            log_webui_exception(f"user_script_runtime_info {script.get('name')}", exc)
            script["last_job"] = None
            script["running_job"] = None
            script["schedule_display"] = "-"
    return scripts


def get_active_job() -> Optional[Dict[str, Any]]:
    """Return any queued/running/stopping job. Used for dashboard hints only."""
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','starting','running','stopping') ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'stopping' THEN 1 ELSE 2 END, id ASC LIMIT 1"
        ).fetchone()
        return row_to_dict(row) if row else None


def queued_jobs_count() -> int:
    with db() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'").fetchone()
        return int(row["n"] if row else 0)


def format_bytes(value: Optional[int]) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return "-"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if abs(num) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(num)} {unit}"
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PiB"


def human_size(value: Optional[int]) -> str:
    """Compatibility wrapper for older/newer template helpers.

    Some pages use the historic helper name human_size while the rest of the
    application uses format_bytes. Keeping this small alias prevents upload or
    listing routes from failing with NameError if a template/helper path still
    references human_size.
    """
    return format_bytes(value)


def disk_usage_info(path: Path) -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0
        return {
            "path": str(path),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": percent,
            "total_h": format_bytes(usage.total),
            "used_h": format_bytes(usage.used),
            "free_h": format_bytes(usage.free),
            "error": "",
        }
    except Exception as exc:
        return {"path": str(path), "error": str(exc), "total_h": "-", "used_h": "-", "free_h": "-", "percent": 0}


def direct_path_size_info(path_value: str, timeout_seconds: int) -> Dict[str, Any]:
    """Berechnet die Größe direkt. Diese Funktion wird nur im Hintergrund genutzt."""
    path = Path(path_value)
    if not path.exists():
        return {"exists": False, "bytes": 0, "size_h": "0 B", "files": None, "dirs": None, "error": "Pfad existiert noch nicht.", "status": "missing"}
    result = subprocess.run(
        ["du", "-sb", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        size = int(result.stdout.split()[0])
        return {"exists": True, "bytes": size, "size_h": format_bytes(size), "files": None, "dirs": None, "error": "", "status": "ok"}
    raise RuntimeError((result.stderr or result.stdout or "du konnte die Größe nicht berechnen.").strip())


def _size_cache_row(path_value: str) -> Optional[Dict[str, Any]]:
    try:
        with db() as con:
            row = con.execute("SELECT * FROM mirror_size_cache WHERE path=?", (path_value,)).fetchone()
            return row_to_dict(row) if row else None
    except Exception:
        return None


def _write_size_cache(path_value: str, *, status: str, exists_flag: int = 0, bytes_value: Optional[int] = None, error: str = "", started_at: str = "", calculated_at: str = "") -> None:
    try:
        with db() as con:
            con.execute(
                """
                INSERT INTO mirror_size_cache(path, bytes, exists_flag, status, error, started_at, calculated_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    bytes=excluded.bytes,
                    exists_flag=excluded.exists_flag,
                    status=excluded.status,
                    error=excluded.error,
                    started_at=excluded.started_at,
                    calculated_at=excluded.calculated_at,
                    updated_at=excluded.updated_at
                """,
                (path_value, bytes_value, exists_flag, status, error, started_at, calculated_at, now_iso()),
            )
    except Exception as exc:
        add_event("warning", f"Größen-Cache konnte nicht geschrieben werden: {exc}")


def _size_worker(path_value: str) -> None:
    started = now_iso()
    _write_size_cache(path_value, status="calculating", exists_flag=1 if Path(path_value).exists() else 0, started_at=started)
    try:
        if queued_or_active_jobs_count() > 0:
            old = _size_cache_row(path_value) or {}
            _write_size_cache(
                path_value,
                status="queued",
                exists_flag=1 if Path(path_value).exists() else 0,
                bytes_value=old.get("bytes"),
                error="Größenberechnung wartet, weil noch ein Job läuft oder in der Warteschlange steht.",
                started_at=old.get("started_at") or "",
                calculated_at=old.get("calculated_at") or "",
            )
            return
        info = direct_path_size_info(path_value, size_calc_timeout_seconds())
        _write_size_cache(
            path_value,
            status=info.get("status") or "ok",
            exists_flag=1 if info.get("exists") else 0,
            bytes_value=info.get("bytes"),
            error=info.get("error") or "",
            started_at=started,
            calculated_at=now_iso(),
        )
    except subprocess.TimeoutExpired:
        old = _size_cache_row(path_value) or {}
        _write_size_cache(path_value, status="timeout", exists_flag=1 if Path(path_value).exists() else 0, bytes_value=old.get("bytes"), error="Größenberechnung dauerte zu lange. Der letzte bekannte Wert bleibt erhalten.", started_at=started, calculated_at=now_iso())
    except Exception as exc:
        old = _size_cache_row(path_value) or {}
        _write_size_cache(path_value, status="error", exists_flag=1 if Path(path_value).exists() else 0, bytes_value=old.get("bytes"), error=str(exc), started_at=started, calculated_at=now_iso())
    finally:
        with SIZE_CALC_LOCK:
            SIZE_CALC_RUNNING.discard(path_value)


def request_size_calculation(path_value: str, force: bool = False, *, queue_when_blocked: bool = True) -> bool:
    raw_path = (path_value or "").strip()
    if not raw_path:
        return False
    path_value = str(Path(raw_path))
    try:
        if queued_or_active_jobs_count() > 0:
            if queue_when_blocked:
                old = _size_cache_row(path_value) or {}
                _write_size_cache(
                    path_value,
                    status="queued",
                    exists_flag=1 if Path(path_value).exists() else 0,
                    bytes_value=old.get("bytes"),
                    error="Größenberechnung wartet, weil noch ein Job läuft oder in der Warteschlange steht.",
                    started_at=old.get("started_at") or "",
                    calculated_at=old.get("calculated_at") or "",
                )
            return False
    except Exception as exc:
        log_webui_exception("size_calc_job_guard", exc)
        return False
    try:
        max_parallel = size_calc_max_parallel()
    except Exception as exc:
        log_webui_exception("size_calc_max_parallel", exc)
        max_parallel = DEFAULT_SIZE_CALC_MAX_PARALLEL
    with SIZE_CALC_LOCK:
        if path_value in SIZE_CALC_RUNNING:
            return False
        if len(SIZE_CALC_RUNNING) >= max_parallel:
            old = _size_cache_row(path_value) or {}
            _write_size_cache(
                path_value,
                status="queued",
                exists_flag=1 if Path(path_value).exists() else 0,
                bytes_value=old.get("bytes"),
                error="Größenberechnung wartet auf freie Kapazität.",
                started_at=old.get("started_at") or "",
                calculated_at=old.get("calculated_at") or "",
            )
            return False
        SIZE_CALC_RUNNING.add(path_value)
    try:
        thread = threading.Thread(target=_size_worker, args=(path_value,), daemon=True, name=f"size-calc-{Path(path_value).name or 'mirror'}")
        thread.start()
        return True
    except Exception as exc:
        with SIZE_CALC_LOCK:
            SIZE_CALC_RUNNING.discard(path_value)
        _write_size_cache(path_value, status="error", exists_flag=1 if Path(path_value).exists() else 0, error=str(exc), calculated_at=now_iso())
        log_webui_exception("request_size_calculation", exc)
        return False

def cached_path_size_info(path_value: str, *, force_refresh: bool = False, auto_refresh: bool = False) -> Dict[str, Any]:
    raw_path = (path_value or "").strip()
    if not raw_path:
        return {"exists": False, "bytes": 0, "size_h": "0 B", "files": None, "dirs": None, "error": "Kein Pfad gesetzt.", "status": "missing", "calculated_at": "", "started_at": ""}
    path_value = str(Path(raw_path))
    exists_now = Path(path_value).exists()
    if not exists_now:
        return {"exists": False, "bytes": 0, "size_h": "0 B", "files": None, "dirs": None, "error": "Pfad existiert noch nicht.", "status": "missing", "calculated_at": "", "started_at": ""}

    row = _size_cache_row(path_value)
    now = local_now()
    stale = True
    if row and row.get("calculated_at"):
        try:
            calculated = dt.datetime.fromisoformat(str(row["calculated_at"]))
            stale = (now - calculated).total_seconds() > size_cache_ttl_seconds()
        except Exception:
            stale = True
    if force_refresh or (auto_refresh and (not row or stale)):
        request_size_calculation(path_value, force=force_refresh)

    # Nach dem Anstoß erneut lesen, damit der Status 'calculating' sichtbar wird.
    row = _size_cache_row(path_value) or row
    if row and row.get("bytes") is not None:
        error = str(row.get("error") or "")
        status = str(row.get("status") or "ok")
        if stale and status == "ok":
            status = "stale"
        if str(row.get("path") or "") in SIZE_CALC_RUNNING:
            status = "calculating"
            error = "Größe wird im Hintergrund aktualisiert. Angezeigt wird der letzte bekannte Wert."
        return {
            "exists": bool(row.get("exists_flag")),
            "bytes": row.get("bytes"),
            "size_h": format_bytes(int(row["bytes"])),
            "files": None,
            "dirs": None,
            "error": error,
            "status": status,
            "calculated_at": row.get("calculated_at") or "",
            "started_at": row.get("started_at") or "",
        }
    if row and str(row.get("status") or "") == "calculating":
        return {"exists": True, "bytes": None, "size_h": "Berechnung läuft", "files": None, "dirs": None, "error": "Die Größe wird im Hintergrund berechnet.", "status": "calculating", "calculated_at": row.get("calculated_at") or "", "started_at": row.get("started_at") or ""}
    if row and str(row.get("status") or "") in {"queued", "pending"}:
        label = "wartet" if str(row.get("status") or "") == "queued" else "vorgemerkt"
        return {"exists": True, "bytes": row.get("bytes"), "size_h": format_bytes(int(row["bytes"])) if row.get("bytes") is not None else "Wartet", "files": None, "dirs": None, "error": row.get("error") or "Größenberechnung wartet.", "status": label, "calculated_at": row.get("calculated_at") or "", "started_at": row.get("started_at") or ""}
    if row and str(row.get("status") or "") in {"timeout", "error"}:
        return {"exists": True, "bytes": None, "size_h": "Unbekannt", "files": None, "dirs": None, "error": row.get("error") or "Größenberechnung fehlgeschlagen.", "status": row.get("status") or "error", "calculated_at": row.get("calculated_at") or "", "started_at": row.get("started_at") or ""}
    return {"exists": True, "bytes": None, "size_h": "Unbekannt", "files": None, "dirs": None, "error": "Noch kein Größenwert vorhanden. Starte die Berechnung im Profil manuell oder nutze die automatische Berechnung nach Job-Ruhefenster.", "status": "unknown", "calculated_at": "", "started_at": ""}


def path_size_info(path_value: str, timeout_seconds: int = 20) -> Dict[str, Any]:
    # Rückwärtskompatible API: nicht mehr blockierend berechnen.
    return cached_path_size_info(path_value)


def mirror_stats(mirror: Dict[str, Any], *, auto_refresh: bool = False) -> Dict[str, Any]:
    try:
        return cached_path_size_info(mirror.get("target_path") or "", auto_refresh=auto_refresh)
    except Exception as exc:
        log_webui_exception(f"mirror_stats {mirror.get('name') if isinstance(mirror, dict) else ''}", exc)
        return {"exists": False, "bytes": None, "size_h": "Unbekannt", "files": None, "dirs": None, "error": f"Größenstatus konnte nicht gelesen werden: {exc}", "status": "error", "calculated_at": "", "started_at": ""}


def sample_profiles() -> List[Dict[str, Any]]:
    return [
        {
            "key": "debian-bookworm",
            "title": "Debian Bookworm Basis + Updates",
            "description": "Basis- und Update-Repository für Debian Bookworm ohne Security-Repository.",
            "values": {
                "name": "Debian Bookworm", "enabled": 1, "method": "rsync", "host": "ftp.de.debian.org", "root_path": "debian",
                "target_path": str(MIRROR_BASE / "debian"), "dists": "bookworm,bookworm-updates",
                "sections": "main,contrib,non-free,non-free-firmware", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "debian-bookworm-security",
            "title": "Debian Bookworm Security",
            "description": "Separates Debian-Security-Repository für bookworm-security.",
            "values": {
                "name": "Debian Bookworm Security", "enabled": 1, "method": "rsync", "host": "security.debian.org", "root_path": "debian-security",
                "target_path": str(MIRROR_BASE / "debian-security"), "dists": "bookworm-security",
                "sections": "main,contrib,non-free,non-free-firmware", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "debian-trixie",
            "title": "Debian Trixie Basis + Updates",
            "description": "Basis- und Update-Repository für Debian Trixie ohne Security-Repository.",
            "values": {
                "name": "Debian Trixie", "enabled": 1, "method": "rsync", "host": "ftp.de.debian.org", "root_path": "debian",
                "target_path": str(MIRROR_BASE / "debian-trixie"), "dists": "trixie,trixie-updates",
                "sections": "main,contrib,non-free,non-free-firmware", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "ubuntu-jammy",
            "title": "Ubuntu Jammy Basis + Updates",
            "description": "Basis- und Update-Repository für Ubuntu 22.04 Jammy ohne Security-Repository.",
            "values": {
                "name": "Ubuntu Jammy", "enabled": 1, "method": "rsync", "host": "archive.ubuntu.com", "root_path": "ubuntu",
                "target_path": str(MIRROR_BASE / "ubuntu-jammy"), "dists": "jammy,jammy-updates",
                "sections": "main,restricted,universe,multiverse", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "ubuntu-jammy-security",
            "title": "Ubuntu Jammy Security",
            "description": "Separates Security-Repository für Ubuntu 22.04 Jammy.",
            "values": {
                "name": "Ubuntu Jammy Security", "enabled": 1, "method": "rsync", "host": "security.ubuntu.com", "root_path": "ubuntu",
                "target_path": str(MIRROR_BASE / "ubuntu-jammy-security"), "dists": "jammy-security",
                "sections": "main,restricted,universe,multiverse", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "ubuntu-noble",
            "title": "Ubuntu Noble Basis + Updates",
            "description": "Basis- und Update-Repository für Ubuntu 24.04 Noble ohne Security-Repository.",
            "values": {
                "name": "Ubuntu Noble", "enabled": 1, "method": "rsync", "host": "archive.ubuntu.com", "root_path": "ubuntu",
                "target_path": str(MIRROR_BASE / "ubuntu-noble"), "dists": "noble,noble-updates",
                "sections": "main,restricted,universe,multiverse", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "ubuntu-noble-security",
            "title": "Ubuntu Noble Security",
            "description": "Separates Security-Repository für Ubuntu 24.04 Noble.",
            "values": {
                "name": "Ubuntu Noble Security", "enabled": 1, "method": "rsync", "host": "security.ubuntu.com", "root_path": "ubuntu",
                "target_path": str(MIRROR_BASE / "ubuntu-noble-security"), "dists": "noble-security",
                "sections": "main,restricted,universe,multiverse", "archs": "amd64", "source_mode": "nosource",
            },
        },
        {
            "key": "scpcom-stable-riscv64",
            "title": "SCPCom Stable RISC-V",
            "description": "Beispiel für scpcom.github.io mit sg200x und licheervnano-kvm für riscv64.",
            "values": {
                "name": "SCPCom Stable RISC-V", "enabled": 1, "method": "http", "host": "scpcom.github.io", "root_path": ":deb/",
                "target_path": str(MIRROR_BASE / "scpcom"), "dists": "stable",
                "sections": "sg200x,licheervnano-kvm", "archs": "riscv64", "source_mode": "nosource",
                "i18n": 1, "diff_mode": "use", "rsync_extra": "none", "extra_options": "--passive",
            },
        },
    ]


def default_mirror_values(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "enabled": 1,
        "method": "rsync",
        "host": "ftp.de.debian.org",
        "root_path": "debian",
        "target_path": str(MIRROR_BASE / "debian"),
        "dists": "bookworm,bookworm-updates",
        "sections": "main,contrib,non-free,non-free-firmware",
        "archs": "amd64",
        "source_mode": "nosource",
        "keyring": "",
        "keyring_fingerprint": "",
        "postcleanup": 1,
        "diff_mode": "use",
        "progress": 1,
        "verbose": 1,
        "getcontents": 0,
        "i18n": 0,
        "timeout_seconds": "",
        "rsync_extra": "",
        "extra_options": "",
        "include_patterns": "",
        "exclude_patterns": "",
        "schedule_mode": "manual",
        "schedule_time": "22:00",
        "schedule_weekday": 6,
        "interval_hours": 24,
    }
    if overrides:
        values.update(overrides)
    return values


def normalize_fingerprint(value: str) -> str:
    return re.sub(r"[^A-Fa-f0-9]", "", value or "").upper()


def keyring_fingerprint_matches(path: str, expected: str) -> bool:
    expected_n = normalize_fingerprint(expected)
    if not expected_n:
        return True
    fps = [normalize_fingerprint(fp) for fp in key_fingerprints(Path(path))]
    return any(fingerprint_matches(fp, expected_n) for fp in fps)


def extract_missing_pubkeys(log_text: str) -> List[Dict[str, str]]:
    """Extract truly missing OpenPGP keys from debmirror/gpgv output.

    Wichtig: `gpgv: using RSA key ...` ist kein Fehler. Diese Zeile erscheint
    auch bei erfolgreicher Signaturprüfung. Als fehlend gilt ein Key nur bei
    NO_PUBKEY/ERRSIG oder eindeutigen Fehlerzeilen.
    """
    text = log_text or ""
    no_pubkeys = [normalize_fingerprint(m.group(1)) for m in re.finditer(r"NO_PUBKEY\s+([A-Fa-f0-9]{8,40})", text, re.I)]
    full_keys = [normalize_fingerprint(m.group(1)) for m in re.finditer(r"using\s+(?:RSA|DSA|ECDSA|EDDSA)?\s*key\s+([A-Fa-f0-9]{32,40})", text, re.I)]
    # ERRSIG-Zeilen enthalten bei gpgv häufig zuerst die Key-ID und später den vollen Fingerprint.
    for line in text.splitlines():
        if "ERRSIG" in line:
            for token in line.split():
                clean = normalize_fingerprint(token)
                if len(clean) >= 32:
                    full_keys.append(clean)
                elif 8 <= len(clean) <= 16:
                    no_pubkeys.append(clean)

    # Wenn nur `using RSA key` und `Good signature` vorhanden sind, ist nichts fehlend.
    if not no_pubkeys:
        return []

    results: List[Dict[str, str]] = []
    seen = set()
    for short in no_pubkeys:
        full = ""
        for candidate in full_keys:
            if candidate.endswith(short):
                full = candidate
                break
        key = full or short
        if key not in seen:
            seen.add(key)
            results.append({"key_id": short, "fingerprint": full or short, "has_full_fingerprint": "1" if len(full or short) >= 32 else "0"})
    return results


def default_keyring_filename(fingerprint: str, suffix: str = ".gpg") -> str:
    clean = normalize_fingerprint(fingerprint)
    tail = clean[-16:] if clean else local_now().strftime("%Y%m%d%H%M%S")
    return secure_filename(f"key-{tail}{suffix}")


def import_key_from_keyserver(fingerprint: str, filename: Optional[str] = None, keyserver: str = "hkps://keyserver.ubuntu.com") -> Path:
    fp = normalize_fingerprint(fingerprint)
    if len(fp) < 16:
        raise ValueError("Für Keyserver-Import ist mindestens eine 16-stellige Key-ID erforderlich. Besser ist der vollständige Fingerprint.")
    filename = secure_filename(filename or default_keyring_filename(fp))
    if not filename.endswith(".gpg"):
        filename += ".gpg"
    dest = (APP_KEYRING_DIR / filename).resolve(strict=False)
    base = APP_KEYRING_DIR.resolve(strict=False)
    if base != dest and base not in dest.parents:
        raise ValueError("Ungültiger Keyring-Dateiname.")
    tmp_home = APP_DATA_DIR / "tmp-gpg" / secrets.token_hex(8)
    tmp_home.mkdir(parents=True, exist_ok=True)
    try:
        recv = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--keyserver", keyserver, "--recv-keys", fp],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60, check=False,
        )
        if recv.returncode != 0:
            raise RuntimeError((recv.stdout or "Keyserver-Import fehlgeschlagen.").strip())
        export = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--export", fp],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
        )
        if export.returncode != 0 or not export.stdout:
            raise RuntimeError((export.stderr.decode("utf-8", "replace") or "Key konnte nicht exportiert werden.").strip())
        dest.write_bytes(export.stdout)
        fps = [normalize_fingerprint(x) for x in key_fingerprints(dest)]
        if fp and not any(x.endswith(fp) or fp.endswith(x) or x == fp for x in fps):
            dest.unlink(missing_ok=True)
            raise ValueError("Importierter Key passt nicht zum erwarteten Fingerprint.")
        return dest
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def maybe_dearmor_key_file(path: Path) -> Path:
    """Convert ASCII-armored keys to binary .gpg keyrings for gpgv/debmirror."""
    try:
        head = path.read_bytes()[:128]
    except Exception:
        return path
    if b"-----BEGIN PGP PUBLIC KEY BLOCK-----" not in head:
        return path
    dest = path.with_suffix(".gpg")
    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--dearmor", "--output", str(dest), str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout or "gpg --dearmor fehlgeschlagen.").strip())
    if dest != path:
        path.unlink(missing_ok=True)
    return dest


def assign_keyring_to_mirror(mirror_id: Optional[int], keyring_path: Path, fingerprint: str = "") -> None:
    if not mirror_id:
        return
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        fps = key_fingerprints(keyring_path)
        fp = normalize_fingerprint(fps[0]) if fps else ""
    with db() as con:
        con.execute(
            "UPDATE mirrors SET keyring=?, keyring_fingerprint=?, updated_at=? WHERE id=?",
            (str(keyring_path), fp, now_iso(), mirror_id),
        )



# ---------------------------------------------------------------------------
# Benutzerskripte
# ---------------------------------------------------------------------------

SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@+\-]+$")


def user_script_targets() -> Dict[str, str]:
    raw = load_settings().get("user_script_targets") or {}
    return raw if isinstance(raw, dict) else {}


def get_user_script_target(script_name: str) -> str:
    return str(user_script_targets().get(script_name) or "").strip()


def set_user_script_target(script_name: str, target_path: str) -> None:
    safe_user_script_path(script_name)
    settings = load_settings()
    targets = settings.get("user_script_targets") or {}
    if not isinstance(targets, dict):
        targets = {}
    cleaned = (target_path or "").strip()
    if cleaned:
        cleaned = normalize_target_path(cleaned)
        targets[script_name] = cleaned
    else:
        targets.pop(script_name, None)
    settings["user_script_targets"] = targets
    settings["user_script_targets_updated_at"] = now_iso()
    save_settings(settings)


def list_user_scripts() -> List[Dict[str, Any]]:
    USER_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for path in sorted(USER_SCRIPT_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.is_symlink() or path.name.startswith("."):
            continue
        stat_info = path.stat()
        executable = os.access(path, os.X_OK)
        target_path = get_user_script_target(path.name)
        size_info = cached_path_size_info(target_path) if target_path else {"size_h": "-", "status": "nicht gesetzt", "error": "", "calculated_at": ""}
        items.append({
            "name": path.name,
            "path": str(path),
            "size": stat_info.st_size,
            "size_h": human_size(stat_info.st_size),
            "modified_at": dt.datetime.fromtimestamp(stat_info.st_mtime).replace(microsecond=0).isoformat(sep=" "),
            "executable": executable,
            "target_path": target_path,
            "target_size_info": size_info,
        })
    return items


def safe_user_script_path(script_name: str) -> Path:
    script_name = (script_name or "").strip()
    if not script_name or not SCRIPT_NAME_RE.match(script_name):
        raise ValueError("Ungültiger Skriptname. Erlaubt sind nur Dateinamen ohne Unterverzeichnisse.")
    path = (USER_SCRIPT_DIR / script_name).resolve(strict=False)
    base = USER_SCRIPT_DIR.resolve(strict=False)
    if base != path.parent:
        raise ValueError("Skript muss direkt im Benutzerskript-Verzeichnis liegen.")
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ValueError("Benutzerskript nicht gefunden.")
    return path


def build_user_script_command(script_name: str) -> List[str]:
    path = safe_user_script_path(script_name)
    if path.suffix.lower() == ".sh":
        return ["/bin/bash", str(path)]
    if os.access(path, os.X_OK):
        return [str(path)]
    return ["/bin/bash", str(path)]


def start_script_job(script_name: str, source: str = "manual") -> int:
    path = safe_user_script_path(script_name)
    cmd = build_user_script_command(script_name)
    queued_at = now_iso()
    safe_name = secure_filename(path.name) or "user-script"
    log_path = APP_LOG_DIR / f"{local_now().strftime('%Y%m%d-%H%M%S')}-script-{safe_name}.log"
    with db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, script_name, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (NULL, ?, 'script', ?, 'queued', 0, ?, ?, ?, ?, ?)
            """,
            (f"Script: {path.name}", path.name, shell_join(cmd), json.dumps(cmd, ensure_ascii=False), str(log_path), queued_at, source),
        )
        job_id = int(cur.lastrowid)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        log.write(f"[{queued_at}] DebMirror Manager {APP_VERSION}\n")
        log.write(f"[{queued_at}] Quelle: {source}\n")
        log.write(f"[{queued_at}] Job-Typ: user-script\n")
        log.write(f"[{queued_at}] Skript: {path}\n")
        log.write(f"[{queued_at}] Status: queued\n")
        log.write(f"[{queued_at}] Befehl: {shell_join(cmd)}\n")
        log.write(f"[{queued_at}] Hinweis: Benutzerskripte laufen über dieselbe globale Warteschlange wie debmirror-Jobs.\n\n")
    ensure_job_worker_thread()
    return job_id

# ---------------------------------------------------------------------------
# debmirror command generation
# ---------------------------------------------------------------------------

def build_debmirror_command(mirror: Dict[str, Any], dry_run: bool = False, validate_keyring: bool = True) -> List[str]:
    target = normalize_target_path(mirror["target_path"])
    Path(target).mkdir(parents=True, exist_ok=True)

    method = mirror["method"]
    if method not in {"rsync", "http", "https", "ftp"}:
        raise ValueError("Ungültige Methode.")

    cmd = [
        "debmirror",
        f"--method={method}",
        f"--host={mirror['host'].strip()}",
        f"--root={normalize_root_path(mirror['root_path'])}",
        f"--dist={','.join(csv_to_list(mirror['dists']))}",
        f"--section={','.join(csv_to_list(mirror['sections']))}",
        f"--arch={','.join(csv_to_list(mirror['archs']))}",
    ]

    if mirror.get("source_mode") == "source":
        cmd.append("--source")
    else:
        cmd.append("--nosource")

    keyring = allowed_keyring_path(mirror.get("keyring") or "")
    if keyring:
        expected_fp = normalize_fingerprint(str(mirror.get("keyring_fingerprint") or ""))
        if validate_keyring and expected_fp and not keyring_fingerprint_matches(keyring, expected_fp):
            raise ValueError("Der hinterlegte Keyring-Fingerprint passt nicht zum ausgewählten Keyring. Prüfe Keyring und erwarteten Fingerprint im Mirror-Profil.")
        cmd.append(f"--keyring={keyring}")

    if mirror.get("postcleanup"):
        cmd.append("--postcleanup")
    else:
        cmd.append("--cleanup")

    diff_mode = mirror.get("diff_mode") or "none"
    if diff_mode in {"use", "mirror", "none"}:
        cmd.append(f"--diff={diff_mode}")

    if mirror.get("progress"):
        cmd.append("--progress")
    if mirror.get("verbose"):
        cmd.append("--verbose")
    if mirror.get("getcontents"):
        cmd.append("--getcontents")
    if mirror.get("i18n"):
        cmd.append("--i18n")

    timeout = mirror.get("timeout_seconds")
    if timeout:
        cmd.append(f"--timeout={int(timeout)}")

    rsync_extra_parts = []
    rsync_extra = (mirror.get("rsync_extra") or "").strip()
    if rsync_extra:
        # Whitelisted extra transport option field. It is passed as a single debmirror option,
        # not via shell=True, so shell injection is avoided.
        rsync_extra_parts.append(rsync_extra)
    if rsync_extra_parts:
        cmd.append(f"--rsync-extra={' '.join(rsync_extra_parts)}")

    for extra in parse_extra_options(mirror.get("extra_options") or ""):
        cmd.append(extra)

    for pattern in csv_to_list(mirror.get("include_patterns") or ""):
        cmd.append(f"--include={pattern}")
    for pattern in csv_to_list(mirror.get("exclude_patterns") or ""):
        cmd.append(f"--exclude={pattern}")

    if dry_run:
        cmd.append("--dry-run")

    cmd.append(target)
    return cmd


def shell_join(args: Iterable[str]) -> str:
    # Minimal readable command display without using a shell for execution.
    import shlex

    return " ".join(shlex.quote(a) for a in args)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def start_job(mirror_id: int, dry_run: bool = False, source: str = "manual") -> int:
    mirror = get_mirror(mirror_id)
    if not mirror:
        raise ValueError("Mirror nicht gefunden.")
    active_for_mirror = get_running_job_for_mirror(mirror_id)
    if active_for_mirror:
        raise RuntimeError(f"Für diesen Mirror ist bereits Job #{active_for_mirror['id']} im Zustand {active_for_mirror['status']} vorhanden.")
    guard = mirror_storage_guard_info()
    if not dry_run and guard.get("blocked"):
        raise RuntimeError(guard.get("message") or "Mirror-Speicher-Grenzwert überschritten. Neue Mirror-Jobs werden pausiert.")

    cmd = build_debmirror_command(mirror, dry_run=dry_run)
    queued_at = now_iso()
    safe_name = secure_filename(mirror["name"]) or f"mirror-{mirror_id}"
    log_path = APP_LOG_DIR / f"{local_now().strftime('%Y%m%d-%H%M%S')}-{safe_name}.log"

    with db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)
            """,
            (mirror_id, mirror["name"], 1 if dry_run else 0, shell_join(cmd), json.dumps(cmd, ensure_ascii=False), str(log_path), queued_at, source),
        )
        job_id = int(cur.lastrowid)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        log.write(f"[{queued_at}] DebMirror Manager {APP_VERSION}\n")
        log.write(f"[{queued_at}] Quelle: {source}\n")
        log.write(f"[{queued_at}] Status: queued\n")
        log.write(f"[{queued_at}] Befehl: {shell_join(cmd)}\n")
        log.write(f"[{queued_at}] Hinweis: Jobs werden über die globale Warteschlange ausgeführt. Die maximale Parallelität ist einstellbar.\n\n")
    ensure_job_worker_thread()
    return job_id


def active_jobs_count() -> int:
    with db() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('starting','running','stopping')").fetchone()
        return int(row["n"] if row else 0)


def next_queued_jobs() -> List[Dict[str, Any]]:
    """Return queued jobs up to the configured global concurrency limit.

    If the mirror storage guard is active, real mirror jobs remain queued until
    the usage drops below the configured threshold. Dry-runs and user scripts may
    still run.
    """
    capacity = max_parallel_jobs() - active_jobs_count()
    if capacity <= 0:
        return []
    guard = mirror_storage_guard_info()
    with db() as con:
        rows = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id ASC LIMIT ?", (max(capacity * 5, capacity + 10),)).fetchall()
    jobs: List[Dict[str, Any]] = []
    for row in rows:
        job = row_to_dict(row)
        if guard.get("blocked") and (job.get("job_type") or "mirror") == "mirror" and int(job.get("dry_run") or 0) == 0:
            continue
        jobs.append(job)
        if len(jobs) >= capacity:
            break
    return jobs


def command_for_queued_job(job: Dict[str, Any]) -> List[str]:
    raw_json = job.get("command_json") or ""
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed
        except Exception:
            pass
    return shlex_split(job.get("command") or "")


def job_worker_loop() -> None:
    while True:
        try:
            jobs_to_start = next_queued_jobs()
            if not jobs_to_start:
                time.sleep(2)
                continue
            for job in jobs_to_start:
                cmd = command_for_queued_job(job)
                if not cmd:
                    with db() as con:
                        con.execute(
                            "UPDATE jobs SET status='error', finished_at=?, exit_code=?, error_message=? WHERE id=?",
                            (now_iso(), 1, "Gespeicherter Befehl konnte nicht gelesen werden.", job["id"]),
                        )
                    continue
                with db() as con:
                    con.execute("UPDATE jobs SET status='starting' WHERE id=? AND status='queued'", (job["id"],))
                thread = threading.Thread(
                    target=run_job_thread,
                    args=(int(job["id"]), cmd, Path(job["log_path"]), job.get("source") or "manual"),
                    daemon=True,
                    name=f"debmirror-job-{job['id']}",
                )
                thread.start()
            time.sleep(1)
        except Exception as exc:
            add_event("error", f"Job-Warteschlange Fehler: {exc}")
            time.sleep(5)


def ensure_job_worker_thread() -> None:
    global JOB_WORKER_STARTED
    with JOB_WORKER_LOCK:
        if JOB_WORKER_STARTED:
            return
        thread = threading.Thread(target=job_worker_loop, daemon=True, name="debmirror-job-worker")
        thread.start()
        JOB_WORKER_STARTED = True


def run_job_thread(job_id: int, cmd: List[str], log_path: Path, source: str) -> None:
    exit_code: Optional[int] = None
    status = "error"
    error_message = ""
    with db() as con:
        job_meta_row = con.execute("SELECT job_type, script_name FROM jobs WHERE id=?", (job_id,)).fetchone()
    job_type = (job_meta_row["job_type"] if job_meta_row else "mirror") or "mirror"
    script_name = (job_meta_row["script_name"] if job_meta_row else "") or ""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        started_time = now_iso()
        log.write(f"[{started_time}] Status: running\n")
        log.flush()
        try:
            if job_type == "mirror":
                dep_checks = runtime_dependency_checks()
                missing_required = [item for item in dep_checks if item["required"] and not item["found"]]
                missing_optional = [item for item in dep_checks if not item["required"] and not item["found"]]
                if missing_optional:
                    log.write(f"[{now_iso()}] WARNUNG: Optionale Programme fehlen im Container: {', '.join(item['name'] for item in missing_optional)}\n")
                    log.write(f"[{now_iso()}] Hinweis: Bei fehlendem patch/ed fällt debmirror bei --diff=use auf --diff=none zurück.\n")
                    log.flush()
                if missing_required:
                    exit_code = 127
                    status = "error"
                    error_message = "Pflichtprogramme fehlen im Container: " + ", ".join(item["name"] for item in missing_required)
                    log.write(f"[{now_iso()}] FEHLER: {error_message}\n")
                    log.write(f"[{now_iso()}] Aktion: Container mit der aktuellen Version neu bauen/starten, damit die fehlenden Pakete installiert werden.\n")
                    log.flush()
                    return
            else:
                log.write(f"[{now_iso()}] Benutzerskript wird ausgeführt: {script_name}\n")
                log.flush()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                start_new_session=True,
            )
            with RUNNING_PROCESSES_LOCK:
                RUNNING_PROCESSES[job_id] = proc
            with db() as con:
                con.execute("UPDATE jobs SET status='running', pid=?, started_at=? WHERE id=?", (proc.pid, started_time, job_id))
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
            exit_code = proc.wait()
            if exit_code == 0:
                status = "success"
            elif exit_code < 0:
                status = "stopped"
                error_message = f"Prozess wurde durch Signal {-exit_code} beendet."
            else:
                status = "error"
                error_message = f"{'Benutzerskript' if job_type == 'script' else 'debmirror'} wurde mit Exit-Code {exit_code} beendet."
        except FileNotFoundError:
            exit_code = 127
            status = "error"
            error_message = "Befehl wurde im Container nicht gefunden."
            log.write(f"[{now_iso()}] FEHLER: {error_message}\n")
        except Exception as exc:  # noqa: BLE001 - log full operational failure
            exit_code = 1
            status = "error"
            error_message = str(exc)
            log.write(f"[{now_iso()}] FEHLER: {error_message}\n")
        finally:
            with RUNNING_PROCESSES_LOCK:
                RUNNING_PROCESSES.pop(job_id, None)
            finished_time = now_iso()
            duration_h = format_duration_between(started_time, finished_time)
            log.write(f"\n[{finished_time}] Ende Status={status} Exit-Code={exit_code} Dauer={duration_h}\n")
            log.flush()
            with db() as con:
                con.execute(
                    "UPDATE jobs SET status=?, finished_at=?, exit_code=?, error_message=? WHERE id=?",
                    (status, finished_time, exit_code, error_message, job_id),
                )
                job_row = con.execute("SELECT mirror_id, mirror_name, job_type, script_name, dry_run, source, log_path FROM jobs WHERE id=?", (job_id,)).fetchone()
            add_event("info" if status == "success" else "warning", f"Job #{job_id} beendet: {status}")
            try:
                if job_row:
                    mark_pending_auto_size_calculation_after_job(job_id, job_type, script_name, row_to_dict(job_row), status, finished_time)
            except Exception as exc:
                add_event("warning", f"Automatische Größenberechnung für Job #{job_id} konnte nicht vorgemerkt werden: {exc}")
            try:
                if job_row:
                    notify_job_finished(job_id, status, exit_code, job_row["mirror_name"], job_row["log_path"], error_message)
            except Exception as exc:
                add_event("warning", f"Benachrichtigung für Job #{job_id} fehlgeschlagen: {exc}")


def stop_job(job_id: int) -> None:
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Job nicht gefunden.")
        if row["status"] == "queued":
            con.execute("UPDATE jobs SET status='stopped', finished_at=?, exit_code=?, error_message=? WHERE id=?", (now_iso(), -15, "Job wurde aus der Warteschlange entfernt.", job_id))
            try:
                with open(row["log_path"], "a", encoding="utf-8", errors="replace") as log:
                    log.write(f"[{now_iso()}] Job wurde aus der Warteschlange entfernt.\n")
            except Exception:
                pass
            return
        con.execute("UPDATE jobs SET status='stopping' WHERE id=?", (job_id,))

    proc: Optional[subprocess.Popen]
    with RUNNING_PROCESSES_LOCK:
        proc = RUNNING_PROCESSES.get(job_id)
    if not proc:
        pid = row["pid"]
        if not pid:
            return
        try:
            os.killpg(int(pid), signal.SIGTERM)
            time.sleep(JOB_STOP_GRACE_SECONDS)
            os.killpg(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=JOB_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass




PROFILE_SCHEDULE_PREFIX = "Profilzeitplan:"


def profile_schedule_name(mirror_name: str) -> str:
    return f"{PROFILE_SCHEDULE_PREFIX} {mirror_name}".strip()


def profile_schedule_values_from_mirror(mirror_id: int, mirror_name: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mode = str(values.get("schedule_mode") or "manual")
    if mode == "manual":
        return None
    schedule_time = str(values.get("schedule_time") or "22:00").strip() or "22:00"
    interval_hours = max(1, int(values.get("interval_hours") or 24))
    if mode == "daily":
        schedule_type = "daily"
        weekdays = "0,1,2,3,4,5,6"
        times = schedule_time
    elif mode == "weekly":
        schedule_type = "weekly"
        weekdays = str(int(values.get("schedule_weekday") or 0))
        times = schedule_time
    elif mode == "interval":
        schedule_type = "interval"
        weekdays = "0,1,2,3,4,5,6"
        times = schedule_time
    else:
        return None
    return {
        "name": profile_schedule_name(mirror_name),
        "job_kind": "mirror",
        "mirror_id": mirror_id,
        "script_name": "",
        "script_selection": "single",
        "script_names": "",
        "enabled": 1,
        "schedule_type": schedule_type,
        "times": times,
        "weekdays": weekdays,
        "interval_hours": interval_hours,
        "dry_run": 0,
        "origin": "profile",
        "updated_at": now_iso(),
    }


def sync_profile_schedule(con: sqlite3.Connection, mirror_id: int, mirror_name: str, values: Dict[str, Any]) -> None:
    schedule_values = profile_schedule_values_from_mirror(mirror_id, mirror_name, values)
    if schedule_values is None:
        con.execute("DELETE FROM job_schedules WHERE origin='profile' AND mirror_id=?", (mirror_id,))
        return
    existing = con.execute("SELECT id, enabled FROM job_schedules WHERE origin='profile' AND mirror_id=? ORDER BY id LIMIT 1", (mirror_id,)).fetchone()
    if existing:
        # Beim Bearbeiten im Profil sollen Zeitwerte aktualisiert werden. Der Aktiv/Inaktiv-Zustand
        # aus der Job-Zeitplanliste bleibt erhalten.
        schedule_values["enabled"] = int(existing["enabled"] or 0)
        con.execute(
            """
            UPDATE job_schedules
            SET name=:name, job_kind=:job_kind, mirror_id=:mirror_id, script_name=:script_name,
                script_selection=:script_selection, script_names=:script_names, enabled=:enabled,
                schedule_type=:schedule_type, times=:times, weekdays=:weekdays,
                interval_hours=:interval_hours, dry_run=:dry_run, origin=:origin, updated_at=:updated_at
            WHERE id=:id
            """,
            {**schedule_values, "id": existing["id"]},
        )
        con.execute("DELETE FROM job_schedules WHERE origin='profile' AND mirror_id=? AND id<>?", (mirror_id, existing["id"]))
    else:
        schedule_values["created_at"] = now_iso()
        con.execute(
            """
            INSERT INTO job_schedules(name, job_kind, mirror_id, script_name, script_selection, script_names,
                                      enabled, schedule_type, times, weekdays, interval_hours, dry_run,
                                      origin, created_at, updated_at)
            VALUES (:name, :job_kind, :mirror_id, :script_name, :script_selection, :script_names,
                    :enabled, :schedule_type, :times, :weekdays, :interval_hours, :dry_run,
                    :origin, :created_at, :updated_at)
            """,
            schedule_values,
        )

def list_job_schedules() -> List[Dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """
            SELECT s.*, m.name AS mirror_name
            FROM job_schedules s
            LEFT JOIN mirrors m ON m.id=s.mirror_id
            ORDER BY s.enabled DESC, s.name COLLATE NOCASE, s.id DESC
            """
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def list_schedules_for_mirror(mirror_id: int) -> List[Dict[str, Any]]:
    with db() as con:
        rows = con.execute("SELECT * FROM job_schedules WHERE mirror_id=? ORDER BY enabled DESC, name COLLATE NOCASE", (mirror_id,)).fetchall()
        return [row_to_dict(r) for r in rows]


def list_relevant_schedules_for_mirror(mirror_id: int) -> List[Dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """
            SELECT * FROM job_schedules
            WHERE job_kind='mirror' AND enabled=1 AND (mirror_id=? OR mirror_id IS NULL)
            ORDER BY mirror_id IS NULL, name COLLATE NOCASE
            """,
            (mirror_id,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def schedule_summary(schedule: Dict[str, Any]) -> str:
    name = str(schedule.get("name") or f"Zeitplan #{schedule.get('id')}").strip()
    stype = str(schedule.get("schedule_type") or "daily")
    times = str(schedule.get("times") or "").strip()
    if stype == "interval":
        suffix = f"alle {schedule.get('interval_hours') or 24}h"
    else:
        suffix = times or "-"
    return f"{name} ({suffix})"


def schedule_display_for_mirror(mirror: Dict[str, Any]) -> str:
    mirror_id = int(mirror.get("id") or 0)
    try:
        schedules = list_relevant_schedules_for_mirror(mirror_id)
    except Exception as exc:
        log_webui_exception(f"schedule_display_for_mirror {mirror_id}", exc)
        schedules = []
    if schedules:
        values = [schedule_summary(s) for s in schedules[:3]]
        if len(schedules) > 3:
            values.append(f"+{len(schedules)-3} weitere")
        return "; ".join(values)
    mode = str(mirror.get("schedule_mode") or "manual")
    if mode == "manual":
        return "kein Zeitplan"
    if mode == "interval":
        return f"Legacy: alle {mirror.get('interval_hours') or 24}h"
    if mode in {"daily", "weekly"}:
        return f"Legacy: {mode} {mirror.get('schedule_time') or ''}".strip()
    return mode




def list_relevant_schedules_for_script(script_name: str) -> List[Dict[str, Any]]:
    script_name = (script_name or "").strip()
    if not script_name:
        return []
    with db() as con:
        rows = con.execute(
            """
            SELECT * FROM job_schedules
            WHERE job_kind='script' AND enabled=1 AND (
                script_selection='all'
                OR (script_selection='single' AND script_name=?)
                OR (script_selection='selected' AND (',' || REPLACE(script_names, ' ', '') || ',') LIKE ?)
            )
            ORDER BY CASE script_selection WHEN 'single' THEN 0 WHEN 'selected' THEN 1 ELSE 2 END, name COLLATE NOCASE
            """,
            (script_name, f"%,{script_name},%"),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def schedule_display_for_script(script_name: str) -> str:
    try:
        schedules = list_relevant_schedules_for_script(script_name)
    except Exception as exc:
        log_webui_exception(f"schedule_display_for_script {script_name}", exc)
        schedules = []
    if schedules:
        values = [schedule_summary(s) for s in schedules[:3]]
        if len(schedules) > 3:
            values.append(f"+{len(schedules)-3} weitere")
        return "; ".join(values)
    return "kein Zeitplan"

def job_source_label(source: str) -> str:
    source = (source or "manual").strip()
    if source.startswith("schedule:"):
        try:
            sid = int(source.split(":", 1)[1])
            schedule = get_schedule(sid)
            if schedule:
                return "Zeitplan: " + str(schedule.get("name") or f"#{sid}")
        except Exception:
            pass
        return "Zeitplan"
    if source == "legacy-scheduler":
        return "Legacy-Zeitplan"
    if source in {"manual", "manual-script"}:
        return "manuell"
    if source.startswith("api"):
        return "API"
    return source


def parse_times_list(value: str) -> List[str]:
    times = []
    for item in re.split(r"[,;\s]+", value or ""):
        item = item.strip()
        if not item:
            continue
        h, m = parse_hhmm(item)
        normalized = f"{h:02d}:{m:02d}"
        if normalized not in times:
            times.append(normalized)
    return times or ["22:00"]


def parse_weekdays_list(values: Iterable[str] | str) -> List[int]:
    raw: List[str]
    if isinstance(values, str):
        raw = [x for x in re.split(r"[,;\s]+", values) if x]
    else:
        raw = [str(x) for x in values]
    days = []
    for item in raw:
        try:
            n = int(item)
        except Exception:
            continue
        if 0 <= n <= 6 and n not in days:
            days.append(n)
    return days or [0, 1, 2, 3, 4, 5, 6]


def schedule_is_due(schedule: Dict[str, Any], now: dt.datetime) -> Tuple[bool, str]:
    if not int(schedule.get("enabled") or 0):
        return False, ""
    stype = schedule.get("schedule_type") or "daily"
    last_key = schedule.get("last_run_key") or ""
    if stype in {"daily", "weekly"}:
        weekdays = parse_weekdays_list(schedule.get("weekdays") or "0,1,2,3,4,5,6")
        if stype == "weekly" and now.weekday() not in weekdays:
            return False, ""
        if stype == "daily" and now.weekday() not in weekdays:
            return False, ""
        for time_value in parse_times_list(schedule.get("times") or "22:00"):
            hour, minute = parse_hhmm(time_value)
            slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            window = dt.timedelta(seconds=max(SCHEDULER_SCAN_SECONDS + 90, 120))
            key = f"{slot.date().isoformat()}T{time_value}"
            if slot <= now < slot + window and key != last_key:
                return True, key
        return False, ""
    if stype == "interval":
        interval = max(1, int(schedule.get("interval_hours") or 24))
        current_key = now.isoformat(timespec="hours")
        if not last_key:
            return True, current_key
        try:
            last = dt.datetime.fromisoformat(last_key)
        except Exception:
            return True, current_key
        if now - last >= dt.timedelta(hours=interval):
            return True, current_key
    return False, ""


def mark_schedule_run(schedule_id: int, run_key: str) -> None:
    with db() as con:
        con.execute("UPDATE job_schedules SET last_run_key=?, updated_at=? WHERE id=?", (run_key, now_iso(), schedule_id))


def targets_for_schedule(schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    mirror_id = schedule.get("mirror_id")
    if mirror_id:
        mirror = get_mirror(int(mirror_id))
        return [mirror] if mirror and int(mirror.get("enabled") or 0) else []
    return [m for m in list_mirrors() if int(m.get("enabled") or 0) == 1]


def split_script_names(value: str) -> List[str]:
    names: List[str] = []
    for item in re.split(r"[,;\n]+", value or ""):
        item = item.strip()
        if item and item not in names:
            names.append(item)
    return names


def script_targets_for_schedule(schedule: Dict[str, Any]) -> List[str]:
    selection = str(schedule.get("script_selection") or "single").strip()
    if selection == "all":
        return [item["name"] for item in list_user_scripts()]
    if selection == "selected":
        return split_script_names(str(schedule.get("script_names") or ""))
    script_name = str(schedule.get("script_name") or "").strip()
    return [script_name] if script_name else []


def script_target_for_schedule(schedule: Dict[str, Any]) -> str:
    targets = script_targets_for_schedule(schedule)
    return targets[0] if targets else ""


def describe_schedule_target(schedule: Dict[str, Any]) -> str:
    if (schedule.get("job_kind") or "mirror") == "script":
        selection = str(schedule.get("script_selection") or "single")
        targets = script_targets_for_schedule(schedule)
        if selection == "all":
            return "Alle Benutzerskripte"
        if selection == "selected":
            return "Ausgewählte Benutzerskripte: " + (", ".join(targets) if targets else "-")
        return "Benutzerskript: " + (targets[0] if targets else "-")
    if schedule.get("mirror_id"):
        return str(schedule.get("mirror_name") or "Mirror-Profil")
    return "Alle aktiven Mirror-Profile"


def cleanup_old_jobs_and_logs() -> Dict[str, int]:
    days = job_retention_days()
    cutoff = local_now() - dt.timedelta(days=days)
    cutoff_s = cutoff.isoformat(sep=" ", timespec="seconds")
    deleted_jobs = 0
    deleted_logs = 0
    with db() as con:
        rows = con.execute(
            "SELECT id, log_path FROM jobs WHERE status NOT IN ('queued','starting','running','stopping') AND COALESCE(finished_at, started_at) < ?",
            (cutoff_s,),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        for r in rows:
            try:
                lp = Path(r["log_path"])
                if lp.exists() and lp.is_file():
                    lp.unlink()
                    deleted_logs += 1
            except Exception:
                pass
        if ids:
            con.executemany("DELETE FROM jobs WHERE id=?", [(i,) for i in ids])
            deleted_jobs = len(ids)
    return {"deleted_jobs": deleted_jobs, "deleted_logs": deleted_logs, "retention_days": days}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def parse_hhmm(value: str) -> Tuple[int, int]:
    try:
        hour_s, min_s = value.split(":", 1)
        hour = int(hour_s)
        minute = int(min_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except Exception:
        pass
    return 22, 0


def last_non_dry_job(mirror_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE mirror_id=? AND dry_run=0 ORDER BY started_at DESC LIMIT 1",
            (mirror_id,),
        ).fetchone()
        return row_to_dict(row) if row else None



def parse_dt_value(value: str) -> Optional[dt.datetime]:
    return parse_datetime_flexible(value)


def queued_or_active_jobs_count() -> int:
    with db() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','starting','running','stopping')").fetchone()
        return int(row["n"] if row else 0)


def last_finished_real_mirror_job_time() -> Optional[dt.datetime]:
    with db() as con:
        row = con.execute(
            """
            SELECT finished_at FROM jobs
            WHERE job_type='mirror' AND dry_run=0 AND finished_at IS NOT NULL AND status NOT IN ('queued','starting','running','stopping')
            ORDER BY finished_at DESC LIMIT 1
            """
        ).fetchone()
    return parse_dt_value(row["finished_at"]) if row else None


def next_time_from_times(now: dt.datetime, times_value: str, weekdays_value: str, days_ahead: int = 8) -> Optional[dt.datetime]:
    weekdays = parse_weekdays_list(weekdays_value or "0,1,2,3,4,5,6")
    best: Optional[dt.datetime] = None
    for offset in range(days_ahead + 1):
        day = now.date() + dt.timedelta(days=offset)
        probe = dt.datetime.combine(day, dt.time.min)
        if probe.weekday() not in weekdays:
            continue
        for time_value in parse_times_list(times_value or "22:00"):
            hour, minute = parse_hhmm(time_value)
            candidate = probe.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                continue
            if best is None or candidate < best:
                best = candidate
    return best


def next_due_for_schedule(schedule: Dict[str, Any], now: dt.datetime) -> Optional[dt.datetime]:
    if not int(schedule.get("enabled") or 0):
        return None
    stype = schedule.get("schedule_type") or "daily"
    if stype in {"daily", "weekly"}:
        weekdays = schedule.get("weekdays") or "0,1,2,3,4,5,6"
        return next_time_from_times(now, schedule.get("times") or "22:00", weekdays)
    if stype == "interval":
        interval = max(1, int(schedule.get("interval_hours") or 24))
        last_key = schedule.get("last_run_key") or ""
        last = parse_dt_value(last_key)
        if not last:
            return now
        return last + dt.timedelta(hours=interval)
    return None


def next_due_for_legacy_profile(mirror: Dict[str, Any], now: dt.datetime) -> Optional[dt.datetime]:
    if not int(mirror.get("enabled") or 0):
        return None
    mode = mirror.get("schedule_mode") or "manual"
    if mode == "manual":
        return None
    if mode in {"daily", "weekly"}:
        weekdays = "0,1,2,3,4,5,6"
        if mode == "weekly":
            weekdays = str(int(mirror.get("schedule_weekday") or 0))
        return next_time_from_times(now, mirror.get("schedule_time") or "22:00", weekdays)
    if mode == "interval":
        interval = max(1, int(mirror.get("interval_hours") or 24))
        last = last_non_dry_job(int(mirror["id"]))
        last_start = parse_dt_value(last.get("started_at") if last else "")
        if not last_start:
            return now
        return last_start + dt.timedelta(hours=interval)
    return None


def next_scheduled_job_time(now: dt.datetime) -> Optional[dt.datetime]:
    candidates: List[dt.datetime] = []
    try:
        for schedule in list_job_schedules():
            nxt = next_due_for_schedule(schedule, now)
            if nxt:
                candidates.append(nxt)
    except Exception as exc:
        log_webui_exception("next_scheduled_job_time flexible", exc)
    try:
        for mirror in list_mirrors():
            nxt = next_due_for_legacy_profile(mirror, now)
            if nxt:
                candidates.append(nxt)
    except Exception as exc:
        log_webui_exception("next_scheduled_job_time legacy", exc)
    return min(candidates) if candidates else None


def size_cache_calculated_after(path_value: str, ts: dt.datetime) -> bool:
    row = _size_cache_row(str(Path(path_value)))
    if not row:
        return False
    calculated = parse_dt_value(row.get("calculated_at") or "")
    return bool(calculated and calculated >= ts)



def pending_auto_size_calculations() -> List[Dict[str, Any]]:
    raw_items = load_settings().get("pending_auto_size_calculations") or []
    if not isinstance(raw_items, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        path_value = _normalized_size_path(str(item.get("path") or ""))
        if not path_value:
            continue
        cleaned = dict(item)
        cleaned["path"] = path_value
        result.append(cleaned)
    return result


def save_pending_auto_size_calculations(items: List[Dict[str, Any]]) -> None:
    settings = load_settings()
    cleaned: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items[-200:]:
        path_value = _normalized_size_path(str(item.get("path") or ""))
        if not path_value:
            continue
        key = f"{item.get('target_type') or 'path'}:{item.get('target_id') or path_value}:{path_value}"
        if key in seen:
            continue
        seen.add(key)
        new_item = dict(item)
        new_item["path"] = path_value
        cleaned.append(new_item)
    settings["pending_auto_size_calculations"] = cleaned
    settings["pending_auto_size_calculations_updated_at"] = now_iso()
    save_settings(settings)


def add_pending_auto_size_calculation(*, target_type: str, target_id: str, target_name: str, path_value: str, job_id: int, finished_at: str, source: str) -> None:
    path_value = _normalized_size_path(path_value)
    if not path_value:
        return
    items = pending_auto_size_calculations()
    # Für dasselbe Ziel reicht der neueste Marker. So kann ein Profil nicht mehrfach
    # unnötig in der automatischen Größenwarteschlange landen.
    dedupe_key = (target_type, str(target_id), path_value)
    items = [item for item in items if (item.get("target_type"), str(item.get("target_id") or ""), item.get("path")) != dedupe_key]
    item = {
        "target_type": target_type,
        "target_id": str(target_id),
        "target_name": target_name,
        "path": path_value,
        "job_id": int(job_id),
        "finished_at": finished_at,
        "source": source,
        "created_at": now_iso(),
    }
    items.append(item)
    save_pending_auto_size_calculations(items)
    old = _size_cache_row(path_value) or {}
    _write_size_cache(
        path_value,
        status="pending",
        exists_flag=1 if Path(path_value).exists() else 0,
        bytes_value=old.get("bytes"),
        error=f"Automatische Größenberechnung nach Zeitplan-Job #{job_id} vorgemerkt; wartet auf Ruhefenster und freie Job-Warteschlange.",
        started_at=old.get("started_at") or "",
        calculated_at=old.get("calculated_at") or "",
    )


def mark_pending_auto_size_calculation_after_job(job_id: int, job_type: str, script_name: str, job_row: Dict[str, Any], status: str, finished_at: str) -> None:
    if status not in {"success", "error"} or not auto_size_recalc_enabled():
        return
    source = str(job_row.get("source") or "")
    if not is_scheduled_job_source(source):
        return
    if job_type == "mirror":
        if int(job_row.get("dry_run") or 0):
            return
        mirror_id = job_row.get("mirror_id")
        if mirror_id is None:
            return
        mirror = get_mirror(int(mirror_id))
        if not mirror:
            return
        path_value = mirror.get("target_path") or ""
        if not path_value:
            return
        add_pending_auto_size_calculation(
            target_type="mirror",
            target_id=str(mirror_id),
            target_name=mirror.get("name") or job_row.get("mirror_name") or f"Mirror {mirror_id}",
            path_value=path_value,
            job_id=job_id,
            finished_at=finished_at,
            source=source,
        )
        add_event("info", f"Automatische Größenberechnung für Mirror '{mirror.get('name')}' vorgemerkt.")
        return
    if job_type == "script" and script_name:
        target_path = get_user_script_target(script_name)
        if not target_path:
            return
        add_pending_auto_size_calculation(
            target_type="script",
            target_id=script_name,
            target_name=script_name,
            path_value=target_path,
            job_id=job_id,
            finished_at=finished_at,
            source=source,
        )
        add_event("info", f"Automatische Größenberechnung für Benutzerskript '{script_name}' vorgemerkt.")


def running_size_calculations_count() -> int:
    with SIZE_CALC_LOCK:
        return len(SIZE_CALC_RUNNING)


def size_calculation_queue_state() -> Dict[str, Any]:
    try:
        with SIZE_CALC_LOCK:
            running_paths = sorted(SIZE_CALC_RUNNING)
        with db() as con:
            queued_rows = [row_to_dict(r) for r in con.execute("SELECT path, status, error, updated_at FROM mirror_size_cache WHERE status='queued' ORDER BY updated_at ASC").fetchall()]
        pending_items = pending_auto_size_calculations()
        return {
            "running_count": len(running_paths),
            "running_paths": running_paths,
            "queued_count": len(queued_rows),
            "queued_items": queued_rows,
            "pending_count": len(pending_items),
            "pending_items": pending_items,
            "total_waiting": len(queued_rows) + len(pending_items),
        }
    except Exception as exc:
        log_webui_exception("size_calculation_queue_state", exc)
        return {"running_count": 0, "running_paths": [], "queued_count": 0, "queued_items": [], "pending_count": 0, "pending_items": [], "total_waiting": 0}

def process_queued_size_calculations() -> None:
    """Startet manuell/kapazitätsbedingt wartende Größenberechnungen nur ohne aktive Jobs."""
    try:
        if queued_or_active_jobs_count() > 0:
            return
        with SIZE_CALC_LOCK:
            free_capacity = max(0, size_calc_max_parallel() - len(SIZE_CALC_RUNNING))
        if free_capacity <= 0:
            return
        with db() as con:
            rows = con.execute(
                "SELECT path FROM mirror_size_cache WHERE status='queued' ORDER BY updated_at ASC LIMIT ?",
                (free_capacity,),
            ).fetchall()
        for row in rows:
            request_size_calculation(row["path"], force=True)
    except Exception as exc:
        log_webui_exception("process_queued_size_calculations", exc)


def auto_size_recalculation_scan() -> None:
    """Startet vorgemerkte Größenberechnungen nach Zeitplan-Jobs.

    Automatik gibt es bewusst nur für Marker, die beim Abschluss eines
    Zeitplan-Jobs gesetzt wurden. Manuelle Jobs lösen keine automatische
    Größenberechnung aus. Es wird nur das konkrete Profil oder Benutzerskript
    berechnet, zu dem der beendete Zeitplan-Job gehört.
    """
    if not auto_size_recalc_enabled():
        return
    try:
        if queued_or_active_jobs_count() > 0:
            return
        now = local_now()
        idle_window = dt.timedelta(minutes=auto_size_idle_minutes())
        next_due = next_scheduled_job_time(now)
        if next_due and next_due <= now + idle_window:
            return
        with SIZE_CALC_LOCK:
            free_capacity = max(0, size_calc_max_parallel() - len(SIZE_CALC_RUNNING))
        if free_capacity <= 0:
            return
        pending = pending_auto_size_calculations()
        if not pending:
            return
        remaining: List[Dict[str, Any]] = []
        started = 0
        skipped_current = 0
        for item in pending:
            path_value = _normalized_size_path(str(item.get("path") or ""))
            if not path_value:
                continue
            finished_at = parse_dt_value(str(item.get("finished_at") or ""))
            if finished_at and size_cache_calculated_after(path_value, finished_at):
                skipped_current += 1
                continue
            if started >= free_capacity:
                remaining.append(item)
                continue
            if request_size_calculation(path_value, force=True, queue_when_blocked=False):
                started += 1
            else:
                remaining.append(item)
        save_pending_auto_size_calculations(remaining)
        if started:
            add_event("info", f"Automatische Größenberechnung gestartet: {started} Ziel(e), Ruhefenster {auto_size_idle_minutes()} Minuten.")
        if skipped_current:
            add_event("info", f"Automatische Größenberechnung übersprungen: {skipped_current} Ziel(e) bereits aktuell.")
    except Exception as exc:
        log_webui_exception("auto_size_recalculation_scan", exc)
        add_event("warning", f"Automatische Größenberechnung konnte nicht geprüft werden: {exc}")

def scheduler_scan() -> None:
    if not SCHEDULER_LOCK.acquire(blocking=False):
        return
    try:
        cleanup_old_jobs_and_logs()
        now = local_now()

        # Neue flexible Zeitplanliste: mehrere Uhrzeiten, globale Zeitpläne und löschbare Einzeleinträge.
        for schedule in list_job_schedules():
            due, run_key = schedule_is_due(schedule, now)
            if not due:
                continue
            started_any = False
            if (schedule.get("job_kind") or "mirror") == "script":
                for script_name in script_targets_for_schedule(schedule):
                    try:
                        safe_user_script_path(script_name)
                        job_id = start_script_job(script_name, source=f"schedule:{schedule['id']}")
                        started_any = True
                        add_event("info", f"Zeitplan '{schedule['name']}' hat Benutzerskript-Job #{job_id} für {script_name} eingereiht.")
                    except Exception as exc:
                        add_event("error", f"Zeitplan '{schedule['name']}' konnte Benutzerskript {script_name or '-'} nicht einreihen: {exc}")
            else:
                for mirror in targets_for_schedule(schedule):
                    if get_running_job_for_mirror(mirror["id"]):
                        continue
                    try:
                        job_id = start_job(mirror["id"], dry_run=bool(int(schedule.get("dry_run") or 0)), source=f"schedule:{schedule['id']}")
                        started_any = True
                        add_event("info", f"Zeitplan '{schedule['name']}' hat Job #{job_id} für {mirror['name']} eingereiht.")
                    except Exception as exc:
                        add_event("error", f"Zeitplan '{schedule['name']}' konnte {mirror['name']} nicht einreihen: {exc}")
            if started_any:
                mark_schedule_run(int(schedule["id"]), run_key)

        # Kompatibilität: alte einfache Profil-Zeitpläne weiter auswerten.
        for mirror in list_mirrors():
            if not mirror.get("enabled"):
                continue
            if get_running_job_for_mirror(mirror["id"]):
                continue

            mode = mirror.get("schedule_mode") or "manual"
            if mode == "manual":
                continue

            due = False
            last = last_non_dry_job(mirror["id"])
            last_start = None
            if last:
                try:
                    last_start = dt.datetime.fromisoformat(last["started_at"])
                except Exception:
                    last_start = None

            if mode in {"daily", "weekly"}:
                hour, minute = parse_hhmm(mirror.get("schedule_time") or "22:00")
                current_slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                within_window = current_slot <= now < current_slot + dt.timedelta(seconds=SCHEDULER_SCAN_SECONDS + 90)
                if mode == "weekly" and int(mirror.get("schedule_weekday") or 0) != now.weekday():
                    within_window = False
                if within_window:
                    if not last_start or last_start.date() != now.date():
                        due = True
            elif mode == "interval":
                interval = max(1, int(mirror.get("interval_hours") or 24))
                if not last_start or now - last_start >= dt.timedelta(hours=interval):
                    due = True

            if due:
                try:
                    job_id = start_job(mirror["id"], dry_run=False, source="legacy-scheduler")
                    add_event("info", f"Profil-Zeitplan hat Job #{job_id} für {mirror['name']} eingereiht.")
                except Exception as exc:
                    add_event("error", f"Profil-Zeitplan konnte {mirror['name']} nicht einreihen: {exc}")
    finally:
        SCHEDULER_LOCK.release()


SCHEDULER_STARTED = False


def scheduler_loop() -> None:
    time.sleep(5)
    while True:
        try:
            scheduler_scan()
            healthcheck_scan()
            process_queued_size_calculations()
            auto_size_recalculation_scan()
        except Exception as exc:
            add_event("error", f"Scheduler-/Healthcheck-Fehler: {exc}")
        time.sleep(SCHEDULER_SCAN_SECONDS)


def start_scheduler_thread() -> None:
    global SCHEDULER_STARTED
    if SCHEDULER_STARTED:
        return
    thread = threading.Thread(target=scheduler_loop, daemon=True, name="debmirror-scheduler")
    thread.start()
    SCHEDULER_STARTED = True


def recover_stale_jobs() -> None:
    try:
        with db() as con:
            con.execute(
                "UPDATE jobs SET status='error', finished_at=?, exit_code=?, error_message=? WHERE status IN ('starting','running','stopping')",
                (now_iso(), 1, "Job war beim Start der Anwendung noch als laufend markiert. Er wurde als abgebrochen markiert."),
            )
    except Exception as exc:
        add_event("warning", f"Konnte alte laufende Jobs nicht bereinigen: {exc}")



# ---------------------------------------------------------------------------
# Appearance / Dark Mode
# ---------------------------------------------------------------------------

def current_appearance() -> str:
    settings = load_settings()
    value = str(settings.get("appearance") or "light").strip().lower()
    if value not in {"light", "dark", "auto"}:
        return "light"
    return value


@app.route("/theme/toggle", methods=["POST"])
@require_admin
def toggle_theme():
    current = current_appearance()
    settings = load_settings()
    settings["appearance"] = "light" if current == "dark" else "dark"
    settings["appearance_updated_at"] = now_iso()
    save_settings(settings)
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------------------
# Runtime dependency checks
# ---------------------------------------------------------------------------

def runtime_dependency_checks() -> List[Dict[str, Any]]:
    """Return status for binaries debmirror needs inside the container."""
    specs = [
        ("debmirror", True, "Hauptprogramm für den Repository-Spiegel"),
        ("gpgv", True, "prüft Release.gpg/InRelease-Signaturen"),
        ("gpg", False, "liest Fingerprints aus Keyrings"),
        ("patch", False, "wird für PDiff/Diff-Modus genutzt"),
        ("ed", False, "wird für PDiff/Diff-Modus genutzt"),
        ("rsync", False, "wird für rsync-Upstreams benötigt"),
        ("dirmngr", False, "wird für Keyserver-Importe über gpg benötigt"),
        ("curl", False, "hilfreich für Diagnose und URL-Tests"),
        ("lftp", False, "wird von eigenen Benutzerskripten oder FTP/SFTP-Workflows genutzt"),
    ]
    result: List[Dict[str, Any]] = []
    for name, required, description in specs:
        path = shutil.which(name)
        result.append({
            "name": name,
            "required": required,
            "description": description,
            "found": bool(path),
            "path": path or "",
        })
    return result


def missing_required_dependencies() -> List[Dict[str, Any]]:
    return [item for item in runtime_dependency_checks() if item["required"] and not item["found"]]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "auth_enabled": auth_enabled(),
        "setup_required": setup_required(),
        "auth_source": (admin_config() or {}).get("source", "nicht eingerichtet"),
        "mirror_base": str(MIRROR_BASE),
        "app_timezone": app_timezone_name(),
        "appearance": current_appearance(),
        "current_user": current_user() if session.get("authenticated") else {},
        "is_admin": is_admin_user(),
    }


@app.route("/")
@require_auth
def dashboard():
    try:
        mirrors = list_mirrors()
    except Exception as exc:
        log_webui_exception("dashboard list_mirrors", exc)
        mirrors = []
        flash(f"Mirror-Profile konnten nicht geladen werden: {exc}", "danger")
    try:
        with db() as con:
            running_jobs = enrich_jobs_duration([row_to_dict(r) for r in con.execute("SELECT * FROM jobs WHERE status IN ('queued','starting','running','stopping') ORDER BY id ASC").fetchall()])
            recent_jobs = enrich_jobs_duration([row_to_dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (dashboard_recent_jobs_limit(),)).fetchall()])
            for _job in recent_jobs:
                _job["source_h"] = job_source_label(_job.get("source") or "")
            events = [row_to_dict(r) for r in con.execute("SELECT * FROM app_events ORDER BY id DESC LIMIT ?", (dashboard_events_limit(),)).fetchall()]
    except Exception as exc:
        log_webui_exception("dashboard jobs/events", exc)
        running_jobs, recent_jobs, events = [], [], []
        flash(f"Jobs/Ereignisse konnten nicht geladen werden: {exc}", "warning")
    for m in mirrors:
        try:
            m["last_job"] = get_last_job(m["id"])
            if m["last_job"]:
                enrich_job_duration(m["last_job"])
                m["last_job"]["source_h"] = job_source_label(m["last_job"].get("source") or "")
            m["schedule_display"] = schedule_display_for_mirror(m)
            m["running_job"] = get_running_job_for_mirror(m["id"])
            if m["running_job"]:
                enrich_job_duration(m["running_job"])
        except Exception as exc:
            log_webui_exception(f"dashboard mirror job state {m.get('name')}", exc)
            m["last_job"] = None
            m["running_job"] = None
            m["schedule_display"] = schedule_display_for_mirror(m) if m.get("id") else "-"
        m["size_info"] = mirror_stats(m)
    storage = disk_usage_info(MIRROR_BASE)
    try:
        healthchecks = list_healthchecks()
    except Exception as exc:
        log_webui_exception("dashboard healthchecks", exc)
        healthchecks = []
    try:
        queue_count_value = queued_jobs_count()
        active_job_value = get_active_job()
        active_jobs_count_value = active_jobs_count()
        size_queue_state_value = size_calculation_queue_state()
    except Exception as exc:
        log_webui_exception("dashboard queue state", exc)
        queue_count_value = 0
        active_job_value = None
        active_jobs_count_value = 0
        size_queue_state_value = {"running_count": 0, "queued_count": 0, "pending_count": 0, "total_waiting": 0, "running_paths": [], "queued_items": [], "pending_items": []}
    try:
        user_scripts = enrich_user_script_runtime_info(list_user_scripts())
    except Exception as exc:
        log_webui_exception("dashboard user scripts", exc)
        user_scripts = []
        flash(f"Benutzerskripte konnten nicht geladen werden: {exc}", "warning")
    return render_template(
        "dashboard.html",
        mirrors=mirrors,
        user_scripts=user_scripts,
        running_jobs=running_jobs,
        recent_jobs=recent_jobs,
        events=events,
        storage=storage,
        storage_guard=mirror_storage_guard_info(),
        healthchecks=healthchecks,
        queue_count=queue_count_value,
        active_job=active_job_value,
        max_parallel_jobs=max_parallel_jobs(),
        active_jobs_count=active_jobs_count_value,
        size_queue_state=size_queue_state_value,
    )


@app.route("/mirrors")
@require_auth
def mirrors_page():
    mirrors = list_mirrors()
    for m in mirrors:
        try:
            m["last_job"] = get_last_job(m["id"])
            if m["last_job"]:
                enrich_job_duration(m["last_job"])
                m["last_job"]["source_h"] = job_source_label(m["last_job"].get("source") or "")
            m["schedule_display"] = schedule_display_for_mirror(m)
            m["running_job"] = get_running_job_for_mirror(m["id"])
            if m["running_job"]:
                enrich_job_duration(m["running_job"])
        except Exception as exc:
            log_webui_exception(f"mirrors_page job state {m.get('name')}", exc)
            m["last_job"] = None
            m["running_job"] = None
            m["schedule_display"] = schedule_display_for_mirror(m) if m.get("id") else "-"
        m["size_info"] = mirror_stats(m)
    storage = disk_usage_info(MIRROR_BASE)
    try:
        queue_count_value = queued_jobs_count()
        active_job_value = get_active_job()
    except Exception as exc:
        log_webui_exception("mirrors_page queue state", exc)
        queue_count_value = 0
        active_job_value = None
    return render_template("mirrors.html", mirrors=mirrors, storage=storage, queue_count=queue_count_value, active_job=active_job_value)


@app.route("/mirrors/new", methods=["GET", "POST"])
@require_admin
def mirror_new():
    if request.method == "POST":
        return save_mirror(None)

    template_key = request.args.get("template", "").strip()
    selected_template = None
    for profile in sample_profiles():
        if profile["key"] == template_key:
            selected_template = profile
            break
    mirror = default_mirror_values(selected_template["values"] if selected_template else None)
    return render_template(
        "mirror_form.html",
        mirror=mirror,
        title="Mirror anlegen",
        keyrings=list_keyring_files(),
        examples=sample_profiles(),
        selected_template=selected_template,
        return_url=url_for("mirrors_page"),
        return_label="Zurück zu Profilen",
    )



DISTRO_GENERATOR = {
    "debian": {
        "label": "Debian",
        "method": "rsync",
        "host": "ftp.de.debian.org",
        "root_path": "debian",
        "security_host": "security.debian.org",
        "security_root": "debian-security",
        "releases": ["bookworm", "trixie", "forky"],
        "components": ["main", "contrib", "non-free", "non-free-firmware"],
        "archs": ["amd64", "arm64", "i386", "riscv64"],
    },
    "ubuntu": {
        "label": "Ubuntu",
        "method": "rsync",
        "host": "archive.ubuntu.com",
        "root_path": "ubuntu",
        "security_host": "security.ubuntu.com",
        "security_root": "ubuntu",
        "releases": ["jammy", "noble", "oracular", "plucky"],
        "components": ["main", "restricted", "universe", "multiverse"],
        "archs": ["amd64", "arm64", "i386"],
    },
}


def get_profile_generator_config() -> Dict[str, Any]:
    settings = load_settings()
    cfg = settings.get("profile_generator_config")
    if isinstance(cfg, dict) and cfg:
        # Sehr einfache Validierung: fehlende Hauptgruppen fallen auf die Standardwerte zurück.
        merged = json.loads(json.dumps(DISTRO_GENERATOR))
        for key, value in cfg.items():
            if isinstance(value, dict):
                merged.setdefault(key, {}).update(value)
        return merged
    return DISTRO_GENERATOR


@app.route("/profile-generator/settings", methods=["GET", "POST"])
@require_admin
def profile_generator_settings():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "reset":
                settings = load_settings()
                settings.pop("profile_generator_config", None)
                save_settings(settings)
                flash("Generator-Konfiguration wurde auf Standard zurückgesetzt.", "success")
                return redirect(url_for("profile_generator_settings"))
            raw = request.form.get("generator_json", "")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Die Generator-Konfiguration muss ein JSON-Objekt sein.")
            for family, spec in data.items():
                if not isinstance(spec, dict):
                    raise ValueError(f"Generator-Gruppe {family} muss ein Objekt sein.")
                for list_key in ("releases", "components", "archs"):
                    if list_key in spec and not isinstance(spec[list_key], list):
                        raise ValueError(f"{family}.{list_key} muss eine Liste sein.")
            save_app_setting_values({"profile_generator_config": data})
            flash("Generator-Konfiguration wurde gespeichert.", "success")
            return redirect(url_for("profile_generator_settings"))
        except Exception as exc:
            flash(str(exc), "danger")
    cfg = get_profile_generator_config()
    return render_template("profile_generator_settings.html", generator_json=json.dumps(cfg, indent=2, ensure_ascii=False))


def generator_build_values(form) -> Dict[str, Any]:
    family = form.get("family", "debian")
    generator = get_profile_generator_config()
    spec = generator.get(family) or generator["debian"]
    release = form.get("release") or spec["releases"][0]
    repo_kind = form.get("repo_kind", "base")
    components = [c for c in form.getlist("components") if c in spec["components"]]
    if not components:
        components = spec["components"][:1]
    # Reihenfolge behalten und Duplikate entfernen, weil Generatorgruppen teilweise dieselben Namen enthalten.
    components = list(dict.fromkeys(components))
    archs = [a for a in form.getlist("archs") if a in spec["archs"]]
    if not archs:
        archs = ["amd64"]
    include_updates = bool_from_form("include_updates")
    include_security = repo_kind == "security" or bool_from_form("include_security")
    name_parts = [spec["label"], release.capitalize()]
    if repo_kind == "security":
        name_parts.append("Security")
    elif include_security:
        name_parts.append("Komplett")
    else:
        name_parts.append("Basis")
    dists = [release]
    if include_updates and repo_kind != "security":
        dists.append(f"{release}-updates")
    if repo_kind == "security":
        dists = [f"{release}-security"]
    elif include_security:
        dists.append(f"{release}-security")
    host = spec["security_host"] if repo_kind == "security" else spec["host"]
    root_path = spec["security_root"] if repo_kind == "security" else spec["root_path"]
    target_suffix = f"{family}-{release}" + ("-security" if repo_kind == "security" else "")
    values = default_mirror_values({
        "name": " ".join(name_parts),
        "enabled": 1,
        "method": spec["method"],
        "host": host,
        "root_path": root_path,
        "target_path": str(MIRROR_BASE / target_suffix),
        "dists": ",".join(dists),
        "sections": ",".join(components),
        "archs": ",".join(archs),
        "source_mode": "nosource",
        "schedule_mode": "manual",
    })
    if family == "ubuntu" and include_security and repo_kind != "security":
        values["extra_options"] = ""
    return values


@app.route("/profile-generator", methods=["GET", "POST"])
@require_admin
def profile_generator():
    if request.method == "POST":
        values = generator_build_values(request.form)
        flash("Profil wurde aus dem Generator vorbereitet. Prüfe die Werte und speichere danach das Profil.", "success")
        return render_template(
            "mirror_form.html",
            mirror=values,
            title="Profil aus Generator speichern",
            keyrings=list_keyring_files(),
            return_url=url_for("profile_generator"),
            return_label="Zurück zum Generator",
        )
    return render_template("profile_generator.html", generator=get_profile_generator_config())


@app.route("/examples")
@require_admin
def examples_page():
    flash("Die alten Basisprofile wurden durch den Profilgenerator ersetzt.", "info")
    return redirect(url_for("profile_generator"))


@app.route("/mirrors/<int:mirror_id>")
@require_auth
def mirror_detail(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("dashboard"))
    command_error = ""
    try:
        cmd = shell_join(build_debmirror_command(mirror, dry_run=False))
        dry_cmd = shell_join(build_debmirror_command(mirror, dry_run=True))
    except ValueError as exc:
        # Die Detailseite darf durch eine ungültige Profil-/Keyring-Konfiguration
        # nicht mit HTTP 500 abbrechen. Für reine Anzeige wird der Befehl ohne
        # harte Keyring-Validierung erzeugt und die eigentliche Warnung sichtbar
        # im Template angezeigt. Beim Job-Start bleibt die Prüfung aktiv.
        command_error = str(exc)
        try:
            cmd = shell_join(build_debmirror_command(mirror, dry_run=False, validate_keyring=False))
            dry_cmd = shell_join(build_debmirror_command(mirror, dry_run=True, validate_keyring=False))
        except Exception as inner_exc:
            command_error = f"{command_error} Zusätzlich konnte der Befehl nicht angezeigt werden: {inner_exc}"
            cmd = "Befehl konnte nicht generiert werden."
            dry_cmd = "Befehl konnte nicht generiert werden."
    with db() as con:
        jobs = enrich_jobs_duration([row_to_dict(r) for r in con.execute("SELECT * FROM jobs WHERE mirror_id=? ORDER BY id DESC LIMIT ?", (mirror_id, min(job_list_limit(), 200))).fetchall()])
    stats = mirror_stats(mirror)
    storage = disk_usage_info(MIRROR_BASE)
    return render_template("mirror_detail.html", mirror=mirror, jobs=jobs, schedules=list_schedules_for_mirror(mirror_id), command=cmd, dry_command=dry_cmd, command_error=command_error, stats=stats, storage=storage)


@app.route("/mirrors/<int:mirror_id>/size/recalculate", methods=["POST"])
@require_admin
def mirror_size_recalculate(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("mirrors_page"))
    try:
        started = request_size_calculation(mirror.get("target_path") or "", force=True)
        if started:
            flash("Größenberechnung wurde im Hintergrund gestartet.", "success")
        else:
            flash("Größenberechnung läuft bereits oder wartet, bis keine Jobs mehr laufen und Kapazität frei ist.", "info")
    except Exception as exc:
        log_webui_exception(f"mirror_size_recalculate mirror_id={mirror_id}", exc)
        flash(f"Größenberechnung konnte nicht gestartet werden: {exc}", "danger")
    return redirect(request.referrer or url_for("mirror_detail", mirror_id=mirror_id))


@app.route("/mirrors/<int:mirror_id>/edit", methods=["GET", "POST"])
@require_admin
def mirror_edit(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        return save_mirror(mirror_id)
    return render_template(
        "mirror_form.html",
        mirror=mirror,
        title="Mirror bearbeiten",
        keyrings=list_keyring_files(),
        return_url=url_for("mirror_detail", mirror_id=mirror_id),
        return_label="Zurück zum Profil",
    )


def save_mirror(mirror_id: Optional[int]):
    try:
        name = request.form.get("name", "").strip()
        if not name:
            raise ValueError("Name darf nicht leer sein.")
        target_path = normalize_target_path(request.form.get("target_path", ""))
        keyring = allowed_keyring_path(request.form.get("keyring", ""))
        values = {
            "name": name,
            "enabled": bool_from_form("enabled"),
            "method": request.form.get("method", "rsync"),
            "host": request.form.get("host", "").strip(),
            "root_path": normalize_root_path(request.form.get("root_path", "")),
            "target_path": target_path,
            "dists": request.form.get("dists", "").strip(),
            "sections": request.form.get("sections", "").strip(),
            "archs": request.form.get("archs", "").strip(),
            "source_mode": request.form.get("source_mode", "nosource"),
            "keyring": keyring,
            "keyring_fingerprint": normalize_fingerprint(request.form.get("keyring_fingerprint", "")),
            "postcleanup": bool_from_form("postcleanup"),
            "diff_mode": request.form.get("diff_mode", "use"),
            "progress": bool_from_form("progress"),
            "verbose": bool_from_form("verbose"),
            "getcontents": bool_from_form("getcontents"),
            "i18n": bool_from_form("i18n"),
            "timeout_seconds": int(request.form["timeout_seconds"]) if request.form.get("timeout_seconds") else None,
            "rsync_extra": request.form.get("rsync_extra", "").strip(),
            "extra_options": request.form.get("extra_options", "").strip(),
            "include_patterns": request.form.get("include_patterns", "").strip(),
            "exclude_patterns": request.form.get("exclude_patterns", "").strip(),
            "schedule_mode": request.form.get("schedule_mode", "manual"),
            "schedule_time": request.form.get("schedule_time", "22:00"),
            "schedule_weekday": int(request.form.get("schedule_weekday", "6")),
            "interval_hours": int(request.form.get("interval_hours", "24") or 24),
            "updated_at": now_iso(),
        }
        for required in ("host", "root_path", "dists", "sections", "archs"):
            if not values[required]:
                raise ValueError(f"{required} darf nicht leer sein.")
        if values["method"] not in {"rsync", "http", "https", "ftp"}:
            raise ValueError("Ungültige Methode.")
        parse_extra_options(values.get("extra_options") or "")
        if values["schedule_mode"] not in {"manual", "daily", "weekly", "interval"}:
            raise ValueError("Ungültiger Zeitplanmodus.")
        parse_hhmm(values["schedule_time"])
        created_new = mirror_id is None
        with db() as con:
            if mirror_id is None:
                values["created_at"] = now_iso()
                columns = ",".join(values.keys())
                placeholders = ",".join(["?"] * len(values))
                cur = con.execute(
                    f"INSERT INTO mirrors({columns}) VALUES ({placeholders})",
                    list(values.values()),
                )
                mirror_id = int(cur.lastrowid)
            else:
                assignments = ",".join([f"{k}=?" for k in values.keys()])
                con.execute(
                    f"UPDATE mirrors SET {assignments} WHERE id=?",
                    list(values.values()) + [mirror_id],
                )
            sync_profile_schedule(con, int(mirror_id), name, values)
        add_event("info", f"Mirror {'angelegt' if created_new else 'aktualisiert'}: {name}")
        flash("Mirror gespeichert.", "success")
        return redirect(url_for("mirror_detail", mirror_id=mirror_id))
    except Exception as exc:
        flash(str(exc), "danger")
        mirror = dict(request.form)
        mirror["enabled"] = bool_from_form("enabled")
        mirror["postcleanup"] = bool_from_form("postcleanup")
        mirror["progress"] = bool_from_form("progress")
        mirror["verbose"] = bool_from_form("verbose")
        mirror["getcontents"] = bool_from_form("getcontents")
        mirror["i18n"] = bool_from_form("i18n")
        mirror["id"] = mirror_id
        title = "Mirror anlegen" if mirror_id is None else "Mirror bearbeiten"
        return_url = url_for("mirrors_page") if mirror_id is None else url_for("mirror_detail", mirror_id=mirror_id)
        return_label = "Zurück zu Profilen" if mirror_id is None else "Zurück zum Profil"
        return render_template(
            "mirror_form.html",
            mirror=mirror,
            title=title,
            keyrings=list_keyring_files(),
            return_url=return_url,
            return_label=return_label,
        ), 400


@app.route("/mirrors/<int:mirror_id>/delete", methods=["POST"])
@require_admin
def mirror_delete(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("dashboard"))
    if get_running_job_for_mirror(mirror_id):
        flash("Mirror kann nicht gelöscht werden, solange ein Job läuft.", "danger")
        return redirect(url_for("mirror_detail", mirror_id=mirror_id))
    with db() as con:
        con.execute("DELETE FROM mirrors WHERE id=?", (mirror_id,))
    add_event("warning", f"Mirror gelöscht: {mirror['name']}")
    flash("Mirror gelöscht.", "success")
    return redirect(url_for("mirrors_page"))


@app.route("/mirrors/<int:mirror_id>/run", methods=["POST"])
@require_admin
def mirror_run(mirror_id: int):
    try:
        dry_run = bool_from_form("dry_run")
        job_id = start_job(mirror_id, dry_run=dry_run, source="manual")
        flash(f"Job #{job_id} wurde in die Warteschlange gestellt.", "success")
        return redirect(url_for("job_detail", job_id=job_id))
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("mirror_detail", mirror_id=mirror_id))



@app.route("/user-scripts", methods=["GET", "POST"])
@require_admin_write
def user_scripts_page():
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "run":
                script_name = request.form.get("script_name", "")
                job_id = start_script_job(script_name, source="manual-script")
                flash(f"Benutzerskript wurde als Job #{job_id} eingereiht.", "success")
                return redirect(url_for("job_detail", job_id=job_id))
            if action == "upload":
                file = request.files.get("script_file")
                if not file or not file.filename:
                    raise ValueError("Keine Skriptdatei ausgewählt.")
                filename = secure_filename(file.filename)
                if not filename:
                    raise ValueError("Ungültiger Dateiname.")
                if not SCRIPT_NAME_RE.match(filename):
                    raise ValueError("Ungültiger Dateiname. Keine Unterverzeichnisse oder Sonderzeichen verwenden.")
                dest = USER_SCRIPT_DIR / filename
                file.save(dest)
                try:
                    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                except Exception:
                    pass
                add_event("info", f"Benutzerskript hochgeladen: {filename}")
                flash("Benutzerskript wurde hochgeladen.", "success")
                return redirect(url_for("user_scripts_page"))
            if action == "save_target":
                script_name = request.form.get("script_name", "")
                target_path = request.form.get("target_path", "")
                # Das Zielverzeichnis beeinflusst den Skriptaufruf nicht. Es dient
                # ausschließlich der Größenberechnung/Anzeige für Skript-Sync-Ziele.
                set_user_script_target(script_name, target_path)
                add_event("info", f"Zielverzeichnis für Benutzerskript gesetzt: {script_name}")
                flash("Zielverzeichnis für die Größenberechnung wurde gespeichert.", "success")
                return redirect(url_for("user_scripts_page"))
            if action == "recalculate_size":
                script_name = request.form.get("script_name", "")
                safe_user_script_path(script_name)
                target_path = get_user_script_target(script_name)
                if not target_path:
                    raise ValueError("Für dieses Benutzerskript ist kein Zielverzeichnis gesetzt.")
                started = request_size_calculation(target_path, force=True)
                if started:
                    flash("Größenberechnung für dieses Benutzerskript-Ziel wurde gestartet.", "success")
                else:
                    flash("Größenberechnung läuft bereits oder wartet, bis keine Jobs mehr laufen und Kapazität frei ist.", "info")
                return redirect(url_for("user_scripts_page"))
            raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("user_scripts.html", scripts=list_user_scripts(), user_script_dir=str(USER_SCRIPT_DIR))


@app.route("/user-scripts/<script_name>/delete", methods=["POST"])
@require_admin
def user_script_delete(script_name: str):
    try:
        path = safe_user_script_path(script_name)
        path.unlink()
        add_event("warning", f"Benutzerskript gelöscht: {script_name}")
        flash("Benutzerskript wurde gelöscht.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("user_scripts_page"))


def normalize_schedule_form_values(schedule_id: Optional[int] = None) -> Dict[str, Any]:
    name = request.form.get("name", "").strip()
    if not name:
        raise ValueError("Name darf nicht leer sein.")

    job_kind = request.form.get("job_kind", "mirror")
    if job_kind not in {"mirror", "script"}:
        raise ValueError("Ungültiger Job-Typ.")

    mirror_raw = request.form.get("mirror_id", "")
    mirror_id = int(mirror_raw) if mirror_raw and job_kind == "mirror" else None

    script_name = ""
    script_selection = "single"
    script_names = ""
    dry_run = bool_from_form("dry_run") if job_kind == "mirror" else False

    if job_kind == "script":
        script_selection = request.form.get("script_selection", "single")
        if script_selection not in {"all", "single", "selected"}:
            raise ValueError("Ungültige Benutzerskript-Auswahl.")
        if script_selection == "single":
            script_name = request.form.get("script_name", "").strip()
            safe_user_script_path(script_name)
        elif script_selection == "selected":
            selected = request.form.getlist("script_names")
            selected = [item.strip() for item in selected if item.strip()]
            if not selected:
                raise ValueError("Bitte mindestens ein Benutzerskript auswählen.")
            for item in selected:
                safe_user_script_path(item)
            script_names = ",".join(dict.fromkeys(selected))
        else:
            if not list_user_scripts():
                raise ValueError("Es sind keine Benutzerskripte vorhanden.")
    else:
        # Mirror-Ziel darf leer sein. Leer bedeutet: alle aktiven Mirror-Profile.
        script_selection = "single"

    schedule_type = request.form.get("schedule_type", "daily")
    if schedule_type not in {"daily", "weekly", "interval"}:
        raise ValueError("Ungültiger Zeitplantyp.")
    times = ",".join(parse_times_list(request.form.get("times", "22:00")))
    weekdays = ",".join(str(x) for x in parse_weekdays_list(request.form.getlist("weekdays")))
    interval_hours = max(1, int(request.form.get("interval_hours", "24") or 24))
    enabled = bool_from_form("enabled")

    return {
        "id": schedule_id,
        "name": name,
        "job_kind": job_kind,
        "mirror_id": mirror_id,
        "script_name": script_name,
        "script_selection": script_selection,
        "script_names": script_names,
        "enabled": int(enabled),
        "schedule_type": schedule_type,
        "times": times,
        "weekdays": weekdays,
        "interval_hours": interval_hours,
        "dry_run": int(dry_run),
        "origin": "custom",
        "updated_at": now_iso(),
    }


def get_schedule(schedule_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute(
            """
            SELECT s.*, m.name AS mirror_name
            FROM job_schedules s
            LEFT JOIN mirrors m ON m.id=s.mirror_id
            WHERE s.id=?
            """,
            (schedule_id,),
        ).fetchone()
        return row_to_dict(row) if row else None


@app.route("/schedules", methods=["GET", "POST"])
@require_admin_write
def schedules_page():
    if request.method == "POST":
        try:
            action = request.form.get("action", "create")
            if action == "cleanup_now":
                result = cleanup_old_jobs_and_logs()
                flash(f"Bereinigung abgeschlossen: {result['deleted_jobs']} Jobs und {result['deleted_logs']} Logdateien gelöscht.", "success")
                return redirect(url_for("schedules_page"))
            values = normalize_schedule_form_values()
            values["created_at"] = now_iso()
            with db() as con:
                con.execute(
                    """
                    INSERT INTO job_schedules(name, job_kind, mirror_id, script_name, script_selection, script_names, enabled, schedule_type, times, weekdays, interval_hours, dry_run, origin, created_at, updated_at)
                    VALUES (:name, :job_kind, :mirror_id, :script_name, :script_selection, :script_names, :enabled, :schedule_type, :times, :weekdays, :interval_hours, :dry_run, :origin, :created_at, :updated_at)
                    """,
                    values,
                )
            add_event("info", f"Zeitplan angelegt: {values['name']}")
            flash("Zeitplan wurde angelegt.", "success")
            return redirect(url_for("schedules_page"))
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template(
        "schedules.html",
        schedules=list_job_schedules(),
        edit_schedule=None,
        mirrors=list_mirrors(),
        user_scripts=list_user_scripts(),
        max_parallel_jobs=max_parallel_jobs(),
        job_retention_days=job_retention_days(),
        job_list_limit=job_list_limit(),
    )


@app.route("/schedules/<int:schedule_id>/edit", methods=["GET", "POST"])
@require_admin
def schedule_edit(schedule_id: int):
    schedule = get_schedule(schedule_id)
    if not schedule:
        flash("Zeitplan nicht gefunden.", "danger")
        return redirect(url_for("schedules_page"))
    if request.method == "POST":
        try:
            values = normalize_schedule_form_values(schedule_id)
            with db() as con:
                con.execute(
                    """
                    UPDATE job_schedules
                    SET name=:name, job_kind=:job_kind, mirror_id=:mirror_id, script_name=:script_name,
                        script_selection=:script_selection, script_names=:script_names, enabled=:enabled,
                        schedule_type=:schedule_type, times=:times, weekdays=:weekdays,
                        interval_hours=:interval_hours, dry_run=:dry_run, updated_at=:updated_at
                    WHERE id=:id
                    """,
                    values,
                )
            add_event("info", f"Zeitplan bearbeitet: {values['name']}")
            flash("Zeitplan wurde aktualisiert.", "success")
            return redirect(url_for("schedules_page"))
        except Exception as exc:
            flash(str(exc), "danger")
            schedule.update({k: v for k, v in request.form.items()})
    return render_template(
        "schedules.html",
        schedules=list_job_schedules(),
        edit_schedule=schedule,
        mirrors=list_mirrors(),
        user_scripts=list_user_scripts(),
        max_parallel_jobs=max_parallel_jobs(),
        job_retention_days=job_retention_days(),
        job_list_limit=job_list_limit(),
    )



@app.route("/schedules/<int:schedule_id>/toggle", methods=["POST"])
@require_admin
def schedule_toggle(schedule_id: int):
    with db() as con:
        row = con.execute("SELECT name, enabled FROM job_schedules WHERE id=?", (schedule_id,)).fetchone()
        if not row:
            flash("Zeitplan nicht gefunden.", "danger")
            return redirect(url_for("schedules_page"))
        new_enabled = 0 if int(row["enabled"] or 0) else 1
        con.execute("UPDATE job_schedules SET enabled=?, updated_at=? WHERE id=?", (new_enabled, now_iso(), schedule_id))
    add_event("info", f"Zeitplan {'aktiviert' if new_enabled else 'deaktiviert'}: {row['name']}")
    flash(f"Zeitplan wurde {'aktiviert' if new_enabled else 'deaktiviert'}.", "success")
    return redirect(request.referrer or url_for("schedules_page"))

@app.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@require_admin
def schedule_delete(schedule_id: int):
    with db() as con:
        row = con.execute("SELECT name, origin, mirror_id FROM job_schedules WHERE id=?", (schedule_id,)).fetchone()
        if not row:
            flash("Zeitplan nicht gefunden.", "danger")
            return redirect(url_for("schedules_page"))
        con.execute("DELETE FROM job_schedules WHERE id=?", (schedule_id,))
        if str(row["origin"] or "custom") == "profile" and row["mirror_id"]:
            con.execute("UPDATE mirrors SET schedule_mode='manual', updated_at=? WHERE id=?", (now_iso(), row["mirror_id"]))
    add_event("warning", f"Zeitplan gelöscht: {row['name']}")
    if str(row["origin"] or "custom") == "profile":
        flash("Profil-Zeitplan wurde gelöscht; das zugehörige Mirror-Profil wurde auf manuell gestellt.", "success")
    else:
        flash("Zeitplan wurde gelöscht.", "success")
    return redirect(url_for("schedules_page"))


@app.route("/jobs")
@require_auth
def jobs():
    with db() as con:
        rows = enrich_jobs_duration([row_to_dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (job_list_limit(),)).fetchall()])
    return render_template("jobs.html", jobs=rows, job_list_limit=job_list_limit(), job_retention_days=job_retention_days(), max_parallel_jobs=max_parallel_jobs(), active_jobs_count=active_jobs_count())


def classify_job_error(log_text: str, exit_code: Optional[int], error_message: str = "") -> Dict[str, Any]:
    text = f"{error_message}\n{log_text}".lower()
    empty = {"type": "", "title": "", "detail": "", "action": "", "missing_keys": [], "matching_keyrings": []}
    if not log_text and not error_message:
        return empty

    # Ein erfolgreicher Job darf keine Fehlerauswertung mehr anzeigen.
    # gpgv schreibt auch bei Erfolg `using RSA key ...`; entscheidend ist
    # `Good signature` zusammen mit Exit-Code 0 / Everything OK / All done.
    if (exit_code == 0 or exit_code is None) and (
        "good signature" in text or "everything ok" in text or "all done" in text
    ) and not any(p in text for p in ("no_pubkey", "can't check signature", "signature does not verify", "errsig")):
        return empty

    missing_keys = extract_missing_pubkeys(log_text)
    matching_keyrings: List[Dict[str, Any]] = []
    for missing_key in missing_keys:
        for match in find_matching_keyrings(missing_key.get("fingerprint") or missing_key.get("key_id") or ""):
            item = dict(match)
            item["expected"] = missing_key.get("fingerprint") or missing_key.get("key_id") or ""
            if not any(existing.get("path") == item.get("path") and existing.get("expected") == item.get("expected") for existing in matching_keyrings):
                matching_keyrings.append(item)

    missing_binary_patterns = [
        "gpgv binary missing", "gpgv failed: gpgv binary missing", "pflichtprogramme fehlen",
        "debmirror wurde im container nicht gefunden", "patch binary missing", "ed binary missing",
    ]
    if any(p in text for p in missing_binary_patterns):
        return {
            "type": "container-tool",
            "title": "Fehlende Programme im Container",
            "detail": "Im Log wurden fehlende Laufzeitprogramme erkannt. Das ist ein Container-/Image-Problem und kein Fehler deiner Mirror-Konfiguration.",
            "action": "Führe ./update.sh --rebuild oder ein Update auf die aktuelle Version aus. Dadurch wird der Container neu gebaut und die benötigten Pakete gpgv, patch und ed werden installiert.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    key_patterns = [
        "no_pubkey", "public key is not available", "can't check signature", "cannot check signature",
        "unknown public key", "signature verification failed", "release signature",
        "the following signatures couldn't be verified", "keine gültige signatur",
        "signature does not verify",
    ]
    if any(p in text for p in key_patterns) or missing_keys:
        key_detail = ""
        if missing_keys:
            key_detail = " Erkannter fehlender Key: " + ", ".join(k.get("fingerprint") or k.get("key_id") for k in missing_keys) + "."
        return {
            "type": "gpg-key",
            "title": "Fehlender oder falscher GPG-Key",
            "detail": "Die Release-Dateien wurden geladen, aber gpgv kann die Signatur nicht prüfen." + key_detail,
            "action": "Importiere den passenden Archiv-Key im Bereich Keyrings oder direkt über die Schaltfläche unten. Danach wird der Keyring automatisch im Mirror-Profil hinterlegt.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    if "no space left on device" in text or "kein speicherplatz" in text:
        return {
            "type": "disk-full",
            "title": "Wahrscheinlich zu wenig Speicherplatz",
            "detail": "Im Log wurden Hinweise auf vollen Datenträger erkannt.",
            "action": "Prüfe den Speicherstatus im Dashboard, lösche nicht mehr benötigte Mirror-Daten oder vergrößere das Volume für /srv/mirror.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    if "rsync error" in text or "connection timed out" in text or "temporary failure" in text or "connection refused" in text:
        return {
            "type": "network",
            "title": "Wahrscheinlich Netzwerk- oder Upstream-Problem",
            "detail": "Im Log wurden Verbindungsfehler erkannt.",
            "action": "Prüfe Host, Methode, Root-Pfad, DNS und ob der Upstream per rsync/http erreichbar ist. Wiederhole danach einen Dry-Run.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    if "404 not found" in text or "failed to open release file" in text or ("release file" in text and "not found" in text):
        return {
            "type": "dist",
            "title": "Wahrscheinlich falsche Distribution oder falscher Root-Pfad",
            "detail": "Im Log wurden Hinweise auf fehlende Release-Dateien erkannt.",
            "action": "Prüfe Distributionen wie bookworm, bookworm-updates oder noble-updates sowie Host und Root-Pfad. Security-Repositories liegen häufig auf einem separaten Host/Root.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    if exit_code and exit_code != 0:
        return {
            "type": "generic",
            "title": "Job mit Fehler beendet",
            "detail": error_message or f"debmirror wurde mit Exit-Code {exit_code} beendet.",
            "action": "Prüfe die letzten Logzeilen. Falls der Fehler nicht eindeutig ist, starte zuerst einen Dry-Run mit erhöhter Ausgabe.",
            "missing_keys": missing_keys,
            "matching_keyrings": matching_keyrings,
        }

    return {"type": "", "title": "", "detail": "", "action": "", "missing_keys": missing_keys, "matching_keyrings": matching_keyrings}


def build_job_diagnosis(job: Dict[str, Any]) -> Dict[str, Any]:
    """Build the post-run diagnosis from a larger log tail than the visible live log.

    The visible log box is intentionally small enough for the browser.  Error
    diagnosis may need earlier lines from the same run, especially for GPG
    failures, so we inspect a larger tail here.  This function must never break
    the job page; errors are converted into a generic diagnosis card.
    """
    try:
        log_path = Path(job.get("log_path") or "")
        diagnostic_log = read_log_tail(log_path, max_bytes=2_000_000)
        return classify_job_error(diagnostic_log, job.get("exit_code"), job.get("error_message") or "")
    except Exception as exc:
        log_webui_exception(f"build_job_diagnosis job={job.get('id')}", exc)
        return {
            "type": "generic",
            "title": "Fehlerauswertung nicht vollständig möglich",
            "detail": f"Die automatische Fehlerauswertung konnte nicht vollständig erstellt werden: {exc}",
            "action": "Prüfe das vollständige Log. Die WebUI selbst bleibt nutzbar.",
            "missing_keys": [],
            "matching_keyrings": [],
        }


@app.route("/jobs/<int:job_id>")
@require_auth
def job_detail(job_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            flash("Job nicht gefunden.", "danger")
            return redirect(url_for("jobs"))
        job = enrich_job_duration(row_to_dict(row))
    log_path = Path(job["log_path"])
    log_tail = read_log_tail(log_path, max_bytes=80_000)
    try:
        log_size = log_path.stat().st_size if log_path.exists() else 0
    except Exception:
        log_size = 0
    diagnosis = build_job_diagnosis(job)
    return render_template("job_detail.html", job=job, log_tail=log_tail, log_size=log_size, diagnosis=diagnosis)


@app.route("/jobs/<int:job_id>/diagnosis")
@require_auth
def job_diagnosis_fragment(job_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return "", 404
        job = enrich_job_duration(row_to_dict(row))
    diagnosis = build_job_diagnosis(job)
    return render_template("_job_diagnosis.html", job=job, diagnosis=diagnosis)


@app.route("/jobs/<int:job_id>/stop", methods=["POST"])
@require_admin
def job_stop(job_id: int):
    try:
        stop_job(job_id)
        flash(f"Stop für Job #{job_id} angefordert.", "warning")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/log")
@require_auth
def job_log(job_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return "Job nicht gefunden", 404
        path = Path(row["log_path"])
    return Response(read_log_tail(path, max_bytes=2_000_000), mimetype="text/plain; charset=utf-8")


@app.route("/jobs/<int:job_id>/stream")
@require_auth
def job_stream(job_id: int):
    def generate():
        try:
            position = max(0, int(request.args.get("offset", "0")))
        except Exception:
            position = 0
        last_status = None
        while True:
            with db() as con:
                row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                yield "event: error\ndata: Job nicht gefunden\n\n"
                break
            path = Path(row["log_path"])
            if path.exists():
                try:
                    current_size = path.stat().st_size
                    if position > current_size:
                        position = 0
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(position)
                        chunk = f.read()
                        position = f.tell()
                    if chunk:
                        data = json.dumps({"chunk": chunk, "status": row["status"], "offset": position})
                        yield f"event: log\ndata: {data}\n\n"
                except Exception as exc:
                    data = json.dumps({"chunk": f"\n[Live-Log Fehler: {exc}]\n", "status": row["status"], "offset": position})
                    yield f"event: log\ndata: {data}\n\n"
            if row["status"] != last_status:
                data = json.dumps({"status": row["status"]})
                yield f"event: status\ndata: {data}\n\n"
                last_status = row["status"]
            if row["status"] not in {"queued", "running", "stopping"}:
                time.sleep(1)
                final_row = row_to_dict(row)
                diagnosis_html = ""
                try:
                    diagnosis_html = render_template("_job_diagnosis.html", job=final_row, diagnosis=build_job_diagnosis(final_row))
                    diag_data = json.dumps({"html": diagnosis_html})
                    yield f"event: diagnosis\ndata: {diag_data}\n\n"
                except Exception as exc:
                    log_webui_exception(f"job_stream diagnosis job={job_id}", exc)
                data = json.dumps({
                    "status": row["status"],
                    "finished_at": row["finished_at"] or "",
                    "duration_h": format_job_duration(final_row) or "",
                    "diagnosis_html": diagnosis_html,
                })
                yield f"event: done\ndata: {data}\n\n"
                break
            time.sleep(1)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

def read_log_tail(path: Path, max_bytes: int = 80_000) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            data = f.read()
            return "... Log gekürzt, vollständiges Log über Download/Plain-Text anzeigen ...\n" + data.decode("utf-8", errors="replace")
        return f.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Import bestehender debmirror-Skripte
# ---------------------------------------------------------------------------

def normalize_multiline_shell(script_text: str) -> List[str]:
    lines: List[str] = []
    buf = ""
    for raw in script_text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        lines.append(buf.strip())
        buf = ""
    if buf.strip():
        lines.append(buf.strip())
    return lines


_ASSIGNMENT_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def strip_inline_comment(value: str) -> str:
    """Remove simple unquoted shell comments from assignment values."""
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(value):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_single:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "#" and not in_single and not in_double and (idx == 0 or value[idx - 1].isspace()):
            return value[:idx].rstrip()
    return value.strip()


def parse_shell_assignments(script_text: str) -> Dict[str, str]:
    """Parse simple VAR=value shell assignments used by many debmirror scripts.

    This intentionally does not execute shell code. Command substitutions such as
    DATE=$(date ...) are ignored for import purposes.
    """
    variables: Dict[str, str] = {}
    for line in normalize_multiline_shell(script_text):
        match = _ASSIGNMENT_RE.match(line.strip())
        if not match:
            continue
        name, raw_value = match.group(1), strip_inline_comment(match.group(2).strip())
        if "$(`" in raw_value or raw_value.startswith("$("):
            # Runtime values are not needed for mirror profile import.
            continue
        try:
            parts = shlex_split(raw_value)
            value = parts[0] if parts else ""
        except ValueError:
            value = raw_value.strip().strip('"').strip("'")
        variables[name] = expand_shell_variables(value, variables)
    # One extra pass for values that referenced variables declared later.
    for key, value in list(variables.items()):
        variables[key] = expand_shell_variables(value, variables)
    return variables


def expand_shell_variables(value: str, variables: Dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or ""
        return variables.get(name, match.group(0))

    current = value
    for _ in range(4):
        expanded = _VAR_RE.sub(repl, current)
        if expanded == current:
            break
        current = expanded
    return current


def expand_debmirror_tokens(tokens: List[str], variables: Dict[str, str]) -> List[str]:
    expanded: List[str] = []
    for token in tokens:
        var_match = re.fullmatch(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", token)
        if var_match:
            name = var_match.group(1) or var_match.group(2) or ""
            if name in variables:
                try:
                    expanded.extend(shlex_split(variables[name]))
                except ValueError:
                    expanded.append(variables[name])
            else:
                expanded.append(token)
            continue
        expanded.append(expand_shell_variables(token, variables))
    return expanded


def normalize_import_target(target: str, warnings: List[str]) -> str:
    target = (target or "").strip()
    if not target:
        return str(MIRROR_BASE / "imported")
    path = Path(target)
    base = MIRROR_BASE.resolve(strict=False)
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        if base == resolved or base in resolved.parents:
            return str(resolved)

        for host_base_raw in IMPORT_HOST_MIRROR_PATHS:
            host_base_raw = host_base_raw.strip()
            if not host_base_raw:
                continue
            host_base = Path(host_base_raw).resolve(strict=False)
            if host_base == resolved or host_base in resolved.parents:
                try:
                    rel = resolved.relative_to(host_base)
                except ValueError:
                    continue
                mapped = MIRROR_BASE / rel
                warnings.append(
                    f"Host-Zielpfad {target} wurde anhand IMPORT_HOST_MIRROR_PATHS auf den Containerpfad {mapped} gemappt."
                )
                return str(mapped)

        mapped_name = path.name or "imported"
        mapped = MIRROR_BASE / secure_filename(mapped_name)
        warnings.append(
            f"Zielpfad {target} liegt außerhalb des Container-Mirror-Verzeichnisses. "
            f"Er wurde für die WebUI auf {mapped} gemappt. Passe bei Bedarf MIRROR_PATH oder IMPORT_HOST_MIRROR_PATHS in .env an."
        )
        return str(mapped)
    return str(MIRROR_BASE / target)


def values_from_debmirror_variables(variables: Dict[str, str], warnings: List[str]) -> Optional[Dict[str, Any]]:
    aliases = {
        "target_path": ["DEB_MIRROR_DIR", "MIRROR_DIR", "TARGET_DIR", "DEST_DIR"],
        "host": ["DEB_HOST", "MIRROR_HOST", "HOST"],
        "root_path": ["DEB_ROOT", "MIRROR_ROOT", "ROOT"],
        "dists": ["DEB_DIST", "DEB_DISTS", "DIST", "DISTS"],
        "sections": ["DEB_SECT", "DEB_SECTION", "DEB_SECTIONS", "SECTION", "SECTIONS"],
        "archs": ["DEB_ARCH", "DEB_ARCHS", "ARCH", "ARCHS"],
        "keyring": ["DEB_KEYRING", "KEYRING", "GPG_KEYRING", "MIRROR_KEYRING"],
        "keyring_fingerprint": ["DEB_KEY_FINGERPRINT", "DEB_KEYRING_FINGERPRINT", "GPG_FINGERPRINT", "MIRROR_KEY_FINGERPRINT"],
    }

    def first(names: List[str]) -> str:
        for name in names:
            if variables.get(name):
                return variables[name]
        return ""

    host = first(aliases["host"])
    dists = first(aliases["dists"])
    sections = first(aliases["sections"])
    archs = first(aliases["archs"])
    if not any([host, dists, sections, archs]):
        return None

    values = default_mirror_values({
        "name": "Importierter Mirror",
        "method": "rsync",
        "host": host,
        "root_path": normalize_root_path(first(aliases["root_path"])) or "debian",
        "target_path": normalize_import_target(first(aliases["target_path"]), warnings),
        "dists": dists,
        "sections": sections,
        "archs": archs,
        "source_mode": "nosource",
    })
    keyring_value = first(aliases["keyring"])
    if keyring_value:
        try:
            values["keyring"] = allowed_keyring_path(keyring_value)
        except Exception:
            values["keyring"] = keyring_value
            warnings.append("Keyring aus Shell-Variable erkannt, liegt aber nicht im verwalteten Keyring-Verzeichnis. Bitte beim Import prüfen/ersetzen.")
    fp_value = first(aliases["keyring_fingerprint"])
    if fp_value:
        values["keyring_fingerprint"] = normalize_fingerprint(fp_value)
    opts = variables.get("DEB_OPT") or variables.get("MIRROR_OPT") or variables.get("DEBMIRROR_OPT") or ""
    if opts:
        apply_debmirror_options(["debmirror", values["target_path"]] + shlex_split(opts), values, warnings)
    return values


def apply_debmirror_options(tokens: List[str], values: Dict[str, Any], warnings: List[str]) -> None:
    include_patterns: List[str] = csv_to_list(values.get("include_patterns") or "")
    exclude_patterns: List[str] = csv_to_list(values.get("exclude_patterns") or "")
    positional: List[str] = []
    extra_options: List[str] = shlex_split(values.get("extra_options") or "")

    def option_value(current: str, index: int) -> Tuple[Optional[str], int]:
        if "=" in current:
            return current.split("=", 1)[1], index
        if index + 1 < len(tokens):
            return tokens[index + 1], index + 1
        return None, index

    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in {"&&", ";", "||", "|"}:
            break
        if tok in {"-v", "--verbose"}:
            values["verbose"] = 1
        elif tok in {"-q", "--quiet"}:
            values["verbose"] = 0
            warnings.append("Option -q/--quiet wurde als verbose=aus übernommen.")
        elif tok.startswith("--"):
            opt = tok.split("=", 1)[0]
            val: Optional[str] = None
            takes_value = {
                "--method", "--host", "--root", "--dist", "--dists", "--section", "--sections",
                "--arch", "--archs", "--keyring", "--diff", "--timeout", "--rsync-extra",
                "--include", "--exclude",
            }
            if opt in takes_value:
                val, used_i = option_value(tok, i)
                i = used_i
            if opt == "--method" and val:
                values["method"] = val
            elif opt == "--host" and val:
                values["host"] = val
            elif opt == "--root" and val:
                values["root_path"] = normalize_root_path(val)
            elif opt in {"--dist", "--dists"} and val:
                values["dists"] = val
            elif opt in {"--section", "--sections"} and val:
                values["sections"] = val
            elif opt in {"--arch", "--archs"} and val:
                values["archs"] = val
            elif opt == "--keyring" and val:
                try:
                    values["keyring"] = allowed_keyring_path(val)
                except Exception:
                    values["keyring"] = val
                    warnings.append("Der Keyring-Pfad aus dem Skript liegt nicht im verwalteten Keyring-Verzeichnis und muss nach dem Import geprüft werden.")
            elif opt == "--source":
                values["source_mode"] = "source"
            elif opt == "--nosource":
                values["source_mode"] = "nosource"
            elif opt == "--postcleanup":
                values["postcleanup"] = 1
            elif opt == "--cleanup":
                values["postcleanup"] = 0
            elif opt == "--diff" and val:
                values["diff_mode"] = val
            elif opt == "--progress":
                values["progress"] = 1
            elif opt == "--getcontents":
                values["getcontents"] = 1
            elif opt == "--i18n":
                values["i18n"] = 1
            elif opt == "--timeout" and val:
                values["timeout_seconds"] = val
            elif opt == "--rsync-extra" and val:
                values["rsync_extra"] = val
            elif opt == "--include" and val:
                include_patterns.append(val)
            elif opt == "--exclude" and val:
                exclude_patterns.append(val)
            elif opt in SAFE_EXTRA_FLAGS:
                if opt not in extra_options:
                    extra_options.append(opt)
                if opt in {"--no-check-gpg", "--ignore-release-gpg"}:
                    warnings.append(f"Sicherheitsrelevante Option {opt} wurde übernommen. Prüfe, ob du wirklich ohne Release-GPG-Prüfung spiegeln willst.")
            else:
                if opt not in {"--dry-run"}:
                    warnings.append(f"Option {opt} wurde nicht automatisch übernommen.")
        elif tok.startswith("-"):
            warnings.append(f"Kurzoption {tok} wurde nicht automatisch übernommen.")
        else:
            positional.append(tok)
        i += 1

    if include_patterns:
        values["include_patterns"] = ",".join(include_patterns)
    if exclude_patterns:
        values["exclude_patterns"] = ",".join(exclude_patterns)
    if extra_options:
        values["extra_options"] = " ".join(extra_options)
    if positional:
        values["target_path"] = normalize_import_target(positional[-1], warnings)


def parse_debmirror_script(script_text: str) -> Tuple[Dict[str, Any], List[str], str]:
    warnings: List[str] = []
    command_line = ""
    tokens: List[str] = []
    variables = parse_shell_assignments(script_text)

    for line in normalize_multiline_shell(script_text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "debmirror" not in stripped:
            continue
        try:
            parts = shlex_split(line)
        except ValueError as exc:
            warnings.append(f"Shell-Zeile konnte nicht vollständig geparst werden: {exc}")
            continue
        for idx, token in enumerate(parts):
            candidate = token.strip()
            if "=" not in candidate and (candidate == "debmirror" or candidate.endswith("/debmirror")):
                tokens = expand_debmirror_tokens(parts[idx:], variables)
                command_line = line
                break
        if tokens:
            break

    values = default_mirror_values({
        "name": "Importierter Mirror",
        "host": "",
        "root_path": "",
        "target_path": str(MIRROR_BASE / "imported"),
        "dists": "",
        "sections": "",
        "archs": "",
    })

    if tokens:
        apply_debmirror_options(tokens, values, warnings)
    else:
        fallback = values_from_debmirror_variables(variables, warnings)
        if fallback:
            values = fallback
            command_line = "Aus Shell-Variablen rekonstruiert"
        else:
            raise ValueError(
                "Es wurde kein direkt aufrufbarer debmirror-Befehl und kein unterstützter DEB_*-Variablenblock gefunden. "
                "Unterstützt werden direkte debmirror-Befehle und einfache Variablen-Skripte wie DEB_HOST/DEB_ROOT/DEB_DIST/DEB_SECT/DEB_ARCH/DEB_OPT. Komplexe Skripte mit Arrays bitte zuerst auf den finalen debmirror-Befehl reduzieren."
            )

    if variables:
        relevant = ", ".join(sorted(k for k in variables if k.startswith(("DEB_", "MIRROR_"))))
        if relevant:
            warnings.insert(0, f"Einfache Shell-Variablen wurden erkannt und aufgelöst: {relevant}")
        if {"DEB_MIRROR_DIR", "DEB_HOST", "DEB_ROOT", "DEB_DIST", "DEB_SECT", "DEB_ARCH"}.issubset(set(variables)):
            warnings.insert(0, "AB-/DEB_*-Skriptstil erkannt: Variablenblock plus run_debmirror()-Funktion wurde ausgewertet.")

    for key in ["method", "host", "root_path", "target_path", "dists", "sections", "archs", "keyring", "extra_options"]:
        if "$" in str(values.get(key) or ""):
            warnings.append(f"Feld {key} enthält noch eine Shell-Variable und muss vor dem Speichern manuell geprüft werden: {values.get(key)}")

    target_name = secure_filename(Path(str(values.get("target_path") or "imported")).name) or "imported"
    name_parts = [target_name]
    if values.get("dists"):
        name_parts.append(str(values["dists"]).split(",", 1)[0])
    values["name"] = f"Import {' '.join(name_parts)}"[:80]
    return values, warnings, command_line


def shlex_split(command: str) -> List[str]:
    import shlex
    return shlex.split(command, posix=True)


def list_import_script_files() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        for p in sorted(IMPORT_SCRIPT_DIR.glob("*")):
            if p.is_file() and p.suffix.lower() in {".sh", ".bash", ".txt", ""}:
                rows.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
    except Exception:
        pass
    return rows


def insert_mirror_values(values: Dict[str, Any]) -> int:
    clean = default_mirror_values(values)
    clean["name"] = str(clean.get("name") or "Importierter Mirror").strip()
    if not clean["name"]:
        raise ValueError("Name darf nicht leer sein.")
    clean["target_path"] = normalize_target_path(str(clean.get("target_path") or ""))
    clean["keyring"] = allowed_keyring_path(str(clean.get("keyring") or "")) if clean.get("keyring") else ""
    clean["keyring_fingerprint"] = normalize_fingerprint(str(clean.get("keyring_fingerprint") or ""))
    clean["root_path"] = normalize_root_path(str(clean.get("root_path") or ""))
    clean["host"] = str(clean.get("host") or "").strip()
    clean["dists"] = str(clean.get("dists") or "").strip()
    clean["sections"] = str(clean.get("sections") or "").strip()
    clean["archs"] = str(clean.get("archs") or "").strip()
    for required in ("host", "root_path", "dists", "sections", "archs"):
        if not clean[required]:
            raise ValueError(f"{required} darf nicht leer sein.")
    if clean["method"] not in {"rsync", "http", "https", "ftp"}:
        raise ValueError("Ungültige Methode.")
    parse_extra_options(clean.get("extra_options") or "")
    clean["created_at"] = now_iso()
    clean["updated_at"] = now_iso()
    with db() as con:
        cur = con.execute(
            """
            INSERT INTO mirrors(name, enabled, method, host, root_path, target_path, dists, sections, archs, source_mode, keyring, keyring_fingerprint,
                                postcleanup, diff_mode, progress, verbose, getcontents, i18n, timeout_seconds, rsync_extra, extra_options,
                                include_patterns, exclude_patterns, schedule_mode, schedule_time, schedule_weekday, interval_hours,
                                created_at, updated_at)
            VALUES (:name, :enabled, :method, :host, :root_path, :target_path, :dists, :sections, :archs, :source_mode, :keyring, :keyring_fingerprint,
                    :postcleanup, :diff_mode, :progress, :verbose, :getcontents, :i18n, :timeout_seconds, :rsync_extra, :extra_options,
                    :include_patterns, :exclude_patterns, :schedule_mode, :schedule_time, :schedule_weekday, :interval_hours,
                    :created_at, :updated_at)
            """,
            clean,
        )
        mirror_id = int(cur.lastrowid)
    add_event("info", f"Mirror aus Skript/Beispiel importiert: {clean['name']}")
    return mirror_id


@app.route("/script-import", methods=["GET", "POST"])
@require_admin
def script_import():
    preview = None
    warnings: List[str] = []
    command_line = ""
    script_text = ""
    if request.method == "POST":
        action = request.form.get("action", "preview")
        try:
            if action == "load_file":
                filename = secure_filename(request.form.get("import_file", ""))
                path = (IMPORT_SCRIPT_DIR / filename).resolve(strict=False)
                base = IMPORT_SCRIPT_DIR.resolve(strict=False)
                if base != path and base not in path.parents:
                    raise ValueError("Ungültiger Skriptpfad.")
                script_text = path.read_text(encoding="utf-8", errors="replace")
                preview, warnings, command_line = parse_debmirror_script(script_text)
            elif action == "preview":
                uploaded = request.files.get("script_file")
                if uploaded and uploaded.filename:
                    script_text = uploaded.read().decode("utf-8", errors="replace")
                else:
                    script_text = request.form.get("script_text", "")
                if not script_text.strip():
                    raise ValueError("Kein Skriptinhalt angegeben.")
                preview, warnings, command_line = parse_debmirror_script(script_text)
            elif action == "create":
                raw = request.form.get("values_json", "")
                values = json.loads(raw)
                # Allow final edits from visible preview fields.
                for key in ["name", "target_path", "host", "root_path", "dists", "sections", "archs", "method", "keyring_fingerprint"]:
                    if key in request.form:
                        values[key] = request.form.get(key, "").strip()

                selected_keyring = request.form.get("keyring", "").strip()
                expected_fp = normalize_fingerprint(request.form.get("keyring_fingerprint", ""))
                keyserver_fp = normalize_fingerprint(request.form.get("keyserver_fingerprint", ""))
                keyserver = request.form.get("keyserver", "hkps://keyserver.ubuntu.com").strip() or "hkps://keyserver.ubuntu.com"
                key_url = request.form.get("key_url", "").strip()
                key_upload = request.files.get("keyfile")

                if key_upload and key_upload.filename:
                    filename = secure_filename(key_upload.filename)
                    if not filename:
                        raise ValueError("Ungültiger Keyring-Dateiname.")
                    dest = APP_KEYRING_DIR / filename
                    key_upload.save(dest)
                    dest = maybe_dearmor_key_file(dest)
                    fps = [normalize_fingerprint(fp) for fp in key_fingerprints(dest)]
                    if expected_fp and not any(fp.endswith(expected_fp) or expected_fp.endswith(fp) or fp == expected_fp for fp in fps):
                        dest.unlink(missing_ok=True)
                        raise ValueError("Fingerprint passt nicht. Key wurde nicht gespeichert.")
                    values["keyring"] = str(dest)
                    values["keyring_fingerprint"] = expected_fp or (fps[0] if fps else "")
                elif key_url:
                    if not key_url.startswith(("https://", "http://")):
                        raise ValueError("Für Key-URLs sind nur http/https erlaubt.")
                    filename = secure_filename(request.form.get("key_filename", "") or Path(key_url).name or default_keyring_filename(expected_fp or "imported"))
                    data = urllib.request.urlopen(key_url, timeout=30).read(16 * 1024 * 1024)
                    dest = APP_KEYRING_DIR / filename
                    dest.write_bytes(data)
                    dest = maybe_dearmor_key_file(dest)
                    fps = [normalize_fingerprint(fp) for fp in key_fingerprints(dest)]
                    if expected_fp and not any(fp.endswith(expected_fp) or expected_fp.endswith(fp) or fp == expected_fp for fp in fps):
                        dest.unlink(missing_ok=True)
                        raise ValueError("Fingerprint passt nicht. Key wurde nicht gespeichert.")
                    values["keyring"] = str(dest)
                    values["keyring_fingerprint"] = expected_fp or (fps[0] if fps else "")
                elif keyserver_fp:
                    dest = import_key_from_keyserver(keyserver_fp, filename=default_keyring_filename(keyserver_fp), keyserver=keyserver)
                    values["keyring"] = str(dest)
                    values["keyring_fingerprint"] = keyserver_fp
                elif selected_keyring:
                    values["keyring"] = allowed_keyring_path(selected_keyring)
                    if expected_fp:
                        values["keyring_fingerprint"] = expected_fp
                    elif not values.get("keyring_fingerprint"):
                        fps = key_fingerprints(Path(values["keyring"]))
                        values["keyring_fingerprint"] = normalize_fingerprint(fps[0]) if fps else ""

                mirror_id = insert_mirror_values(values)
                flash("Mirror-Profil wurde aus dem Skript angelegt.", "success")
                return redirect(url_for("mirror_detail", mirror_id=mirror_id))
            else:
                raise ValueError("Unbekannte Import-Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template(
        "script_import.html",
        preview=preview,
        warnings=warnings,
        command_line=command_line,
        script_text=script_text,
        import_files=list_import_script_files(),
        import_dir=str(IMPORT_SCRIPT_DIR),
        keyrings=list_keyring_files(),
    )


# ---------------------------------------------------------------------------
# Keyrings
# ---------------------------------------------------------------------------

def list_keyring_files() -> List[str]:
    files = []
    for p in APP_KEYRING_DIR.glob("*"):
        if p.is_file() and p.suffix.lower() in {".gpg", ".asc", ".key"}:
            files.append(str(p))
    return sorted(files)


def key_fingerprints(path: Path) -> List[str]:
    try:
        result = subprocess.run(
            ["gpg", "--show-keys", "--with-colons", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
        fps = []
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if parts and parts[0] == "fpr" and len(parts) > 9:
                fps.append(parts[9])
        return fps
    except Exception:
        return []


def fingerprint_matches(candidate: str, expected: str) -> bool:
    candidate_n = normalize_fingerprint(candidate)
    expected_n = normalize_fingerprint(expected)
    if not candidate_n or not expected_n:
        return False
    return candidate_n == expected_n or candidate_n.endswith(expected_n) or expected_n.endswith(candidate_n)


def find_matching_keyrings(expected: str) -> List[Dict[str, Any]]:
    """Find already imported keyrings that contain the expected key id/fingerprint."""
    expected_n = normalize_fingerprint(expected)
    if not expected_n:
        return []
    matches: List[Dict[str, Any]] = []
    for file in list_keyring_files():
        p = Path(file)
        fps = [normalize_fingerprint(fp) for fp in key_fingerprints(p)]
        matched_fps = [fp for fp in fps if fingerprint_matches(fp, expected_n)]
        if matched_fps:
            matches.append({
                "path": str(p),
                "name": p.name,
                "fingerprints": matched_fps,
                "fingerprint": matched_fps[0],
            })
    return matches


@app.route("/keyrings", methods=["GET", "POST"])
@require_admin
def keyrings():
    prefill_fp = normalize_fingerprint(request.args.get("fingerprint", ""))
    assign_mirror_id = request.args.get("mirror_id", "").strip()
    assign_mirror_id_int = int(assign_mirror_id) if assign_mirror_id.isdigit() else None
    if request.method == "POST":
        action = request.form.get("action")
        assign_to = request.form.get("assign_mirror_id", "").strip()
        assign_to_int = int(assign_to) if assign_to.isdigit() else None
        try:
            dest: Optional[Path] = None
            expected = normalize_fingerprint(request.form.get("expected_fingerprint", ""))
            if action == "assign_existing":
                keyring_value = request.form.get("keyring", "").strip()
                if not keyring_value:
                    raise ValueError("Kein vorhandener Keyring ausgewählt.")
                keyring_path = Path(allowed_keyring_path(keyring_value))
                if not keyring_path.exists():
                    raise ValueError("Der ausgewählte Keyring existiert nicht mehr.")
                fps = [normalize_fingerprint(fp) for fp in key_fingerprints(keyring_path)]
                if expected and not any(fingerprint_matches(fp, expected) for fp in fps):
                    raise ValueError("Der ausgewählte Keyring enthält den erwarteten Fingerprint nicht.")
                assign_keyring_to_mirror(assign_to_int, keyring_path, expected or (fps[0] if fps else ""))
                flash("Vorhandener Keyring wurde dem Mirror-Profil zugewiesen.", "success")
                add_event("info", f"Vorhandener Keyring zugewiesen: {keyring_path.name}")
            elif action == "upload":
                file = request.files.get("keyfile")
                if not file or not file.filename:
                    raise ValueError("Keine Key-Datei ausgewählt.")
                filename = secure_filename(file.filename)
                if not filename:
                    raise ValueError("Ungültiger Dateiname.")
                dest = APP_KEYRING_DIR / filename
                file.save(dest)
                dest = maybe_dearmor_key_file(dest)
                fps = [normalize_fingerprint(fp) for fp in key_fingerprints(dest)]
                if expected and not any(fp.endswith(expected) or expected.endswith(fp) or fp == expected for fp in fps):
                    dest.unlink(missing_ok=True)
                    raise ValueError("Fingerprint passt nicht. Key wurde nicht gespeichert.")
                assign_keyring_to_mirror(assign_to_int, dest, expected)
                flash("Keyring-Datei gespeichert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring hochgeladen: {dest.name}")
            elif action == "url":
                url = request.form.get("url", "").strip()
                filename = secure_filename(request.form.get("filename", "") or Path(url).name or default_keyring_filename(expected or "imported"))
                if not url.startswith(("https://", "http://")):
                    raise ValueError("Nur http/https URLs sind erlaubt.")
                if not filename:
                    raise ValueError("Ungültiger Dateiname.")
                data = urllib.request.urlopen(url, timeout=30).read(16 * 1024 * 1024)
                dest = APP_KEYRING_DIR / filename
                dest.write_bytes(data)
                dest = maybe_dearmor_key_file(dest)
                fps = [normalize_fingerprint(fp) for fp in key_fingerprints(dest)]
                if expected and not any(fp.endswith(expected) or expected.endswith(fp) or fp == expected for fp in fps):
                    dest.unlink(missing_ok=True)
                    raise ValueError("Fingerprint passt nicht. Key wurde nicht gespeichert.")
                assign_keyring_to_mirror(assign_to_int, dest, expected)
                flash("Key aus URL importiert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring aus URL importiert: {dest.name}")
            elif action == "keyserver":
                fingerprint = normalize_fingerprint(request.form.get("fingerprint", ""))
                keyserver = request.form.get("keyserver", "hkps://keyserver.ubuntu.com").strip() or "hkps://keyserver.ubuntu.com"
                filename = secure_filename(request.form.get("filename", "") or default_keyring_filename(fingerprint))
                dest = import_key_from_keyserver(fingerprint, filename=filename, keyserver=keyserver)
                assign_keyring_to_mirror(assign_to_int, dest, fingerprint)
                flash("Key vom Keyserver importiert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring vom Keyserver importiert: {dest.name}")
            else:
                raise ValueError("Unbekannte Keyring-Aktion.")
            if assign_to_int:
                return redirect(url_for("mirror_detail", mirror_id=assign_to_int))
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("keyrings", fingerprint=request.form.get("expected_fingerprint") or request.form.get("fingerprint", ""), mirror_id=assign_to or ""))

    rows = []
    for file in list_keyring_files():
        p = Path(file)
        rows.append({"path": str(p), "name": p.name, "size": p.stat().st_size, "fingerprints": key_fingerprints(p)})
    return render_template("keyrings.html", keyrings=rows, prefill_fp=prefill_fp, assign_mirror_id=assign_mirror_id_int)


@app.route("/keyrings/<path:filename>/delete", methods=["POST"])
@require_admin
def keyring_delete(filename: str):
    try:
        path = (APP_KEYRING_DIR / secure_filename(filename)).resolve(strict=False)
        base = APP_KEYRING_DIR.resolve(strict=False)
        if base != path and base not in path.parents:
            raise ValueError("Ungültiger Pfad.")
        path.unlink(missing_ok=True)
        flash("Keyring gelöscht.", "success")
        add_event("warning", f"Keyring gelöscht: {path.name}")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("keyrings"))



# ---------------------------------------------------------------------------
# Users / Mehrbenutzerfähigkeit
# ---------------------------------------------------------------------------

@app.route("/users", methods=["GET", "POST"])
@require_admin
def users_page():
    edit_user = None
    if request.args.get("edit"):
        try:
            uid = int(request.args.get("edit", "0"))
            with db() as con:
                row = con.execute("SELECT id, username, role, enabled FROM users WHERE id=?", (uid,)).fetchone()
                edit_user = row_to_dict(row) if row else None
        except Exception:
            edit_user = None
    if request.method == "POST":
        action = request.form.get("action", "save")
        try:
            if action == "save":
                uid_raw = request.form.get("user_id", "").strip()
                uid = int(uid_raw) if uid_raw else None
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "") or None
                role = request.form.get("role", "user")
                enabled = bool_from_form("enabled")
                if uid is None and not password:
                    raise ValueError("Für neue Benutzer muss ein Passwort gesetzt werden.")
                create_or_update_user(username, password, role=role, enabled=enabled, user_id=uid)
                flash("Benutzer gespeichert.", "success")
                add_event("info", f"Benutzer gespeichert: {username}")
                return redirect(url_for("users_page"))
            if action == "delete":
                uid = int(request.form.get("user_id", "0"))
                user = current_user()
                if int(user.get("id") or 0) == uid:
                    raise ValueError("Der aktuell angemeldete Benutzer kann nicht gelöscht werden.")
                with db() as con:
                    con.execute("DELETE FROM users WHERE id=?", (uid,))
                flash("Benutzer gelöscht.", "success")
                add_event("warning", f"Benutzer-ID gelöscht: {uid}")
                return redirect(url_for("users_page"))
            raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("users.html", users=list_users(), edit_user=edit_user)


# ---------------------------------------------------------------------------
# API tokens and JSON API
# ---------------------------------------------------------------------------

def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_api_token(name: str, created_by: str = "") -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Token-Name darf nicht leer sein.")
    token = "dmm_" + secrets.token_urlsafe(36)
    with db() as con:
        con.execute(
            "INSERT INTO api_tokens(name, token_hash, enabled, created_at, created_by) VALUES (?, ?, 1, ?, ?)",
            (name, token_hash(token), now_iso(), created_by),
        )
    return token


def list_api_tokens() -> List[Dict[str, Any]]:
    with db() as con:
        return [row_to_dict(r) for r in con.execute("SELECT id, name, enabled, created_at, last_used_at, created_by FROM api_tokens ORDER BY id DESC").fetchall()]


def verify_api_request() -> Optional[Dict[str, Any]]:
    header = request.headers.get("Authorization", "")
    token = ""
    if header.lower().startswith("bearer "):
        token = header.split(None, 1)[1].strip()
    token = token or request.headers.get("X-API-Token", "").strip()
    if not token:
        return None
    h = token_hash(token)
    with db() as con:
        row = con.execute("SELECT * FROM api_tokens WHERE token_hash=? AND enabled=1", (h,)).fetchone()
        if row:
            con.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (now_iso(), row["id"]))
            return row_to_dict(row)
    return None


def require_api_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not verify_api_request():
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


@app.route("/api-tokens", methods=["GET", "POST"])
@require_admin
def api_tokens_page():
    new_token = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                new_token = create_api_token(request.form.get("name", ""), created_by=current_user().get("username", ""))
                flash("API-Token wurde erstellt. Kopiere ihn jetzt; er wird später nicht erneut angezeigt.", "success")
            elif action == "delete":
                token_id = int(request.form.get("token_id", "0"))
                with db() as con:
                    con.execute("DELETE FROM api_tokens WHERE id=?", (token_id,))
                flash("API-Token gelöscht.", "success")
            elif action == "toggle":
                token_id = int(request.form.get("token_id", "0"))
                with db() as con:
                    row = con.execute("SELECT enabled FROM api_tokens WHERE id=?", (token_id,)).fetchone()
                    if row:
                        con.execute("UPDATE api_tokens SET enabled=? WHERE id=?", (0 if row["enabled"] else 1, token_id))
                flash("API-Token Status geändert.", "success")
            else:
                raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("api_tokens.html", tokens=list_api_tokens(), new_token=new_token)


@app.route("/api/v1/status")
@require_api_auth
def api_status():
    with db() as con:
        mirrors_n = con.execute("SELECT COUNT(*) AS n FROM mirrors").fetchone()["n"]
        running_n = con.execute("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','starting','running','stopping')").fetchone()["n"]
    return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION, "storage": disk_usage_info(MIRROR_BASE), "storage_guard": mirror_storage_guard_info(), "mirrors": mirrors_n, "running_jobs": running_n, "queued_jobs": queued_jobs_count()})


@app.route("/api/v1/mirrors")
@require_api_auth
def api_mirrors():
    rows = list_mirrors()
    for row in rows:
        row["last_job"] = get_last_job(row["id"])
        row["size_info"] = mirror_stats(row)
    return jsonify({"ok": True, "mirrors": rows})


@app.route("/api/v1/mirrors/<int:mirror_id>")
@require_api_auth
def api_mirror(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        return jsonify({"ok": False, "error": "Mirror not found"}), 404
    mirror["last_job"] = get_last_job(mirror_id)
    mirror["size_info"] = mirror_stats(mirror)
    try:
        mirror["command"] = shell_join(build_debmirror_command(mirror, dry_run=False))
        mirror["command_error"] = ""
    except ValueError as exc:
        mirror["command_error"] = str(exc)
        mirror["command"] = shell_join(build_debmirror_command(mirror, dry_run=False, validate_keyring=False))
    return jsonify({"ok": True, "mirror": mirror})


@app.route("/api/v1/mirrors/<int:mirror_id>/run", methods=["POST"])
@require_api_auth
def api_mirror_run(mirror_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        job_id = start_job(mirror_id, dry_run=bool(payload.get("dry_run")), source="api")
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/v1/jobs")
@require_api_auth
def api_jobs():
    limit = min(500, max(1, int(request.args.get("limit", "100"))))
    with db() as con:
        rows = [row_to_dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    return jsonify({"ok": True, "jobs": rows})


@app.route("/api/v1/jobs/<int:job_id>")
@require_api_auth
def api_job(job_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    job = row_to_dict(row)
    job["log_tail"] = read_log_tail(Path(job["log_path"]), max_bytes=40_000)
    job["diagnosis"] = classify_job_error(job["log_tail"], job.get("exit_code"), job.get("error_message") or "")
    return jsonify({"ok": True, "job": job})


@app.route("/api/v1/jobs/<int:job_id>/stop", methods=["POST"])
@require_api_auth
def api_job_stop(job_id: int):
    try:
        stop_job(job_id)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/v1/user-scripts")
@require_api_auth
def api_user_scripts():
    return jsonify({"ok": True, "scripts": list_user_scripts()})


@app.route("/api/v1/user-scripts/<script_name>/run", methods=["POST"])
@require_api_auth
def api_user_script_run(script_name: str):
    try:
        job_id = start_script_job(script_name, source="api-script")
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400



# ---------------------------------------------------------------------------
# Vollbackup / Restore
# ---------------------------------------------------------------------------

BACKUP_FORMAT = "debmirror-manager-full-backup"


def safe_backup_name(label: str = "") -> str:
    stamp = local_now().strftime("%Y%m%d-%H%M%S")
    suffix = secure_filename(label.strip()) if label and label.strip() else "full"
    return f"debmirror-manager-backup-v{APP_VERSION}-{stamp}-{suffix}.zip"


def sqlite_snapshot(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(DB_PATH, timeout=60)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def add_dir_to_zip(zf: zipfile.ZipFile, source_dir: Path, arc_prefix: str) -> int:
    count = 0
    if not source_dir.exists():
        return count
    for path in source_dir.rglob("*"):
        if path.is_file():
            zf.write(path, f"{arc_prefix}/{path.relative_to(source_dir).as_posix()}")
            count += 1
    return count


def create_full_backup(label: str = "manual") -> Path:
    APP_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = APP_BACKUP_DIR / safe_backup_name(label)
    tmp_db = APP_DATA_DIR / f"backup-db-{secrets.token_hex(6)}.sqlite3"
    sqlite_snapshot(tmp_db)
    manifest = {
        "format": BACKUP_FORMAT,
        "app_version": APP_VERSION,
        "created_at": now_iso(),
        "label": label,
        "includes": ["database", "settings", "config_export", "keyrings", "import_scripts", "user_scripts"],
    }
    try:
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            zf.writestr("config_export.json", json.dumps(build_config_export(), indent=2, ensure_ascii=False) + "\n")
            if SETTINGS_PATH.exists():
                zf.write(SETTINGS_PATH, "settings.json")
            zf.write(tmp_db, "database/debmirror-manager.sqlite3")
            add_dir_to_zip(zf, APP_KEYRING_DIR, "keyrings")
            add_dir_to_zip(zf, IMPORT_SCRIPT_DIR, "import-scripts")
            add_dir_to_zip(zf, USER_SCRIPT_DIR, "user-scripts")
        add_event("info", f"Backup erstellt: {backup_path.name}")
        return backup_path
    finally:
        try:
            tmp_db.unlink()
        except FileNotFoundError:
            pass


def list_full_backups() -> List[Dict[str, Any]]:
    APP_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(APP_BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = path.stat()
        manifest = {}
        try:
            with zipfile.ZipFile(path) as zf:
                if "manifest.json" in zf.namelist():
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8", "replace"))
        except Exception:
            manifest = {}
        items.append({"name": path.name, "size_h": format_bytes(st.st_size), "mtime": dt.datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).isoformat(sep=" "), "manifest": manifest})
    return items


def safe_extract_zip_to_tmp(uploaded_path: Path) -> Path:
    tmp = APP_DATA_DIR / "restore-tmp" / secrets.token_hex(8)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(uploaded_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Unsicherer ZIP-Pfad: {name}")
        zf.extractall(tmp)
    return tmp


def copy_table_rows(src_db: Path, table: str, replace: bool = False) -> int:
    src = sqlite3.connect(src_db)
    src.row_factory = sqlite3.Row
    try:
        src_cols_rows = src.execute(f"PRAGMA table_info({table})").fetchall()
        if not src_cols_rows:
            return 0
        src_cols = [r["name"] for r in src_cols_rows]
        rows = [dict(r) for r in src.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        src.close()
    if not rows:
        return 0
    with db() as con:
        dst_cols = [r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
        cols = [c for c in src_cols if c in dst_cols]
        if not cols:
            return 0
        if replace:
            con.execute(f"DELETE FROM {table}")
        placeholders = ",".join(["?"] * len(cols))
        col_sql = ",".join(cols)
        sql = f"INSERT OR REPLACE INTO {table}({col_sql}) VALUES ({placeholders})"
        count = 0
        for row in rows:
            con.execute(sql, [row.get(c) for c in cols])
            count += 1
        return count


def restore_full_backup_from_path(zip_path: Path, replace: bool = False, include_users: bool = True) -> Dict[str, int]:
    tmp = safe_extract_zip_to_tmp(zip_path)
    result = {"mirrors": 0, "healthchecks": 0, "schedules": 0, "users": 0, "api_tokens": 0, "keyrings": 0, "import_scripts": 0, "user_scripts": 0, "settings": 0}
    try:
        manifest_path = tmp / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("format") != BACKUP_FORMAT:
                raise ValueError("Das ZIP ist kein DebMirror-Manager-Vollbackup.")
        db_snapshot = tmp / "database" / "debmirror-manager.sqlite3"
        if db_snapshot.exists():
            if replace:
                with db() as con:
                    con.execute("DELETE FROM api_tokens")
                    if include_users:
                        con.execute("DELETE FROM users")
                    con.execute("DELETE FROM job_schedules")
                    con.execute("DELETE FROM healthchecks")
                    con.execute("DELETE FROM mirrors")
            result["mirrors"] = copy_table_rows(db_snapshot, "mirrors", replace=False)
            result["healthchecks"] = copy_table_rows(db_snapshot, "healthchecks", replace=False)
            result["schedules"] = copy_table_rows(db_snapshot, "job_schedules", replace=False)
            if include_users:
                result["users"] = copy_table_rows(db_snapshot, "users", replace=False)
                result["api_tokens"] = copy_table_rows(db_snapshot, "api_tokens", replace=False)
        else:
            config_path = tmp / "config_export.json"
            if config_path.exists():
                imported = import_config_data(json.loads(config_path.read_text(encoding="utf-8")), replace_existing=replace)
                result["mirrors"] = imported.get("mirrors", 0)
                result["healthchecks"] = imported.get("healthchecks", 0)
                result["settings"] = imported.get("settings", 0)
        if (tmp / "settings.json").exists():
            shutil.copy2(tmp / "settings.json", SETTINGS_PATH)
            result["settings"] += 1
        for folder, dest, key in [(tmp / "keyrings", APP_KEYRING_DIR, "keyrings"), (tmp / "import-scripts", IMPORT_SCRIPT_DIR, "import_scripts"), (tmp / "user-scripts", USER_SCRIPT_DIR, "user_scripts")]:
            if folder.exists():
                if replace and dest.exists():
                    for pth in dest.iterdir():
                        if pth.is_file() or pth.is_symlink():
                            pth.unlink()
                        elif pth.is_dir():
                            shutil.rmtree(pth)
                dest.mkdir(parents=True, exist_ok=True)
                for src in folder.rglob("*"):
                    if src.is_file():
                        rel = src.relative_to(folder)
                        out = dest / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, out)
                        result[key] += 1
        add_event("warning", f"Backup wiederhergestellt: {zip_path.name}")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.route("/backups", methods=["GET", "POST"])
@require_admin
def backups_page():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                path = create_full_backup(request.form.get("label", "manual"))
                flash(f"Backup erstellt: {path.name}", "success")
            elif action == "restore_upload":
                uploaded = request.files.get("backup_file")
                if not uploaded or not uploaded.filename:
                    raise ValueError("Keine Backup-Datei ausgewählt.")
                tmp_upload = APP_DATA_DIR / f"restore-upload-{secrets.token_hex(6)}.zip"
                uploaded.save(tmp_upload)
                result = restore_full_backup_from_path(tmp_upload, replace=bool_from_form("replace"), include_users=bool_from_form("include_users"))
                tmp_upload.unlink(missing_ok=True)
                flash(f"Restore abgeschlossen: {result}", "success")
            elif action == "restore_existing":
                name = secure_filename(request.form.get("backup_name", ""))
                if not name:
                    raise ValueError("Kein Backup ausgewählt.")
                path = (APP_BACKUP_DIR / name).resolve(strict=False)
                if APP_BACKUP_DIR.resolve(strict=False) not in path.parents or not path.exists():
                    raise ValueError("Backup-Datei nicht gefunden.")
                result = restore_full_backup_from_path(path, replace=bool_from_form("replace"), include_users=bool_from_form("include_users"))
                flash(f"Restore abgeschlossen: {result}", "success")
            elif action == "delete":
                name = secure_filename(request.form.get("backup_name", ""))
                path = (APP_BACKUP_DIR / name).resolve(strict=False)
                if APP_BACKUP_DIR.resolve(strict=False) not in path.parents or not path.exists():
                    raise ValueError("Backup-Datei nicht gefunden.")
                path.unlink()
                flash(f"Backup gelöscht: {name}", "success")
            else:
                raise ValueError("Unbekannte Backup-Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("backups_page"))
    return render_template("backups.html", backups=list_full_backups(), backup_dir=str(APP_BACKUP_DIR))


@app.route("/backups/<path:name>/download")
@require_admin
def backup_download(name: str):
    safe = secure_filename(name)
    path = (APP_BACKUP_DIR / safe).resolve(strict=False)
    if APP_BACKUP_DIR.resolve(strict=False) not in path.parents or not path.exists():
        return "Backup nicht gefunden", 404
    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=path.name)


# ---------------------------------------------------------------------------
# Export / Import der Konfiguration
# ---------------------------------------------------------------------------

EXPORT_MIRROR_COLUMNS = [
    "name", "enabled", "method", "host", "root_path", "target_path", "dists", "sections", "archs", "source_mode", "keyring", "keyring_fingerprint",
    "postcleanup", "diff_mode", "progress", "verbose", "getcontents", "i18n", "timeout_seconds", "rsync_extra", "extra_options",
    "include_patterns", "exclude_patterns", "schedule_mode", "schedule_time", "schedule_weekday", "interval_hours",
]


def build_config_export() -> Dict[str, Any]:
    mirrors = []
    for m in list_mirrors():
        mirrors.append({k: m.get(k) for k in EXPORT_MIRROR_COLUMNS if k in m})
    settings = load_settings()
    safe_settings = {k: v for k, v in settings.items() if k in {"appearance", "max_parallel_jobs", "job_retention_days", "job_list_limit", "size_cache_ttl_seconds", "size_calc_timeout_seconds", "size_calc_max_parallel", "auto_size_recalc_enabled", "auto_size_idle_minutes", "storage_guard_enabled", "storage_guard_threshold_percent", "profile_generator_config", "dashboard_recent_jobs_limit", "dashboard_events_limit", "user_script_targets"}}
    if isinstance(settings.get("notify"), dict):
        notify_export = dict(settings["notify"])
        for field in SECRET_FIELDS:
            notify_export.pop(field, None)
        safe_settings["notify"] = notify_export
    with db() as con:
        healthchecks = [row_to_dict(r) for r in con.execute("SELECT name, url, expected_status, method, timeout_seconds, interval_minutes, enabled FROM healthchecks ORDER BY name").fetchall()]
        schedules = [row_to_dict(r) for r in con.execute("SELECT name, job_kind, mirror_id, script_name, script_selection, script_names, enabled, schedule_type, times, weekdays, interval_hours, dry_run, origin FROM job_schedules ORDER BY name").fetchall()]
    return {"format": "debmirror-manager-config", "format_version": 2, "app_version": APP_VERSION, "exported_at": now_iso(), "mirrors": mirrors, "healthchecks": healthchecks, "schedules": schedules, "settings": safe_settings}


def import_config_data(data: Dict[str, Any], replace_existing: bool = False) -> Dict[str, int]:
    if data.get("format") != "debmirror-manager-config":
        raise ValueError("Ungültiges Konfigurationsformat.")
    imported = {"mirrors": 0, "healthchecks": 0, "schedules": 0, "settings": 0}
    with db() as con:
        for m in data.get("mirrors", []):
            clean = default_mirror_values({k: m.get(k) for k in EXPORT_MIRROR_COLUMNS if k in m})
            clean["target_path"] = normalize_target_path(str(clean.get("target_path") or ""))
            clean["root_path"] = normalize_root_path(str(clean.get("root_path") or ""))
            clean["keyring"] = allowed_keyring_path(str(clean.get("keyring") or "")) if clean.get("keyring") else ""
            clean["keyring_fingerprint"] = normalize_fingerprint(str(clean.get("keyring_fingerprint") or ""))
            clean["updated_at"] = now_iso()
            row = con.execute("SELECT id FROM mirrors WHERE name=?", (clean["name"],)).fetchone()
            if row and replace_existing:
                assignments = ",".join([f"{k}=?" for k in clean.keys() if k != "created_at"])
                vals = [v for k, v in clean.items() if k != "created_at"] + [row["id"]]
                con.execute(f"UPDATE mirrors SET {assignments} WHERE id=?", vals)
                imported["mirrors"] += 1
            elif not row:
                clean["created_at"] = now_iso()
                cols = ",".join(clean.keys())
                placeholders = ",".join(["?"] * len(clean))
                con.execute(f"INSERT INTO mirrors({cols}) VALUES ({placeholders})", list(clean.values()))
                imported["mirrors"] += 1
        for h in data.get("healthchecks", []):
            row = con.execute("SELECT id FROM healthchecks WHERE name=?", (h.get("name"),)).fetchone()
            vals = {
                "name": str(h.get("name") or "").strip(), "url": str(h.get("url") or "").strip(),
                "expected_status": int(h.get("expected_status") or 200), "method": str(h.get("method") or "GET").upper(),
                "timeout_seconds": int(h.get("timeout_seconds") or 10), "interval_minutes": int(h.get("interval_minutes") or 60),
                "enabled": 1 if h.get("enabled", 1) else 0, "updated_at": now_iso(), "created_at": now_iso(),
            }
            if not vals["name"] or not vals["url"]:
                continue
            if row and replace_existing:
                con.execute("UPDATE healthchecks SET url=:url, expected_status=:expected_status, method=:method, timeout_seconds=:timeout_seconds, interval_minutes=:interval_minutes, enabled=:enabled, updated_at=:updated_at WHERE id=:id", {**vals, "id": row["id"]})
                imported["healthchecks"] += 1
            elif not row:
                con.execute("INSERT INTO healthchecks(name, url, expected_status, method, timeout_seconds, interval_minutes, enabled, created_at, updated_at) VALUES (:name, :url, :expected_status, :method, :timeout_seconds, :interval_minutes, :enabled, :created_at, :updated_at)", vals)
                imported["healthchecks"] += 1
        for sched in data.get("schedules", []):
            name = str(sched.get("name") or "").strip()
            if not name:
                continue
            vals = {
                "name": name,
                "job_kind": str(sched.get("job_kind") or "mirror") if str(sched.get("job_kind") or "mirror") in {"mirror", "script"} else "mirror",
                "mirror_id": int(sched["mirror_id"]) if sched.get("mirror_id") and str(sched.get("job_kind") or "mirror") == "mirror" else None,
                "script_name": str(sched.get("script_name") or "").strip(),
                "script_selection": str(sched.get("script_selection") or "single") if str(sched.get("script_selection") or "single") in {"all", "single", "selected"} else "single",
                "script_names": str(sched.get("script_names") or "").strip(),
                "enabled": 1 if sched.get("enabled", 1) else 0,
                "schedule_type": str(sched.get("schedule_type") or "daily"),
                "times": ",".join(parse_times_list(str(sched.get("times") or "22:00"))),
                "weekdays": ",".join(str(x) for x in parse_weekdays_list(str(sched.get("weekdays") or "0,1,2,3,4,5,6"))),
                "interval_hours": max(1, int(sched.get("interval_hours") or 24)),
                "dry_run": 1 if sched.get("dry_run") else 0,
                "origin": str(sched.get("origin") or "custom") if str(sched.get("origin") or "custom") in {"custom", "profile"} else "custom",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            row = con.execute("SELECT id FROM job_schedules WHERE name=?", (name,)).fetchone()
            if row and replace_existing:
                con.execute("UPDATE job_schedules SET job_kind=:job_kind, mirror_id=:mirror_id, script_name=:script_name, script_selection=:script_selection, script_names=:script_names, enabled=:enabled, schedule_type=:schedule_type, times=:times, weekdays=:weekdays, interval_hours=:interval_hours, dry_run=:dry_run, origin=:origin, updated_at=:updated_at WHERE id=:id", {**vals, "id": row["id"]})
                imported["schedules"] += 1
            elif not row:
                con.execute("INSERT INTO job_schedules(name, job_kind, mirror_id, script_name, script_selection, script_names, enabled, schedule_type, times, weekdays, interval_hours, dry_run, origin, created_at, updated_at) VALUES (:name, :job_kind, :mirror_id, :script_name, :script_selection, :script_names, :enabled, :schedule_type, :times, :weekdays, :interval_hours, :dry_run, :origin, :created_at, :updated_at)", vals)
                imported["schedules"] += 1
    safe_settings = data.get("settings") or {}
    if isinstance(safe_settings, dict):
        current = load_settings()
        for key in ("appearance", "notify", "max_parallel_jobs", "job_retention_days", "job_list_limit", "dashboard_recent_jobs_limit", "dashboard_events_limit", "size_cache_ttl_seconds", "size_calc_timeout_seconds", "size_calc_max_parallel", "auto_size_recalc_enabled", "auto_size_idle_minutes", "storage_guard_enabled", "storage_guard_threshold_percent", "profile_generator_config", "user_script_targets"):
            if key in safe_settings:
                current[key] = safe_settings[key]
                imported["settings"] += 1
        save_settings(current)
    return imported


@app.route("/config", methods=["GET", "POST"])
@require_admin
def config_page():
    if request.method == "POST":
        try:
            uploaded = request.files.get("config_file")
            raw = uploaded.read().decode("utf-8", "replace") if uploaded and uploaded.filename else request.form.get("config_json", "")
            if not raw.strip():
                raise ValueError("Keine Konfiguration angegeben.")
            result = import_config_data(json.loads(raw), replace_existing=bool_from_form("replace_existing"))
            flash(f"Import abgeschlossen: {result['mirrors']} Mirror, {result['healthchecks']} Healthchecks, {result.get('schedules', 0)} Zeitpläne, {result['settings']} Einstellungen.", "success")
            add_event("info", "Konfiguration importiert.")
            return redirect(url_for("config_page"))
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("config.html", export_preview=json.dumps(build_config_export(), indent=2, ensure_ascii=False))


@app.route("/config/export")
@require_admin
def config_export_download():
    data = json.dumps(build_config_export(), indent=2, ensure_ascii=False).encode("utf-8")
    bio = io.BytesIO(data)
    bio.seek(0)
    return send_file(bio, mimetype="application/json", as_attachment=True, download_name=f"debmirror-manager-config-v{APP_VERSION}-{local_now().strftime('%Y%m%d-%H%M%S')}.json")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notification_defaults() -> Dict[str, Any]:
    return {
        "enabled": False, "on_success": False, "on_error": True, "on_healthcheck_error": True,
        "smtp_enabled": False, "smtp_host": "", "smtp_port": 587, "smtp_tls": True, "smtp_username": "", "smtp_password": "", "smtp_from": "", "smtp_to": "",
        "telegram_enabled": False, "telegram_bot_token": "", "telegram_chat_id": "",
        "discord_enabled": False, "discord_webhook_url": "",
    }


def raw_notification_settings() -> Dict[str, Any]:
    settings = load_settings().get("notify") or {}
    defaults = notification_defaults()
    defaults.update(settings if isinstance(settings, dict) else {})
    return defaults


def notification_settings() -> Dict[str, Any]:
    cfg = raw_notification_settings()
    for field in SECRET_FIELDS:
        cfg[field] = decrypt_secret(str(cfg.get(field) or ""))
    return cfg


def notification_form_settings() -> Dict[str, Any]:
    raw = raw_notification_settings()
    cfg = notification_settings()
    for field in SECRET_FIELDS:
        cfg[field + "_set"] = bool(str(raw.get(field) or ""))
        cfg[field] = ""
    cfg["encryption_available"] = encryption_available()
    return cfg


def save_notification_settings(form) -> None:
    raw_current = raw_notification_settings()
    notify = notification_defaults()
    notify.update({
        "enabled": bool_from_form("enabled"), "on_success": bool_from_form("on_success"), "on_error": bool_from_form("on_error"), "on_healthcheck_error": bool_from_form("on_healthcheck_error"),
        "smtp_enabled": bool_from_form("smtp_enabled"), "smtp_host": form.get("smtp_host", "").strip(), "smtp_port": int(form.get("smtp_port") or 587), "smtp_tls": bool_from_form("smtp_tls"),
        "smtp_username": form.get("smtp_username", "").strip(), "smtp_from": form.get("smtp_from", "").strip(), "smtp_to": form.get("smtp_to", "").strip(),
        "telegram_enabled": bool_from_form("telegram_enabled"), "telegram_chat_id": form.get("telegram_chat_id", "").strip(),
        "discord_enabled": bool_from_form("discord_enabled"),
    })
    secret_map = {
        "smtp_password": form.get("smtp_password", ""),
        "telegram_bot_token": form.get("telegram_bot_token", ""),
        "discord_webhook_url": form.get("discord_webhook_url", ""),
    }
    for field, new_value in secret_map.items():
        new_value = (new_value or "").strip()
        if new_value:
            notify[field] = encrypt_secret(new_value)
        else:
            notify[field] = raw_current.get(field, "")
    settings = load_settings()
    settings["notify"] = notify
    settings["notify_updated_at"] = now_iso()
    save_settings(settings)


def post_json(url: str, payload: Dict[str, Any], timeout: int = 20) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Webhook HTTP {resp.status}")


def send_notification(subject: str, message: str, kind: str = "info") -> List[str]:
    cfg = notification_settings()
    results: List[str] = []
    if not cfg.get("enabled"):
        return ["Benachrichtigungen sind deaktiviert."]
    if cfg.get("smtp_enabled") and cfg.get("smtp_host") and cfg.get("smtp_to"):
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_username") or "debmirror-manager@localhost"
            msg["To"] = cfg.get("smtp_to")
            msg.set_content(message)
            with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port") or 587), timeout=20) as s:
                if cfg.get("smtp_tls"):
                    s.starttls()
                if cfg.get("smtp_username"):
                    s.login(cfg.get("smtp_username"), cfg.get("smtp_password") or "")
                s.send_message(msg)
            results.append("Mail gesendet")
        except Exception as exc:
            results.append(f"Mail Fehler: {exc}")
    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        try:
            url = f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/sendMessage"
            post_json(url, {"chat_id": cfg["telegram_chat_id"], "text": f"{subject}\n\n{message}"})
            results.append("Telegram gesendet")
        except Exception as exc:
            results.append(f"Telegram Fehler: {exc}")
    if cfg.get("discord_enabled") and cfg.get("discord_webhook_url"):
        try:
            post_json(cfg["discord_webhook_url"], {"content": f"**{subject}**\n{message}"})
            results.append("Discord gesendet")
        except Exception as exc:
            results.append(f"Discord Fehler: {exc}")
    if not results:
        results.append("Kein Benachrichtigungskanal aktiv oder vollständig konfiguriert.")
    for r in results:
        add_event("info" if "gesendet" in r else "warning", f"Benachrichtigung: {r}")
    return results


def notify_job_finished(job_id: int, status: str, exit_code: Optional[int], mirror_name: str, log_path: str, error_message: str = "") -> None:
    cfg = notification_settings()
    if not cfg.get("enabled"):
        return
    if status == "success" and not cfg.get("on_success"):
        return
    if status != "success" and not cfg.get("on_error"):
        return
    log_tail = read_log_tail(Path(log_path), max_bytes=8000)
    diagnosis = classify_job_error(log_tail, exit_code, error_message)
    subject = f"DebMirror Manager: {mirror_name} -> {status}"
    message = f"Job #{job_id}\nMirror: {mirror_name}\nStatus: {status}\nExit-Code: {exit_code}\nZeit: {now_iso()}\n"
    if diagnosis.get("title"):
        message += f"\nFehlerauswertung: {diagnosis['title']}\n{diagnosis['action']}\n"
    message += f"\nLetzte Logzeilen:\n{log_tail[-4000:]}"
    send_notification(subject, message, kind="job")


@app.route("/notifications", methods=["GET", "POST"])
@require_admin
def notifications_page():
    test_results = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "save":
                save_notification_settings(request.form)
                flash("Benachrichtigungseinstellungen gespeichert.", "success")
                return redirect(url_for("notifications_page"))
            if action == "test":
                save_notification_settings(request.form)
                test_results = send_notification("DebMirror Manager Test", f"Testnachricht von {APP_NAME} v{APP_VERSION} um {now_iso()}", kind="test")
                flash("Testbenachrichtigung wurde ausgeführt. Ergebnis siehe unten.", "success")
            else:
                raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("notifications.html", notify=notification_form_settings(), test_results=test_results)


# ---------------------------------------------------------------------------
# Healthchecks für lokale Clients
# ---------------------------------------------------------------------------

def list_healthchecks() -> List[Dict[str, Any]]:
    with db() as con:
        return [row_to_dict(r) for r in con.execute("SELECT * FROM healthchecks ORDER BY name COLLATE NOCASE").fetchall()]


def get_healthcheck(check_id: int) -> Optional[Dict[str, Any]]:
    with db() as con:
        row = con.execute("SELECT * FROM healthchecks WHERE id=?", (check_id,)).fetchone()
        return row_to_dict(row) if row else None


def run_healthcheck_once(check: Dict[str, Any]) -> Dict[str, Any]:
    method = (check.get("method") or "GET").upper()
    if method not in {"GET", "HEAD"}:
        method = "GET"
    start = time.monotonic()
    status_code = None
    ok = False
    err = ""
    try:
        req = urllib.request.Request(check["url"], method=method, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=int(check.get("timeout_seconds") or 10)) as resp:
            status_code = int(resp.status)
            ok = status_code == int(check.get("expected_status") or 200)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        ok = status_code == int(check.get("expected_status") or 200)
        err = "" if ok else str(exc)
    except Exception as exc:
        err = str(exc)
    latency = int((time.monotonic() - start) * 1000)
    state = "ok" if ok else "error"
    with db() as con:
        con.execute(
            "UPDATE healthchecks SET last_check_at=?, last_ok=?, last_status_code=?, last_latency_ms=?, last_error=?, last_notify_state=? WHERE id=?",
            (now_iso(), 1 if ok else 0, status_code, latency, err, state, check["id"]),
        )
    if not ok and notification_settings().get("enabled") and notification_settings().get("on_healthcheck_error"):
        if check.get("last_notify_state") != "error":
            send_notification(f"DebMirror Healthcheck Fehler: {check['name']}", f"URL: {check['url']}\nErwartet: {check.get('expected_status')}\nStatus: {status_code}\nFehler: {err}\nZeit: {now_iso()}", kind="healthcheck")
    return {"ok": ok, "status_code": status_code, "latency_ms": latency, "error": err}


def healthcheck_scan() -> None:
    now = local_now()
    for check in list_healthchecks():
        if not check.get("enabled"):
            continue
        last_at = None
        if check.get("last_check_at"):
            try:
                last_at = dt.datetime.fromisoformat(check["last_check_at"])
            except Exception:
                last_at = None
        interval = max(1, int(check.get("interval_minutes") or 60))
        if not last_at or now - last_at >= dt.timedelta(minutes=interval):
            try:
                run_healthcheck_once(check)
            except Exception as exc:
                add_event("warning", f"Healthcheck Fehler: {check.get('name')}: {exc}")


@app.route("/healthchecks", methods=["GET", "POST"])
@require_admin_write
def healthchecks_page():
    edit_check = None
    if is_admin_user() and request.args.get("edit"):
        try:
            edit_check = get_healthcheck(int(request.args.get("edit", "0")))
        except Exception:
            edit_check = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "save":
                check_id_raw = request.form.get("check_id", "").strip()
                values = {
                    "name": request.form.get("name", "").strip(), "url": request.form.get("url", "").strip(),
                    "expected_status": int(request.form.get("expected_status") or 200), "method": request.form.get("method", "GET").upper(),
                    "timeout_seconds": int(request.form.get("timeout_seconds") or 10), "interval_minutes": int(request.form.get("interval_minutes") or 60),
                    "enabled": bool_from_form("enabled"), "updated_at": now_iso(),
                }
                if not values["name"] or not values["url"]:
                    raise ValueError("Name und URL sind Pflichtfelder.")
                if not values["url"].startswith(("http://", "https://")):
                    raise ValueError("Healthcheck-URL muss mit http:// oder https:// beginnen.")
                with db() as con:
                    if check_id_raw:
                        values["id"] = int(check_id_raw)
                        con.execute("UPDATE healthchecks SET name=:name, url=:url, expected_status=:expected_status, method=:method, timeout_seconds=:timeout_seconds, interval_minutes=:interval_minutes, enabled=:enabled, updated_at=:updated_at WHERE id=:id", values)
                    else:
                        values["created_at"] = now_iso()
                        con.execute("INSERT INTO healthchecks(name, url, expected_status, method, timeout_seconds, interval_minutes, enabled, created_at, updated_at) VALUES (:name, :url, :expected_status, :method, :timeout_seconds, :interval_minutes, :enabled, :created_at, :updated_at)", values)
                flash("Healthcheck gespeichert.", "success")
                return redirect(url_for("healthchecks_page"))
            if action == "delete":
                with db() as con:
                    con.execute("DELETE FROM healthchecks WHERE id=?", (int(request.form.get("check_id", "0")),))
                flash("Healthcheck gelöscht.", "success")
                return redirect(url_for("healthchecks_page"))
            if action == "run":
                check = get_healthcheck(int(request.form.get("check_id", "0")))
                if not check:
                    raise ValueError("Healthcheck nicht gefunden.")
                result = run_healthcheck_once(check)
                flash(f"Healthcheck ausgeführt: {'OK' if result['ok'] else 'Fehler'}", "success" if result["ok"] else "danger")
                return redirect(url_for("healthchecks_page"))
            raise ValueError("Unbekannte Aktion.")
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("healthchecks.html", checks=list_healthchecks(), edit_check=edit_check)


@app.route("/api/v1/schedules")
@require_api_auth
def api_schedules():
    return jsonify({"ok": True, "schedules": list_job_schedules()})


@app.route("/api/v1/healthchecks")
@require_api_auth
def api_healthchecks():
    return jsonify({"ok": True, "healthchecks": list_healthchecks()})


@app.route("/api/v1/healthchecks/<int:check_id>/run", methods=["POST"])
@require_api_auth
def api_healthcheck_run(check_id: int):
    check = get_healthcheck(check_id)
    if not check:
        return jsonify({"ok": False, "error": "Healthcheck not found"}), 404
    return jsonify({"ok": True, "result": run_healthcheck_once(check)})

# ---------------------------------------------------------------------------
# Static content pages
# ---------------------------------------------------------------------------

def render_markdown_light(markdown_text: str) -> str:
    """Small safe Markdown renderer for built-in documentation/release notes.

    It intentionally supports only common documentation elements and escapes all
    text before wrapping it in HTML. This keeps the dependency footprint small.
    """
    out: List[str] = []
    in_code = False
    code_lines: List[str] = []
    in_ul = False
    in_ol = False
    paragraph: List[str] = []

    def inline(text: str) -> str:
        escaped = html.escape(text)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        return escaped

    def close_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + "<br>".join(inline(p) for p in paragraph) + "</p>")
            paragraph = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in markdown_text.splitlines():
        line = raw.rstrip("\n")
        if line.strip().startswith("```"):
            if in_code:
                out.append('<pre class="code doc-code"><code>' + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                close_paragraph(); close_lists(); in_code = True; code_lines = []
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            close_paragraph(); close_lists(); continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            close_paragraph(); close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue
        if line.startswith("- "):
            close_paragraph()
            if not in_ul:
                close_lists(); out.append("<ul>"); in_ul = True
            out.append("<li>" + inline(line[2:].strip()) + "</li>")
            continue
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        if ordered:
            close_paragraph()
            if not in_ol:
                close_lists(); out.append("<ol>"); in_ol = True
            out.append("<li>" + inline(ordered.group(1).strip()) + "</li>")
            continue
        close_lists()
        paragraph.append(line)
    if in_code:
        out.append('<pre class="code doc-code"><code>' + html.escape("\n".join(code_lines)) + "</code></pre>")
    close_paragraph(); close_lists()
    return "\n".join(out)


@app.route("/release-notes")
@require_auth
def release_notes():
    notes_path = Path(__file__).resolve().parents[1] / "RELEASE_NOTES.md"
    content = notes_path.read_text(encoding="utf-8") if notes_path.exists() else BUILTIN_RELEASE_NOTES
    return render_template("markdown_page.html", title="Release Notes", content_html=render_markdown_light(content))


@app.route("/help")
@require_auth
def help_page():
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    content = readme_path.read_text(encoding="utf-8") if readme_path.exists() else BUILTIN_HELP
    return render_template("markdown_page.html", title="Anleitung", content_html=render_markdown_light(content))


BUILTIN_RELEASE_NOTES = "# Release Notes\n\n## v0.1.33\n\n- Fallback-Release-Notes. Normalerweise wird RELEASE_NOTES.md aus dem Projektordner gelesen.\n"

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    init_db()
    ensure_initial_user_from_legacy_config()
    migrate_notification_secret_storage()
    recover_stale_jobs()
    ensure_job_worker_thread()
    start_scheduler_thread()
    return app


create_app()

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)
