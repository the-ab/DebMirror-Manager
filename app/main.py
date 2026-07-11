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
import ipaddress
import json
import os
import re
import secrets
import signal
import shutil
import stat
import smtplib
import sqlite3
import tempfile
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
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
KEY_IMPORT_PREVIEW_DIR = APP_DATA_DIR / "key-import-previews"
MASTER_KEYRING_DIR = APP_KEYRING_DIR / "master"
MASTER_KEYRING_PATH = MASTER_KEYRING_DIR / "debmirror-manager-master.gpg"
PROFILE_KEYRING_DIR = APP_KEYRING_DIR / "profiles"
ARCHIVE_KEYRING_DIR = APP_KEYRING_DIR / "archive"
KEYSERVER_KEYRING_DIR = APP_KEYRING_DIR / "keyserver"
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
NOTIFICATION_SECRET_KEY_PATH = APP_DATA_DIR / "notification-secrets.key"
JOB_AUTH_CONFIG_DIR = Path(os.environ.get("JOB_AUTH_CONFIG_DIR", "/tmp/debmirror-manager-auth"))
SSH_DIR = APP_DATA_DIR / "ssh"
SSH_KEY_DIR = SSH_DIR / "keys"
SSH_KNOWN_HOSTS_PATH = SSH_DIR / "known_hosts"
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
KEY_IMPORT_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
MASTER_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
KEYSERVER_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
APP_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
USER_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
MIRROR_BASE.mkdir(parents=True, exist_ok=True)
JOB_AUTH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SSH_KEY_DIR.mkdir(parents=True, exist_ok=True)
try:
    JOB_AUTH_CONFIG_DIR.chmod(0o700)
except OSError:
    pass
for secure_dir in (SSH_DIR, SSH_KEY_DIR):
    try:
        secure_dir.chmod(0o700)
    except OSError:
        pass
if not SSH_KNOWN_HOSTS_PATH.exists():
    try:
        SSH_KNOWN_HOSTS_PATH.touch(mode=0o600, exist_ok=True)
    except OSError:
        pass
try:
    SSH_KNOWN_HOSTS_PATH.chmod(0o600)
except OSError:
    pass

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
PROFILE_SCAN_JOBS: Dict[str, Dict[str, Any]] = {}
PROFILE_SCAN_JOBS_LOCK = threading.Lock()
PROFILE_SCAN_AUTH_CONTEXT = threading.local()
PROFILE_SCAN_JOB_TTL_SECONDS = 3600
PROFILE_SCAN_JOB_MAX_ENTRIES = 40
NOTIFICATION_SECRET_KEY_LOCK = threading.Lock()


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
                manual_extra_options TEXT DEFAULT '',
                remote_user TEXT DEFAULT '',
                remote_password_enc TEXT DEFAULT '',
                rsync_ssh_enabled INTEGER NOT NULL DEFAULT 0,
                rsync_ssh_user TEXT DEFAULT '',
                rsync_ssh_key TEXT DEFAULT '',
                rsync_ssh_port INTEGER NOT NULL DEFAULT 22,
                rsync_ssh_accept_new_host_key INTEGER NOT NULL DEFAULT 1,
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
        if "manual_extra_options" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN manual_extra_options TEXT DEFAULT ''")
        if "remote_user" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN remote_user TEXT DEFAULT ''")
        if "remote_password_enc" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN remote_password_enc TEXT DEFAULT ''")
        if "rsync_ssh_enabled" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN rsync_ssh_enabled INTEGER NOT NULL DEFAULT 0")
        if "rsync_ssh_user" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN rsync_ssh_user TEXT DEFAULT ''")
        if "rsync_ssh_key" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN rsync_ssh_key TEXT DEFAULT ''")
        if "rsync_ssh_port" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN rsync_ssh_port INTEGER NOT NULL DEFAULT 22")
        if "rsync_ssh_accept_new_host_key" not in columns:
            con.execute("ALTER TABLE mirrors ADD COLUMN rsync_ssh_accept_new_host_key INTEGER NOT NULL DEFAULT 1")

        # v0.1.71 bot irrtümlich Passwortauthentifizierung für rsync-Daemons an.
        # Diese Kombination wird nicht weitergeführt. Vorhandene rsync-Zugangsdaten
        # werden entfernt, damit kein Profil scheinbar mit einer nicht mehr
        # unterstützten Authentifizierungsart weiterläuft.
        legacy_rsync_auth = con.execute(
            "SELECT COUNT(*) AS n FROM mirrors WHERE method='rsync' AND (COALESCE(remote_user,'') <> '' OR COALESCE(remote_password_enc,'') <> '')"
        ).fetchone()
        if legacy_rsync_auth and int(legacy_rsync_auth["n"] or 0) > 0:
            con.execute("UPDATE mirrors SET remote_user='', remote_password_enc='' WHERE method='rsync'")
            con.execute(
                "INSERT INTO app_events(level, message, created_at) VALUES ('warning', ?, ?)",
                ("Veraltete rsync-Benutzer/Passwort-Angaben wurden entfernt. Für geschützte rsync-Quellen bitte SSH-Schlüsselanmeldung konfigurieren.", now_iso()),
            )
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


def default_dashboard_layout() -> Dict[str, Any]:
    return {
        "zones": {
            "summary": {
                "order": ["storage", "queue", "profile-script-summary", "health-summary"],
                "sizes": {},
                "widths": {},
                "heights": {},
            },
            "main": {
                "order": ["mirror-script-list", "recent-jobs", "events", "healthchecks"],
                "sizes": {},
                "widths": {},
                "heights": {},
            },
        }
    }


def sanitize_dashboard_layout(value: Any) -> Dict[str, Any]:
    default = default_dashboard_layout()
    if not isinstance(value, dict):
        return default
    raw_zones = value.get("zones") if isinstance(value.get("zones"), dict) else {}
    cleaned = {"zones": {}}
    allowed_sizes = {"normal", "wide", "full"}
    default_zone_for_block: Dict[str, str] = {}
    for z_name, z_data in default["zones"].items():
        for block_id in z_data.get("order", []):
            default_zone_for_block[block_id] = z_name

    global_seen = set()
    raw_seen = set()
    for zone_name in default["zones"]:
        raw_zone = raw_zones.get(zone_name) if isinstance(raw_zones.get(zone_name), dict) else {}
        raw_order = raw_zone.get("order") if isinstance(raw_zone.get("order"), list) else []
        for item in raw_order:
            ident = str(item or "").strip()
            if ident:
                raw_seen.add(ident)

    for zone_name, default_zone in default["zones"].items():
        raw_zone = raw_zones.get(zone_name) if isinstance(raw_zones.get(zone_name), dict) else {}
        raw_order = raw_zone.get("order") if isinstance(raw_zone.get("order"), list) else []
        order: List[str] = []
        for item in raw_order:
            ident = str(item or "").strip()
            if not ident or ident in global_seen:
                continue
            order.append(ident)
            global_seen.add(ident)

        # Neue oder bisher nicht gespeicherte Standardblöcke in ihrer ursprünglichen Zone ergänzen,
        # aber Blöcke, die bewusst in eine andere Zone gezogen wurden, nicht zurückverschieben.
        for item in default_zone.get("order", []):
            if item not in global_seen and item not in raw_seen and default_zone_for_block.get(item) == zone_name:
                order.append(item)
                global_seen.add(item)

        raw_sizes = raw_zone.get("sizes") if isinstance(raw_zone.get("sizes"), dict) else {}
        sizes: Dict[str, str] = {}
        for key, val in raw_sizes.items():
            block = str(key or "").strip()
            size = str(val or "").strip().lower()
            if block and size in allowed_sizes:
                sizes[block] = size

        raw_widths = raw_zone.get("widths") if isinstance(raw_zone.get("widths"), dict) else {}
        widths: Dict[str, int] = {}
        for key, val in raw_widths.items():
            block = str(key or "").strip()
            if not block:
                continue
            try:
                width = int(val)
            except Exception:
                continue
            if 3 <= width <= 12:
                widths[block] = width

        raw_heights = raw_zone.get("heights") if isinstance(raw_zone.get("heights"), dict) else {}
        heights: Dict[str, int] = {}
        for key, val in raw_heights.items():
            block = str(key or "").strip()
            if not block:
                continue
            try:
                height = int(val)
            except Exception:
                continue
            if 120 <= height <= 1400:
                heights[block] = height

        cleaned["zones"][zone_name] = {"order": order, "sizes": sizes, "widths": widths, "heights": heights}
    return cleaned


def dashboard_layout_settings() -> Dict[str, Any]:
    return sanitize_dashboard_layout(load_settings().get("dashboard_layout"))


def save_dashboard_layout_settings(layout: Any) -> Dict[str, Any]:
    cleaned = sanitize_dashboard_layout(layout)
    settings = load_settings()
    settings["dashboard_layout"] = cleaned
    settings["dashboard_layout_updated_at"] = now_iso()
    save_settings(settings)
    return cleaned


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------

SECRET_FIELDS = {"smtp_password", "telegram_bot_token", "discord_webhook_url"}
LEGACY_SECRET_PREFIX = "enc:v1:"
SECRET_PREFIX = "enc:v2:"


def encryption_available() -> bool:
    return Fernet is not None


def _legacy_fernet_instance() -> Optional[Any]:
    if Fernet is None or not app.secret_key:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(str(app.secret_key).encode("utf-8")).digest())
    return Fernet(key)


def _persistent_fernet_instance(create: bool = False) -> Optional[Any]:
    """Return the persistent notification-secret cipher.

    The key lives in APP_DATA_DIR so it survives container recreation and is
    included in full backups.  It is deliberately separate from APP_SECRET_KEY,
    because APP_SECRET_KEY belongs to the installation's .env and may change
    after a clean reinstall.
    """
    if Fernet is None:
        return None
    try:
        if NOTIFICATION_SECRET_KEY_PATH.exists():
            key = NOTIFICATION_SECRET_KEY_PATH.read_bytes().strip()
            return Fernet(key)
        if not create:
            return None
        with NOTIFICATION_SECRET_KEY_LOCK:
            if NOTIFICATION_SECRET_KEY_PATH.exists():
                key = NOTIFICATION_SECRET_KEY_PATH.read_bytes().strip()
                return Fernet(key)
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            tmp = NOTIFICATION_SECRET_KEY_PATH.with_suffix(".tmp")
            tmp.write_bytes(key + b"\n")
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            tmp.replace(NOTIFICATION_SECRET_KEY_PATH)
            try:
                NOTIFICATION_SECRET_KEY_PATH.chmod(0o600)
            except OSError:
                pass
            return Fernet(key)
    except Exception as exc:
        log_webui_exception("notification secret key", exc)
        return None


def encrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if value.startswith(SECRET_PREFIX):
        return value
    if value.startswith(LEGACY_SECRET_PREFIX):
        plain = decrypt_secret(value)
        if not plain:
            return value
        value = plain
    f = _persistent_fernet_instance(create=True)
    if not f:
        # Do not silently downgrade newly entered credentials to plaintext.
        raise RuntimeError("Geheimwert konnte nicht verschlüsselt werden.")
    return SECRET_PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    if value.startswith(SECRET_PREFIX):
        f = _persistent_fernet_instance(create=False)
        if not f:
            return ""
        token = value[len(SECRET_PREFIX):]
        try:
            return f.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            return ""
    if value.startswith(LEGACY_SECRET_PREFIX):
        f = _legacy_fernet_instance()
        if not f:
            return ""
        token = value[len(LEGACY_SECRET_PREFIX):]
        try:
            return f.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            return ""
    return value


def notification_secret_storage_status() -> Dict[str, Any]:
    raw = load_settings().get("notify") or {}
    unreadable: List[str] = []
    if isinstance(raw, dict):
        for field in SECRET_FIELDS:
            value = str(raw.get(field) or "")
            if value.startswith((SECRET_PREFIX, LEGACY_SECRET_PREFIX)) and not decrypt_secret(value):
                unreadable.append(field)
    unreadable_mirror_passwords: List[str] = []
    try:
        with db() as con:
            rows = con.execute("SELECT id, name, remote_password_enc FROM mirrors WHERE COALESCE(remote_password_enc, '') <> ''").fetchall()
        for row in rows:
            encrypted = str(row["remote_password_enc"] or "")
            if not decrypt_secret(encrypted):
                unreadable_mirror_passwords.append(f"#{row['id']} {row['name']}")
    except sqlite3.OperationalError:
        # During very early startup the migration may not have added the column yet.
        pass
    return {
        "key_present": NOTIFICATION_SECRET_KEY_PATH.exists(),
        "key_path": str(NOTIFICATION_SECRET_KEY_PATH),
        "unreadable_fields": unreadable,
        "unreadable_mirror_passwords": unreadable_mirror_passwords,
        "readable": not unreadable and not unreadable_mirror_passwords,
    }


def migrate_notification_secret_storage() -> None:
    """Migrate notification secrets to a backup-safe persistent data key.

    v1 values were derived from APP_SECRET_KEY and could become unreadable after
    a clean reinstall.  v2 values use notification-secrets.key in APP_DATA_DIR;
    full backups include that key and restore it together with settings.json.
    """
    try:
        settings = load_settings()
        changed = False
        notify = settings.get("notify")
        if isinstance(notify, dict):
            for field in SECRET_FIELDS:
                value = str(notify.get(field) or "")
                if not value or value.startswith(SECRET_PREFIX):
                    continue
                plain = decrypt_secret(value) if value.startswith(LEGACY_SECRET_PREFIX) else value
                if plain:
                    notify[field] = encrypt_secret(plain)
                    changed = True
                elif value.startswith(LEGACY_SECRET_PREFIX):
                    log_webui_exception(
                        "migrate notification secret",
                        RuntimeError(f"Legacy-Geheimwert {field} konnte nicht entschlüsselt werden."),
                    )
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
            settings["notification_secret_storage_version"] = 2
            settings["notification_secret_storage_updated_at"] = now_iso()
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
    if request.method == "POST":
        action = request.form.get("action")
        try:
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


RSYNC_EXTRA_CHOICES = [
    {"value": "doc", "label": "doc", "help": "Dokumentation und README-Dateien im Archiv-Root spiegeln."},
    {"value": "indices", "label": "indices", "help": "Zusätzliche Indexdateien spiegeln; kann viel Speicher benötigen."},
    {"value": "tools", "label": "tools", "help": "Werkzeuge aus dem tools-Verzeichnis spiegeln."},
    {"value": "trace", "label": "trace", "help": "Mirror-Trace-Dateien spiegeln; standardmäßig aktiv."},
    {"value": "none", "label": "none", "help": "Alle Rsync-Extras ausdrücklich deaktivieren."},
]
RSYNC_EXTRA_VALUES = {item["value"] for item in RSYNC_EXTRA_CHOICES}

# Zusätzliche profilbezogene Optionen aus debmirror(1), soweit sie sich sicher
# als einzelnes argv-Element übergeben lassen. Basisoptionen mit eigenen
# Formularfeldern (Host, Root, Suites, Sections, Architekturen, Keyring,
# Include/Exclude, Timeout, Diff, Rsync-Extra usw.) werden hier nicht doppelt
# angeboten. --dry-run bleibt eine Job-Aktion; --help/--version sind für Profile
# nicht sinnvoll. Zugangsdaten werden ausschließlich in eigenen Feldern
# verwaltet und dürfen nicht zusätzlich als freie debmirror-Option vorkommen.
DEBMIRROR_EXTRA_OPTION_CATALOG = [
    {"flag": "--debug", "key": "debug", "label": "Debug-Ausgabe", "takes_value": False, "help": "Sehr ausführliche Diagnoseausgabe einschließlich Transferdetails."},
    {"flag": "--passive", "key": "passive", "label": "FTP Passive Mode", "takes_value": False, "help": "FTP im passiven Modus verwenden."},
    {"flag": "--proxy", "key": "proxy", "label": "HTTP/FTP-Proxy", "takes_value": True, "placeholder": "http://proxy.example:3128/", "help": "Proxy-URL für HTTP- oder FTP-Transfers."},
    {"flag": "--omit-suite-symlinks", "key": "omit_suite_symlinks", "label": "Suite-Symlinks auslassen", "takes_value": False, "help": "Keine Suite-zu-Codename-Symlinks erzeugen; nützlich bei Archiv-Repositories."},
    {"flag": "--di-dist", "key": "di_dist", "label": "Debian-Installer Suites", "takes_value": True, "placeholder": "dists oder bookworm,trixie", "help": "Installer-Abbilder für die angegebenen Suites spiegeln."},
    {"flag": "--di-arch", "key": "di_arch", "label": "Debian-Installer Architekturen", "takes_value": True, "placeholder": "arches oder amd64,arm64", "help": "Installer-Abbilder für die angegebenen Architekturen spiegeln."},
    {"flag": "--checksums", "key": "checksums", "label": "Checksummen prüfen", "takes_value": False, "help": "Lokale Dateien zusätzlich anhand der Prüfsumme kontrollieren."},
    {"flag": "--ignore-missing-release", "key": "ignore_missing_release", "label": "Fehlende Release-Datei tolerieren", "takes_value": False, "help": "Nicht abbrechen, wenn eine Release-Datei fehlt."},
    {"flag": "--check-gpg", "key": "check_gpg", "label": "GPG-Prüfung erzwingen", "takes_value": False, "help": "Release-Signaturen ausdrücklich prüfen."},
    {"flag": "--no-check-gpg", "key": "no_check_gpg", "label": "GPG-Prüfung deaktivieren", "takes_value": False, "help": "Release-Signaturen nicht prüfen; sicherheitsrelevant."},
    {"flag": "--ignore-release-gpg", "key": "ignore_release_gpg", "label": "Fehlendes Release.gpg tolerieren", "takes_value": False, "help": "Fehlende Release.gpg-Datei nicht als Fehler behandeln."},
    {"flag": "--ignore", "key": "ignore", "label": "Dateien nie löschen", "takes_value": True, "placeholder": "^/project/trace/", "help": "Perl-RegEx; passende lokale Dateien werden bei der Bereinigung nie entfernt."},
    {"flag": "--exclude-deb-section", "key": "exclude_deb_section", "label": "Debian-Section ausschließen", "takes_value": True, "placeholder": "^(debug|games)$", "help": "Pakete anhand ihres Debian-Section-Feldes ausschließen."},
    {"flag": "--limit-priority", "key": "limit_priority", "label": "Priorität begrenzen", "takes_value": True, "placeholder": "^(required|important|standard)$", "help": "Nur Pakete mit passender Debian-Priorität spiegeln."},
    {"flag": "--exclude-field", "key": "exclude_field", "label": "Paketfeld ausschließen", "takes_value": True, "placeholder": "Package=^linux-image-debug", "help": "Format Feldname=RegEx; passende Binärpakete ausschließen."},
    {"flag": "--include-field", "key": "include_field", "label": "Paketfeld einschließen", "takes_value": True, "placeholder": "Package=^linux-image", "help": "Format Feldname=RegEx; passende Binärpakete wieder einschließen."},
    {"flag": "--max-batch", "key": "max_batch", "label": "Maximale Dateien pro Lauf", "takes_value": True, "value_type": "positive_int", "placeholder": "1000", "help": "Pro Lauf höchstens diese Anzahl Dateien herunterladen."},
    {"flag": "--rsync-batch", "key": "rsync_batch", "label": "Dateien pro Rsync-Aufruf", "takes_value": True, "value_type": "positive_int", "placeholder": "200", "help": "Rsync-Downloads in Pakete dieser Größe aufteilen."},
    {"flag": "--rsync-options", "key": "rsync_options", "label": "Zusätzliche Rsync-Optionen", "takes_value": True, "placeholder": "-aIL --partial --bwlimit=50000", "help": "Alternative/ergänzende Rsync-Optionen; sorgfältig prüfen."},
    {"flag": "--precleanup", "key": "precleanup", "label": "Vor dem Spiegeln bereinigen", "takes_value": False, "help": "Lokale Bereinigung vor dem Download; Mirror kann währenddessen inkonsistent sein."},
    {"flag": "--nocleanup", "key": "nocleanup", "label": "Bereinigung deaktivieren", "takes_value": False, "help": "Unbekannte lokale Dateien nicht entfernen."},
    {"flag": "--skippackages", "key": "skippackages", "label": "Packages/Sources nicht neu laden", "takes_value": False, "help": "Metadaten nicht erneut laden, wenn sie sicher aktuell sind."},
    {"flag": "--gzip-options", "key": "gzip_options", "label": "Gzip-Optionen", "takes_value": True, "placeholder": "-9 -n --rsyncable", "help": "Optionen für die Komprimierung nach Diff-Anwendung."},
    {"flag": "--slow-cpu", "key": "slow_cpu", "label": "Langsame CPU", "takes_value": False, "help": "Weniger CPU-intensive Verarbeitung; impliziert diff=none."},
    {"flag": "--state-cache-days", "key": "state_cache_days", "label": "State-Cache in Tagen", "takes_value": True, "value_type": "nonnegative_int", "placeholder": "7", "help": "Mirror-Zustand für diese Anzahl Tage zwischenspeichern."},
    {"flag": "--ignore-small-errors", "key": "ignore_small_errors", "label": "Kleine Downloadfehler tolerieren", "takes_value": False, "help": "Fehlende einzelne Paketdateien tolerieren, Metadaten aber streng prüfen."},
    {"flag": "--allow-dist-rename", "key": "allow_dist_rename", "label": "Distribution umbenennen erlauben", "takes_value": False, "help": "Alte Suite-Verzeichnisse automatisch auf Codenames umstellen."},
    {"flag": "--disable-ssl-verification", "key": "disable_ssl_verification", "label": "TLS-Zertifikatsprüfung deaktivieren", "takes_value": False, "help": "Nur für bewusst verwendete selbstsignierte HTTPS-Quellen; sicherheitsrelevant."},
    {"flag": "--debmarshal", "key": "debmarshal", "label": "Debmarshal-Modus", "takes_value": False, "help": "Metadatenstände nummeriert aufbewahren; normale Bereinigung wird deaktiviert."},
    {"flag": "--retry-rsync-packages", "key": "retry_rsync_packages", "label": "Rsync-Paketmetadaten wiederholen", "takes_value": True, "value_type": "retry_int", "placeholder": "10", "help": "Experimentell: Anzahl Verbindungsversuche; 0 oder -1 bedeutet unbegrenzt."},
]
DEBMIRROR_EXTRA_OPTION_BY_FLAG = {item["flag"]: item for item in DEBMIRROR_EXTRA_OPTION_CATALOG}
SAFE_EXTRA_FLAGS = {item["flag"] for item in DEBMIRROR_EXTRA_OPTION_CATALOG if not item.get("takes_value")}


def validate_debmirror_extra_value(flag: str, value: str) -> str:
    spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG.get(flag)
    if not spec or not spec.get("takes_value"):
        raise ValueError(f"Zusatzoption benötigt keinen Wert: {flag}")
    value = (value or "").strip()
    if not value:
        raise ValueError(f"Für {flag} muss ein Wert angegeben werden.")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Ungültiger Wert für {flag}.")
    value_type = spec.get("value_type", "text")
    if value_type == "positive_int":
        number = int(value)
        if number < 1:
            raise ValueError(f"Der Wert für {flag} muss mindestens 1 sein.")
        return str(number)
    if value_type == "nonnegative_int":
        number = int(value)
        if number < 0:
            raise ValueError(f"Der Wert für {flag} darf nicht negativ sein.")
        return str(number)
    if value_type == "retry_int":
        number = int(value)
        if number < -1:
            raise ValueError(f"Der Wert für {flag} muss -1, 0 oder positiv sein.")
        return str(number)
    if flag in {"--exclude-field", "--include-field"} and "=" not in value:
        raise ValueError(f"{flag} erwartet Feldname=RegEx.")
    if flag in {"--rsync-options", "--gzip-options"}:
        try:
            command_tokens = shlex_split(value)
        except Exception as exc:
            raise ValueError(f"{flag} enthält ungültige Anführungszeichen oder Escape-Zeichen.") from exc
        if not command_tokens or len(command_tokens) > 40:
            raise ValueError(f"{flag} muss zwischen 1 und 40 einzelne Optionen enthalten.")
        normalized_tokens: List[str] = []
        for token in command_tokens:
            if not token.startswith("-") or token == "--":
                raise ValueError(f"{flag} darf ausschließlich Optionsschalter enthalten: {token}")
            if not re.fullmatch(r"[-A-Za-z0-9_.,=+:/%@]+", token):
                raise ValueError(f"{flag} enthält einen nicht sicher übergebbaren Wert: {token}")
            normalized_tokens.append(token)
        if flag == "--rsync-options":
            blocked_rsync_flags = {"-e", "--rsh", "--password-file", "--rsync-path"}
            for token in normalized_tokens:
                token_flag = token.split("=", 1)[0]
                if token_flag in blocked_rsync_flags:
                    raise ValueError(f"{token_flag} wird über eigene sichere Profilfelder verwaltet und ist in --rsync-options nicht zulässig.")
        return " ".join(normalized_tokens)
    return value


def validate_extra_option_conflicts(tokens: List[str]) -> None:
    flags = {token.split("=", 1)[0] for token in tokens}
    conflicts = [
        ({"--check-gpg", "--no-check-gpg"}, "--check-gpg und --no-check-gpg können nicht gleichzeitig verwendet werden."),
        ({"--precleanup", "--nocleanup"}, "--precleanup und --nocleanup können nicht gleichzeitig verwendet werden."),
        ({"--precleanup", "--debmarshal"}, "--precleanup und --debmarshal können nicht gleichzeitig verwendet werden."),
        ({"--nocleanup", "--debmarshal"}, "--nocleanup und --debmarshal können nicht gleichzeitig verwendet werden."),
    ]
    for pair, message in conflicts:
        if pair.issubset(flags):
            raise ValueError(message)


def parse_extra_options(value: str) -> List[str]:
    """Parse and validate additional debmirror profile options.

    Every returned value is passed as one argv element without shell=True.
    Unknown options, missing values and conflicting switches are rejected.
    """
    if not (value or "").strip():
        return []
    result: List[str] = []
    for token in shlex_split(value):
        flag, separator, raw_value = token.partition("=")
        spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG.get(flag)
        if not spec:
            raise ValueError(f"Zusatzoption ist nicht freigegeben: {token}")
        if spec.get("takes_value"):
            if not separator:
                raise ValueError(f"Zusatzoption benötigt einen Wert im Format {flag}=WERT.")
            normalized = validate_debmirror_extra_value(flag, raw_value)
            result.append(f"{flag}={normalized}")
        else:
            if separator:
                raise ValueError(f"Zusatzoption akzeptiert keinen Wert: {flag}")
            result.append(flag)
    validate_extra_option_conflicts(result)
    return result


def serialize_extra_options(tokens: Iterable[str]) -> str:
    import shlex
    return " ".join(shlex.quote(token) for token in tokens)


def extra_options_from_form(form: Any) -> str:
    selected = form.getlist("extra_flag") if hasattr(form, "getlist") else []
    tokens: List[str] = []
    seen = set()
    for flag in selected:
        flag = (flag or "").strip()
        if flag in seen:
            continue
        seen.add(flag)
        spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG.get(flag)
        if not spec:
            raise ValueError(f"Unbekannte Zusatzoption: {flag}")
        if spec.get("takes_value"):
            value = form.get(f"extra_value_{spec['key']}", "")
            tokens.append(f"{flag}={validate_debmirror_extra_value(flag, value)}")
        else:
            tokens.append(flag)
    validate_extra_option_conflicts(tokens)
    return serialize_extra_options(tokens)


def extra_option_selection(value: str) -> Dict[str, str]:
    """Return a tolerant form representation, even for conflicting legacy input."""
    selected: Dict[str, str] = {}
    try:
        tokens = shlex_split(value or "")
    except Exception:
        tokens = []
    for token in tokens:
        flag, separator, raw_value = token.partition("=")
        spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG.get(flag)
        if not spec:
            continue
        if spec.get("takes_value"):
            selected[flag] = raw_value if separator else ""
        else:
            selected[flag] = ""
    return selected


MANUAL_EXTRA_BLOCKED_FLAGS = {
    "--host", "--root", "--method", "--dist", "--section", "--arch",
    "--source", "--nosource", "--keyring", "--user", "--passwd",
    "--config-file", "--dry-run", "--help", "--version", "--progress",
    "--verbose", "--getcontents", "--i18n", "--timeout", "--rsync-extra",
    "--include", "--exclude", "--cleanup", "--postcleanup", "--diff",
}


def parse_manual_extra_options(value: str) -> List[str]:
    """Validate expert-mode debmirror argv without invoking a shell.

    Only long options are accepted. Core profile options and credentials stay in
    dedicated fields so they cannot be duplicated or silently override the UI.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    if len(raw) > 4096:
        raise ValueError("Manuelle Zusatzoptionen sind auf 4096 Zeichen begrenzt.")
    tokens = shlex_split(raw)
    if len(tokens) > 50:
        raise ValueError("Es sind maximal 50 manuelle Zusatzoptionen erlaubt.")
    result: List[str] = []
    seen_flags: set[str] = set()
    for token in tokens:
        if not token.startswith("--") or token == "--":
            raise ValueError(f"Manuelle Zusatzoption muss mit -- beginnen: {token}")
        if "\x00" in token or "\n" in token or "\r" in token:
            raise ValueError("Ungültige Zeichen in manuellen Zusatzoptionen.")
        flag = token.split("=", 1)[0]
        if flag in MANUAL_EXTRA_BLOCKED_FLAGS:
            raise ValueError(f"{flag} wird über ein eigenes Profilfeld verwaltet und ist im Expertenfeld nicht erlaubt.")
        if flag in DEBMIRROR_EXTRA_OPTION_BY_FLAG:
            raise ValueError(f"{flag} ist bereits in der Auswahlliste vorhanden. Bitte dort auswählen.")
        if flag in seen_flags:
            raise ValueError(f"Manuelle Zusatzoption doppelt angegeben: {flag}")
        seen_flags.add(flag)
        result.append(token)
    return result


def serialize_manual_extra_options(value: str) -> str:
    return serialize_extra_options(parse_manual_extra_options(value))


def mirror_remote_password_plain(mirror: Dict[str, Any]) -> str:
    encrypted = str(mirror.get("remote_password_enc") or "")
    if not encrypted:
        return ""
    return decrypt_secret(encrypted)


def mirror_remote_password_set(mirror: Dict[str, Any]) -> bool:
    encrypted = str(mirror.get("remote_password_enc") or "")
    return bool(encrypted and mirror_remote_password_plain(mirror))


def ssh_key_fingerprint(path: Path) -> str:
    if not path.exists() or not shutil.which("ssh-keygen"):
        return ""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[1]
    except Exception:
        pass
    return ""


def allowed_ssh_key_name(value: str, must_exist: bool = True) -> str:
    name = (value or "").strip()
    if not name:
        return ""
    if name != Path(name).name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Ungültiger SSH-Schlüsselname.")
    path = (SSH_KEY_DIR / name).resolve(strict=False)
    base = SSH_KEY_DIR.resolve(strict=False)
    if path.parent != base:
        raise ValueError("SSH-Schlüssel muss aus dem verwalteten SSH-Schlüsselverzeichnis stammen.")
    if must_exist and (not path.exists() or not path.is_file() or path.is_symlink()):
        raise ValueError(f"SSH-Privatschlüssel nicht gefunden: {name}")
    if path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return name


def validate_ssh_private_key_file(path: Path) -> None:
    if not shutil.which("ssh-keygen"):
        raise ValueError("ssh-keygen fehlt im Container. Container mit der aktuellen Version neu bauen.")
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ValueError("SSH-Privatschlüsseldatei ist ungültig.")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    result = subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or result.stdout or "").strip().lower()
        if "passphrase" in detail or "incorrect passphrase" in detail:
            raise ValueError("Passwortgeschützte SSH-Privatschlüssel werden für unbeaufsichtigte Jobs nicht unterstützt. Bitte einen eigenen, eingeschränkten Schlüssel ohne Passphrase verwenden.")
        raise ValueError("Die hochgeladene Datei ist kein verwendbarer OpenSSH-Privatschlüssel.")


def save_uploaded_ssh_private_key(uploaded: Any) -> str:
    if uploaded is None or not getattr(uploaded, "filename", ""):
        return ""
    original_name = secure_filename(str(uploaded.filename)) or "ssh-key"
    data = uploaded.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("SSH-Privatschlüssel ist größer als 2 MiB.")
    if not data.strip() or b"\x00" in data:
        raise ValueError("SSH-Privatschlüsseldatei ist leer oder ungültig.")
    SSH_KEY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SSH_KEY_DIR.chmod(0o700)
    except OSError:
        pass
    digest = hashlib.sha256(data).hexdigest()
    stem = secure_filename(Path(original_name).stem) or "ssh-key"
    final_name = f"{stem}-{digest[:12]}"
    final_path = SSH_KEY_DIR / final_name
    if final_path.exists():
        if final_path.read_bytes() != data:
            raise ValueError("SSH-Schlüsselname kollidiert mit einer vorhandenen Datei.")
        validate_ssh_private_key_file(final_path)
        return final_name
    fd, temp_name = tempfile.mkstemp(prefix="upload-", dir=str(SSH_KEY_DIR))
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        validate_ssh_private_key_file(temp_path)
        temp_path.replace(final_path)
        final_path.chmod(0o600)
        return final_name
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def list_ssh_private_keys() -> List[Dict[str, Any]]:
    SSH_KEY_DIR.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for path in sorted(SSH_KEY_DIR.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.is_symlink() or path.name.startswith("upload-"):
            continue
        try:
            path.chmod(0o600)
        except OSError:
            pass
        items.append({
            "name": path.name,
            "fingerprint": ssh_key_fingerprint(path),
            "size": path.stat().st_size,
        })
    return items


def validate_mirror_remote_credentials(method: str, remote_user: str, remote_password_enc: str) -> None:
    user = (remote_user or "").strip()
    if len(user) > 255 or any(ch in user for ch in ("\x00", "\r", "\n")):
        raise ValueError("Der Remote-Benutzer enthält unzulässige Steuerzeichen oder ist zu lang.")
    if method == "rsync" and (user or remote_password_enc):
        raise ValueError("Benutzer/Passwort ist für die Methode rsync nicht zulässig. Verwende dafür die separate SSH-Schlüsselanmeldung.")
    if remote_password_enc and not user:
        raise ValueError("Für ein gespeichertes Remote-Passwort muss ein Remote-Benutzer angegeben werden.")
    if remote_password_enc:
        password = decrypt_secret(remote_password_enc)
        if not password:
            raise ValueError("Das gespeicherte Remote-Passwort kann nicht entschlüsselt werden. Bitte neu setzen.")
        if len(password) > 4096 or any(ch in password for ch in ("\x00", "\r", "\n")):
            raise ValueError("Das gespeicherte Remote-Passwort enthält unzulässige Steuerzeichen oder ist zu lang. Bitte neu setzen.")


def validate_non_rsync_host_value(host: str) -> str:
    value = (host or "").strip()
    if not value or "://" in value or "/" in value or "@" in value or any(ch.isspace() for ch in value):
        raise ValueError("Im Host-Feld darf nur ein Hostname oder eine IP-Adresse stehen; Protokoll, Zugangsdaten und Pfade gehören in die eigenen Felder.")
    try:
        parsed = urllib.parse.urlparse("//" + value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Das Host-Feld enthält eine ungültige Port- oder IPv6-Angabe.") from exc
    if not parsed.hostname or parsed.path not in {"", "/"}:
        raise ValueError("Das Host-Feld enthält keinen gültigen Hostnamen oder keine gültige IP-Adresse.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Der Port im Host-Feld muss zwischen 1 und 65535 liegen.")
    return value


def rsync_options_value(mirror: Dict[str, Any]) -> str:
    for token in parse_extra_options(str(mirror.get("extra_options") or "")):
        if token.startswith("--rsync-options="):
            return token.split("=", 1)[1]
    return ""


def validate_rsync_host_value(host: str) -> str:
    value = (host or "").strip()
    if not value or "://" in value or "/" in value or "@" in value or any(ch.isspace() for ch in value):
        raise ValueError("Für Rsync muss im Host-Feld nur ein Hostname oder eine IP-Adresse stehen.")
    if value.startswith("[") and value.endswith("]"):
        try:
            if ipaddress.ip_address(value[1:-1]).version != 6:
                raise ValueError
            return value
        except ValueError as exc:
            raise ValueError("Die IPv6-Adresse im Host-Feld ist ungültig.") from exc
    if ":" in value:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("Einen Port bitte nicht im Host-Feld angeben. Für direkten Rsync-Daemon-Zugriff kann --port in den Rsync-Optionen verwendet werden; bei SSH steht das Feld SSH-Port bereit.")
        raise ValueError("IPv6-Adressen im Host-Feld bitte in eckigen Klammern angeben, z. B. [2001:db8::1].")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if len(value) > 253 or not re.fullmatch(r"(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?", value):
        raise ValueError("Das Host-Feld für Rsync enthält keinen gültigen Hostnamen oder keine gültige IP-Adresse.")
    return value


def validate_rsync_module_path(root_path: str) -> str:
    raw = (root_path or "").strip()
    if raw.startswith(("/", "\\")):
        raise ValueError("Für Rsync muss der Root-Pfad als Modulname ohne führenden Schrägstrich angegeben werden.")
    value = normalize_root_path(raw)
    if not value or value in {".", ".."} or value.startswith(":"):
        raise ValueError("Für Rsync muss der Root-Pfad mit einem Rsync-Modulnamen beginnen.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Der Rsync-Modulpfad darf keine leeren Segmente, '.' oder '..' enthalten.")
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", parts[0]):
        raise ValueError("Der erste Teil des Root-Pfads muss ein gültiger Rsync-Modulname sein.")
    if any(not re.fullmatch(r"[A-Za-z0-9._+@%=-]+", part) for part in parts[1:]):
        raise ValueError("Der Unterpfad des Rsync-Moduls enthält unzulässige Zeichen.")
    return value


def validate_rsync_ssh_settings(mirror: Dict[str, Any], require_key: bool = True) -> None:
    enabled = bool(int(mirror.get("rsync_ssh_enabled") or 0))
    if not enabled:
        return
    if str(mirror.get("method") or "") != "rsync":
        raise ValueError("SSH-Schlüsselanmeldung kann nur mit der Transfermethode rsync verwendet werden.")
    if str(mirror.get("remote_user") or "").strip() or str(mirror.get("remote_password_enc") or "").strip():
        raise ValueError("SSH-Schlüsselanmeldung kann nicht mit Remote-Benutzer/Passwort kombiniert werden.")
    user = str(mirror.get("rsync_ssh_user") or "").strip()
    if not user:
        raise ValueError("Für die SSH-Schlüsselanmeldung muss ein SSH-Benutzer angegeben werden.")
    if any(ch.isspace() for ch in user) or any(ch in user for ch in "@:/\\") or any(ord(ch) < 32 for ch in user):
        raise ValueError("Der SSH-Benutzer enthält unzulässige Zeichen.")
    validate_rsync_host_value(str(mirror.get("host") or ""))
    validate_rsync_module_path(str(mirror.get("root_path") or ""))
    try:
        port = int(mirror.get("rsync_ssh_port") or 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH-Port muss eine Zahl sein.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SSH-Port muss zwischen 1 und 65535 liegen.")
    key_name = str(mirror.get("rsync_ssh_key") or "").strip()
    if not key_name:
        raise ValueError("Für die SSH-Schlüsselanmeldung muss ein privater Schlüssel ausgewählt oder hochgeladen werden.")
    if require_key:
        allowed_ssh_key_name(key_name, must_exist=True)
    else:
        allowed_ssh_key_name(key_name, must_exist=False)
    options = rsync_options_value(mirror)
    if options:
        try:
            option_tokens = shlex_split(options)
        except Exception as exc:
            raise ValueError("Zusätzliche Rsync-Optionen können nicht ausgewertet werden.") from exc
        blocked = []
        for index, token in enumerate(option_tokens):
            flag = token.split("=", 1)[0]
            if flag in {"-e", "--rsh", "--password-file", "--port"} or token.startswith(("--rsh=", "--password-file=", "--port=")):
                blocked.append(token)
            if index and option_tokens[index - 1] == "-e":
                blocked.append(token)
        if blocked:
            raise ValueError("Bei aktiver SSH-Schlüsselanmeldung dürfen --rsync-options keine eigene Remote-Shell, Passwortdatei oder Rsync-Daemon-Port setzen.")


def rsync_ssh_rsh_command(mirror: Dict[str, Any]) -> str:
    validate_rsync_ssh_settings(mirror, require_key=True)
    if not shutil.which("ssh"):
        raise ValueError("SSH-Client fehlt im Container. Bitte den Container mit der aktuellen Version neu bauen.")
    key_path = SSH_KEY_DIR / allowed_ssh_key_name(str(mirror.get("rsync_ssh_key") or ""), must_exist=True)
    try:
        key_path.chmod(0o600)
        SSH_KNOWN_HOSTS_PATH.chmod(0o600)
    except OSError:
        pass
    port = int(mirror.get("rsync_ssh_port") or 22)
    user = str(mirror.get("rsync_ssh_user") or "").strip()
    strict_mode = "accept-new" if bool(int(mirror.get("rsync_ssh_accept_new_host_key") or 0)) else "yes"
    parts = [
        "ssh", "-i", str(key_path), "-p", str(port), "-l", user,
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", f"StrictHostKeyChecking={strict_mode}",
        "-o", f"UserKnownHostsFile={SSH_KNOWN_HOSTS_PATH}",
    ]
    import shlex
    return shlex.join(parts)


def rsync_options_with_ssh(mirror: Dict[str, Any]) -> str:
    import shlex
    base = rsync_options_value(mirror).strip() or "-aIL --partial"
    rsh = rsync_ssh_rsh_command(mirror)
    return f"{base} --rsh={shlex.quote(rsh)}"


def _perl_single_quoted(value: str) -> str:
    return "'" + (value or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def create_job_auth_config(mirror: Dict[str, Any], job_id: int) -> Optional[Path]:
    method = str(mirror.get("method") or "")
    if method == "rsync":
        return None
    user = str(mirror.get("remote_user") or "").strip()
    password = mirror_remote_password_plain(mirror)
    if not user and not password:
        return None
    validate_mirror_remote_credentials(method, user, str(mirror.get("remote_password_enc") or ""))
    JOB_AUTH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = JOB_AUTH_CONFIG_DIR / f"job-{int(job_id)}-{secrets.token_hex(8)}.conf"
    content = ["# Temporäre Zugangsdaten für einen DebMirror-Manager-Job"]
    if user:
        content.append(f"$user={_perl_single_quoted(user)};")
    if password:
        content.append(f"$passwd={_perl_single_quoted(password)};")
    content.append("1;")
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def display_debmirror_command(mirror: Dict[str, Any], dry_run: bool = False, validate_keyring: bool = True) -> List[str]:
    cmd = build_debmirror_command(mirror, dry_run=dry_run, validate_keyring=validate_keyring)
    if str(mirror.get("method") or "") != "rsync":
        target = cmd.pop() if cmd else ""
        user = str(mirror.get("remote_user") or "").strip()
        if user:
            cmd.append(f"--user={user}")
        if mirror.get("remote_password_enc"):
            cmd.append("--passwd=<verschlüsselt gespeichert>")
        if target:
            cmd.append(target)
    return cmd


def normalize_rsync_extra_values(values: Iterable[str]) -> str:
    result: List[str] = []
    for raw in values:
        for value in csv_to_list(raw or ""):
            if value not in RSYNC_EXTRA_VALUES:
                raise ValueError(f"Ungültiger Rsync-Extra-Wert: {value}")
            if value not in result:
                result.append(value)
    if "none" in result and len(result) > 1:
        raise ValueError("Rsync Extra 'none' kann nicht zusammen mit anderen Werten verwendet werden.")
    return ",".join(result)


def normalize_mirror_option_compatibility(values: Dict[str, Any]) -> None:
    """Store one unambiguous value for options that imply another setting."""
    extra_options = parse_extra_options(str(values.get("extra_options") or ""))
    flags = {item.split("=", 1)[0] for item in extra_options}
    if "--slow-cpu" in flags:
        values["diff_mode"] = "none"
    if {"--precleanup", "--nocleanup", "--debmarshal"} & flags:
        values["postcleanup"] = 0


def validate_mirror_configuration(values: Dict[str, Any], require_ssh_key: bool = True) -> None:
    method = str(values.get("method") or "")
    if method not in {"rsync", "http", "https", "ftp"}:
        raise ValueError("Ungültige Methode.")
    if str(values.get("source_mode") or "nosource") not in {"source", "nosource"}:
        raise ValueError("Ungültige Quellpaket-Einstellung.")
    if str(values.get("diff_mode") or "none") not in {"use", "mirror", "none"}:
        raise ValueError("Ungültiger Diff-Modus.")
    if method == "rsync":
        validate_rsync_host_value(str(values.get("host") or ""))
        validate_rsync_module_path(str(values.get("root_path") or ""))
    else:
        validate_non_rsync_host_value(str(values.get("host") or ""))
    for field, label in (("dists", "Distributionen"), ("sections", "Komponenten/Sections"), ("archs", "Architekturen")):
        if not csv_to_list(str(values.get(field) or "")):
            raise ValueError(f"{label} muss mindestens einen gültigen Wert enthalten.")
    timeout = values.get("timeout_seconds")
    if timeout not in (None, ""):
        try:
            timeout_number = int(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("Timeout muss eine ganze Zahl sein.") from exc
        if timeout_number < 1:
            raise ValueError("Timeout muss mindestens 1 Sekunde betragen.")
    validate_mirror_remote_credentials(method, str(values.get("remote_user") or ""), str(values.get("remote_password_enc") or ""))
    validate_rsync_ssh_settings(values, require_key=require_ssh_key)
    extra_options = parse_extra_options(str(values.get("extra_options") or ""))
    flags = {item.split("=", 1)[0] for item in extra_options}
    if "--passive" in flags and method != "ftp":
        raise ValueError("--passive ist nur mit der Transfermethode FTP sinnvoll.")
    if "--disable-ssl-verification" in flags and method != "https":
        raise ValueError("--disable-ssl-verification ist nur mit der Transfermethode HTTPS zulässig.")
    if "--proxy" in flags and method not in {"http", "https", "ftp"}:
        raise ValueError("--proxy kann nur mit HTTP, HTTPS oder FTP verwendet werden.")
    if "--no-check-gpg" in flags and (str(values.get("keyring") or "").strip() or str(values.get("keyring_fingerprint") or "").strip()):
        raise ValueError("Ein Keyring/Fingerprint kann nicht gleichzeitig mit deaktivierter GPG-Prüfung verwendet werden.")
    if "--no-check-gpg" in flags and "--ignore-release-gpg" in flags:
        raise ValueError("--ignore-release-gpg ist bei vollständig deaktivierter GPG-Prüfung wirkungslos.")
    if "--slow-cpu" in flags and str(values.get("diff_mode") or "") != "none":
        raise ValueError("--slow-cpu erfordert Diff-Modus none.")
    if "--gzip-options" in flags and str(values.get("diff_mode") or "none") == "none":
        raise ValueError("--gzip-options wird nur beim Anwenden von Diff-Dateien verwendet und ist mit Diff-Modus none wirkungslos.")
    cleanup_flags = {"--precleanup", "--nocleanup", "--debmarshal"} & flags
    if cleanup_flags and bool(int(values.get("postcleanup") or 0)):
        raise ValueError("Post-Cleanup darf nicht gleichzeitig mit einem alternativen Bereinigungsmodus aktiviert sein.")
    rsync_specific = {"--rsync-options", "--rsync-batch", "--retry-rsync-packages"} & flags
    if method != "rsync" and str(values.get("rsync_extra") or "") == "none" and rsync_specific:
        raise ValueError("Rsync-spezifische Optionen werden nicht verwendet, wenn die Hauptmethode nicht rsync ist und Rsync Extra auf none steht.")
    package_rsync_only = {"--rsync-batch", "--retry-rsync-packages"} & flags
    if method != "rsync" and package_rsync_only:
        raise ValueError("--rsync-batch und --retry-rsync-packages wirken nur, wenn Pakete mit der Hauptmethode rsync geladen werden.")
    schedule_mode = str(values.get("schedule_mode") or "manual")
    if schedule_mode not in {"manual", "daily", "weekly", "interval"}:
        raise ValueError("Ungültiger Zeitplanmodus.")
    if schedule_mode in {"daily", "weekly"}:
        validate_hhmm(str(values.get("schedule_time") or ""))
    weekday = int(values.get("schedule_weekday") if values.get("schedule_weekday") not in (None, "") else 6)
    if not 0 <= weekday <= 6:
        raise ValueError("Wochentag muss zwischen Montag und Sonntag liegen.")
    interval = int(values.get("interval_hours") or 24)
    if not 1 <= interval <= 8760:
        raise ValueError("Intervall muss zwischen 1 und 8760 Stunden liegen.")


def mirror_form_option_context(mirror: Dict[str, Any]) -> Dict[str, Any]:
    selected_options = extra_option_selection(str(mirror.get("extra_options") or ""))
    raw_rsync_extra = str(mirror.get("rsync_extra") or "").strip()
    selected_rsync: List[str] = []
    if raw_rsync_extra:
        try:
            selected_rsync = csv_to_list(normalize_rsync_extra_values([raw_rsync_extra]))
        except Exception:
            # Older versions suggested --bwlimit in the wrong field. Present that
            # legacy value as --rsync-options so saving the form migrates it.
            if raw_rsync_extra.startswith("-") and "--rsync-options" not in selected_options:
                selected_options["--rsync-options"] = raw_rsync_extra
    return {
        "debmirror_extra_catalog": DEBMIRROR_EXTRA_OPTION_CATALOG,
        "selected_debmirror_options": selected_options,
        "rsync_extra_choices": RSYNC_EXTRA_CHOICES,
        "selected_rsync_extra": selected_rsync,
        "remote_password_set": mirror_remote_password_set(mirror),
        "ssh_private_keys": list_ssh_private_keys(),
    }


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


def latest_size_changing_job_finished_at(*, mirror_id: Optional[int] = None, script_name: str = "") -> str:
    """Liefert den letzten beendeten echten Job, der ein Ziel verändert haben kann.

    Das Alter des Cache-Eintrags allein darf keinen Größenwert als veraltet
    markieren. Wartende Jobs, Dry-Runs und Fehler vor dem Prozessstart zählen
    deshalb nicht als Änderung des Zielinhalts.
    """
    if mirror_id is None and not (script_name or "").strip():
        return ""
    where = ["dry_run=0", "finished_at IS NOT NULL"]
    params: List[Any] = []
    if mirror_id is not None:
        where.extend(["job_type='mirror'", "mirror_id=?"])
        params.append(int(mirror_id))
    else:
        where.extend(["job_type='script'", "script_name=?"])
        params.append((script_name or "").strip())
    # Erfolg wurde ausgeführt. Fehler/Stop zählen nur mit vergebener PID; damit
    # bleiben Vorprüfungsfehler und aus der Queue entfernte Jobs ausgeschlossen.
    where.append("(status='success' OR (status IN ('error','stopped') AND pid IS NOT NULL))")
    with db() as con:
        row = con.execute(
            f"SELECT finished_at FROM jobs WHERE {' AND '.join(where)} ORDER BY finished_at DESC, id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
    return str(row["finished_at"] or "") if row else ""


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
            script["dashboard_status"] = dashboard_entity_status("script", script)
            script["start_block_reason"] = script_start_block_reason_from_item(script)
        except Exception as exc:
            log_webui_exception(f"user_script_runtime_info {script.get('name')}", exc)
            script["last_job"] = None
            script["running_job"] = None
            script["schedule_display"] = "-"
            script["dashboard_status"] = {"label": "error", "class": "error", "title": "Status konnte nicht ermittelt werden"}
            script["start_block_reason"] = "Status konnte nicht ermittelt werden"
        if "start_block_reason" not in script:
            script["start_block_reason"] = script_start_block_reason_from_item(script)
    return scripts


def get_active_job() -> Optional[Dict[str, Any]]:
    """Return any queued/running/stopping job. Used for dashboard hints only."""
    with db() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','starting','running','stopping') ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'stopping' THEN 1 ELSE 2 END, id ASC LIMIT 1"
        ).fetchone()
        return row_to_dict(row) if row else None


def dashboard_job_badge(job: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not job:
        return None
    status = str(job.get("status") or "").strip().lower()
    job_id = job.get("id") or "-"
    if status == "queued":
        return {"label": f"queue #{job_id}", "class": "queued", "title": "Job wartet in der Warteschlange", "job_id": str(job_id)}
    if status in {"starting", "running", "stopping"}:
        return {"label": f"aktiv #{job_id}", "class": "running", "title": "Job läuft oder wird gerade gestartet/gestoppt", "job_id": str(job_id)}
    if status == "error":
        return {"label": f"error #{job_id}", "class": "error", "title": "Job wurde mit Fehler beendet", "job_id": str(job_id)}
    return {"label": f"{status or 'job'} #{job_id}", "class": status or "muted", "title": "Jobstatus", "job_id": str(job_id)}


def mirror_dashboard_issue(mirror: Dict[str, Any]) -> str:
    issues: List[str] = []
    if str(mirror.get("method") or "").strip() not in {"rsync", "http", "https", "ftp"}:
        issues.append("Methode")
    for field, label in (("host", "Host"), ("target_path", "Ziel"), ("dists", "Dist"), ("sections", "Sektion"), ("archs", "Arch")):
        if not str(mirror.get(field) or "").strip():
            issues.append(label)
    try:
        if str(mirror.get("target_path") or "").strip():
            normalize_target_path(str(mirror.get("target_path") or ""))
    except Exception:
        issues.append("Zielpfad")
    try:
        validate_mirror_configuration(mirror, require_ssh_key=True)
    except Exception:
        issues.append("Optionen/Anmeldung")
    if issues:
        return "Profil prüfen: " + ", ".join(dict.fromkeys(issues))
    return ""


def mirror_keyring_dashboard_notice(mirror: Dict[str, Any]) -> str:
    """Return a non-blocking dashboard hint for missing profile keyrings."""
    mirror_id = int(mirror.get("id") or 0)
    raw_keyring = str(mirror.get("keyring") or "").strip()
    assignments: List[Dict[str, str]] = []
    if mirror_id:
        try:
            assignments = mirror_keyring_assignment_items(mirror_id)
        except Exception:
            assignments = []
    if not raw_keyring and not assignments:
        return "Kein Keyring zugeordnet."
    if assignments and not raw_keyring:
        return "Profil-Keyring noch nicht erzeugt."
    if raw_keyring:
        try:
            keyring_path = Path(allowed_keyring_path(raw_keyring))
            if not keyring_path.exists():
                return "Profil-Keyring-Datei fehlt." if assignments else "Keyring-Datei fehlt."
        except Exception:
            return "Keyring-Pfad prüfen."
    return ""


def mirror_start_block_reason(mirror: Dict[str, Any], *, dry_run: bool = False) -> str:
    issue = mirror_dashboard_issue(mirror)
    if issue:
        return issue
    if not dry_run and int(mirror.get("enabled") or 0) != 1:
        return "Mirror-Profil ist deaktiviert."
    return ""


def script_start_block_reason_from_item(script: Dict[str, Any]) -> str:
    if not script.get("enabled"):
        return "Benutzerskript ist deaktiviert."
    if not script.get("executable"):
        return "Benutzerskript ist nicht ausführbar."
    return ""


def dashboard_entity_status(kind: str, item: Dict[str, Any]) -> Dict[str, str]:
    job_badge = dashboard_job_badge(item.get("running_job"))
    if job_badge:
        return job_badge
    if kind == "mirror":
        issue = mirror_dashboard_issue(item)
        if issue:
            return {"label": "error", "class": "error", "title": issue}
        keyring_notice = mirror_keyring_dashboard_notice(item)
        if keyring_notice:
            return {"label": "no key", "class": "warning", "title": keyring_notice}
        if int(item.get("enabled") or 0) != 1:
            return {"label": "inaktiv", "class": "muted", "title": "Mirror-Profil ist deaktiviert"}
        return {"label": "idle", "class": "idle", "title": "Kein Job läuft und kein Job wartet"}
    if kind == "script":
        reason = script_start_block_reason_from_item(item)
        if reason:
            return {"label": "error", "class": "error", "title": reason}
        return {"label": "idle", "class": "idle", "title": "Kein Job läuft und kein Job wartet"}
    return {"label": "idle", "class": "idle", "title": "Kein Job läuft und kein Job wartet"}


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
        _write_size_cache(path_value, status="timeout", exists_flag=1 if Path(path_value).exists() else 0, bytes_value=old.get("bytes"), error="Größenberechnung dauerte zu lange. Der Wert der letzten Prüfung bleibt erhalten.", started_at=started, calculated_at=now_iso())
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

def _size_value_is_outdated(row: Optional[Dict[str, Any]], content_changed_at: str) -> bool:
    if not row or row.get("bytes") is None:
        return False
    changed = parse_datetime_flexible(str(content_changed_at or ""))
    if not changed:
        return False
    calculated = parse_datetime_flexible(str(row.get("calculated_at") or ""))
    return calculated is None or changed > calculated


def cached_path_size_info(
    path_value: str,
    *,
    force_refresh: bool = False,
    auto_refresh: bool = False,
    content_changed_at: str = "",
) -> Dict[str, Any]:
    raw_path = (path_value or "").strip()
    if not raw_path:
        return {"exists": False, "bytes": 0, "size_h": "0 B", "files": None, "dirs": None, "error": "Kein Pfad gesetzt.", "status": "missing", "calculated_at": "", "started_at": ""}
    path_value = str(Path(raw_path))
    exists_now = Path(path_value).exists()
    if not exists_now:
        return {"exists": False, "bytes": 0, "size_h": "0 B", "files": None, "dirs": None, "error": "Pfad existiert noch nicht.", "status": "missing", "calculated_at": "", "started_at": ""}

    row = _size_cache_row(path_value)
    cache_expired = True
    if row and row.get("calculated_at"):
        try:
            calculated = dt.datetime.fromisoformat(str(row["calculated_at"]))
            cache_expired = (local_now() - calculated).total_seconds() > size_cache_ttl_seconds()
        except Exception:
            cache_expired = True
    if force_refresh or (auto_refresh and (not row or cache_expired)):
        request_size_calculation(path_value, force=force_refresh)

    # Nach dem Anstoß erneut lesen, damit 'calculating' sofort sichtbar wird.
    row = _size_cache_row(path_value) or row
    if row and row.get("bytes") is not None:
        error = str(row.get("error") or "")
        status = str(row.get("status") or "ok")
        if status == "ok" and _size_value_is_outdated(row, content_changed_at):
            status = "stale"
        if str(row.get("path") or "") in SIZE_CALC_RUNNING:
            status = "calculating"
            error = "Größe wird im Hintergrund aktualisiert. Angezeigt wird der Wert der letzten Prüfung."
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


SIZE_STATUS_PRESENTATION: Dict[str, Tuple[str, str, str]] = {
    "ok": ("aktuell", "ok", "Seit der letzten Größenprüfung wurde kein weiterer echter Job für dieses Ziel beendet."),
    "stale": ("veraltet", "warning", "Nach der letzten Größenprüfung wurde ein echter Job für dieses Ziel beendet. Mit Aktualisieren wird der aktuelle Wert neu ermittelt."),
    "calculating": ("wird aktualisiert", "running", "Die Größe wird im Hintergrund neu berechnet; bis zum Abschluss wird der Wert der letzten Prüfung angezeigt."),
    "queued": ("wartet", "queued", "Die Größenberechnung wartet auf freie Kapazität."),
    "pending": ("vorgemerkt", "queued", "Die Größenberechnung ist für das nächste freie Ruhefenster vorgemerkt."),
    "wartet": ("wartet", "queued", "Die Größenberechnung wartet auf freie Kapazität."),
    "vorgemerkt": ("vorgemerkt", "queued", "Die Größenberechnung ist für das nächste freie Ruhefenster vorgemerkt."),
    "missing": ("Pfad fehlt", "warning", "Das konfigurierte Zielverzeichnis existiert noch nicht."),
    "unknown": ("noch nicht berechnet", "muted", "Für dieses Zielverzeichnis ist noch kein Größenwert vorhanden."),
    "timeout": ("Zeitüberschreitung", "error", "Die letzte Größenberechnung hat das Zeitlimit überschritten."),
    "error": ("Fehler", "error", "Die Größenberechnung ist fehlgeschlagen."),
    "nicht gesetzt": ("nicht gesetzt", "muted", "Für dieses Benutzerskript ist kein Zielverzeichnis zur Größenberechnung hinterlegt."),
}


def size_status_label(status: Any) -> str:
    value = str(status or "").strip()
    return SIZE_STATUS_PRESENTATION.get(value, (value or "unbekannt", "muted", ""))[0]


def size_status_class(status: Any) -> str:
    value = str(status or "").strip()
    return SIZE_STATUS_PRESENTATION.get(value, ("", "muted", ""))[1]


def size_status_title(status: Any) -> str:
    value = str(status or "").strip()
    return SIZE_STATUS_PRESENTATION.get(value, ("", "muted", "Kein zusätzlicher Statushinweis verfügbar."))[2]


def path_size_info(path_value: str, timeout_seconds: int = 20) -> Dict[str, Any]:
    # Rückwärtskompatible API: nicht mehr blockierend berechnen.
    return cached_path_size_info(path_value)


def mirror_stats(mirror: Dict[str, Any], *, auto_refresh: bool = False) -> Dict[str, Any]:
    try:
        return cached_path_size_info(
            mirror.get("target_path") or "",
            auto_refresh=auto_refresh,
            content_changed_at=latest_size_changing_job_finished_at(mirror_id=int(mirror.get("id") or 0)) if mirror.get("id") else "",
        )
    except Exception as exc:
        log_webui_exception(f"mirror_stats {mirror.get('name') if isinstance(mirror, dict) else ''}", exc)
        return {"exists": False, "bytes": None, "size_h": "Unbekannt", "files": None, "dirs": None, "error": f"Größenstatus konnte nicht gelesen werden: {exc}", "status": "error", "calculated_at": "", "started_at": ""}


def configured_size_target_paths(*, existing_directories_only: bool = False) -> List[str]:
    """Return all unique configured mirror/script target directories.

    The same directory can be referenced by more than one profile or script.
    It must only be calculated once per bulk refresh.
    """
    candidates: List[str] = []
    try:
        candidates.extend(str(item.get("target_path") or "") for item in list_mirrors())
    except Exception as exc:
        log_webui_exception("configured_size_target_paths mirrors", exc)
    try:
        candidates.extend(str(item.get("target_path") or "") for item in list_user_scripts())
    except Exception as exc:
        log_webui_exception("configured_size_target_paths user_scripts", exc)

    result: List[str] = []
    seen: set[str] = set()
    for raw_path in candidates:
        path_value = _normalized_size_path(raw_path)
        if not path_value or path_value in seen:
            continue
        path = Path(path_value)
        if existing_directories_only and (not path.exists() or not path.is_dir()):
            continue
        seen.add(path_value)
        result.append(path_value)
    return result


def request_all_configured_size_calculations() -> Dict[str, int]:
    """Start or queue a size refresh for every existing configured directory."""
    paths = configured_size_target_paths(existing_directories_only=True)
    started = 0
    waiting = 0
    for path_value in paths:
        if request_size_calculation(path_value, force=True):
            started += 1
        else:
            waiting += 1
    return {"total": len(paths), "started": started, "waiting": waiting}


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
                "i18n": 1, "diff_mode": "use", "rsync_extra": "none", "extra_options": "",
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
        "manual_extra_options": "",
        "remote_user": "",
        "remote_password_enc": "",
        "rsync_ssh_enabled": 0,
        "rsync_ssh_user": "",
        "rsync_ssh_key": "",
        "rsync_ssh_port": 22,
        "rsync_ssh_accept_new_host_key": 1,
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
    """Extract OpenPGP key IDs/fingerprints that need attention.

    `gpgv: using RSA key ...` allein ist kein Fehler. Gewertet werden nur
    Fehler-Kontexte wie NO_PUBKEY, ERRSIG, EXPKEYSIG, REVKEYSIG oder BADSIG.
    Die Funktion sammelt kurze Key-IDs, Long-Key-IDs und volle Fingerprints,
    damit die spätere Diagnose gegen Master- und Archiv-Keyrings robust
    auflösen kann.
    """
    text = log_text or ""
    missing_ids: List[str] = []
    full_keys: List[str] = []

    def add_missing(value: str) -> None:
        clean = normalize_fingerprint(value)
        if 8 <= len(clean) <= 40 and clean not in missing_ids:
            missing_ids.append(clean)

    def add_full(value: str) -> None:
        clean = normalize_fingerprint(value)
        if 32 <= len(clean) <= 40 and clean not in full_keys:
            full_keys.append(clean)

    for m in re.finditer(r"NO_PUBKEY\s+([A-Fa-f0-9]{8,40})", text, re.I):
        add_missing(m.group(1))
    for m in re.finditer(r"(?:ERRSIG|EXPKEYSIG|REVKEYSIG|BADSIG)\s+([A-Fa-f0-9]{8,40})", text, re.I):
        add_missing(m.group(1))
    for m in re.finditer(r"using\s+(?:RSA|DSA|ECDSA|EDDSA)?\s*key\s+([A-Fa-f0-9]{32,40})", text, re.I):
        add_full(m.group(1))

    # ERRSIG-Zeilen enthalten bei gpgv häufig zuerst die Key-ID und später
    # optional weitere Fingerprint-ähnliche Tokens.
    error_markers = ("NO_PUBKEY", "ERRSIG", "EXPKEYSIG", "REVKEYSIG", "BADSIG")
    for line in text.splitlines():
        if any(marker in line.upper() for marker in error_markers):
            for token in line.split():
                clean = normalize_fingerprint(token)
                if len(clean) >= 32:
                    add_full(clean)
                    add_missing(clean)
                elif 8 <= len(clean) <= 16:
                    add_missing(clean)

    if not missing_ids:
        return []

    results: List[Dict[str, str]] = []
    seen = set()
    for missing in missing_ids:
        full = ""
        for candidate in full_keys:
            if fingerprint_matches(candidate, missing):
                full = candidate
                break
        key = full or missing
        if key not in seen:
            seen.add(key)
            results.append({"key_id": missing, "fingerprint": key, "has_full_fingerprint": "1" if len(key) >= 32 else "0"})
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
    # Keyserver-Imports werden als eigene Quelldateien gespeichert. Dadurch
    # bleiben sie auch nach einem späteren Master-Keyring-Neuaufbau verfügbar
    # und gehen nicht verloren, wenn der Master-Keyring selbst vorher geleert wird.
    dest = unique_keyring_path(filename, KEYSERVER_KEYRING_DIR)
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
        import_keyring_into_master(dest)
        return dest
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def maybe_dearmor_key_file(path: Path) -> Path:
    """Convert ASCII-armored keys to binary .gpg keyrings for gpgv/debmirror."""
    try:
        head = path.read_bytes()[:256]
    except Exception:
        return path
    if b"-----BEGIN PGP PUBLIC KEY BLOCK-----" not in head:
        return path
    dest = path.with_suffix(".gpg")
    # gpg --dearmor darf Eingabe und Ausgabe nicht dieselbe Datei sein.
    # Bei hochgeladenen .gpg-Dateien mit ASCII-Inhalt wird deshalb erst in
    # eine temporäre Datei geschrieben und danach atomar ersetzt.
    output = dest
    tmp_output: Optional[Path] = None
    if dest == path:
        tmp_output = path.with_suffix(path.suffix + ".dearmored.tmp")
        output = tmp_output
    result = subprocess.run(
        ["gpg", "--batch", "--yes", "--dearmor", "--output", str(output), str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        if tmp_output:
            tmp_output.unlink(missing_ok=True)
        raise RuntimeError((result.stdout or "gpg --dearmor fehlgeschlagen.").strip())
    if tmp_output:
        tmp_output.replace(dest)
    elif dest != path:
        path.unlink(missing_ok=True)
    return dest


def assign_keyring_to_mirror(mirror_id: Optional[int], keyring_path: Path, fingerprint: str = "") -> None:
    if not mirror_id:
        return
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        fps = [normalize_fingerprint(x) for x in key_fingerprints(keyring_path)]
        fp = fps[0] if len(fps) == 1 else ""
    if fp:
        try:
            if not fingerprint_in_master(fp):
                import_keyring_into_master(keyring_path)
            assign_master_fingerprint_to_mirror(int(mirror_id), fp)
            return
        except Exception:
            pass
    # Fallback für externe/alte Pfade: direktes Feld weiterhin kompatibel setzen.
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


def user_script_enabled_map() -> Dict[str, bool]:
    raw = load_settings().get("user_script_enabled") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(name): bool(value) for name, value in raw.items()}


def is_user_script_enabled(script_name: str) -> bool:
    script_name = (script_name or "").strip()
    if not script_name:
        return False
    enabled_map = user_script_enabled_map()
    return bool(enabled_map.get(script_name, True))


def set_user_script_enabled(script_name: str, enabled: bool, *, require_existing: bool = True) -> None:
    if require_existing:
        safe_user_script_path(script_name)
    script_name = (script_name or "").strip()
    if not script_name or not SCRIPT_NAME_RE.match(script_name):
        raise ValueError("Ungültiger Skriptname.")
    settings = load_settings()
    enabled_map = settings.get("user_script_enabled") or {}
    if not isinstance(enabled_map, dict):
        enabled_map = {}
    enabled_map[script_name] = 1 if enabled else 0
    settings["user_script_enabled"] = enabled_map
    settings["user_script_enabled_updated_at"] = now_iso()
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
        size_info = cached_path_size_info(
            target_path,
            content_changed_at=latest_size_changing_job_finished_at(script_name=path.name),
        ) if target_path else {"size_h": "-", "status": "nicht gesetzt", "error": "", "calculated_at": ""}
        items.append({
            "name": path.name,
            "path": str(path),
            "size": stat_info.st_size,
            "size_h": human_size(stat_info.st_size),
            "modified_at": dt.datetime.fromtimestamp(stat_info.st_mtime).replace(microsecond=0).isoformat(sep=" "),
            "executable": executable,
            "enabled": is_user_script_enabled(path.name),
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


def user_script_start_block_reason(script_name: str) -> str:
    path = safe_user_script_path(script_name)
    if not is_user_script_enabled(path.name):
        return "Benutzerskript ist deaktiviert."
    if not os.access(path, os.X_OK):
        return "Benutzerskript ist nicht ausführbar. Bitte chmod +x setzen oder das Skript aktiv korrigieren."
    return ""


def build_user_script_command(script_name: str) -> List[str]:
    path = safe_user_script_path(script_name)
    reason = user_script_start_block_reason(path.name)
    if reason:
        raise RuntimeError(reason)
    return [str(path)]


def start_script_job(script_name: str, source: str = "manual") -> int:
    path = safe_user_script_path(script_name)
    reason = user_script_start_block_reason(path.name)
    if reason:
        raise RuntimeError(reason)
    active_for_script = get_running_job_for_script(path.name)
    if active_for_script:
        raise RuntimeError(f"Für dieses Benutzerskript ist bereits Job #{active_for_script['id']} im Zustand {active_for_script['status']} vorhanden.")
    cmd = build_user_script_command(path.name)
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
    validate_mirror_configuration(mirror, require_ssh_key=True)
    root_value = normalize_root_path(mirror["root_path"])

    cmd = [
        "debmirror",
        f"--method={method}",
        f"--host={mirror['host'].strip()}",
        f"--root={root_value}",
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

    extra_options = parse_extra_options(mirror.get("extra_options") or "")
    if bool(int(mirror.get("rsync_ssh_enabled") or 0)):
        extra_options = [item for item in extra_options if item.split("=", 1)[0] != "--rsync-options"]
        extra_options.append(f"--rsync-options={rsync_options_with_ssh(mirror)}")
    extra_flags = {item.split("=", 1)[0] for item in extra_options}
    if not ({"--precleanup", "--nocleanup", "--debmarshal"} & extra_flags):
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

    rsync_extra = (mirror.get("rsync_extra") or "").strip()
    if rsync_extra:
        try:
            normalized_rsync_extra = normalize_rsync_extra_values([rsync_extra])
            if normalized_rsync_extra:
                cmd.append(f"--rsync-extra={normalized_rsync_extra}")
        except ValueError:
            # Backward compatibility for profiles created when the UI incorrectly
            # suggested --bwlimit in the Rsync-Extra field.
            if rsync_extra.startswith("-"):
                if "--rsync-options" not in extra_flags:
                    cmd.append(f"--rsync-options={rsync_extra}")
            else:
                raise

    for extra in extra_options:
        cmd.append(extra)

    for extra in parse_manual_extra_options(str(mirror.get("manual_extra_options") or "")):
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
    reason = mirror_start_block_reason(mirror, dry_run=dry_run)
    if reason:
        raise RuntimeError(reason)
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
        job_meta_row = con.execute("SELECT job_type, script_name, mirror_id FROM jobs WHERE id=?", (job_id,)).fetchone()
    job_type = (job_meta_row["job_type"] if job_meta_row else "mirror") or "mirror"
    script_name = (job_meta_row["script_name"] if job_meta_row else "") or ""
    mirror_id_for_job = int(job_meta_row["mirror_id"]) if job_meta_row and job_meta_row["mirror_id"] is not None else None
    auth_config_path: Optional[Path] = None
    process_env = os.environ.copy()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        started_time = now_iso()
        log.write(f"[{started_time}] Status: running\n")
        log.flush()
        try:
            if job_type == "mirror":
                mirror_for_job = get_mirror(mirror_id_for_job) if mirror_id_for_job is not None else None
                if mirror_for_job:
                    auth_config_path = create_job_auth_config(mirror_for_job, job_id)
                    if auth_config_path:
                        cmd = list(cmd)
                        target_arg = cmd.pop() if cmd else ""
                        cmd.append(f"--config-file={auth_config_path}")
                        if target_arg:
                            cmd.append(target_arg)
                    if bool(int(mirror_for_job.get("rsync_ssh_enabled") or 0)):
                        log.write(f"[{now_iso()}] Rsync verwendet eine explizite SSH-Remote-Shell mit Schlüssel, BatchMode, IdentitiesOnly und persistenter known_hosts-Datei.\n")
                    if auth_config_path:
                        log.write(f"[{now_iso()}] Remote-Zugangsdaten werden über eine temporäre, geschützte debmirror-Konfigurationsdatei mit Dateimodus 0600 bereitgestellt.\n")
                        log.flush()
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
                env=process_env,
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
            for auth_path, label in ((auth_config_path, "Auth-Konfiguration"),):
                if auth_path is None:
                    continue
                try:
                    auth_path.unlink(missing_ok=True)
                except Exception as exc:
                    log.write(f"[{now_iso()}] WARNUNG: Temporäre {label} konnte nicht entfernt werden: {exc}\n")
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
    scripts_by_name = {item["name"]: item for item in list_user_scripts()}
    def allowed(name: str) -> bool:
        item = scripts_by_name.get((name or "").strip())
        return bool(item and item.get("enabled") and item.get("executable"))
    if selection == "all":
        return [item["name"] for item in scripts_by_name.values() if item.get("enabled") and item.get("executable")]
    if selection == "selected":
        return [name for name in split_script_names(str(schedule.get("script_names") or "")) if allowed(name)]
    script_name = str(schedule.get("script_name") or "").strip()
    return [script_name] if script_name and allowed(script_name) else []


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

def validate_hhmm(value: str) -> Tuple[int, int]:
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{2}):(\d{2})", text)
    if not match:
        raise ValueError("Zeitangabe muss im Format HH:MM stehen.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Zeitangabe enthält keine gültige Uhrzeit.")
    return hour, minute


def parse_hhmm(value: str) -> Tuple[int, int]:
    try:
        return validate_hhmm(value)
    except ValueError:
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
        ("ssh", False, "wird für Rsync-Module über SSH-Schlüssel benötigt"),
        ("ssh-keygen", False, "prüft hochgeladene SSH-Privatschlüssel"),
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
        "size_status_label": size_status_label,
        "size_status_class": size_status_class,
        "size_status_title": size_status_title,
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
            m["dashboard_status"] = dashboard_entity_status("mirror", m)
            m["start_block_reason"] = mirror_start_block_reason(m, dry_run=False)
        except Exception as exc:
            log_webui_exception(f"dashboard mirror job state {m.get('name')}", exc)
            m["last_job"] = None
            m["running_job"] = None
            m["schedule_display"] = schedule_display_for_mirror(m) if m.get("id") else "-"
            m["dashboard_status"] = {"label": "error", "class": "error", "title": "Status konnte nicht ermittelt werden"}
            m["start_block_reason"] = "Status konnte nicht ermittelt werden"
        if "start_block_reason" not in m:
            m["start_block_reason"] = mirror_start_block_reason(m, dry_run=False)
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
        dashboard_layout=dashboard_layout_settings(),
    )


@app.route("/dashboard/layout", methods=["GET"])
@require_auth
def dashboard_layout_get():
    return jsonify(dashboard_layout_settings())


@app.route("/dashboard/layout", methods=["POST"])
@require_admin
def dashboard_layout_save():
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "layout": save_dashboard_layout_settings(data)})


@app.route("/dashboard/layout/reset", methods=["POST"])
@require_admin
def dashboard_layout_reset():
    settings = load_settings()
    settings.pop("dashboard_layout", None)
    settings["dashboard_layout_updated_at"] = now_iso()
    save_settings(settings)
    return jsonify({"ok": True, "layout": dashboard_layout_settings()})


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
            m["dashboard_status"] = dashboard_entity_status("mirror", m)
            m["start_block_reason"] = mirror_start_block_reason(m, dry_run=False)
        except Exception as exc:
            log_webui_exception(f"mirrors_page job state {m.get('name')}", exc)
            m["last_job"] = None
            m["running_job"] = None
            m["schedule_display"] = schedule_display_for_mirror(m) if m.get("id") else "-"
            m["dashboard_status"] = {"label": "error", "class": "error", "title": "Status konnte nicht ermittelt werden"}
            m["start_block_reason"] = "Status konnte nicht ermittelt werden"
        if "start_block_reason" not in m:
            m["start_block_reason"] = mirror_start_block_reason(m, dry_run=False)
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
        **mirror_form_option_context(mirror),
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
            if action == "reset_scan_paths":
                settings = load_settings()
                settings.pop("profile_scan_path_variables", None)
                save_settings(settings)
                flash("Suchpfad-Variablen wurden auf Standard zurückgesetzt.", "success")
                return redirect(url_for("profile_generator_settings"))
            if action == "save_scan_paths":
                paths = profile_scan_clean_path_variables(request.form.get("scan_path_variables", ""))
                if not paths:
                    raise ValueError("Bitte mindestens eine Suchpfad-Variable eintragen.")
                save_app_setting_values({"profile_scan_path_variables": paths})
                flash("Suchpfad-Variablen wurden gespeichert.", "success")
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
    scan_paths = get_profile_scan_path_variables()
    return render_template(
        "profile_generator_settings.html",
        generator_json=json.dumps(cfg, indent=2, ensure_ascii=False),
        scan_path_variables="\n".join(scan_paths),
        default_scan_path_variables=PROFILE_SCAN_DEFAULT_PATH_VARIABLES,
        max_scan_path_variables=PROFILE_SCAN_MAX_PATH_VARIABLES,
    )



PROFILE_SCAN_TIMEOUT_SECONDS = 8
PROFILE_SCAN_MAX_BYTES = 512 * 1024
PROFILE_SCAN_USER_AGENT = f"DebMirror-Manager/{APP_VERSION} profile-generator"
PROFILE_SCAN_KEY_NAMES = [
    "Release.key",
    "repo.gpg",
    "repository.gpg",
    "archive-keyring.gpg",
    "keyring.gpg",
    "key.gpg",
    "public.key",
    "public.gpg",
    "signing-key.asc",
    "signing-key.gpg",
    "gpg.key",
    "GPG-KEY",
    "key.asc",
]
PROFILE_SCAN_KEY_DIRS = ["", "keys", "keyrings", "apt", "gpg"]
PROFILE_SCAN_DEFAULT_DEPTH = 5
PROFILE_SCAN_MAX_DEPTH = 10
PROFILE_SCAN_MAX_DIRECTORY_PAGES = 80
PROFILE_SCAN_MAX_LINKS_PER_PAGE = 120
PROFILE_SCAN_MAX_REPOSITORY_ROOTS = 60
PROFILE_SCAN_MAX_KEY_CANDIDATES = 160
PROFILE_SCAN_PACKAGE_PATH_RE = re.compile(
    r"(?:^|\s)(?P<component>[^/\s]+)/(?:(?:debian-installer/)?binary-(?P<arch>[^/\s]+)/Packages(?:\.(?:gz|xz|bz2|lzma|zst))?|source/Sources(?:\.(?:gz|xz|bz2|lzma|zst))?)(?:\s|$)"
)
PROFILE_SCAN_PROBE_SUITES = [
    "stable",
    "testing",
    "unstable",
    "oldstable",
    "sid",
    "latest",
    "current",
    "main",
]
PROFILE_SCAN_DEFAULT_PATH_VARIABLES = [
    "deb",
    "debian",
    "repo",
    "repos",
    "repository",
    "repositories",
    "apt",
    "packages",
    "package",
    "mirror",
    "linux",
    "download",
    "downloads",
    "pub",
    "public",
]
PROFILE_SCAN_MAX_PATH_VARIABLES = 80


class ProfileScanCancelled(Exception):
    pass


def profile_scan_unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def profile_scan_slug(value: str, fallback: str = "repo") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip()).strip("-._")
    return slug[:80] or fallback


def profile_scan_parse_depth(value: Any) -> int:
    try:
        depth = int(value)
    except (TypeError, ValueError):
        depth = PROFILE_SCAN_DEFAULT_DEPTH
    return max(0, min(PROFILE_SCAN_MAX_DEPTH, depth))


def profile_scan_clean_path_variables(values: Any) -> List[str]:
    if isinstance(values, str):
        raw_items = re.split(r"[\r\n,]+", values)
    elif isinstance(values, list):
        raw_items = values
    else:
        raw_items = []
    cleaned: List[str] = []
    for raw in raw_items:
        item = str(raw or "").strip().strip("/")
        if not item or item.startswith(("http://", "https://", "rsync://")):
            continue
        # Nur relative Suchpfade zulassen. Dadurch bleibt der Scan innerhalb der eingegebenen Basisadresse.
        parts = []
        for part in item.split("/"):
            part = part.strip()
            if not part or part in {".", ".."}:
                continue
            safe = re.sub(r"[^A-Za-z0-9_.+-]", "", part)
            if safe:
                parts.append(safe)
        if not parts:
            continue
        cleaned.append("/".join(parts))
    return profile_scan_unique(cleaned)[:PROFILE_SCAN_MAX_PATH_VARIABLES]


def get_profile_scan_path_variables() -> List[str]:
    settings = load_settings()
    stored = settings.get("profile_scan_path_variables")
    if stored:
        merged = profile_scan_clean_path_variables(stored)
        if merged:
            return merged
    return list(PROFILE_SCAN_DEFAULT_PATH_VARIABLES)


def profile_scan_check_cancel(result: Dict[str, Any]) -> None:
    token = result.get("_job_token")
    if not token:
        return
    with PROFILE_SCAN_JOBS_LOCK:
        job = PROFILE_SCAN_JOBS.get(str(token))
        cancelled = bool(job and job.get("cancel_requested"))
    if cancelled:
        profile_scan_status(result, "Prüfung wurde gestoppt.", "warning")
        raise ProfileScanCancelled("Prüfung wurde gestoppt.")


def profile_scan_status(result: Dict[str, Any], message: str, level: str = "info") -> None:
    line = {
        "level": level if level in {"info", "ok", "warning", "error"} else "info",
        "message": str(message),
        "timestamp": now_iso(),
    }
    result.setdefault("status_lines", []).append(line)
    token = result.get("_job_token")
    if token:
        with PROFILE_SCAN_JOBS_LOCK:
            job = PROFILE_SCAN_JOBS.get(str(token))
            if job is not None:
                job.setdefault("status_lines", []).append(line)
                job["updated_at"] = time.time()


def profile_scan_jobs_cleanup() -> None:
    now_ts = time.time()
    with PROFILE_SCAN_JOBS_LOCK:
        old_tokens = [
            token for token, job in PROFILE_SCAN_JOBS.items()
            if now_ts - float(job.get("updated_at") or job.get("created_at") or now_ts) > PROFILE_SCAN_JOB_TTL_SECONDS
        ]
        for token in old_tokens:
            PROFILE_SCAN_JOBS.pop(token, None)
        if len(PROFILE_SCAN_JOBS) > PROFILE_SCAN_JOB_MAX_ENTRIES:
            ordered = sorted(PROFILE_SCAN_JOBS.items(), key=lambda item: float(item[1].get("updated_at") or item[1].get("created_at") or 0))
            for token, _job in ordered[: max(0, len(PROFILE_SCAN_JOBS) - PROFILE_SCAN_JOB_MAX_ENTRIES)]:
                PROFILE_SCAN_JOBS.pop(token, None)


def profile_scan_directory_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def profile_scan_same_scope(base_url: str, candidate_url: str) -> bool:
    base = urllib.parse.urlparse(profile_scan_directory_url(base_url))
    candidate = urllib.parse.urlparse(profile_scan_directory_url(candidate_url))
    if candidate.scheme != base.scheme or candidate.netloc != base.netloc:
        return False
    base_path = base.path or "/"
    cand_path = candidate.path or "/"
    return cand_path == base_path or cand_path.startswith(base_path)


def profile_scan_link_looks_like_directory(link: str, absolute_url: str) -> bool:
    raw = (link or "").split("#", 1)[0].split("?", 1)[0].strip()
    if not raw or raw.startswith(("mailto:", "javascript:")):
        return False
    if raw.endswith("/"):
        return True
    name = Path(urllib.parse.urlparse(absolute_url).path).name
    if not name or name in {"Release", "InRelease"} or name.startswith("Packages") or name.startswith("Sources"):
        return False
    return "." not in name


def profile_scan_collect_directory_pages(base_url: str, max_depth: int, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    start_url = profile_scan_directory_url(base_url)
    queue: List[Tuple[str, int]] = [(start_url, 0)]
    queued = {start_url}
    visited = set()
    pages: List[Dict[str, Any]] = []
    while queue and len(pages) < PROFILE_SCAN_MAX_DIRECTORY_PAGES:
        profile_scan_check_cancel(result)
        current_url, depth = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)
        ok, detail, data, content_type = profile_scan_fetch(current_url)
        if not ok:
            profile_scan_status(result, f"Tiefe {depth}: Verzeichnis nicht lesbar: {current_url.rstrip('/')} ({detail})", "warning")
            continue
        text = profile_scan_decode(data)
        pages.append({
            "url": current_url,
            "depth": depth,
            "html": text,
            "content_type": content_type,
            "detail": detail,
        })
        profile_scan_status(result, f"Tiefe {depth}: Verzeichnis gelesen: {current_url.rstrip('/')} ({detail})", "ok")
        if depth >= max_depth:
            continue
        for link in profile_scan_extract_links(text)[:PROFILE_SCAN_MAX_LINKS_PER_PAGE]:
            profile_scan_check_cancel(result)
            absolute = urllib.parse.urljoin(current_url, link)
            if not profile_scan_link_looks_like_directory(link, absolute):
                continue
            directory_url = profile_scan_directory_url(absolute)
            if directory_url in queued or directory_url in visited:
                continue
            if not profile_scan_same_scope(start_url, directory_url):
                continue
            queue.append((directory_url, depth + 1))
            queued.add(directory_url)
    if queue:
        profile_scan_status(result, f"Scan-Limit erreicht: maximal {PROFILE_SCAN_MAX_DIRECTORY_PAGES} Verzeichnisse geprüft. Weitere Verzeichnisse wurden übersprungen.", "warning")
    return pages


def normalize_profile_scan_url(raw_url: str) -> str:
    raw = (raw_url or "").strip()
    if not raw:
        raise ValueError("Bitte eine Repository-Adresse eingeben.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https", "ftp", "rsync"}:
        raise ValueError("Für die Prüfung sind aktuell http, https, ftp und rsync vorgesehen.")
    if not parsed.netloc:
        raise ValueError("Die Repository-Adresse enthält keinen Host.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Zugangsdaten dürfen nicht in der Repository-Adresse stehen. Verwende dafür die separaten Felder im Profilgenerator.")
    path = parsed.path or "/"
    if parsed.scheme in {"http", "https"} and not path.endswith("/"):
        path += "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def validate_profile_scan_access_mode(normalized_url: str, auth_username: str, auth_password: str, ssh_values: Dict[str, Any]) -> None:
    parsed = urllib.parse.urlparse(normalized_url)
    scheme = parsed.scheme.lower()
    username = (auth_username or "").strip()
    password = auth_password or ""
    ssh_enabled = bool(int(ssh_values.get("rsync_ssh_enabled") or 0))
    if len(username) > 255 or any(ch in username for ch in ("\x00", "\r", "\n")):
        raise ValueError("Der Scan-Benutzer enthält unzulässige Steuerzeichen oder ist zu lang.")
    if len(password) > 4096 or any(ch in password for ch in ("\x00", "\r", "\n")):
        raise ValueError("Das Scan-Passwort enthält unzulässige Steuerzeichen oder ist zu lang.")
    if password and not username:
        raise ValueError("Für ein Scan-Passwort muss ein Benutzername angegeben werden.")
    if scheme == "rsync":
        if username or password:
            raise ValueError("HTTP/FTP-Zugangsdaten können nicht mit einem Rsync-Scan kombiniert werden. Verwende für Rsync ausschließlich die optionale SSH-Schlüsselanmeldung.")
        if ssh_enabled and parsed.port is not None:
            raise ValueError("Bei Rsync über SSH wird der Port ausschließlich im Feld SSH-Port angegeben. Entferne den Port aus der rsync://-Adresse.")
    elif ssh_enabled:
        raise ValueError("SSH-Schlüsselanmeldung kann im Profilgenerator nur mit einer ausdrücklich angegebenen rsync://-Adresse verwendet werden.")
    if (username or password) and scheme not in {"http", "https", "ftp"}:
        raise ValueError("Benutzername und Passwort sind im Profilgenerator nur für HTTP, HTTPS oder FTP vorgesehen.")


def profile_scan_root_path_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    root = (parsed.path or "").strip("/")
    return root or "."


def profile_scan_url_join(base_url: str, *parts: str) -> str:
    url = base_url if base_url.endswith("/") else base_url + "/"
    for part in parts:
        if not part:
            continue
        clean = str(part).strip("/")
        if str(part).endswith("/"):
            clean += "/"
        url = urllib.parse.urljoin(url, clean)
    return url


def profile_scan_resolve_path_variables(variables: Any = None) -> List[str]:
    if variables is None:
        active_variables = get_profile_scan_path_variables()
    else:
        active_variables = profile_scan_clean_path_variables(variables)
    if not active_variables:
        active_variables = list(PROFILE_SCAN_DEFAULT_PATH_VARIABLES)
    return active_variables


def profile_scan_variable_candidate_roots(start_url: str, result: Dict[str, Any], variables: Any = None) -> List[str]:
    base_url = profile_scan_directory_url(start_url)
    active_variables = profile_scan_resolve_path_variables(variables)
    candidates: List[str] = []
    for variable in active_variables:
        candidate_url = profile_scan_url_join(base_url, variable + "/")
        candidates.append(candidate_url)
        profile_scan_status(result, f"Suchpfad-Variable '{variable}' wird relativ zur Eingabe geprüft: {candidate_url.rstrip('/')}", "info")
    candidates = profile_scan_unique(candidates)[:PROFILE_SCAN_MAX_REPOSITORY_ROOTS]
    if candidates:
        profile_scan_status(result, f"Suchpfad-Variablen aktiv: {len(candidates)} zusätzliche Pfade unterhalb von {base_url.rstrip('/')}.", "info")
    return candidates


def profile_scan_variable_dists_candidate_roots(start_url: str, result: Dict[str, Any], variables: Any = None) -> List[str]:
    base_url = profile_scan_directory_url(start_url)
    active_variables = profile_scan_resolve_path_variables(variables)
    candidates: List[str] = []
    for variable in active_variables:
        candidate_url = profile_scan_url_join(base_url, variable + "/", "dists/")
        candidates.append(candidate_url)
        profile_scan_status(result, f"Suchpfad-Variable '{variable}' mit angehängtem dists/ wird geprüft: {candidate_url.rstrip('/')}", "info")
    candidates = profile_scan_unique(candidates)[:PROFILE_SCAN_MAX_REPOSITORY_ROOTS]
    if candidates:
        profile_scan_status(result, f"Zusatzprüfung aktiv: {len(candidates)} Suchpfad-dists/-Pfade werden geprüft.", "info")
    return candidates


def profile_scan_set_auth(username: str = "", password: str = "") -> None:
    PROFILE_SCAN_AUTH_CONTEXT.username = (username or "").strip()
    PROFILE_SCAN_AUTH_CONTEXT.password = password or ""


def profile_scan_set_ssh(enabled: bool = False, user: str = "", key_name: str = "", port: int = 22, accept_new_host_key: bool = True) -> None:
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_enabled = bool(enabled)
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_user = (user or "").strip()
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_key = (key_name or "").strip()
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_port = int(port or 22)
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_accept_new_host_key = bool(accept_new_host_key)


def profile_scan_clear_auth() -> None:
    PROFILE_SCAN_AUTH_CONTEXT.username = ""
    PROFILE_SCAN_AUTH_CONTEXT.password = ""
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_enabled = False
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_user = ""
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_key = ""
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_port = 22
    PROFILE_SCAN_AUTH_CONTEXT.rsync_ssh_accept_new_host_key = True


def profile_scan_auth_values() -> Tuple[str, str]:
    return (str(getattr(PROFILE_SCAN_AUTH_CONTEXT, "username", "") or ""), str(getattr(PROFILE_SCAN_AUTH_CONTEXT, "password", "") or ""))


def profile_scan_ssh_values() -> Dict[str, Any]:
    return {
        "rsync_ssh_enabled": 1 if bool(getattr(PROFILE_SCAN_AUTH_CONTEXT, "rsync_ssh_enabled", False)) else 0,
        "rsync_ssh_user": str(getattr(PROFILE_SCAN_AUTH_CONTEXT, "rsync_ssh_user", "") or ""),
        "rsync_ssh_key": str(getattr(PROFILE_SCAN_AUTH_CONTEXT, "rsync_ssh_key", "") or ""),
        "rsync_ssh_port": int(getattr(PROFILE_SCAN_AUTH_CONTEXT, "rsync_ssh_port", 22) or 22),
        "rsync_ssh_accept_new_host_key": 1 if bool(getattr(PROFILE_SCAN_AUTH_CONTEXT, "rsync_ssh_accept_new_host_key", True)) else 0,
    }


def profile_scan_authenticated_url(url: str, username: str, password: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "ftp" or not username:
        return url
    userinfo = urllib.parse.quote(username, safe="")
    if password:
        userinfo += ":" + urllib.parse.quote(password, safe="")
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, f"{userinfo}@{host}", parsed.path, parsed.params, parsed.query, parsed.fragment))


def profile_scan_redact_auth_detail(value: Any) -> str:
    """Remove scan credentials from transport errors before UI/log output."""
    text = str(value or "")
    username, password = profile_scan_auth_values()
    for secret in (password, urllib.parse.quote(password, safe="") if password else ""):
        if secret:
            text = text.replace(secret, "***")
    if username:
        # Remove user-info from FTP URLs while keeping host/path useful.
        text = re.sub(r"(ftp://)[^/@\s]+@", r"\1", text, flags=re.IGNORECASE)
    return text


def profile_scan_fetch(url: str, max_bytes: int = PROFILE_SCAN_MAX_BYTES) -> Tuple[bool, str, bytes, str]:
    username, password = profile_scan_auth_values()
    request_url = profile_scan_authenticated_url(url, username, password)
    headers = {
        "User-Agent": PROFILE_SCAN_USER_AGENT,
        "Accept": "text/plain,text/html,application/octet-stream,*/*",
    }
    if username and urllib.parse.urlparse(url).scheme in {"http", "https"}:
        basic = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {basic}"
    request_obj = urllib.request.Request(request_url, headers=headers)
    try:
        with urllib.request.urlopen(request_obj, timeout=PROFILE_SCAN_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            content_type = response.headers.get("Content-Type", "")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                data = data[:max_bytes]
            return 200 <= int(status) < 400, f"HTTP {status}", data, content_type
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}", b"", exc.headers.get("Content-Type", "") if exc.headers else ""
    except urllib.error.URLError as exc:
        return False, profile_scan_redact_auth_detail(exc.reason), b"", ""
    except Exception as exc:
        return False, profile_scan_redact_auth_detail(exc), b"", ""


def profile_scan_decode(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def profile_scan_extract_links(html_text: str) -> List[str]:
    links: List[str] = []
    for match in re.finditer(r"href\s*=\s*[\"']([^\"']+)[\"']", html_text or "", re.IGNORECASE):
        href = html.unescape(match.group(1)).strip()
        if not href or href.startswith(("?", "#", "mailto:", "javascript:")):
            continue
        clean = href.split("#", 1)[0].split("?", 1)[0].strip()
        if clean in {"/", "../", "./", "..", "."}:
            continue
        links.append(clean)
    return profile_scan_unique(links)


def profile_scan_parse_release(text: str, fallback_suite: str = "") -> Dict[str, Any]:
    fields: Dict[str, str] = {}
    current_key = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            current_key = ""
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.*)$", line)
        if match:
            current_key = match.group(1)
            fields[current_key] = match.group(2).strip()
        elif current_key and line.startswith(" "):
            fields[current_key] = (fields[current_key] + " " + line.strip()).strip()
    components: List[str] = csv_to_list((fields.get("Components") or "").replace(" ", ","))
    archs: List[str] = csv_to_list((fields.get("Architectures") or "").replace(" ", ","))
    inferred_components: List[str] = []
    inferred_archs: List[str] = []
    for match in PROFILE_SCAN_PACKAGE_PATH_RE.finditer(text or ""):
        component = match.group("component")
        arch = match.group("arch")
        if component:
            inferred_components.append(component)
        if arch:
            inferred_archs.append(arch)
    components = profile_scan_unique(components + inferred_components)
    archs = profile_scan_unique(archs + inferred_archs)
    return {
        "suite": fields.get("Suite") or fallback_suite,
        "codename": fields.get("Codename") or "",
        "origin": fields.get("Origin") or "",
        "label": fields.get("Label") or "",
        "version": fields.get("Version") or "",
        "components": components,
        "archs": archs,
    }


def profile_scan_check_http_transfer(base_url: str, method: str) -> Dict[str, Any]:
    parsed = urllib.parse.urlparse(base_url)
    candidate = urllib.parse.urlunparse((method, parsed.netloc, parsed.path or "/", "", "", ""))
    ok, detail, _data, _ctype = profile_scan_fetch(candidate, max_bytes=2048)
    return {
        "method": method,
        "url": candidate.rstrip("/"),
        "available": ok,
        "status": "available" if ok else "missing",
        "detail": detail,
        "status_class": "ok" if ok else "warning",
    }


def profile_scan_rsync_target_context(base_url: str, relative_path: str = "", trailing_slash: bool = True) -> Dict[str, Any]:
    parsed = urllib.parse.urlparse(base_url)
    host_name = parsed.hostname or parsed.netloc
    if not host_name:
        raise ValueError("Rsync-Adresse enthält keinen Host.")
    root_path = profile_scan_root_path_from_url(base_url)
    if parsed.scheme == "rsync":
        validate_rsync_module_path(root_path)
    relative = (relative_path or "").strip("/")
    if relative:
        relative_parts = relative.split("/")
        if any(part in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9._+@%=-]+", part) for part in relative_parts):
            raise ValueError("Rsync-Prüfpfad enthält unzulässige Segmente.")
    remote_path = root_path if root_path not in {"", "."} else ""
    if relative:
        remote_path = "/".join(part for part in (remote_path, relative) if part)
    if not remote_path:
        raise ValueError("Die Rsync-Adresse muss mindestens einen Modulnamen enthalten.")
    suffix = "/" if trailing_slash else ""
    ssh_values = profile_scan_ssh_values()
    ssh_enabled = bool(int(ssh_values.get("rsync_ssh_enabled") or 0))
    if ssh_enabled:
        mirror_like = {
            "method": "rsync",
            "host": host_name,
            "root_path": root_path,
            "remote_user": "",
            "remote_password_enc": "",
            "extra_options": "",
            **ssh_values,
        }
        validate_rsync_ssh_settings(mirror_like, require_key=True)
        display_host = f"[{host_name}]" if ":" in host_name and not host_name.startswith("[") else host_name
        command_target = f"{display_host}::{remote_path}{suffix}"
        public_url = f"rsync+ssh://{ssh_values.get('rsync_ssh_user')}@{display_host}:{ssh_values.get('rsync_ssh_port')}/{remote_path}{suffix}"
        rsh_option = f"--rsh={rsync_ssh_rsh_command(mirror_like)}"
    else:
        display_host = f"[{host_name}]" if ":" in host_name and not host_name.startswith("[") else host_name
        # Nur ein ausdrücklich eingegebener rsync://-Port gehört zum Rsync-Ziel.
        # HTTP-/HTTPS-Ports dürfen beim ergänzenden Rsync-Test nicht übernommen werden.
        netloc = display_host
        if parsed.scheme == "rsync" and parsed.port:
            netloc += f":{parsed.port}"
        public_url = urllib.parse.urlunparse(("rsync", netloc, "/" + remote_path + suffix, "", "", ""))
        command_target = public_url
        rsh_option = ""
    return {
        "command_target": command_target,
        "public_url": public_url,
        "rsh_option": rsh_option,
        "root_path": root_path,
        "remote_path": remote_path,
        "ssh_enabled": ssh_enabled,
    }


def profile_scan_rsync_run(base_url: str, relative_path: str = "", trailing_slash: bool = True, list_only: bool = False, destination: str = "") -> subprocess.CompletedProcess:
    if not shutil.which("rsync"):
        raise ValueError("rsync ist im WebUI-Container nicht verfügbar.")
    context = profile_scan_rsync_target_context(base_url, relative_path, trailing_slash=trailing_slash)
    command = ["rsync", "--timeout=5", "--no-motd"]
    if list_only:
        command.append("--list-only")
    if context["rsh_option"]:
        command.append(context["rsh_option"])
    command.append(context["command_target"])
    if destination:
        command.append(destination)
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROFILE_SCAN_TIMEOUT_SECONDS,
        check=False,
    )


def profile_scan_rsync_list_directories(base_url: str, relative_path: str) -> List[str]:
    completed = profile_scan_rsync_run(base_url, relative_path, trailing_slash=True, list_only=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"Exit-Code {completed.returncode}").strip().splitlines()[0][:240]
        raise ValueError("Rsync-Verzeichnis konnte nicht gelesen werden: " + profile_scan_redact_auth_detail(detail))
    directories: List[str] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or line[0] not in {"d", "l"}:
            continue
        parts = line.split(maxsplit=4)
        if len(parts) < 5:
            continue
        name = parts[4].strip().rstrip("/")
        if name in {"", ".", ".."} or "/" in name:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name) and name not in directories:
            directories.append(name)
    return directories


def profile_scan_rsync_fetch_file(base_url: str, relative_path: str, max_bytes: int = PROFILE_SCAN_MAX_BYTES) -> Tuple[bool, str, bytes]:
    temp_dir = Path(tempfile.mkdtemp(prefix="debmirror-rsync-scan-"))
    destination = temp_dir / "remote-file"
    try:
        completed = profile_scan_rsync_run(base_url, relative_path, trailing_slash=False, destination=str(destination))
        if completed.returncode != 0 or not destination.is_file():
            detail = (completed.stderr or completed.stdout or f"Exit-Code {completed.returncode}").strip().splitlines()[0][:240]
            return False, profile_scan_redact_auth_detail(detail), b""
        if destination.stat().st_size > max_bytes:
            return False, f"Datei überschreitet das Scan-Limit von {max_bytes} Bytes.", b""
        return True, "OK", destination.read_bytes()
    except Exception as exc:
        return False, profile_scan_redact_auth_detail(exc), b""
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def profile_scan_check_rsync_transfer(base_url: str) -> Dict[str, Any]:
    try:
        context = profile_scan_rsync_target_context(base_url)
    except Exception as exc:
        return {
            "method": "rsync",
            "url": base_url.rstrip("/"),
            "available": False,
            "status": "missing",
            "detail": str(exc),
            "status_class": "warning",
        }
    if not shutil.which("rsync"):
        return {
            "method": "rsync",
            "url": context["public_url"].rstrip("/"),
            "available": False,
            "status": "unknown",
            "detail": "rsync ist im WebUI-Container nicht verfügbar; Transferart wurde nicht geprüft.",
            "status_class": "warning",
        }
    try:
        completed = profile_scan_rsync_run(base_url, list_only=True)
        ok = completed.returncode == 0
        raw_detail = "OK" if ok else (completed.stderr or completed.stdout or f"Exit-Code {completed.returncode}").strip().splitlines()[0][:180]
        return {
            "method": "rsync",
            "url": context["public_url"].rstrip("/"),
            "available": ok,
            "status": "available" if ok else "missing",
            "detail": profile_scan_redact_auth_detail(raw_detail),
            "status_class": "ok" if ok else "warning",
        }
    except Exception as exc:
        return {
            "method": "rsync",
            "url": context["public_url"].rstrip("/"),
            "available": False,
            "status": "unknown",
            "detail": profile_scan_redact_auth_detail(exc),
            "status_class": "warning",
        }


def profile_scan_rsync_release_url(base_url: str, relative_path: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    root = profile_scan_root_path_from_url(base_url).strip("/")
    path = "/" + "/".join(part for part in (root, relative_path.strip("/")) if part)
    return urllib.parse.urlunparse(("rsync", parsed.netloc, path, "", "", ""))


def profile_scan_scan_rsync_repository(base_url: str, result: Dict[str, Any]) -> Dict[str, Any]:
    transfer = profile_scan_check_rsync_transfer(base_url)
    result["transfers"].append(transfer)
    result["rsync_available"] = bool(transfer.get("available"))
    if not transfer.get("available"):
        result["warnings"].append("Rsync-Ziel konnte nicht gelesen werden; eine Profilerzeugung ist deshalb nicht möglich.")
        profile_scan_status(result, f"Rsync-Verbindung fehlgeschlagen: {transfer.get('detail') or 'unbekannter Fehler'}", "error")
        return result
    profile_scan_status(result, "Rsync-Verbindung hergestellt. Prüfe gezielt dists/ und die Release-Dateien.", "ok")
    try:
        suite_names = profile_scan_rsync_list_directories(base_url, "dists")
    except Exception as exc:
        result["warnings"].append(str(exc))
        profile_scan_status(result, str(exc), "error")
        return result
    if not suite_names:
        result["warnings"].append("Im Rsync-Ziel wurde kein lesbares dists/-Verzeichnis mit Suites gefunden.")
        profile_scan_status(result, "Kein lesbares dists/-Verzeichnis mit Suites gefunden.", "error")
        return result
    if len(suite_names) > 80:
        result["warnings"].append("Es wurden mehr als 80 Suite-Verzeichnisse gefunden; für den Scan werden die ersten 80 ausgewertet.")
        suite_names = suite_names[:80]
    suites: List[Dict[str, Any]] = []
    for suite_name in suite_names:
        profile_scan_check_cancel(result)
        release_text = ""
        release_name = ""
        release_detail = ""
        for candidate in ("InRelease", "Release"):
            ok, detail, data = profile_scan_rsync_fetch_file(base_url, f"dists/{suite_name}/{candidate}")
            if ok and data:
                release_text = profile_scan_decode(data)
                release_name = candidate
                release_detail = detail
                break
        if not release_text:
            profile_scan_status(result, f"Suite {suite_name}: keine lesbare InRelease-/Release-Datei ({release_detail or 'nicht vorhanden'}).", "warning")
            continue
        meta = profile_scan_parse_release(release_text, fallback_suite=suite_name)
        if not meta.get("components") or not meta.get("archs"):
            profile_scan_status(result, f"Suite {suite_name}: Release-Datei gelesen, aber Komponenten oder Architekturen fehlen.", "warning")
            continue
        suites.append({
            "name": suite_name,
            "suite": meta.get("suite") or suite_name,
            "codename": meta.get("codename") or "",
            "origin": meta.get("origin") or "",
            "label": meta.get("label") or "",
            "version": meta.get("version") or "",
            "components": meta.get("components") or [],
            "archs": meta.get("archs") or [],
            "release_url": profile_scan_rsync_release_url(base_url, f"dists/{suite_name}/{release_name}"),
            "signed": release_name == "InRelease",
            "repo_base_url": base_url.rstrip("/"),
            "repo_root_path": profile_scan_root_path_from_url(base_url),
        })
        profile_scan_status(result, f"Suite über Rsync gefunden: {suite_name} ({release_name}, {len(meta.get('components') or [])} Komponenten, {len(meta.get('archs') or [])} Architekturen).", "ok")
    result["suites"] = suites
    all_components: List[str] = []
    all_archs: List[str] = []
    for suite in suites:
        all_components.extend(suite.get("components") or [])
        all_archs.extend(suite.get("archs") or [])
    result["components"] = profile_scan_unique(all_components)
    result["archs"] = profile_scan_unique(all_archs)
    result["repository_roots"] = [{
        "base_url": base_url.rstrip("/"),
        "root_path": profile_scan_root_path_from_url(base_url),
        "suite_count": len(suites),
        "components": result["components"],
        "archs": result["archs"],
    }] if suites else []
    result["gpg_keys"] = []
    result["usable"] = bool(suites and result["components"] and result["archs"])
    if result["usable"]:
        profile_scan_status(result, f"Rsync-Prüfung abgeschlossen: verwendbares Repository mit {len(suites)} Suite(s).", "ok")
    else:
        result["warnings"].append("Über Rsync wurde keine vollständig verwendbare APT-Repository-Struktur erkannt.")
        profile_scan_status(result, "Rsync-Prüfung abgeschlossen: keine vollständig verwendbare APT-Repository-Struktur erkannt.", "error")
    return result

def profile_scan_key_candidate_name(value: str) -> bool:
    name = Path(urllib.parse.urlparse(value).path).name.lower()
    return bool(
        name.endswith((".gpg", ".asc", ".key"))
        or "gpg" in name
        or "key" in name
        or "keyring" in name
    )


def profile_scan_find_gpg_keys(base_url: str, base_html: str = "", directory_pages: Optional[List[Dict[str, Any]]] = None, result: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    pages = directory_pages or []
    candidate_dirs = profile_scan_unique([base_url] + [page.get("url", "") for page in pages])[:12]
    candidates: List[str] = []
    for directory_url in candidate_dirs:
        for key_dir in PROFILE_SCAN_KEY_DIRS:
            for name in PROFILE_SCAN_KEY_NAMES:
                if key_dir:
                    candidates.append(profile_scan_url_join(directory_url, key_dir + "/", name))
                else:
                    candidates.append(profile_scan_url_join(directory_url, name))
    html_sources = [base_html] + [page.get("html", "") for page in pages]
    base_for_links = [base_url] + [page.get("url", base_url) for page in pages]
    for html_text, page_url in zip(html_sources, base_for_links):
        for link in profile_scan_extract_links(html_text):
            if profile_scan_key_candidate_name(link):
                candidates.append(urllib.parse.urljoin(page_url, link))
    result_items: List[Dict[str, Any]] = []
    unique_candidates = profile_scan_unique(candidates)[:PROFILE_SCAN_MAX_KEY_CANDIDATES]
    if result is not None:
        profile_scan_status(result, f"GPG-Key-Prüfung: {len(unique_candidates)} mögliche Key-Pfade werden geprüft.", "info")
    for url in unique_candidates:
        profile_scan_check_cancel(result)
        ok, detail, data, content_type = profile_scan_fetch(url, max_bytes=65536)
        if not ok:
            continue
        text_sample = profile_scan_decode(data[:4096])
        likely_key = profile_scan_key_candidate_name(url) or "BEGIN PGP PUBLIC KEY BLOCK" in text_sample
        if not likely_key:
            continue
        item = {
            "url": url.rstrip("/"),
            "name": Path(urllib.parse.urlparse(url).path).name or url.rstrip("/").rsplit("/", 1)[-1],
            "content_type": content_type or "unbekannt",
            "detail": detail,
        }
        result_items.append(item)
        if result is not None:
            profile_scan_status(result, f"GPG-Key gefunden: {item['url']}", "ok")
    return result_items


def profile_scan_suite_names_from_listing(dists_url: str, html_text: str) -> List[str]:
    names: List[str] = []
    for link in profile_scan_extract_links(html_text):
        path = urllib.parse.urlparse(urllib.parse.urljoin(dists_url, link)).path.rstrip("/")
        name = path.rsplit("/", 1)[-1]
        if not name or name in {"by-hash", "Release", "InRelease"}:
            continue
        if re.search(r"[A-Za-z0-9_.+-]", name):
            names.append(name)
    return profile_scan_unique(names)


def profile_scan_release_suite_from_url(root_url: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    directory_url = profile_scan_directory_url(root_url)
    parsed = urllib.parse.urlparse(directory_url)
    path_parts = [part for part in (parsed.path or "/").strip("/").split("/") if part]
    if len(path_parts) < 2 or path_parts[-2] != "dists":
        return None
    suite_name = path_parts[-1]
    repo_path = "/" + "/".join(path_parts[:-2]) + "/" if len(path_parts) > 2 else "/"
    repo_base_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, repo_path, "", "", ""))
    release_text = ""
    release_url = ""
    signed = False
    for release_name in ("InRelease", "Release"):
        candidate_url = urllib.parse.urljoin(directory_url, release_name)
        ok, detail, data, _ctype = profile_scan_fetch(candidate_url)
        if ok and data:
            release_text = profile_scan_decode(data)
            release_url = candidate_url
            signed = release_name == "InRelease"
            profile_scan_status(result, f"Direkte Suite erkannt: {suite_name} unter {directory_url.rstrip('/')} ({release_name}, {detail})", "ok")
            break
    if not release_text:
        return None
    meta = profile_scan_parse_release(release_text, fallback_suite=suite_name)
    return {
        "name": suite_name,
        "suite": meta.get("suite") or suite_name,
        "codename": meta.get("codename") or "",
        "origin": meta.get("origin") or "",
        "label": meta.get("label") or "",
        "version": meta.get("version") or "",
        "components": meta.get("components") or [],
        "archs": meta.get("archs") or [],
        "release_url": release_url,
        "signed": signed,
        "repo_base_url": repo_base_url.rstrip("/"),
        "repo_root_path": profile_scan_root_path_from_url(repo_base_url),
    }


def profile_scan_suite_from_dists_probe(root_url: str, suite_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    repo_base_url = profile_scan_directory_url(root_url)
    suite_url = profile_scan_url_join(repo_base_url, "dists/", suite_name + "/")
    release_text = ""
    release_url = ""
    signed = False
    for release_name in ("InRelease", "Release"):
        candidate_url = urllib.parse.urljoin(suite_url, release_name)
        ok, detail, data, _ctype = profile_scan_fetch(candidate_url)
        if ok and data:
            release_text = profile_scan_decode(data)
            release_url = candidate_url
            signed = release_name == "InRelease"
            profile_scan_status(result, f"Suite per Direktprüfung gefunden: {suite_name} ({release_name}, {detail})", "ok")
            break
    if not release_text:
        return None
    meta = profile_scan_parse_release(release_text, fallback_suite=suite_name)
    return {
        "name": suite_name,
        "suite": meta.get("suite") or suite_name,
        "codename": meta.get("codename") or "",
        "origin": meta.get("origin") or "",
        "label": meta.get("label") or "",
        "version": meta.get("version") or "",
        "components": meta.get("components") or [],
        "archs": meta.get("archs") or [],
        "release_url": release_url,
        "signed": signed,
        "repo_base_url": repo_base_url.rstrip("/"),
        "repo_root_path": profile_scan_root_path_from_url(repo_base_url),
    }


def profile_scan_is_dists_directory_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(profile_scan_directory_url(url))
    path_parts = [part for part in (parsed.path or "/").strip("/").split("/") if part]
    return bool(path_parts and path_parts[-1] == "dists")


def profile_scan_repo_base_from_dists_url(dists_url: str) -> str:
    parsed = urllib.parse.urlparse(profile_scan_directory_url(dists_url))
    path_parts = [part for part in (parsed.path or "/").strip("/").split("/") if part]
    if path_parts and path_parts[-1] == "dists":
        path_parts = path_parts[:-1]
    repo_path = "/" + "/".join(path_parts) + "/" if path_parts else "/"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, repo_path, "", "", ""))


def profile_scan_scan_dists_directory(dists_url: str, result: Dict[str, Any], source_label: str = "dists/") -> List[Dict[str, Any]]:
    dists_url = profile_scan_directory_url(dists_url)
    repo_base_url = profile_scan_repo_base_from_dists_url(dists_url)
    dists_ok, dists_detail, dists_data, _dists_content_type = profile_scan_fetch(dists_url)
    if not dists_ok:
        profile_scan_status(result, f"Kein lesbares dists/-Verzeichnis für {source_label}: {dists_url.rstrip('/')} ({dists_detail})", "info")
        return []
    suite_names = profile_scan_suite_names_from_listing(dists_url, profile_scan_decode(dists_data))
    if not suite_names:
        profile_scan_status(result, f"dists/ gefunden, aber keine Suites im Listing erkannt: {dists_url.rstrip('/')}. Prüfe Standard-Suiten direkt.", "warning")
        suite_names = PROFILE_SCAN_PROBE_SUITES
    else:
        profile_scan_status(result, f"dists/ gefunden: {dists_url.rstrip('/')} | Suites: {', '.join(suite_names[:12])}{' ...' if len(suite_names) > 12 else ''}", "ok")
    suites: List[Dict[str, Any]] = []
    for suite_name in suite_names[:80]:
        profile_scan_check_cancel(result)
        suite_url = profile_scan_url_join(dists_url, suite_name + "/")
        release_text = ""
        release_url = ""
        signed = False
        for release_name in ("InRelease", "Release"):
            candidate_url = urllib.parse.urljoin(suite_url, release_name)
            ok, detail, data, _ctype = profile_scan_fetch(candidate_url)
            if ok and data:
                release_text = profile_scan_decode(data)
                release_url = candidate_url
                signed = release_name == "InRelease"
                profile_scan_status(result, f"Suite {suite_name}: {release_name} gelesen ({detail})", "ok")
                break
        if not release_text:
            profile_scan_status(result, f"Suite {suite_name}: keine Release/InRelease-Datei gefunden.", "warning")
            continue
        meta = profile_scan_parse_release(release_text, fallback_suite=suite_name)
        suites.append({
            "name": suite_name,
            "suite": meta.get("suite") or suite_name,
            "codename": meta.get("codename") or "",
            "origin": meta.get("origin") or "",
            "label": meta.get("label") or "",
            "version": meta.get("version") or "",
            "components": meta.get("components") or [],
            "archs": meta.get("archs") or [],
            "release_url": release_url,
            "signed": signed,
            "repo_base_url": repo_base_url.rstrip("/"),
            "repo_root_path": profile_scan_root_path_from_url(repo_base_url),
        })
    return suites


def profile_scan_scan_dists_root(root_url: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    root_url = profile_scan_directory_url(root_url)
    dists_url = root_url if profile_scan_is_dists_directory_url(root_url) else profile_scan_url_join(root_url, "dists/")
    suites = profile_scan_scan_dists_directory(dists_url, result, "Repository-Basis")
    if not suites and not profile_scan_is_dists_directory_url(root_url):
        profile_scan_status(result, f"Kein dists/ an dieser Basis: {root_url.rstrip('/')}", "info")
    return suites


def profile_scan_scan_flat_root(root_url: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    flat_release_text = ""
    flat_release_url = ""
    for release_name in ("InRelease", "Release"):
        candidate_url = urllib.parse.urljoin(profile_scan_directory_url(root_url), release_name)
        ok, detail, data, _ctype = profile_scan_fetch(candidate_url)
        if ok and data:
            flat_release_text = profile_scan_decode(data)
            flat_release_url = candidate_url
            profile_scan_status(result, f"Flache Release-Datei gefunden: {candidate_url} ({detail})", "ok")
            break
    package_candidates = [
        "Packages.gz",
        "Packages.xz",
        "Packages.bz2",
        "Packages",
        "binary-amd64/Packages.gz",
        "binary-arm64/Packages.gz",
        "binary-all/Packages.gz",
    ]
    package_hits = []
    for package_name in package_candidates:
        profile_scan_check_cancel(result)
        package_url = profile_scan_url_join(root_url, package_name)
        ok, detail, _data, _ctype = profile_scan_fetch(package_url, max_bytes=2048)
        if ok:
            package_hits.append({"path": package_name, "url": package_url, "detail": detail})
            profile_scan_status(result, f"Flache Packages-Datei gefunden: {package_url} ({detail})", "ok")
    if not flat_release_text and not package_hits:
        return None
    meta = profile_scan_parse_release(flat_release_text, fallback_suite=".") if flat_release_text else {"components": [], "archs": [], "suite": ".", "codename": ""}
    return {
        "release_url": flat_release_url,
        "components": meta.get("components") or [],
        "archs": meta.get("archs") or [],
        "packages": package_hits,
        "repo_base_url": root_url.rstrip("/"),
        "repo_root_path": profile_scan_root_path_from_url(root_url),
    }


def profile_scan_same_url_with_scheme(url: str, scheme: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def profile_scan_consolidate_roots(suites: List[Dict[str, Any]], fallback_url: str) -> List[Dict[str, Any]]:
    consolidated_roots: List[Dict[str, Any]] = []
    for suite in suites:
        root_base_url = profile_scan_directory_url(suite.get("repo_base_url") or fallback_url)
        existing = next((item for item in consolidated_roots if profile_scan_directory_url(item.get("base_url", "")) == root_base_url), None)
        if existing is None:
            existing = {
                "base_url": root_base_url.rstrip("/"),
                "root_path": profile_scan_root_path_from_url(root_base_url),
                "suite_count": 0,
                "components": [],
                "archs": [],
            }
            consolidated_roots.append(existing)
        existing["suite_count"] = int(existing.get("suite_count") or 0) + 1
        existing["components"] = profile_scan_unique(list(existing.get("components") or []) + list(suite.get("components") or []))
        existing["archs"] = profile_scan_unique(list(existing.get("archs") or []) + list(suite.get("archs") or []))
    return consolidated_roots


def scan_apt_repository_url(raw_url: str, max_depth: Any = PROFILE_SCAN_DEFAULT_DEPTH, live_token: str = "", scan_path_variables: Any = None) -> Dict[str, Any]:
    depth = profile_scan_parse_depth(max_depth)
    input_has_scheme = bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", (raw_url or "").strip()))
    start_url = normalize_profile_scan_url(raw_url)
    start_parsed = urllib.parse.urlparse(start_url)
    active_scan_path_variables = profile_scan_clean_path_variables(scan_path_variables) if scan_path_variables is not None else get_profile_scan_path_variables()
    if not active_scan_path_variables:
        active_scan_path_variables = list(PROFILE_SCAN_DEFAULT_PATH_VARIABLES)
    result: Dict[str, Any] = {
        "input_url": raw_url,
        "scan_start_url": start_url.rstrip("/"),
        "base_url": start_url.rstrip("/"),
        "method": start_parsed.scheme,
        "host": start_parsed.netloc,
        "root_path": profile_scan_root_path_from_url(start_url),
        "scan_depth": depth,
        "transfers": [],
        "suites": [],
        "repository_roots": [],
        "components": [],
        "archs": [],
        "gpg_keys": [],
        "warnings": [],
        "flat_repo": None,
        "usable": False,
        "rsync_available": False,
        "status_lines": [],
        "scan_path_variables": active_scan_path_variables,
        "_job_token": live_token,
    }
    profile_scan_status(result, f"Scan gestartet: {start_url.rstrip('/')} | Verzeichnistiefe: {depth}", "info")
    profile_scan_status(result, f"Aktive Suchpfad-Variablen aus den Generator-Einstellungen: {', '.join(active_scan_path_variables[:12])}{' ...' if len(active_scan_path_variables) > 12 else ''}", "info")

    if start_parsed.scheme == "rsync":
        return profile_scan_scan_rsync_repository(start_url, result)

    content_start_urls = [start_url]
    if not input_has_scheme and start_parsed.scheme == "https":
        # Zugangsdaten dürfen nicht automatisch von HTTPS auf unverschlüsseltes
        # HTTP weitergereicht werden. Ohne Auth bleibt der bewährte Fallback aktiv.
        auth_username, _auth_password = profile_scan_auth_values()
        if auth_username:
            profile_scan_status(result, "Keine Protokollangabe erkannt. Wegen verwendeter Zugangsdaten wird aus Sicherheitsgründen kein automatischer HTTP-Fallback ausgeführt. Für HTTP bitte das Protokoll ausdrücklich angeben.", "warning")
        else:
            http_start_url = profile_scan_same_url_with_scheme(start_url, "http")
            if http_start_url not in content_start_urls:
                content_start_urls.append(http_start_url)
                profile_scan_status(result, f"Keine Protokollangabe erkannt. Falls HTTPS nichts liefert, wird zusätzlich HTTP geprüft: {http_start_url.rstrip('/')}", "info")

    all_suites: List[Dict[str, Any]] = []
    all_candidate_roots: List[str] = []
    all_directory_pages: List[Dict[str, Any]] = []
    selected_base_url = start_url

    def scan_candidate_roots(roots: List[str], source_label: str) -> List[Dict[str, Any]]:
        found_suites: List[Dict[str, Any]] = []
        for root_url in roots:
            profile_scan_check_cancel(result)
            direct_suite = profile_scan_release_suite_from_url(root_url, result)
            if direct_suite:
                suites = [direct_suite]
            elif profile_scan_is_dists_directory_url(root_url):
                # Wenn das Verzeichnislisting oder eine Suchpfad-Zusatzprüfung direkt auf .../dists/ zeigt,
                # ist die Repository-Basis die Ebene oberhalb von dists/.
                suites = profile_scan_scan_dists_directory(root_url, result, source_label)
            else:
                suites = profile_scan_scan_dists_root(root_url, result)
            if suites:
                profile_scan_status(result, f"Repository über {source_label} gefunden: {profile_scan_directory_url(suites[0].get('repo_base_url') or root_url).rstrip('/')}", "ok")
                found_suites.extend(suites)
        return found_suites

    for index, content_start_url in enumerate(content_start_urls):
        profile_scan_check_cancel(result)
        if index > 0:
            profile_scan_status(result, f"Starte Fallback-Inhaltsprüfung mit anderem Protokoll: {content_start_url.rstrip('/')}", "warning")
        directory_pages = profile_scan_collect_directory_pages(content_start_url, depth, result)
        all_directory_pages.extend(directory_pages)
        if not directory_pages:
            result["warnings"].append(f"Basisadresse konnte nicht als Verzeichnislisting gelesen werden: {content_start_url.rstrip('/')}. Direkte Standardpfade wie dists/ werden trotzdem geprüft.")
            profile_scan_status(result, f"Kein lesbares Verzeichnislisting gefunden; prüfe direkte Standardpfade an dieser Basis: {content_start_url.rstrip('/')}", "warning")
            candidate_roots = [profile_scan_directory_url(content_start_url)]
        else:
            candidate_roots = profile_scan_unique([page.get("url", "") for page in directory_pages])[:PROFILE_SCAN_MAX_REPOSITORY_ROOTS]
        all_candidate_roots.extend(candidate_roots)
        profile_scan_status(result, f"Repository-Basisprüfung ({urllib.parse.urlparse(content_start_url).scheme}): {len(candidate_roots)} mögliche Verzeichnisse werden geprüft.", "info")
        suites = scan_candidate_roots(candidate_roots, "Hauptprüfung")
        if not suites:
            profile_scan_status(result, "Hauptverzeichnis ohne verwendbares dists/-Repository. Prüfe konfigurierte Suchpfad-Variablen.", "warning")
            variable_roots = [root for root in profile_scan_variable_candidate_roots(content_start_url, result, active_scan_path_variables) if root not in candidate_roots]
            all_candidate_roots.extend(variable_roots)
            if variable_roots:
                suites = scan_candidate_roots(variable_roots, "Suchpfad-Variable")
        if not suites:
            profile_scan_status(result, "Auch die Suchpfad-Variablen lieferten kein Repository. Prüfe zusätzlich Suchpfad-Variable + dists/.", "warning")
            variable_dists_roots = [
                root for root in profile_scan_variable_dists_candidate_roots(content_start_url, result, active_scan_path_variables)
                if root not in candidate_roots and root not in all_candidate_roots
            ]
            all_candidate_roots.extend(variable_dists_roots)
            if variable_dists_roots:
                suites = scan_candidate_roots(variable_dists_roots, "Suchpfad-Variable + dists/")
        if suites:
            all_suites.extend(suites)
            selected_base_url = profile_scan_directory_url(suites[0].get("repo_base_url") or content_start_url)
            if index > 0:
                profile_scan_status(result, f"Repository wurde über Fallback-Protokoll gefunden. Aktive Basis: {selected_base_url.rstrip('/')}", "ok")
            break

    all_candidate_roots = profile_scan_unique(all_candidate_roots)[:PROFILE_SCAN_MAX_REPOSITORY_ROOTS]

    if all_suites:
        unique_suites: List[Dict[str, Any]] = []
        seen_suite_keys = set()
        for suite in all_suites:
            suite_key = (profile_scan_directory_url(suite.get("repo_base_url", "")), suite.get("name", ""))
            if suite_key in seen_suite_keys:
                continue
            seen_suite_keys.add(suite_key)
            unique_suites.append(suite)
        all_suites = unique_suites
        result["repository_roots"] = profile_scan_consolidate_roots(all_suites, selected_base_url)
        selected_base_url = profile_scan_directory_url(all_suites[0].get("repo_base_url") or selected_base_url)
        # Alle gefundenen Suites bleiben im Ergebnis erhalten. Die WebUI filtert
        # sie anhand der vom Benutzer ausgewählten Repository-Basis.
        result["suites"] = all_suites
        result["active_base_url"] = selected_base_url.rstrip("/")
        if profile_scan_directory_url(start_url) != selected_base_url:
            profile_scan_status(result, f"Aktive Repository-Basis auf gefundenen Pfad gesetzt: {selected_base_url.rstrip('/')}", "ok")
        if len(result["repository_roots"]) > 1:
            result["warnings"].append("Mehrere Repository-Basen gefunden. Wähle im Prüfergebnis die gewünschte Basis aus; Suites, Komponenten und Architekturen werden passend dazu gefiltert.")
            profile_scan_status(result, "Mehrere Repository-Basen erkannt; die gewünschte Basis kann jetzt vor der Profilerzeugung ausgewählt werden.", "warning")
    else:
        profile_scan_status(result, "Kein vollständiges dists/-Repository gefunden. Prüfe flache APT-Strukturen.", "warning")
        for root_url in all_candidate_roots or [profile_scan_directory_url(start_url)]:
            profile_scan_check_cancel(result)
            flat = profile_scan_scan_flat_root(root_url, result)
            if flat:
                result["flat_repo"] = flat
                selected_base_url = profile_scan_directory_url(flat.get("repo_base_url") or root_url)
                result["warnings"].append("Flache APT-Struktur erkannt. Die automatische Profilerzeugung wird dafür noch nicht sicher aktiviert; nutze bei Bedarf die normale Profilbearbeitung.")
                break

    selected_parsed = urllib.parse.urlparse(selected_base_url)
    result["base_url"] = selected_base_url.rstrip("/")
    result["method"] = selected_parsed.scheme
    result["host"] = selected_parsed.netloc
    result["root_path"] = profile_scan_root_path_from_url(selected_base_url)

    checked_transfer_methods: List[str] = []
    for method in [selected_parsed.scheme, "https", "http"]:
        if method in {"http", "https"} and method not in checked_transfer_methods:
            result["transfers"].append(profile_scan_check_http_transfer(selected_base_url, method))
            checked_transfer_methods.append(method)
        elif method == "ftp" and method not in checked_transfer_methods:
            ok, detail, _data, _ctype = profile_scan_fetch(selected_base_url, max_bytes=2048)
            result["transfers"].append({"method": "ftp", "url": selected_base_url.rstrip("/"), "available": ok, "status": "available" if ok else "missing", "detail": detail, "status_class": "ok" if ok else "warning"})
            checked_transfer_methods.append(method)
    rsync_transfer = profile_scan_check_rsync_transfer(selected_base_url)
    result["transfers"].append(rsync_transfer)
    result["rsync_available"] = bool(rsync_transfer.get("available"))

    all_components: List[str] = []
    all_archs: List[str] = []
    for suite in result["suites"]:
        all_components.extend(suite.get("components") or [])
        all_archs.extend(suite.get("archs") or [])
    if result.get("flat_repo"):
        all_components.extend(result["flat_repo"].get("components") or [])
        all_archs.extend(result["flat_repo"].get("archs") or [])
    result["components"] = profile_scan_unique(all_components)
    result["archs"] = profile_scan_unique(all_archs)

    base_html = ""
    for page in all_directory_pages:
        if profile_scan_directory_url(page.get("url", "")) == selected_base_url:
            base_html = page.get("html", "")
            break
    result["gpg_keys"] = profile_scan_find_gpg_keys(selected_base_url, base_html, all_directory_pages, result)
    if not result["gpg_keys"]:
        result["warnings"].append("Kein möglicher GPG-Key an typischen Speicherorten oder im Verzeichnislisting gefunden.")
        profile_scan_status(result, "Keine mögliche GPG-Key-Datei gefunden.", "warning")
    result["usable"] = bool(result["suites"] and result["components"] and result["archs"])
    if result["usable"]:
        profile_scan_status(result, f"Prüfung abgeschlossen: verwendbares Repository mit {len(result['suites'])} Suite(s), {len(result['components'])} Komponente(n), {len(result['archs'])} Architektur(en).", "ok")
    elif not result.get("flat_repo"):
        result["warnings"].append("Keine vollständige APT-Repository-Struktur erkannt.")
        profile_scan_status(result, "Prüfung abgeschlossen: keine vollständige APT-Repository-Struktur erkannt.", "error")
    return result


def generator_build_values_from_scan(form) -> Dict[str, Any]:
    source_url = normalize_profile_scan_url(form.get("source_url", ""))
    parsed = urllib.parse.urlparse(source_url)
    method = form.get("method") or parsed.scheme
    if method not in {"http", "https", "rsync", "ftp"}:
        method = parsed.scheme if parsed.scheme in {"http", "https", "rsync", "ftp"} else "https"
    suites = profile_scan_unique(form.getlist("suites"))
    components = profile_scan_unique(form.getlist("components"))
    archs = profile_scan_unique(form.getlist("archs"))
    if not suites:
        raise ValueError("Bitte mindestens eine gefundene Suite auswählen.")
    if not components:
        raise ValueError("Bitte mindestens eine Komponente auswählen.")
    if not archs:
        raise ValueError("Bitte mindestens eine Architektur auswählen.")
    root_path = normalize_root_path(form.get("root_path", "") or profile_scan_root_path_from_url(source_url)) or "."
    host = parsed.hostname if method == "rsync" else parsed.netloc
    if not host:
        raise ValueError("Die ausgewählte Repository-Basis enthält keinen Host.")
    default_name = f"{host} {'+'.join(suites[:2])}"
    name = (form.get("profile_name") or default_name).strip()
    target_suffix = profile_scan_slug(form.get("target_suffix") or f"{host}-{root_path}-{suites[0]}")
    overrides: Dict[str, Any] = {
        "name": name,
        "enabled": 1,
        "method": method,
        "host": host,
        "root_path": root_path,
        "target_path": str(MIRROR_BASE / target_suffix),
        "dists": ",".join(suites),
        "sections": ",".join(components),
        "archs": ",".join(archs),
        "source_mode": "nosource",
        "schedule_mode": "manual",
    }
    if method == "rsync" and parsed.scheme == "rsync" and parsed.port:
        import shlex
        overrides["extra_options"] = "--rsync-options=" + shlex.quote(f"-aIL --partial --port={parsed.port}")
    if method != "rsync" and str(form.get("scan_rsync_available") or "0") != "1":
        overrides["rsync_extra"] = "none"
    values = default_mirror_values(overrides)
    validate_mirror_configuration(values, require_ssh_key=False)
    return values

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


def profile_scan_ssh_from_form() -> Dict[str, Any]:
    enabled = bool_from_form("scan_rsync_ssh_enabled")
    upload = request.files.get("scan_rsync_ssh_key_upload")
    if upload and getattr(upload, "filename", "") and not enabled:
        raise ValueError("Zum Hochladen eines SSH-Schlüssels muss 'Rsync-Modul über SSH prüfen' aktiviert sein.")
    uploaded_key = save_uploaded_ssh_private_key(upload) if enabled else ""
    key_name = uploaded_key or (request.form.get("scan_rsync_ssh_key") or "").strip()
    try:
        port = int(request.form.get("scan_rsync_ssh_port") or 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH-Port muss eine Zahl sein.") from exc
    values = {
        "rsync_ssh_enabled": 1 if enabled else 0,
        "rsync_ssh_user": (request.form.get("scan_rsync_ssh_user") or "").strip(),
        "rsync_ssh_key": key_name,
        "rsync_ssh_port": port,
        "rsync_ssh_accept_new_host_key": 1 if bool_from_form("scan_rsync_ssh_accept_new_host_key") else 0,
    }
    if not enabled:
        values.update({"rsync_ssh_user": "", "rsync_ssh_key": "", "rsync_ssh_port": 22, "rsync_ssh_accept_new_host_key": 1})
    return values


def profile_scan_worker(token: str, scan_url: str, scan_depth: int, scan_path_variables: Any = None, auth_username: str = "", auth_password: str = "", ssh_values: Optional[Dict[str, Any]] = None) -> None:
    profile_scan_set_auth(auth_username, auth_password)
    ssh_values = ssh_values or {}
    profile_scan_set_ssh(
        bool(int(ssh_values.get("rsync_ssh_enabled") or 0)),
        str(ssh_values.get("rsync_ssh_user") or ""),
        str(ssh_values.get("rsync_ssh_key") or ""),
        int(ssh_values.get("rsync_ssh_port") or 22),
        bool(int(ssh_values.get("rsync_ssh_accept_new_host_key") if ssh_values.get("rsync_ssh_accept_new_host_key") is not None else 1)),
    )
    try:
        result = scan_apt_repository_url(scan_url, scan_depth, live_token=token, scan_path_variables=scan_path_variables)
        result.pop("_job_token", None)
        status = "done"
        error = ""
    except ProfileScanCancelled as exc:
        result = None
        status = "cancelled"
        error = str(exc)
    except Exception as exc:
        result = None
        status = "error"
        error = str(exc)
    finally:
        profile_scan_clear_auth()
    with PROFILE_SCAN_JOBS_LOCK:
        job = PROFILE_SCAN_JOBS.get(token)
        if job is not None:
            job["status"] = status
            job["result"] = result
            job["error"] = error
            job["updated_at"] = time.time()
            if status == "cancelled":
                job.setdefault("status_lines", []).append({"level": "warning", "message": "Prüfung wurde beendet.", "timestamp": now_iso()})
            elif error:
                job.setdefault("status_lines", []).append({"level": "error", "message": error, "timestamp": now_iso()})


@app.route("/profile-generator/scan/start", methods=["POST"])
@require_admin
def profile_generator_scan_start():
    try:
        profile_scan_jobs_cleanup()
        scan_url = (request.form.get("scan_url") or "").strip()
        scan_depth = profile_scan_parse_depth(request.form.get("scan_depth"))
        scan_path_variables = get_profile_scan_path_variables()
        auth_username = (request.form.get("scan_username") or "").strip()
        auth_password = request.form.get("scan_password") or ""
        auth_password_enc = encrypt_secret(auth_password) if auth_password else ""
        normalized_url = normalize_profile_scan_url(scan_url)
        parsed = urllib.parse.urlparse(normalized_url)
        raw_ssh_mode = {"rsync_ssh_enabled": 1 if bool_from_form("scan_rsync_ssh_enabled") else 0}
        validate_profile_scan_access_mode(normalized_url, auth_username, auth_password, raw_ssh_mode)
        ssh_values = profile_scan_ssh_from_form()
        if bool(int(ssh_values.get("rsync_ssh_enabled") or 0)):
            mirror_like = {"method": "rsync", "host": parsed.hostname or parsed.netloc, "root_path": profile_scan_root_path_from_url(normalized_url), "remote_user": "", "remote_password_enc": "", "extra_options": "", **ssh_values}
            validate_rsync_ssh_settings(mirror_like, require_key=True)
        token = secrets.token_urlsafe(16)
        with PROFILE_SCAN_JOBS_LOCK:
            PROFILE_SCAN_JOBS[token] = {
                "status": "running", "scan_url": scan_url, "scan_depth": scan_depth,
                "scan_path_variables": scan_path_variables, "auth_username": auth_username,
                "auth_password_enc": auth_password_enc, **ssh_values,
                "status_lines": [{"level": "info", "message": "Live-Prüfung wurde gestartet." + (" HTTP/FTP-Zugangsdaten werden nur für den Scan verschlüsselt vorgehalten." if auth_username else "") + (" Rsync wird über SSH-Schlüssel geprüft." if ssh_values.get("rsync_ssh_enabled") else ""), "timestamp": now_iso()}],
                "result": None, "error": "", "created_at": time.time(), "updated_at": time.time(),
            }
        thread = threading.Thread(target=profile_scan_worker, args=(token, scan_url, scan_depth, scan_path_variables, auth_username, auth_password, ssh_values), daemon=True)
        thread.start()
        return jsonify({"ok": True, "token": token})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/profile-generator/scan/status/<token>")
@require_admin
def profile_generator_scan_status(token: str):
    profile_scan_jobs_cleanup()
    with PROFILE_SCAN_JOBS_LOCK:
        job = PROFILE_SCAN_JOBS.get(token)
        if not job:
            return jsonify({"ok": False, "error": "Scan nicht gefunden oder bereits abgelaufen."}), 404
        return jsonify({
            "ok": True,
            "status": job.get("status"),
            "status_lines": job.get("status_lines") or [],
            "error": job.get("error") or "",
            "result_url": url_for("profile_generator", scan_token=token) if job.get("status") == "done" else "",
        })


@app.route("/profile-generator/scan/stop/<token>", methods=["POST"])
@require_admin
def profile_generator_scan_stop(token: str):
    profile_scan_jobs_cleanup()
    with PROFILE_SCAN_JOBS_LOCK:
        job = PROFILE_SCAN_JOBS.get(token)
        if not job:
            return jsonify({"ok": False, "error": "Scan nicht gefunden oder bereits abgelaufen."}), 404
        if job.get("status") in {"done", "error", "cancelled"}:
            return jsonify({"ok": True, "status": job.get("status"), "message": "Scan ist bereits beendet."})
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        job["updated_at"] = time.time()
        job.setdefault("status_lines", []).append({"level": "warning", "message": "Stopp angefordert. Der laufende HTTP-Aufruf wird noch beendet, danach stoppt der Scan.", "timestamp": now_iso()})
    return jsonify({"ok": True, "status": "cancelling"})


@app.route("/profile-generator", methods=["GET", "POST"])
@require_admin
def profile_generator():
    scan_result = None
    scan_url = ""
    scan_depth = PROFILE_SCAN_DEFAULT_DEPTH
    scan_token = request.args.get("scan_token", "").strip()
    scan_auth_username = ""
    scan_auth_password_set = False
    scan_ssh_values: Dict[str, Any] = {
        "rsync_ssh_enabled": 0, "rsync_ssh_user": "", "rsync_ssh_key": "",
        "rsync_ssh_port": 22, "rsync_ssh_accept_new_host_key": 1,
    }
    if request.method == "GET" and scan_token:
        with PROFILE_SCAN_JOBS_LOCK:
            job = PROFILE_SCAN_JOBS.get(scan_token)
        if job and job.get("status") == "done" and job.get("result"):
            scan_result = job.get("result")
            scan_url = job.get("scan_url", "")
            scan_auth_username = str(job.get("auth_username") or "")
            scan_auth_password_set = bool(job.get("auth_password_enc") and decrypt_secret(str(job.get("auth_password_enc") or "")))
            scan_ssh_values = {key: job.get(key, default) for key, default in scan_ssh_values.items()}
            scan_depth = profile_scan_parse_depth(job.get("scan_depth"))
            if scan_result.get("usable"):
                flash("Repository wurde geprüft. Gefundene Suites, Komponenten und Architekturen können jetzt ausgewählt werden.", "success")
            else:
                flash("Prüfung abgeschlossen, aber es wurde noch kein vollständig verwendbares dists/-Repository erkannt.", "warning")
        elif job and job.get("error"):
            scan_url = job.get("scan_url", "")
            scan_depth = profile_scan_parse_depth(job.get("scan_depth"))
            flash(job.get("error"), "danger")
        else:
            flash("Der Live-Scan ist nicht mehr verfügbar. Bitte die Adresse erneut prüfen.", "warning")
    if request.method == "POST":
        action = request.form.get("action") or "legacy_generate"
        if action == "scan_url":
            scan_url = request.form.get("scan_url", "").strip()
            scan_depth = profile_scan_parse_depth(request.form.get("scan_depth"))
            scan_path_variables = get_profile_scan_path_variables()
            scan_auth_username = (request.form.get("scan_username") or "").strip()
            scan_auth_password = request.form.get("scan_password") or ""
            scan_auth_password_set = bool(scan_auth_password)
            try:
                normalized_url = normalize_profile_scan_url(scan_url)
                parsed_scan = urllib.parse.urlparse(normalized_url)
                raw_ssh_mode = {"rsync_ssh_enabled": 1 if bool_from_form("scan_rsync_ssh_enabled") else 0}
                validate_profile_scan_access_mode(normalized_url, scan_auth_username, scan_auth_password, raw_ssh_mode)
                scan_ssh_values = profile_scan_ssh_from_form()
                if bool(int(scan_ssh_values.get("rsync_ssh_enabled") or 0)):
                    validate_rsync_ssh_settings({"method": "rsync", "host": parsed_scan.hostname or parsed_scan.netloc, "root_path": profile_scan_root_path_from_url(normalized_url), "remote_user": "", "remote_password_enc": "", "extra_options": "", **scan_ssh_values}, require_key=True)
                profile_scan_set_auth(scan_auth_username, scan_auth_password)
                profile_scan_set_ssh(bool(int(scan_ssh_values.get("rsync_ssh_enabled") or 0)), str(scan_ssh_values.get("rsync_ssh_user") or ""), str(scan_ssh_values.get("rsync_ssh_key") or ""), int(scan_ssh_values.get("rsync_ssh_port") or 22), bool(int(scan_ssh_values.get("rsync_ssh_accept_new_host_key") or 0)))
                scan_result = scan_apt_repository_url(scan_url, scan_depth, scan_path_variables=scan_path_variables)
                scan_result.pop("_job_token", None)
                if scan_auth_password:
                    scan_result["_auth_password_enc"] = encrypt_secret(scan_auth_password)
                scan_result["_auth_username"] = scan_auth_username
                scan_result.update({"_" + key: value for key, value in scan_ssh_values.items()})
                if scan_result.get("usable"):
                    flash("Repository wurde geprüft. Gefundene Suites, Komponenten und Architekturen können jetzt ausgewählt werden.", "success")
                else:
                    flash("Prüfung abgeschlossen, aber es wurde noch kein vollständig verwendbares dists/-Repository erkannt.", "warning")
            except Exception as exc:
                flash(str(exc), "danger")
            finally:
                profile_scan_clear_auth()
        elif action == "create_from_scan":
            try:
                values = generator_build_values_from_scan(request.form)
                posted_scan_token = (request.form.get("scan_token") or "").strip()
                auth_username = (request.form.get("profile_remote_user") or "").strip()
                auth_password_enc = (request.form.get("prepared_scan_password") or "").strip()
                if posted_scan_token:
                    with PROFILE_SCAN_JOBS_LOCK:
                        auth_job = PROFILE_SCAN_JOBS.get(posted_scan_token) or {}
                    auth_username = auth_username or str(auth_job.get("auth_username") or "")
                    auth_password_enc = auth_password_enc or str(auth_job.get("auth_password_enc") or "")
                selected_method = str(values.get("method") or "")
                ssh_profile_values = {
                    "rsync_ssh_enabled": int(request.form.get("prepared_rsync_ssh_enabled") or 0),
                    "rsync_ssh_user": (request.form.get("prepared_rsync_ssh_user") or "").strip(),
                    "rsync_ssh_key": (request.form.get("prepared_rsync_ssh_key") or "").strip(),
                    "rsync_ssh_port": int(request.form.get("prepared_rsync_ssh_port") or 22),
                    "rsync_ssh_accept_new_host_key": int(request.form.get("prepared_rsync_ssh_accept_new_host_key") or 1),
                }
                if posted_scan_token:
                    ssh_profile_values = {key: auth_job.get(key, value) for key, value in ssh_profile_values.items()}
                if selected_method == "rsync" and bool(int(ssh_profile_values.get("rsync_ssh_enabled") or 0)):
                    values.update(ssh_profile_values)
                    parsed_source = urllib.parse.urlparse((request.form.get("source_url") or "").strip())
                    if parsed_source.hostname:
                        values["host"] = parsed_source.hostname
                elif selected_method != "rsync":
                    if auth_username:
                        values["remote_user"] = auth_username
                    if auth_password_enc and decrypt_secret(auth_password_enc):
                        values["_prepared_remote_password_enc"] = auth_password_enc
                selected_key = request.form.get("selected_gpg_key", "").strip()
                if selected_key:
                    flash(f"GPG-Key gefunden, aber noch nicht automatisch importiert: {selected_key}", "info")
                flash("Profil wurde aus dem Repository-Scan vorbereitet. Prüfe die Werte und speichere danach das Profil.", "success")
                return render_template(
                    "mirror_form.html",
                    mirror=values,
                    title="Profil aus Repository-Scan speichern",
                    keyrings=list_keyring_files(),
                    form_action=url_for("mirror_new"),
                    return_url=url_for("profile_generator"),
                    return_label="Zurück zum Generator",
                    **mirror_form_option_context(values),
                )
            except Exception as exc:
                flash(str(exc), "danger")
                scan_url = request.form.get("source_url", "").strip()
                scan_depth = profile_scan_parse_depth(request.form.get("scan_depth"))
        else:
            values = generator_build_values(request.form)
            flash("Profil wurde aus dem Standardgenerator vorbereitet. Prüfe die Werte und speichere danach das Profil.", "success")
            return render_template(
                "mirror_form.html",
                mirror=values,
                title="Profil aus Generator speichern",
                keyrings=list_keyring_files(),
                form_action=url_for("mirror_new"),
                return_url=url_for("profile_generator"),
                return_label="Zurück zum Generator",
                **mirror_form_option_context(values),
            )
    return render_template(
        "profile_generator.html",
        generator=get_profile_generator_config(),
        scan_result=scan_result,
        scan_url=scan_url,
        scan_depth=scan_depth,
        default_scan_depth=PROFILE_SCAN_DEFAULT_DEPTH,
        max_scan_depth=PROFILE_SCAN_MAX_DEPTH,
        scan_path_variables=get_profile_scan_path_variables(),
        scan_path_variables_text="\n".join(get_profile_scan_path_variables()),
        scan_token=scan_token,
        scan_auth_username=scan_auth_username,
        scan_auth_password_set=scan_auth_password_set,
        scan_ssh_values=scan_ssh_values,
        ssh_private_keys=list_ssh_private_keys(),
    )


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
        cmd = shell_join(display_debmirror_command(mirror, dry_run=False))
        dry_cmd = shell_join(display_debmirror_command(mirror, dry_run=True))
    except ValueError as exc:
        # Die Detailseite darf durch eine ungültige Profil-/Keyring-Konfiguration
        # nicht mit HTTP 500 abbrechen. Für reine Anzeige wird der Befehl ohne
        # harte Keyring-Validierung erzeugt und die eigentliche Warnung sichtbar
        # im Template angezeigt. Beim Job-Start bleibt die Prüfung aktiv.
        command_error = str(exc)
        try:
            cmd = shell_join(display_debmirror_command(mirror, dry_run=False, validate_keyring=False))
            dry_cmd = shell_join(display_debmirror_command(mirror, dry_run=True, validate_keyring=False))
        except Exception as inner_exc:
            command_error = f"{command_error} Zusätzlich konnte der Befehl nicht angezeigt werden: {inner_exc}"
            cmd = "Befehl konnte nicht generiert werden."
            dry_cmd = "Befehl konnte nicht generiert werden."
    with db() as con:
        jobs = enrich_jobs_duration([row_to_dict(r) for r in con.execute("SELECT * FROM jobs WHERE mirror_id=? ORDER BY id DESC LIMIT ?", (mirror_id, min(job_list_limit(), 200))).fetchall()])
    migrate_legacy_keyring_assignments()
    stats = mirror_stats(mirror)
    storage = disk_usage_info(MIRROR_BASE)
    start_block_reason = mirror_start_block_reason(mirror, dry_run=False)
    return render_template(
        "mirror_detail.html",
        mirror=mirror,
        jobs=jobs,
        schedules=list_schedules_for_mirror(mirror_id),
        command=cmd,
        dry_command=dry_cmd,
        command_error=command_error,
        stats=stats,
        storage=storage,
        start_block_reason=start_block_reason,
        profile_keyrings=assigned_keyring_rows_for_mirror(mirror_id),
        profile_keyring_names=mirror_keyring_assignment_names(mirror_id),
        profile_keyring_values=[assignment_value(item.get("filename", ""), item.get("fingerprint", "")) for item in mirror_keyring_assignment_items(mirror_id)],
        keyring_options=master_key_rows(),
        client_export_dists=csv_to_list(str(mirror.get("dists") or "")),
        client_export_archs=csv_to_list(str(mirror.get("archs") or "")),
    )


@app.route("/mirrors/<int:mirror_id>/keyrings", methods=["POST"])
@require_admin
def mirror_keyrings_save(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("mirrors_page"))
    try:
        action = request.form.get("action", "save_assignments")
        if action == "save_assignments":
            assignment_values = request.form.getlist("keyring_assignments") or request.form.getlist("keyrings")
            if assignment_values:
                generated = save_mirror_keyring_assignments_and_rebuild(mirror_id, assignment_values)
                flash(f"Profil-Keyring gespeichert und gezielt aus dem Master-Keyring erzeugt: {generated.name}", "success")
                add_event("info", f"Profil-Keyring aktualisiert: {mirror.get('name')}")
            else:
                clear_managed_keyring_assignments(mirror_id, clear_db_fields=True)
                flash("Alle Keyring-Zuordnungen wurden entfernt.", "success")
                add_event("info", f"Alle Keyring-Zuordnungen entfernt: {mirror.get('name')}")
        elif action == "rebuild_profile_keyring":
            generated = rebuild_profile_keyring(mirror_id)
            flash(f"Profil-Keyring neu erzeugt: {generated.name}", "success")
            add_event("info", f"Profil-Keyring neu erzeugt: {mirror.get('name')}")
        elif action == "remove_assignment":
            filename = request.form.get("filename", "")
            fingerprint = request.form.get("fingerprint", "")
            unassign_keyring_filename_from_mirror(mirror_id, filename, fingerprint)
            flash("Keyring-Zuordnung entfernt.", "success")
            add_event("info", f"Keyring-Zuordnung entfernt: {mirror.get('name')} / {filename}")
        else:
            raise ValueError("Unbekannte Keyring-Aktion.")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("mirror_detail", mirror_id=mirror_id))


@app.route("/sizes/recalculate-all", methods=["POST"])
@require_admin
def all_sizes_recalculate():
    try:
        result = request_all_configured_size_calculations()
        total = int(result.get("total") or 0)
        started = int(result.get("started") or 0)
        waiting = int(result.get("waiting") or 0)
        target_label = "Verzeichnis" if total == 1 else "Verzeichnisse"
        if total == 0:
            flash("Es wurden keine vorhandenen konfigurierten Zielverzeichnisse gefunden.", "info")
        elif waiting:
            flash(f"Größenaktualisierung für {total} {target_label} angefordert: {started} gestartet, {waiting} bereits aktiv oder vorgemerkt.", "success")
        else:
            flash(f"Größenaktualisierung für alle {total} vorhandenen {target_label} wurde gestartet.", "success")
        event_target_label = "Ziel" if total == 1 else "Ziele"
        add_event("info", f"Alle Größen aktualisieren: {total} {event_target_label}, {started} gestartet, {waiting} aktiv/vorgemerkt.")
    except Exception as exc:
        log_webui_exception("all_sizes_recalculate", exc)
        flash(f"Die gemeinsame Größenaktualisierung konnte nicht gestartet werden: {exc}", "danger")
    return redirect(request.referrer or url_for("dashboard"))


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
        keyrings=mirror_keyring_form_options(mirror),
        return_url=url_for("mirror_detail", mirror_id=mirror_id),
        return_label="Zurück zum Profil",
        **mirror_form_option_context(mirror),
    )


def save_mirror(mirror_id: Optional[int]):
    try:
        existing_mirror = get_mirror(int(mirror_id)) if mirror_id is not None else None
        had_managed_keyring_assignments = bool(mirror_keyring_assignment_items(int(mirror_id))) if mirror_id is not None else False
        name = request.form.get("name", "").strip()
        if not name:
            raise ValueError("Name darf nicht leer sein.")
        target_path = normalize_target_path(request.form.get("target_path", ""))
        keyring = allowed_keyring_path(request.form.get("keyring", ""))
        method = request.form.get("method", "rsync").strip()
        remote_user = request.form.get("remote_user", "").strip()
        new_remote_password = request.form.get("remote_password", "")
        rsync_ssh_enabled = bool_from_form("rsync_ssh_enabled")
        ssh_upload = request.files.get("rsync_ssh_key_upload")
        if ssh_upload and getattr(ssh_upload, "filename", "") and (method != "rsync" or not rsync_ssh_enabled):
            raise ValueError("Ein privater SSH-Schlüssel kann nur bei Methode rsync und aktivierter SSH-Schlüsselanmeldung hochgeladen werden.")
        uploaded_ssh_key = save_uploaded_ssh_private_key(ssh_upload) if method == "rsync" and rsync_ssh_enabled else ""
        rsync_ssh_key = uploaded_ssh_key or request.form.get("rsync_ssh_key", "").strip()
        clear_remote_password = bool_from_form("clear_remote_password")
        prepared_remote_password = request.form.get("prepared_remote_password", "").strip()
        if clear_remote_password:
            remote_password_enc = ""
        elif new_remote_password:
            remote_password_enc = encrypt_secret(new_remote_password)
        elif existing_mirror is not None:
            remote_password_enc = str(existing_mirror.get("remote_password_enc") or "")
        elif prepared_remote_password.startswith((SECRET_PREFIX, LEGACY_SECRET_PREFIX)) and decrypt_secret(prepared_remote_password):
            remote_password_enc = encrypt_secret(decrypt_secret(prepared_remote_password))
        else:
            remote_password_enc = ""
        if method == "rsync":
            remote_user = ""
            remote_password_enc = ""
        else:
            rsync_ssh_enabled = False
            rsync_ssh_key = ""
        raw_root_path = request.form.get("root_path", "")
        normalized_root_path = validate_rsync_module_path(raw_root_path) if method == "rsync" else normalize_root_path(raw_root_path)
        values = {
            "name": name,
            "enabled": bool_from_form("enabled"),
            "method": method,
            "host": request.form.get("host", "").strip(),
            "root_path": normalized_root_path,
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
            "rsync_extra": normalize_rsync_extra_values(request.form.getlist("rsync_extra_value")),
            "extra_options": extra_options_from_form(request.form),
            "manual_extra_options": serialize_manual_extra_options(request.form.get("manual_extra_options", "")),
            "remote_user": remote_user,
            "remote_password_enc": remote_password_enc,
            "rsync_ssh_enabled": 1 if rsync_ssh_enabled else 0,
            "rsync_ssh_user": request.form.get("rsync_ssh_user", "").strip() if rsync_ssh_enabled else "",
            "rsync_ssh_key": rsync_ssh_key if rsync_ssh_enabled else "",
            "rsync_ssh_port": int(request.form.get("rsync_ssh_port") or 22) if rsync_ssh_enabled else 22,
            "rsync_ssh_accept_new_host_key": 1 if (rsync_ssh_enabled and bool_from_form("rsync_ssh_accept_new_host_key")) else 0,
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
        parse_manual_extra_options(values.get("manual_extra_options") or "")
        normalize_mirror_option_compatibility(values)
        validate_mirror_configuration(values, require_ssh_key=True)
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
        if not created_new and mirror_id is not None and had_managed_keyring_assignments:
            # If the legacy keyring field is explicitly cleared or changed away from
            # the generated profile keyring, the central fingerprint assignments must
            # be cleared as well. Otherwise the old key appears again in the
            # "Profil-Keyrings" block and can be rebuilt unintentionally.
            if not keyring:
                clear_managed_keyring_assignments(int(mirror_id), clear_db_fields=False)
            elif not is_profile_keyring_path(keyring):
                clear_managed_keyring_assignments(int(mirror_id), clear_db_fields=False)
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
        mirror["rsync_extra"] = ",".join(request.form.getlist("rsync_extra_value"))
        mirror["manual_extra_options"] = request.form.get("manual_extra_options", "")
        mirror["remote_user"] = request.form.get("remote_user", "").strip()
        mirror["remote_password_enc"] = (existing_mirror or {}).get("remote_password_enc", "") if 'existing_mirror' in locals() else ""
        mirror["rsync_ssh_enabled"] = bool_from_form("rsync_ssh_enabled")
        mirror["rsync_ssh_user"] = request.form.get("rsync_ssh_user", "").strip()
        mirror["rsync_ssh_key"] = request.form.get("rsync_ssh_key", "").strip()
        mirror["rsync_ssh_port"] = request.form.get("rsync_ssh_port", "22")
        mirror["rsync_ssh_accept_new_host_key"] = bool_from_form("rsync_ssh_accept_new_host_key")
        raw_extra_tokens: List[str] = []
        for raw_flag in request.form.getlist("extra_flag"):
            spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG.get(raw_flag)
            if not spec:
                continue
            if spec.get("takes_value"):
                field_name = f"extra_value_{spec['key']}"
                raw_extra_tokens.append(f"{raw_flag}={request.form.get(field_name, '')}")
            else:
                raw_extra_tokens.append(raw_flag)
        mirror["extra_options"] = serialize_extra_options(raw_extra_tokens)
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
            **mirror_form_option_context(mirror),
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
                set_user_script_enabled(filename, True, require_existing=True)
                add_event("info", f"Benutzerskript hochgeladen: {filename}")
                flash("Benutzerskript wurde hochgeladen und aktiviert.", "success")
                return redirect(url_for("user_scripts_page"))
            if action == "set_enabled":
                script_name = request.form.get("script_name", "")
                enabled = bool_from_form("enabled")
                set_user_script_enabled(script_name, enabled, require_existing=True)
                add_event("info", f"Benutzerskript {'aktiviert' if enabled else 'deaktiviert'}: {script_name}")
                flash("Aktiv-Status des Benutzerskripts wurde gespeichert.", "success")
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
    return render_template("user_scripts.html", scripts=enrich_user_script_runtime_info(list_user_scripts()), user_script_dir=str(USER_SCRIPT_DIR))


@app.route("/user-scripts/<script_name>/delete", methods=["POST"])
@require_admin
def user_script_delete(script_name: str):
    try:
        path = safe_user_script_path(script_name)
        set_user_script_enabled(script_name, False, require_existing=True)
        path.unlink()
        add_event("warning", f"Benutzerskript gelöscht und deaktiviert: {script_name}")
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
        last_heartbeat = time.monotonic()
        try:
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
                    # Job- und Logschreiber erhalten kurz Zeit, die letzten Daten zu
                    # persistieren, bevor Dauer und Diagnose an den Browser gehen.
                    time.sleep(1)
                    final_job = enrich_job_duration(row_to_dict(row))
                    diagnosis_html = ""
                    try:
                        diagnosis_html = render_template(
                            "_job_diagnosis.html",
                            job=final_job,
                            diagnosis=build_job_diagnosis(final_job),
                        )
                        diag_data = json.dumps({"html": diagnosis_html})
                        yield f"event: diagnosis\ndata: {diag_data}\n\n"
                    except Exception as exc:
                        log_webui_exception(f"job_stream diagnosis job={job_id}", exc)
                    data = json.dumps({
                        "status": final_job.get("status") or "",
                        "finished_at": final_job.get("finished_at") or "",
                        "duration_h": final_job.get("duration_h") or "",
                        "diagnosis_html": diagnosis_html,
                    })
                    yield f"event: done\ndata: {data}\n\n"
                    break

                # SSE-Kommentar hält lange, ausgabearme Jobs durch Proxies und
                # Browser-Verbindungen am Leben, ohne das sichtbare Log zu ändern.
                now_monotonic = time.monotonic()
                if now_monotonic - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = now_monotonic
                time.sleep(1)
        except GeneratorExit:
            # Normaler Browser-Abbruch, z. B. beim Verlassen oder Neuladen der Seite.
            return
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError as exc:
            if getattr(exc, "errno", None) in {32, 54, 104}:
                return
            raise

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["X-Accel-Buffering"] = "no"
    return response

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
            } | {item["flag"] for item in DEBMIRROR_EXTRA_OPTION_CATALOG if item.get("takes_value")}
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
            elif opt in DEBMIRROR_EXTRA_OPTION_BY_FLAG:
                spec = DEBMIRROR_EXTRA_OPTION_BY_FLAG[opt]
                try:
                    extra_token = f"{opt}={validate_debmirror_extra_value(opt, val or '')}" if spec.get("takes_value") else opt
                    if extra_token not in extra_options:
                        extra_options.append(extra_token)
                    if opt in {"--no-check-gpg", "--ignore-release-gpg", "--disable-ssl-verification"}:
                        warnings.append(f"Sicherheitsrelevante Option {opt} wurde übernommen. Prüfe diese Einstellung sorgfältig.")
                except Exception as exc:
                    warnings.append(f"Option {opt} konnte nicht übernommen werden: {exc}")
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
        try:
            validate_extra_option_conflicts(extra_options)
            values["extra_options"] = serialize_extra_options(extra_options)
        except Exception as exc:
            warnings.append(f"Zusatzoptionen enthalten einen Konflikt: {exc}")
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
    raw_import_root = str(clean.get("root_path") or "")
    clean["root_path"] = validate_rsync_module_path(raw_import_root) if clean.get("method") == "rsync" else normalize_root_path(raw_import_root)
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
    normalize_mirror_option_compatibility(clean)
    validate_mirror_configuration(clean, require_ssh_key=True)
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

def list_keyring_files(include_archived: bool = False) -> List[str]:
    """Return imported keyring source files.

    By default only legacy files directly below APP_KEYRING_DIR are returned.
    When include_archived=True, all rebuild source directories are included:
    archive/ for file/URL/text imports and keyserver/ for keys fetched from
    a keyserver. Generated master/profile keyrings are intentionally never
    returned here.
    """
    files: List[str] = []
    search_dirs = [APP_KEYRING_DIR]
    if include_archived:
        search_dirs.extend([ARCHIVE_KEYRING_DIR, KEYSERVER_KEYRING_DIR])
    for directory in search_dirs:
        try:
            for p in directory.glob("*"):
                if p.is_file() and p.suffix.lower() in {".gpg", ".asc", ".key"}:
                    files.append(str(p))
        except Exception:
            continue
    return sorted(set(files))


def is_profile_keyring_path(value: str) -> bool:
    try:
        if not value:
            return False
        path = Path(value)
        if not path.is_absolute():
            path = APP_KEYRING_DIR / path
        resolved = path.resolve(strict=False)
        base = PROFILE_KEYRING_DIR.resolve(strict=False)
        return resolved == base or base in resolved.parents
    except Exception:
        return False


def remove_generated_profile_keyring_files(mirror_id: int) -> None:
    try:
        for path in PROFILE_KEYRING_DIR.glob(f"mirror-{int(mirror_id)}-*.gpg"):
            if path.is_file():
                path.unlink(missing_ok=True)
    except Exception as exc:
        log_webui_exception(f"remove generated profile keyrings mirror_id={mirror_id}", exc)


def clear_managed_keyring_assignments(mirror_id: int, *, clear_db_fields: bool = True) -> None:
    set_mirror_keyring_assignment_items(int(mirror_id), [])
    remove_generated_profile_keyring_files(int(mirror_id))
    if clear_db_fields:
        with db() as con:
            con.execute("UPDATE mirrors SET keyring='', keyring_fingerprint='', updated_at=? WHERE id=?", (now_iso(), int(mirror_id)))


def mirror_keyring_form_options(mirror: Optional[Dict[str, Any]] = None) -> List[str]:
    options = list_keyring_files()
    current = str((mirror or {}).get("keyring") or "").strip()
    if current and current not in options:
        # Generated profile keyrings are hidden from the normal source-file list,
        # but the edit form still has to keep the current value selected.
        options.insert(0, current)
    return options


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


def gpg_show_key_output(path: Path) -> str:
    try:
        result = subprocess.run(
            ["gpg", "--show-keys", "--with-colons", "--with-fingerprint", "--with-subkey-fingerprint", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
        return result.stdout or ""
    except Exception as exc:
        return f"err::::::{exc}"


def gpg_keyring_list_output(path: Path) -> str:
    """List keys from a real GnuPG keyring/keybox file.

    `gpg --show-keys file.gpg` works for exported key blocks, but not reliably
    for keybox/keyring files created with `--keyring`. The Master-Keyring is
    such a real keyring, so it must be read with `--no-default-keyring --keyring`.
    """
    if not path.exists():
        return ""
    tmp_home = gpg_temp_home("debmirror-master-list-")
    try:
        result = subprocess.run(
            [
                "gpg", "--batch", "--homedir", str(tmp_home),
                "--no-default-keyring", "--keyring", str(path),
                "--list-keys", "--with-colons", "--with-fingerprint", "--with-subkey-fingerprint",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout or ""
    except Exception as exc:
        return f"err::::::{exc}"
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def gpg_keyring_query_output(path: Path, expected: str) -> str:
    """Ask GnuPG to resolve one key id/fingerprint inside a real keyring.

    This is more reliable than only comparing parsed fingerprints when gpgv
    reports a short signing-subkey ID. GnuPG can resolve such IDs to the
    corresponding primary key if the key is already present in the Master-Keyring.
    """
    expected_n = normalize_fingerprint(expected)
    if not expected_n or not path.exists():
        return ""
    tmp_home = gpg_temp_home("debmirror-master-query-")
    try:
        result = subprocess.run(
            [
                "gpg", "--batch", "--homedir", str(tmp_home),
                "--no-default-keyring", "--keyring", str(path),
                "--keyid-format", "LONG",
                "--list-keys", "--with-colons", "--with-fingerprint", "--with-subkey-fingerprint",
                expected_n,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout or ""
    except Exception as exc:
        return f"err::::::{exc}"
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def gpg_imported_keyfile_list_output(path: Path, expected: str = "") -> str:
    """Import a public-key file into a temporary GNUPGHOME and list it.

    Archive files may be exported public-key blocks, binary keyrings or older
    imported files.  `--show-keys` is fast but does not always expose the same
    subkey information that a real keyring list exposes.  This fallback imports
    the file into an isolated temporary home and asks GnuPG for the normalized
    key/subkey view.
    """
    if not path.exists():
        return ""
    expected_n = normalize_fingerprint(expected)
    tmp_home = gpg_temp_home("debmirror-archive-import-list-")
    try:
        imp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--import", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=40,
            check=False,
        )
        if imp.returncode != 0:
            # Some old .gpg files are real keyring files rather than importable
            # key blocks.  Return the import output as warning context.
            return imp.stdout or ""
        cmd = [
            "gpg", "--batch", "--homedir", str(tmp_home), "--keyid-format", "LONG",
            "--list-keys", "--with-colons", "--with-fingerprint", "--with-subkey-fingerprint",
        ]
        if expected_n:
            cmd.append(expected_n)
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=40,
            check=False,
        )
        return result.stdout or ""
    except Exception as exc:
        return f"err::::::{exc}"
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def merge_gpg_detail_sets(*detail_sets: Dict[str, Any]) -> Dict[str, Any]:
    """Merge parsed GPG details from different read methods.

    The same archive file can be readable as an exported key block, as a real
    GnuPG keyring or after temporary import.  Merging prevents the UI and error
    diagnosis from losing subkeys that only one read path exposes.
    """
    merged: Dict[str, Any] = {"keys": [], "fingerprints": [], "subkey_fingerprints": [], "all_fingerprints": [], "warnings": [], "raw": ""}
    key_index: Dict[str, Dict[str, Any]] = {}

    def add_unique(seq: List[str], value: str) -> None:
        value_n = normalize_fingerprint(value)
        if value_n and value_n not in seq:
            seq.append(value_n)

    for details in detail_sets:
        if not isinstance(details, dict):
            continue
        for warning in details.get("warnings") or []:
            if warning and warning not in merged["warnings"]:
                merged["warnings"].append(warning)
        if details.get("raw"):
            merged["raw"] += ("\n" if merged["raw"] else "") + str(details.get("raw") or "")
        for fp in details.get("fingerprints") or []:
            add_unique(merged["fingerprints"], fp)
        for fp in details.get("subkey_fingerprints") or []:
            add_unique(merged["subkey_fingerprints"], fp)
        for fp in details.get("all_fingerprints") or []:
            add_unique(merged["all_fingerprints"], fp)

        for key in details.get("keys") or []:
            primary_fp = normalize_fingerprint(key.get("fingerprint") or "")
            primary_id = normalize_fingerprint(key.get("key_id") or "")
            key_id = primary_fp or primary_id
            if not key_id:
                continue
            if key_id not in key_index:
                copy = dict(key)
                copy["fingerprint"] = primary_fp
                copy["uids"] = list(key.get("uids") or [])
                copy["subkeys"] = []
                key_index[key_id] = copy
                merged["keys"].append(copy)
            target = key_index[key_id]
            for field in ["validity", "length", "algorithm", "key_id", "created", "expires", "status", "status_class", "fingerprint"]:
                if not target.get(field) and key.get(field):
                    target[field] = key.get(field)
            existing_uids = {u.get("uid") for u in target.get("uids") or [] if isinstance(u, dict)}
            for uid in key.get("uids") or []:
                if isinstance(uid, dict) and uid.get("uid") not in existing_uids:
                    target.setdefault("uids", []).append(uid)
                    existing_uids.add(uid.get("uid"))
            existing_subs = {normalize_fingerprint(s.get("fingerprint") or s.get("key_id") or "") for s in target.get("subkeys") or [] if isinstance(s, dict)}
            for sub in key.get("subkeys") or []:
                if not isinstance(sub, dict):
                    continue
                sub_key = normalize_fingerprint(sub.get("fingerprint") or sub.get("key_id") or "")
                if sub_key and sub_key not in existing_subs:
                    target.setdefault("subkeys", []).append(dict(sub))
                    existing_subs.add(sub_key)
                    add_unique(merged["subkey_fingerprints"], sub.get("fingerprint") or "")
                    add_unique(merged["all_fingerprints"], sub.get("fingerprint") or "")

    # Keep primary fingerprints first, then subkeys/other fingerprints.
    ordered_all: List[str] = []
    for fp in merged["fingerprints"]:
        add_unique(ordered_all, fp)
    for fp in merged["all_fingerprints"]:
        add_unique(ordered_all, fp)
    merged["all_fingerprints"] = ordered_all
    return merged


def parse_gpg_colon_output(output: str) -> Dict[str, Any]:
    keys: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_sub: Optional[Dict[str, Any]] = None
    warnings: List[str] = []
    all_fingerprints: List[str] = []
    subkey_fingerprints: List[str] = []
    for line in (output or "").splitlines():
        parts = line.split(":")
        kind = parts[0] if parts else ""
        if kind == "pub":
            status, status_class = gpg_validity_label(parts[1] if len(parts) > 1 else "", parts[6] if len(parts) > 6 else "")
            current = {
                "type": "pub",
                "validity": parts[1] if len(parts) > 1 else "",
                "length": parts[2] if len(parts) > 2 else "",
                "algorithm": gpg_algorithm_name(parts[3] if len(parts) > 3 else ""),
                "key_id": parts[4] if len(parts) > 4 else "",
                "created": gpg_timestamp_to_date(parts[5] if len(parts) > 5 else ""),
                "expires": gpg_timestamp_to_date(parts[6] if len(parts) > 6 else ""),
                "status": status,
                "status_class": status_class,
                "fingerprint": "",
                "uids": [],
                "subkeys": [],
            }
            keys.append(current)
            current_sub = None
        elif kind == "fpr":
            fp = normalize_fingerprint(parts[9] if len(parts) > 9 else "")
            if fp and fp not in all_fingerprints:
                all_fingerprints.append(fp)
            if current_sub is not None:
                current_sub["fingerprint"] = fp
                if fp and fp not in subkey_fingerprints:
                    subkey_fingerprints.append(fp)
            elif current is not None and not current.get("fingerprint"):
                current["fingerprint"] = fp
        elif kind == "uid" and current is not None:
            uid_status, uid_class = gpg_validity_label(parts[1] if len(parts) > 1 else "")
            current["uids"].append({
                "uid": parts[9] if len(parts) > 9 else "",
                "status": uid_status,
                "status_class": uid_class,
            })
        elif kind == "sub" and current is not None:
            status, status_class = gpg_validity_label(parts[1] if len(parts) > 1 else "", parts[6] if len(parts) > 6 else "")
            current_sub = {
                "key_id": parts[4] if len(parts) > 4 else "",
                "length": parts[2] if len(parts) > 2 else "",
                "algorithm": gpg_algorithm_name(parts[3] if len(parts) > 3 else ""),
                "created": gpg_timestamp_to_date(parts[5] if len(parts) > 5 else ""),
                "expires": gpg_timestamp_to_date(parts[6] if len(parts) > 6 else ""),
                "status": status,
                "status_class": status_class,
                "fingerprint": "",
            }
            current["subkeys"].append(current_sub)
        elif kind == "err" or line.lower().startswith("gpg:"):
            if line.strip() and "trustdb" not in line.lower():
                warnings.append(line.strip())
    fingerprints = [normalize_fingerprint(k.get("fingerprint") or "") for k in keys if normalize_fingerprint(k.get("fingerprint") or "")]
    for fp in fingerprints:
        if fp and fp not in all_fingerprints:
            all_fingerprints.insert(0, fp)
    return {
        "keys": keys,
        "fingerprints": fingerprints,
        "subkey_fingerprints": subkey_fingerprints,
        "all_fingerprints": all_fingerprints,
        "warnings": warnings,
        "raw": output or "",
    }


def master_keyring_details() -> Dict[str, Any]:
    return parse_gpg_colon_output(gpg_keyring_list_output(MASTER_KEYRING_PATH))


def master_key_detail_for_primary(primary_fingerprint: str) -> Dict[str, Any]:
    primary = normalize_fingerprint(primary_fingerprint)
    if not primary or not MASTER_KEYRING_PATH.exists():
        return {}
    for key in master_keyring_details().get("keys") or []:
        if fingerprint_matches(key.get("fingerprint") or "", primary):
            return key
    return {}


def merge_master_subkeys_into_archive_details(details: Dict[str, Any]) -> Dict[str, Any]:
    """Supplement archive-file display with Master-Keyring subkey metadata.

    Some exported/imported archive files are parsed differently depending on
    whether GnuPG reads them as key blocks, legacy keyrings or an imported
    temporary keyring.  When the same primary key is already present in the
    Master-Keyring, use the master view as an additional metadata source so the
    archive overview and error diagnosis show the same primary/subkey set.
    """
    if not isinstance(details, dict) or not MASTER_KEYRING_PATH.exists():
        return details
    supplements = []
    for key in details.get("keys") or []:
        primary = normalize_fingerprint(key.get("fingerprint") or "")
        master_key = master_key_detail_for_primary(primary) if primary else {}
        if master_key:
            supplements.append({
                "keys": [master_key],
                "fingerprints": [normalize_fingerprint(master_key.get("fingerprint") or "")],
                "subkey_fingerprints": [normalize_fingerprint(sub.get("fingerprint") or "") for sub in (master_key.get("subkeys") or []) if normalize_fingerprint(sub.get("fingerprint") or "")],
                "all_fingerprints": [normalize_fingerprint(master_key.get("fingerprint") or "")] + [normalize_fingerprint(sub.get("fingerprint") or "") for sub in (master_key.get("subkeys") or []) if normalize_fingerprint(sub.get("fingerprint") or "")],
                "warnings": [],
                "raw": "",
            })
    if not supplements:
        return details
    merged = merge_gpg_detail_sets(details, *supplements)
    merged["master_supplemented"] = True
    return merged


def archive_keyring_details(path: Path, supplement_master: bool = True) -> Dict[str, Any]:
    details = parse_keyring_details(path)
    return merge_master_subkeys_into_archive_details(details) if supplement_master else details


def gpg_timestamp_to_date(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        ts = int(value)
        if ts <= 0:
            return ""
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return value


def gpg_algorithm_name(value: str) -> str:
    mapping = {
        "1": "RSA",
        "2": "RSA-E",
        "3": "RSA-S",
        "16": "ElGamal",
        "17": "DSA",
        "18": "ECDH",
        "19": "ECDSA",
        "20": "ElGamal",
        "22": "EdDSA",
    }
    value = str(value or "").strip()
    return mapping.get(value, value or "-")


def gpg_validity_label(value: str, expires: str = "") -> Tuple[str, str]:
    now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
    try:
        if expires and int(expires) > 0 and int(expires) < now_ts:
            return "abgelaufen", "danger"
    except Exception:
        pass
    mapping = {
        "r": ("widerrufen", "danger"),
        "e": ("abgelaufen", "danger"),
        "d": ("deaktiviert", "warning"),
        "i": ("ungültig", "warning"),
        "-": ("unbekannt", "muted"),
        "q": ("unbekannt", "muted"),
        "n": ("nicht vertraut", "muted"),
        "m": ("teilweise vertraut", "warning"),
        "f": ("voll vertraut", "ok"),
        "u": ("gültig", "ok"),
    }
    return mapping.get(str(value or "")[:1], ("unbekannt", "muted"))


def keyring_metadata_settings() -> Dict[str, Dict[str, Any]]:
    value = load_settings().get("keyring_metadata")
    return value if isinstance(value, dict) else {}


def keyring_metadata_for(filename: str) -> Dict[str, Any]:
    meta = keyring_metadata_settings().get(filename)
    return meta if isinstance(meta, dict) else {}


def save_keyring_metadata(filename: str, values: Dict[str, Any]) -> None:
    filename = secure_filename(filename)
    if not filename:
        raise ValueError("Ungültiger Dateiname.")
    settings = load_settings()
    all_meta = settings.get("keyring_metadata") if isinstance(settings.get("keyring_metadata"), dict) else {}
    current = all_meta.get(filename) if isinstance(all_meta.get(filename), dict) else {}
    for key, value in values.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    current["updated_at"] = now_iso()
    all_meta[filename] = current
    settings["keyring_metadata"] = all_meta
    save_settings(settings)



def mirror_keyring_assignment_settings() -> Dict[str, List[Dict[str, Any]]]:
    value = load_settings().get("mirror_keyring_assignments")
    return value if isinstance(value, dict) else {}


def save_mirror_keyring_assignment_settings(assignments: Dict[str, List[Dict[str, Any]]]) -> None:
    settings = load_settings()
    settings["mirror_keyring_assignments"] = assignments
    save_settings(settings)


def keyring_filename_from_path(path_value: str) -> str:
    if not (path_value or "").strip():
        return ""
    try:
        path = Path(allowed_keyring_path(path_value))
    except Exception:
        return ""
    try:
        base = APP_KEYRING_DIR.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if base != resolved and base not in resolved.parents:
            return ""
    except Exception:
        return ""
    if path.parent.resolve(strict=False) != APP_KEYRING_DIR.resolve(strict=False):
        return ""
    if path.suffix.lower() not in {".gpg", ".asc", ".key"}:
        return ""
    return secure_filename(path.name)


def available_keyring_names() -> List[str]:
    names: List[str] = []
    for file in list_keyring_files():
        name = secure_filename(Path(file).name)
        if name:
            names.append(name)
    return sorted(set(names), key=str.lower)


def mirror_keyring_assignment_names(mirror_id: int) -> List[str]:
    result: List[str] = []
    for item in mirror_keyring_assignment_items(int(mirror_id)):
        name = item.get("filename") or ""
        if name and name not in result:
            result.append(name)
    return result


def set_mirror_keyring_assignment_names(mirror_id: int, filenames: Iterable[str]) -> None:
    set_mirror_keyring_assignment_items(int(mirror_id), [{"filename": filename, "fingerprint": ""} for filename in filenames])


def migrate_legacy_keyring_assignments() -> None:
    """Map old single mirror.keyring values to the new assignment list.

    The actual mirror field stays untouched until the user saves or rebuilds the
    assignment. This keeps old installations compatible and makes the existing
    key immediately visible in the new UI.
    """
    assignments = mirror_keyring_assignment_settings()
    changed = False
    with db() as con:
        rows = con.execute("SELECT id, keyring FROM mirrors WHERE COALESCE(keyring, '') != '' ORDER BY id").fetchall()
    for row in rows:
        mirror_id = int(row["id"])
        if str(mirror_id) in assignments:
            continue
        name = keyring_filename_from_path(row["keyring"] or "")
        if name and (APP_KEYRING_DIR / name).exists():
            assignments[str(mirror_id)] = [{"filename": name, "assigned_at": now_iso(), "migrated": 1}]
            changed = True
    if changed:
        save_mirror_keyring_assignment_settings(assignments)


def gpg_temp_home(prefix: str) -> Path:
    tmp_home = Path(tempfile.mkdtemp(prefix=prefix, dir=str(APP_DATA_DIR)))
    tmp_home.chmod(0o700)
    return tmp_home


def gpg_import_to_keyring(keyring_path: Path, source_path: Path) -> None:
    keyring_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_home = gpg_temp_home("debmirror-master-import-")
    try:
        result = subprocess.run(
            [
                "gpg", "--batch", "--yes", "--homedir", str(tmp_home),
                "--no-default-keyring", "--keyring", str(keyring_path),
                "--import", str(source_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            msg = result.stderr.decode("utf-8", "replace") or result.stdout.decode("utf-8", "replace") or "Key konnte nicht in den Master-Keyring importiert werden."
            raise RuntimeError(msg.strip())
        try:
            keyring_path.chmod(0o644)
        except OSError:
            pass
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def key_fingerprints_from_keyring_file(path: Path) -> List[str]:
    return [normalize_fingerprint(fp) for fp in key_fingerprints(path) if normalize_fingerprint(fp)]


def master_keyring_fingerprints() -> List[str]:
    if not MASTER_KEYRING_PATH.exists():
        return []
    return [normalize_fingerprint(fp) for fp in (master_keyring_details().get("fingerprints") or []) if normalize_fingerprint(fp)]


def master_keyring_all_fingerprints() -> List[str]:
    if not MASTER_KEYRING_PATH.exists():
        return []
    return [normalize_fingerprint(fp) for fp in (master_keyring_details().get("all_fingerprints") or []) if normalize_fingerprint(fp)]


def master_keyring_status_summary() -> Dict[str, Any]:
    details = master_keyring_details() if MASTER_KEYRING_PATH.exists() else {"keys": [], "fingerprints": [], "subkey_fingerprints": [], "all_fingerprints": [], "warnings": []}
    archive_files = archived_keyring_rows()
    removed = removed_master_key_fingerprints()
    return {
        "primary_count": len(details.get("fingerprints") or []),
        "subkey_count": len(details.get("subkey_fingerprints") or []),
        "all_fingerprint_count": len(details.get("all_fingerprints") or []),
        "archive_file_count": len(archive_files),
        "archive_primary_count": sum(len(item.get("fingerprints") or []) for item in archive_files),
        "archive_all_fingerprint_count": sum(len(item.get("all_fingerprints") or []) for item in archive_files),
        "removed_count": len(removed),
        "removed_fingerprints": removed,
        "warnings": details.get("warnings") or [],
    }


def fingerprint_in_master(fingerprint: str) -> bool:
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        return False
    return bool(master_keyring_match(fp))


def removed_master_key_fingerprints() -> List[str]:
    value = load_settings().get("removed_master_key_fingerprints")
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        fp = normalize_fingerprint(str(item or ""))
        if fp and fp not in result:
            result.append(fp)
    return result


def save_removed_master_key_fingerprints(fingerprints: Iterable[str]) -> None:
    cleaned: List[str] = []
    for item in fingerprints:
        fp = normalize_fingerprint(str(item or ""))
        if fp and fp not in cleaned:
            cleaned.append(fp)
    settings = load_settings()
    settings["removed_master_key_fingerprints"] = cleaned
    save_settings(settings)


def mark_master_key_removed(fingerprint: str) -> None:
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        return
    values = removed_master_key_fingerprints()
    if fp not in values:
        values.append(fp)
        save_removed_master_key_fingerprints(values)


def unmark_removed_master_fingerprints(fingerprints: Iterable[str]) -> None:
    wanted = [normalize_fingerprint(fp) for fp in fingerprints if normalize_fingerprint(fp)]
    if not wanted:
        return
    current = removed_master_key_fingerprints()
    updated = [fp for fp in current if not any(fingerprint_matches(fp, item) for item in wanted)]
    if updated != current:
        save_removed_master_key_fingerprints(updated)


def delete_fingerprints_from_keyring_file(keyring_path: Path, fingerprints: Iterable[str]) -> None:
    fps = [normalize_fingerprint(fp) for fp in fingerprints if normalize_fingerprint(fp)]
    if not fps or not keyring_path.exists():
        return
    tmp_home = gpg_temp_home("debmirror-master-delete-")
    try:
        cmd = [
            "gpg", "--batch", "--yes", "--homedir", str(tmp_home),
            "--no-default-keyring", "--keyring", str(keyring_path),
            "--delete-keys", *fps,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
        if result.returncode != 0:
            msg = result.stderr.decode("utf-8", "replace") or result.stdout.decode("utf-8", "replace") or "Key konnte nicht aus dem Keyring entfernt werden."
            # Ignore missing-key situations so a stale removal marker does not break rebuilds.
            msg_l = msg.lower()
            if "not found" not in msg_l and "nicht gefunden" not in msg_l and "not exported" not in msg_l:
                raise RuntimeError(msg.strip())
        try:
            keyring_path.chmod(0o644)
        except OSError:
            pass
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def purge_removed_master_key_fingerprints_from_keyring() -> None:
    if not MASTER_KEYRING_PATH.exists():
        return
    for fp in removed_master_key_fingerprints():
        if fingerprint_in_master(fp):
            delete_fingerprints_from_keyring_file(MASTER_KEYRING_PATH, [fp])


def remove_key_fingerprint_metadata_for_fingerprint(fingerprint: str) -> None:
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        return
    settings = load_settings()
    all_meta = settings.get("key_fingerprint_metadata") if isinstance(settings.get("key_fingerprint_metadata"), dict) else {}
    changed = False
    for existing in list(all_meta.keys()):
        if fingerprint_matches(existing, fp):
            all_meta.pop(existing, None)
            changed = True
    if changed:
        settings["key_fingerprint_metadata"] = all_meta
        save_settings(settings)


def remove_master_key(fingerprint: str) -> str:
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        raise ValueError("Kein Fingerprint angegeben.")
    used_by = master_key_used_by(fp)
    if used_by:
        names = ", ".join(str(item.get("name") or f"#{item.get('id')}") for item in used_by)
        raise ValueError(f"Key ist noch Profilen zugeordnet und kann nicht entfernt werden: {names}")
    if not fingerprint_in_master(fp):
        mark_master_key_removed(fp)
        remove_key_fingerprint_metadata_for_fingerprint(fp)
        return fp
    delete_fingerprints_from_keyring_file(MASTER_KEYRING_PATH, [fp])
    mark_master_key_removed(fp)
    remove_key_fingerprint_metadata_for_fingerprint(fp)
    return fp


def archived_keyring_path(filename: str, source_type: str = "") -> Path:
    name = secure_filename(filename or "")
    if not name:
        raise ValueError("Keine Quelldatei ausgewählt.")
    dirs = []
    if source_type == "keyserver":
        dirs = [KEYSERVER_KEYRING_DIR]
    elif source_type == "archive":
        dirs = [ARCHIVE_KEYRING_DIR]
    else:
        dirs = [ARCHIVE_KEYRING_DIR, KEYSERVER_KEYRING_DIR]
    for directory in dirs:
        path = (directory / name).resolve(strict=False)
        base = directory.resolve(strict=False)
        if base != path and base not in path.parents:
            continue
        if path.exists() and path.is_file():
            return path
    raise ValueError("Quelldatei nicht gefunden.")


def delete_archived_keyring_file(filename: str, source_type: str = "") -> str:
    path = archived_keyring_path(filename, source_type)
    name = path.name
    path.unlink()
    remove_key_fingerprint_metadata_for_file(name)
    settings = load_settings()
    all_meta = settings.get("keyring_metadata") if isinstance(settings.get("keyring_metadata"), dict) else {}
    if name in all_meta:
        all_meta.pop(name, None)
        settings["keyring_metadata"] = all_meta
        save_settings(settings)
    return name


def import_keyring_into_master(path: Path) -> List[str]:
    if not path.exists():
        raise ValueError(f"Keyring existiert nicht: {path}")
    fps = key_fingerprints_from_keyring_file(path)
    if not fps:
        raise ValueError(f"Keyring enthält keinen erkennbaren Fingerprint: {path.name}")
    gpg_import_to_keyring(MASTER_KEYRING_PATH, path)
    unmark_removed_master_fingerprints(fps)
    return fps


def rebuild_master_keyring(include_removed: bool = False) -> List[str]:
    if include_removed:
        # Vollständiger Neuaufbau: zuvor bewusst aus dem Master entfernte
        # Fingerprints werden wieder aus allen Quelldateien zugelassen.
        save_removed_master_key_fingerprints([])
    tmp_path = MASTER_KEYRING_PATH.with_suffix(".gpg.tmp")
    tmp_path.unlink(missing_ok=True)
    imported: List[str] = []
    for file in list_keyring_files(include_archived=True):
        path = Path(file)
        details = parse_keyring_details(path)
        fps = [normalize_fingerprint(fp) for fp in (details.get("fingerprints") or []) if normalize_fingerprint(fp)]
        if not fps:
            continue
        gpg_import_to_keyring(tmp_path, path)
        for fp in fps:
            if fp not in imported:
                imported.append(fp)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.replace(MASTER_KEYRING_PATH)
        try:
            MASTER_KEYRING_PATH.chmod(0o644)
        except OSError:
            pass
    else:
        MASTER_KEYRING_PATH.unlink(missing_ok=True)
    if not include_removed:
        purge_removed_master_key_fingerprints_from_keyring()
    return master_keyring_fingerprints()


def export_fingerprints_from_master(fingerprints: Iterable[str], armor: bool = False) -> bytes:
    if not MASTER_KEYRING_PATH.exists():
        rebuild_master_keyring()
    if not MASTER_KEYRING_PATH.exists():
        raise ValueError("Master-Keyring ist leer oder wurde noch nicht erzeugt.")
    fps: List[str] = []
    for fp in fingerprints:
        clean = normalize_fingerprint(fp)
        if not clean:
            continue
        primary = matching_master_fingerprint(clean) or clean
        if primary and primary not in fps:
            fps.append(primary)
    if not fps:
        raise ValueError("Keine Fingerprints für den Export angegeben.")
    tmp_home = gpg_temp_home("debmirror-master-export-")
    try:
        cmd = [
            "gpg", "--batch", "--homedir", str(tmp_home),
            "--no-default-keyring", "--keyring", str(MASTER_KEYRING_PATH),
        ]
        if armor:
            cmd.append("--armor")
        cmd.extend(["--export", *fps])
        exp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
        if exp.returncode != 0 or not exp.stdout:
            msg = exp.stderr.decode("utf-8", "replace") or "Keys konnten nicht aus dem Master-Keyring exportiert werden."
            raise RuntimeError(msg.strip())
        return exp.stdout
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def assignment_value(filename: str, fingerprint: str = "") -> str:
    name = secure_filename(filename or "")
    fp = normalize_fingerprint(fingerprint or "")
    if fp and not name:
        return f"master|{fp}"
    return f"{name}|{fp}" if fp else name


def parse_assignment_value(value: str) -> Dict[str, str]:
    value = str(value or "").strip()
    if "|" in value:
        name, fp = value.split("|", 1)
    else:
        name, fp = value, ""
    name = secure_filename(name or "")
    fp = normalize_fingerprint(fp or "")
    if name in {"master", "__master__"}:
        name = ""
    return {"filename": name, "fingerprint": fp}


def mirror_keyring_assignment_items(mirror_id: int) -> List[Dict[str, str]]:
    assignments = mirror_keyring_assignment_settings()
    rows = assignments.get(str(mirror_id))
    result: List[Dict[str, str]] = []
    seen = set()
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                name = secure_filename(row.get("filename") or "")
                fp = normalize_fingerprint(row.get("fingerprint") or "")
            else:
                parsed = parse_assignment_value(str(row or ""))
                name = parsed["filename"]
                fp = parsed["fingerprint"]
            key = (name, fp)
            if (name or fp) and key not in seen:
                seen.add(key)
                result.append({"filename": name, "fingerprint": fp})
    return result


def set_mirror_keyring_assignment_items(mirror_id: int, items: Iterable[Dict[str, str]]) -> None:
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        name = secure_filename(item.get("filename") or "")
        fp = normalize_fingerprint(item.get("fingerprint") or "")
        if not name and not fp:
            continue
        if name:
            path = APP_KEYRING_DIR / name
            if not path.exists() or not path.is_file():
                # New imports are archived and assigned by fingerprint only.
                # Keep old broken file assignments from being saved again.
                if not fp:
                    raise ValueError(f"Keyring existiert nicht: {name}")
                name = ""
            else:
                if path.suffix.lower() not in {".gpg", ".asc", ".key"}:
                    raise ValueError(f"Ungültiger Keyring-Typ: {name}")
                available = key_fingerprints_from_keyring_file(path)
                if fp and not any(fingerprint_matches(existing, fp) for existing in available):
                    raise ValueError(f"Fingerprint {fp} wurde in {name} nicht gefunden.")
        if fp:
            master_match = master_keyring_match(fp)
            if master_match:
                fp = normalize_fingerprint(master_match.get("primary_fingerprint") or fp)
            elif name and (APP_KEYRING_DIR / name).exists():
                import_keyring_into_master(APP_KEYRING_DIR / name)
                master_match = master_keyring_match(fp)
                if master_match:
                    fp = normalize_fingerprint(master_match.get("primary_fingerprint") or fp)
            if not fingerprint_in_master(fp):
                raise ValueError(f"Fingerprint {fp} ist nicht im Master-Keyring vorhanden.")
        key = (name, fp)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"filename": name, "fingerprint": fp, "assigned_at": now_iso()})
    assignments = mirror_keyring_assignment_settings()
    if cleaned:
        assignments[str(mirror_id)] = cleaned
    else:
        assignments.pop(str(mirror_id), None)
    save_mirror_keyring_assignment_settings(assignments)


def assigned_fingerprints_for_mirror(mirror_id: int) -> List[str]:
    fps: List[str] = []
    for item in mirror_keyring_assignment_items(mirror_id):
        if item.get("fingerprint") and not item.get("filename"):
            candidates = [item["fingerprint"]]
        else:
            path = APP_KEYRING_DIR / item.get("filename", "")
            if not path.exists():
                continue
            if item.get("fingerprint"):
                candidates = [item["fingerprint"]]
            else:
                candidates = key_fingerprints_from_keyring_file(path)
        for fp in candidates:
            clean = normalize_fingerprint(fp)
            if clean and clean not in fps:
                fps.append(clean)
    return fps


def profile_keyring_path_for_mirror(mirror: Dict[str, Any]) -> Path:
    mirror_id = int(mirror.get("id") or 0)
    safe_name = secure_filename(mirror.get("name") or f"mirror-{mirror_id}") or f"mirror-{mirror_id}"
    return PROFILE_KEYRING_DIR / f"mirror-{mirror_id}-{safe_name}.gpg"


def rebuild_profile_keyring(mirror_id: int) -> Path:
    mirror = get_mirror(mirror_id)
    if not mirror:
        raise ValueError("Mirror-Profil nicht gefunden.")
    items = mirror_keyring_assignment_items(mirror_id)
    generated = profile_keyring_path_for_mirror(mirror)
    if not items:
        clear_managed_keyring_assignments(mirror_id, clear_db_fields=True)
        raise ValueError("Diesem Profil sind keine Keyrings zugeordnet.")

    selected_fps: List[str] = []
    for item in items:
        if item.get("fingerprint") and not item.get("filename"):
            fp = normalize_fingerprint(item["fingerprint"])
            if not fingerprint_in_master(fp):
                raise ValueError(f"Fingerprint {fp} ist nicht im Master-Keyring vorhanden.")
            if fp not in selected_fps:
                selected_fps.append(fp)
            continue
        path = (APP_KEYRING_DIR / item["filename"]).resolve(strict=False)
        base = APP_KEYRING_DIR.resolve(strict=False)
        if base != path and base not in path.parents:
            raise ValueError("Ungültiger Keyring-Pfad.")
        if not path.exists():
            raise ValueError(f"Zugeordneter Keyring fehlt: {path.name}")
        file_fps = import_keyring_into_master(path)
        if item.get("fingerprint"):
            fp = item["fingerprint"]
            if not any(fingerprint_matches(existing, fp) for existing in file_fps):
                raise ValueError(f"Fingerprint {fp} wurde in {path.name} nicht gefunden.")
            if fp not in selected_fps:
                selected_fps.append(fp)
        else:
            # Kompatibilität für alte Dateizuordnungen: ohne Fingerprint werden alle Keys der Datei exportiert.
            for fp in file_fps:
                if fp not in selected_fps:
                    selected_fps.append(fp)

    PROFILE_KEYRING_DIR.mkdir(parents=True, exist_ok=True)
    generated.write_bytes(export_fingerprints_from_master(selected_fps, armor=False))
    try:
        generated.chmod(0o644)
    except OSError:
        pass
    expected = selected_fps[0] if len(selected_fps) == 1 else ""
    with db() as con:
        con.execute(
            "UPDATE mirrors SET keyring=?, keyring_fingerprint=?, updated_at=? WHERE id=?",
            (str(generated), expected, now_iso(), mirror_id),
        )
    return generated


def save_mirror_keyring_assignments_and_rebuild(mirror_id: int, filenames: Iterable[str]) -> Path:
    parsed = [parse_assignment_value(value) for value in filenames]
    set_mirror_keyring_assignment_items(mirror_id, parsed)
    return rebuild_profile_keyring(mirror_id)


def assign_master_fingerprints_to_mirror(mirror_id: Optional[int], fingerprints: Iterable[str]) -> None:
    if not mirror_id:
        return
    resolved: List[str] = []
    for fingerprint in fingerprints:
        fp = normalize_fingerprint(fingerprint)
        if not fp:
            continue
        primary = matching_master_fingerprint(fp)
        if not primary:
            raise ValueError(f"Fingerprint {fp} ist nicht im Master-Keyring vorhanden.")
        if primary not in resolved:
            resolved.append(primary)
    if not resolved:
        raise ValueError("Kein Fingerprint für die Zuordnung angegeben.")
    current = mirror_keyring_assignment_items(int(mirror_id))
    for fp in resolved:
        if not any((not item.get("filename")) and fingerprint_matches(item.get("fingerprint", ""), fp) for item in current):
            current.append({"filename": "", "fingerprint": fp})
    set_mirror_keyring_assignment_items(int(mirror_id), current)
    rebuild_profile_keyring(int(mirror_id))


def assign_master_fingerprint_to_mirror(mirror_id: Optional[int], fingerprint: str) -> None:
    assign_master_fingerprints_to_mirror(mirror_id, [fingerprint])


def assign_keyring_filename_to_mirror(mirror_id: Optional[int], filename: str, fingerprint: str = "") -> None:
    if not mirror_id:
        return
    current = mirror_keyring_assignment_items(int(mirror_id))
    name = secure_filename(filename or "")
    fp = normalize_fingerprint(fingerprint or "")
    if not name:
        raise ValueError("Ungültiger Keyring-Dateiname.")
    if not any(item.get("filename") == name and item.get("fingerprint", "") == fp for item in current):
        current.append({"filename": name, "fingerprint": fp})
    set_mirror_keyring_assignment_items(int(mirror_id), current)
    rebuild_profile_keyring(int(mirror_id))


def unassign_keyring_filename_from_mirror(mirror_id: int, filename: str, fingerprint: str = "") -> None:
    raw_name = str(filename or "").strip()
    name = secure_filename(raw_name)
    if raw_name in {"Master-Keyring", "master", "__master__"} or name in {"Master-Keyring", "master", "__master__"}:
        name = ""
    fp = normalize_fingerprint(fingerprint or "")
    current = []
    for item in mirror_keyring_assignment_items(int(mirror_id)):
        if name and item.get("filename") != name:
            current.append(item)
            continue
        if not name and item.get("filename"):
            current.append(item)
            continue
        if fp and not fingerprint_matches(item.get("fingerprint", ""), fp):
            current.append(item)
    if current:
        set_mirror_keyring_assignment_items(int(mirror_id), current)
        rebuild_profile_keyring(int(mirror_id))
    else:
        clear_managed_keyring_assignments(int(mirror_id), clear_db_fields=True)


def assigned_keyring_rows_for_mirror(mirror_id: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in mirror_keyring_assignment_items(int(mirror_id)):
        name = item.get("filename") or ""
        fp_selected = normalize_fingerprint(item.get("fingerprint") or "")
        if fp_selected and not name:
            matches = [k for k in master_key_rows() if fingerprint_matches(k.get("fingerprint") or "", fp_selected)]
            key = matches[0] if matches else {"fingerprint": fp_selected, "display_name": fp_selected[-16:], "uids": []}
            rows.append({
                "name": "Master-Keyring",
                "path": str(MASTER_KEYRING_PATH),
                "missing": 0 if matches else 1,
                "display_name": key.get("display_name") or fp_selected[-16:],
                "active": 1,
                "fingerprints": [fp_selected],
                "selected_fingerprint": fp_selected,
                "legacy_whole_file": 0,
                "key_entries": [key] if matches else [],
                "master_assignment": 1,
            })
            continue
        path = APP_KEYRING_DIR / name
        if not path.exists():
            rows.append({"name": name, "path": str(path), "missing": 1, "fingerprints": [], "selected_fingerprint": fp_selected, "display_name": name})
            continue
        details = parse_keyring_details(path)
        meta = keyring_metadata_for(path.name)
        entries = details.get("keys") or []
        selected_entries = []
        if fp_selected:
            for key in entries:
                if fingerprint_matches(key.get("fingerprint") or "", fp_selected):
                    selected_entries.append(key)
        else:
            selected_entries = entries
        rows.append({
            "name": path.name,
            "path": str(path),
            "missing": 0,
            "display_name": meta.get("display_name") or path.stem,
            "active": 1 if meta.get("active", 1) else 0,
            "fingerprints": [fp_selected] if fp_selected else (details.get("fingerprints") or key_fingerprints(path)),
            "selected_fingerprint": fp_selected,
            "legacy_whole_file": 0 if fp_selected else 1,
            "key_entries": selected_entries,
        })
    return rows


def mirror_choices_for_keyring_forms() -> List[Dict[str, Any]]:
    return list_mirrors()


def keyring_used_by(path: Path) -> List[Dict[str, Any]]:
    migrate_legacy_keyring_assignments()
    path_s = str(path)
    name = path.name
    result: Dict[int, Dict[str, Any]] = {}
    with db() as con:
        rows = con.execute(
            """
            SELECT id, name, enabled, keyring, keyring_fingerprint
            FROM mirrors
            WHERE keyring = ? OR keyring LIKE ?
            ORDER BY name COLLATE NOCASE
            """,
            (path_s, f"%/{name}"),
        ).fetchall()
    for row in rows:
        item = row_to_dict(row)
        item["usage_type"] = "direkt"
        result[int(item["id"])] = item
    assignments = mirror_keyring_assignment_settings()
    if isinstance(assignments, dict):
        with db() as con:
            for mirror_id_s, items in assignments.items():
                if not isinstance(items, list):
                    continue
                found = False
                for entry in items:
                    entry_name = secure_filename(entry.get("filename") if isinstance(entry, dict) else str(entry or ""))
                    if entry_name == name:
                        found = True
                        break
                if not found:
                    continue
                try:
                    mirror_id = int(mirror_id_s)
                except Exception:
                    continue
                if mirror_id in result:
                    result[mirror_id]["usage_type"] = "direkt + zugeordnet"
                    continue
                row = con.execute("SELECT id, name, enabled, keyring, keyring_fingerprint FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
                if row:
                    item = row_to_dict(row)
                    item["usage_type"] = "zugeordnet"
                    result[mirror_id] = item
    return sorted(result.values(), key=lambda m: (str(m.get("name") or "").lower(), int(m.get("id") or 0)))


def parse_keyring_details(path: Path) -> Dict[str, Any]:
    """Read archive/import key files with all supported GPG read paths.

    Archive files and the Master-Keyring use comparable parsing, with Master metadata as fallback for archive display.
    This avoids missing subkeys in the error diagnosis when `--show-keys` sees
    less than GnuPG's normalized keyring/import view.
    """
    if not path.exists():
        return {"keys": [], "fingerprints": [], "subkey_fingerprints": [], "all_fingerprints": [], "warnings": [], "raw": ""}
    show_details = parse_gpg_colon_output(gpg_show_key_output(path))
    keyring_details = parse_gpg_colon_output(gpg_keyring_list_output(path))
    # Temporary import is the most normalized view for exported public-key
    # blocks.  It also catches cases where a file contains multiple keys and
    # only some subkeys were visible in the fast `--show-keys` path.
    import_details = parse_gpg_colon_output(gpg_imported_keyfile_list_output(path))
    return merge_gpg_detail_sets(show_details, keyring_details, import_details)


def export_keyring_armored_bytes(path: Path) -> bytes:
    tmp_home = Path(tempfile.mkdtemp(prefix="debmirror-key-export-", dir=str(APP_DATA_DIR)))
    try:
        tmp_home.chmod(0o700)
        imp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--import", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if imp.returncode != 0:
            raise RuntimeError((imp.stderr.decode("utf-8", "replace") or "Key konnte nicht importiert werden.").strip())
        exp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--armor", "--export"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if exp.returncode != 0 or not exp.stdout:
            raise RuntimeError((exp.stderr.decode("utf-8", "replace") or "Key konnte nicht exportiert werden.").strip())
        return exp.stdout
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def export_keyring_selected_key_bytes(path: Path, fingerprint: str, armor: bool = False) -> bytes:
    fp = normalize_fingerprint(fingerprint)
    if not fp:
        raise ValueError("Kein Fingerprint angegeben.")
    available = [normalize_fingerprint(item) for item in key_fingerprints(path)]
    if not any(fingerprint_matches(item, fp) for item in available):
        raise ValueError("Dieser Fingerprint wurde im Keyring nicht gefunden.")
    tmp_home = Path(tempfile.mkdtemp(prefix="debmirror-key-single-", dir=str(APP_DATA_DIR)))
    try:
        tmp_home.chmod(0o700)
        imp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--import", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if imp.returncode != 0:
            raise RuntimeError((imp.stderr.decode("utf-8", "replace") or "Key konnte nicht importiert werden.").strip())
        cmd = ["gpg", "--batch", "--homedir", str(tmp_home)]
        if armor:
            cmd.append("--armor")
        cmd.extend(["--export", fp])
        exp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if exp.returncode != 0 or not exp.stdout:
            raise RuntimeError((exp.stderr.decode("utf-8", "replace") or "Einzelner Key konnte nicht exportiert werden.").strip())
        return exp.stdout
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def keyring_binary_bytes_for_client(path: Path) -> bytes:
    if path.suffix.lower() == ".gpg":
        return path.read_bytes()
    tmp_home = Path(tempfile.mkdtemp(prefix="debmirror-key-client-", dir=str(APP_DATA_DIR)))
    try:
        tmp_home.chmod(0o700)
        imp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--import", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if imp.returncode != 0:
            raise RuntimeError((imp.stderr.decode("utf-8", "replace") or "Key konnte nicht importiert werden.").strip())
        exp = subprocess.run(
            ["gpg", "--batch", "--homedir", str(tmp_home), "--export"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if exp.returncode != 0 or not exp.stdout:
            raise RuntimeError((exp.stderr.decode("utf-8", "replace") or "Key konnte nicht als .gpg exportiert werden.").strip())
        return exp.stdout
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


def client_source_lines(
    mirror: Dict[str, Any],
    base_url: str,
    keyring_filename: str,
    selected_dists: Optional[List[str]] = None,
    selected_archs: Optional[List[str]] = None,
) -> Tuple[str, str]:
    name = secure_filename(mirror.get("name") or "mirror") or "mirror"
    base_url = base_url.rstrip("/") + "/"
    dists = selected_dists if selected_dists is not None else csv_to_list(str(mirror.get("dists") or ""))
    sections = " ".join(csv_to_list(str(mirror.get("sections") or ""))) or "main"
    archs = selected_archs if selected_archs is not None else csv_to_list(str(mirror.get("archs") or ""))
    arch_part = ",".join(archs)
    signed_by = f"/usr/share/keyrings/{keyring_filename}"
    types = "deb deb-src" if mirror.get("source_mode") == "source" else "deb"
    suites = " ".join(dists)
    deb822 = [
        f"Types: {types}",
        f"URIs: {base_url}",
        f"Suites: {suites}",
        f"Components: {sections}",
    ]
    if arch_part:
        deb822.append(f"Architectures: {' '.join(archs)}")
    deb822.append(f"Signed-By: {signed_by}")
    deb822_text = "\n".join(deb822) + "\n"

    option_parts = []
    if arch_part:
        option_parts.append(f"arch={arch_part}")
    option_parts.append(f"signed-by={signed_by}")
    opts = "[" + " ".join(option_parts) + "]"
    list_lines = []
    for dist in dists:
        list_lines.append(f"deb {opts} {base_url} {dist} {sections}")
        if mirror.get("source_mode") == "source":
            list_lines.append(f"deb-src {opts} {base_url} {dist} {sections}")
    return deb822_text, "\n".join(list_lines) + "\n"


def validate_client_export_selection(mirror: Dict[str, Any], selected_dists_raw: List[str], selected_archs_raw: List[str]) -> Tuple[List[str], List[str]]:
    profile_dists = csv_to_list(str(mirror.get("dists") or ""))
    profile_archs = csv_to_list(str(mirror.get("archs") or ""))
    selected_dists_set = {str(v).strip() for v in selected_dists_raw if str(v).strip()}
    selected_archs_set = {str(v).strip() for v in selected_archs_raw if str(v).strip()}
    selected_dists = [d for d in profile_dists if d in selected_dists_set]
    selected_archs = [a for a in profile_archs if a in selected_archs_set]
    invalid_dists = sorted(selected_dists_set - set(profile_dists))
    invalid_archs = sorted(selected_archs_set - set(profile_archs))
    if invalid_dists:
        raise ValueError("Ungültige Suite-Auswahl für den Client-Export.")
    if invalid_archs:
        raise ValueError("Ungültige Architektur-Auswahl für den Client-Export.")
    if not selected_dists:
        raise ValueError("Wähle mindestens eine Suite für den Client-Export aus.")
    if profile_archs and not selected_archs:
        raise ValueError("Wähle mindestens eine Architektur für den Client-Export aus.")
    return selected_dists, selected_archs


def fingerprint_matches(candidate: str, expected: str) -> bool:
    candidate_n = normalize_fingerprint(candidate)
    expected_n = normalize_fingerprint(expected)
    if not candidate_n or not expected_n:
        return False
    return candidate_n == expected_n or candidate_n.endswith(expected_n) or expected_n.endswith(candidate_n)


def match_from_key_details(details: Dict[str, Any], expected: str) -> Dict[str, Any]:
    """Resolve a reported key id/fingerprint to the containing primary key.

    gpgv can report a short key ID, a long key ID, a full primary fingerprint
    or a full signing-subkey fingerprint.  Older versions required a populated
    full subkey fingerprint before matching; this missed valid matches when GPG
    exposed only the subkey key_id in one read path.
    """
    expected_n = normalize_fingerprint(expected)
    if not expected_n:
        return {}

    def candidates(*values: str) -> List[str]:
        result: List[str] = []
        for value in values:
            clean = normalize_fingerprint(value or "")
            if not clean:
                continue
            for candidate in (clean, clean[-16:] if len(clean) >= 16 else "", clean[-8:] if len(clean) >= 8 else ""):
                if candidate and candidate not in result:
                    result.append(candidate)
        return result

    def any_match(values: Iterable[str]) -> bool:
        return any(fingerprint_matches(value, expected_n) for value in values if value)

    for key in details.get("keys") or []:
        primary_fp = normalize_fingerprint(key.get("fingerprint") or "")
        primary_key_id = normalize_fingerprint(key.get("key_id") or "")
        primary_candidates = candidates(primary_fp, primary_key_id)
        if any_match(primary_candidates):
            return {
                "primary_fingerprint": primary_fp or primary_key_id,
                "matched_fingerprint": primary_fp or primary_key_id,
                "matched_key_id": primary_key_id,
                "matched_type": "Hauptkey",
                "key": key,
            }
        for sub in key.get("subkeys") or []:
            sub_fp = normalize_fingerprint(sub.get("fingerprint") or "")
            sub_key_id = normalize_fingerprint(sub.get("key_id") or "")
            sub_candidates = candidates(sub_fp, sub_key_id)
            if any_match(sub_candidates):
                return {
                    "primary_fingerprint": primary_fp or primary_key_id,
                    "matched_fingerprint": sub_fp or sub_key_id,
                    "matched_key_id": sub_key_id,
                    "matched_type": "Subkey",
                    "key": key,
                    "subkey": sub,
                }
    return {}


def master_keyring_match(expected: str) -> Dict[str, Any]:
    """Return the primary master key that matches a primary/subkey fp or key-id.

    The matching path is intentionally redundant: parsed Master view, direct
    all-fingerprint scan and GnuPG query.  This prevents false negatives when
    gpgv reports only a signing-subkey ID while the Master-Keyring already
    contains the key.
    """
    expected_n = normalize_fingerprint(expected)
    if not expected_n or not MASTER_KEYRING_PATH.exists():
        return {}
    details = master_keyring_details()
    direct = match_from_key_details(details, expected_n)
    if direct:
        direct["match_source"] = "parsed"
        return direct

    # Last-resort parsed scan over every known primary/subkey fingerprint.
    for key in details.get("keys") or []:
        primary_fp = normalize_fingerprint(key.get("fingerprint") or "")
        primary_key_id = normalize_fingerprint(key.get("key_id") or "")
        for candidate in [primary_fp, primary_key_id, primary_fp[-16:], primary_fp[-8:], primary_key_id[-16:], primary_key_id[-8:]]:
            if candidate and fingerprint_matches(candidate, expected_n):
                return {
                    "primary_fingerprint": primary_fp or primary_key_id,
                    "matched_fingerprint": primary_fp or primary_key_id,
                    "matched_key_id": primary_key_id,
                    "matched_type": "Hauptkey",
                    "key": key,
                    "match_source": "all-fingerprint-scan",
                }
        for sub in key.get("subkeys") or []:
            sub_fp = normalize_fingerprint(sub.get("fingerprint") or "")
            sub_key_id = normalize_fingerprint(sub.get("key_id") or "")
            for candidate in [sub_fp, sub_key_id, sub_fp[-16:], sub_fp[-8:], sub_key_id[-16:], sub_key_id[-8:]]:
                if candidate and fingerprint_matches(candidate, expected_n):
                    return {
                        "primary_fingerprint": primary_fp or primary_key_id,
                        "matched_fingerprint": sub_fp or sub_key_id,
                        "matched_key_id": sub_key_id,
                        "matched_type": "Subkey",
                        "key": key,
                        "subkey": sub,
                        "match_source": "all-fingerprint-scan",
                    }

    queried_details = parse_gpg_colon_output(gpg_keyring_query_output(MASTER_KEYRING_PATH, expected_n))
    queried = match_from_key_details(queried_details, expected_n)
    if queried:
        queried["match_source"] = "gpg-query"
        return queried
    return {}


def keyring_file_match(path: Path, expected: str) -> Dict[str, Any]:
    """Return the primary key in an exported/archive key file matching expected.

    Archive files can be exported key blocks or real GnuPG keyrings.  Use the
    merged generic parser first and then targeted GnuPG queries/imports as a
    fallback for short key IDs from gpgv.
    """
    expected_n = normalize_fingerprint(expected)
    if not expected_n or not path.exists():
        return {}
    details = archive_keyring_details(path)
    direct = match_from_key_details(details, expected_n)
    if direct:
        direct["match_source"] = direct.get("match_source") or "archive-parsed"
        return direct

    # If the Master-Keyring can resolve the reported key/subkey but the archive
    # parser only exposes the matching primary key, still show the archive file
    # as a valid fallback. This avoids confusing cases where a Keyserver import
    # says the key already exists while the diagnosis lists only the Master hit.
    master_match = master_keyring_match(expected_n)
    master_primary = normalize_fingerprint(master_match.get("primary_fingerprint") or "") if master_match else ""
    archive_candidates = list(details.get("fingerprints") or []) + list(details.get("subkey_fingerprints") or []) + list(details.get("all_fingerprints") or [])
    if master_primary and any(fingerprint_matches(fp, master_primary) or fingerprint_matches(fp, expected_n) for fp in archive_candidates):
        result = dict(master_match)
        result["primary_fingerprint"] = master_primary
        result["matched_fingerprint"] = normalize_fingerprint(master_match.get("matched_fingerprint") or expected_n)
        result["matched_type"] = master_match.get("matched_type") or "Master-Abgleich"
        result["match_source"] = "archive-master-crosscheck"
        return result
    # Fallback 1: treat file as a real GnuPG keyring and ask GnuPG to resolve
    # the expected ID/fingerprint inside it.
    keyring_query = match_from_key_details(parse_gpg_colon_output(gpg_keyring_query_output(path, expected_n)), expected_n)
    if keyring_query:
        keyring_query["match_source"] = "archive-keyring-query"
        return keyring_query
    # Fallback 2: import into a temporary GNUPGHOME and query the normalized
    # imported view.  This catches exported key blocks with signing subkey IDs.
    imported_query = match_from_key_details(parse_gpg_colon_output(gpg_imported_keyfile_list_output(path, expected_n)), expected_n)
    if imported_query:
        imported_query["match_source"] = "archive-import-query"
        return imported_query
    return {}


def matching_master_fingerprint(expected: str) -> str:
    """Return the primary master fingerprint matching a key-id/fingerprint."""
    match = master_keyring_match(expected)
    return normalize_fingerprint(match.get("primary_fingerprint") or "")


def find_matching_keyrings(expected: str) -> List[Dict[str, Any]]:
    """Find already imported keys that match the expected key id/fingerprint.

    Master-Keyring matches are resolved from primary and subkey fingerprints to
    the primary fingerprint, so assigning a NO_PUBKEY signing subkey creates a
    correct, minimal profile keyring instead of falling back to an archive file.
    """
    expected_n = normalize_fingerprint(expected)
    if not expected_n:
        return []
    matches: List[Dict[str, Any]] = []
    seen = set()

    def add_match(item: Dict[str, Any]) -> None:
        fp = normalize_fingerprint(item.get("fingerprint") or "")
        key = (item.get("kind") or "", item.get("path") or "", fp, item.get("expected") or expected_n)
        if fp and key not in seen:
            seen.add(key)
            matches.append(item)

    master_match = master_keyring_match(expected_n)
    if master_match:
        primary_fp = normalize_fingerprint(master_match.get("primary_fingerprint") or "")
        add_match({
            "kind": "master",
            "path": str(MASTER_KEYRING_PATH),
            "name": "Master-Keyring",
            "fingerprints": [primary_fp],
            "fingerprint": primary_fp,
            "matched_fingerprint": normalize_fingerprint(master_match.get("matched_fingerprint") or primary_fp),
            "matched_type": master_match.get("matched_type") or "Hauptkey",
            "match_source": master_match.get("match_source") or "parsed",
        })
    for file in list_keyring_files(include_archived=True):
        p = Path(file)
        file_match = keyring_file_match(p, expected_n)
        if file_match:
            primary_fp = normalize_fingerprint(file_match.get("primary_fingerprint") or "")
            if primary_fp and fingerprint_in_master(primary_fp):
                # Prefer direct Master-Keyring assignment when the same primary key
                # is already imported. The archive file remains visible as fallback.
                master_by_primary = master_keyring_match(primary_fp) or file_match
                add_match({
                    "kind": "master",
                    "path": str(MASTER_KEYRING_PATH),
                    "name": "Master-Keyring",
                    "fingerprints": [primary_fp],
                    "fingerprint": primary_fp,
                    "matched_fingerprint": normalize_fingerprint(file_match.get("matched_fingerprint") or primary_fp),
                    "matched_type": file_match.get("matched_type") or "Hauptkey",
                    "match_source": master_by_primary.get("match_source") or "archive-crosscheck",
                })
            add_match({
                "kind": "file",
                "path": str(p),
                "name": p.name,
                "fingerprints": [primary_fp],
                "fingerprint": primary_fp,
                "matched_fingerprint": normalize_fingerprint(file_match.get("matched_fingerprint") or primary_fp),
                "matched_type": file_match.get("matched_type") or "Hauptkey",
            })
    return matches

def keyring_rows() -> List[Dict[str, Any]]:
    """Legacy/import-file rows. Hidden from the main UI since v0.1.51."""
    migrate_legacy_keyring_assignments()
    rows: List[Dict[str, Any]] = []
    for file in list_keyring_files():
        p = Path(file)
        details = parse_keyring_details(p)
        for entry in details.get("keys") or []:
            entry["master_present"] = fingerprint_in_master(entry.get("fingerprint") or "")
        meta = keyring_metadata_for(p.name)
        rows.append({
            "path": str(p),
            "name": p.name,
            "display_name": meta.get("display_name") or p.stem,
            "source_url": meta.get("source_url") or "",
            "notes": meta.get("notes") or "",
            "active": 1 if meta.get("active", 1) else 0,
            "size": p.stat().st_size,
            "fingerprints": details.get("fingerprints") or key_fingerprints(p),
            "key_entries": details.get("keys") or [],
            "warnings": details.get("warnings") or [],
            "master_present": all(fingerprint_in_master(fp) for fp in (details.get("fingerprints") or [])) if (details.get("fingerprints") or []) else False,
            "used_by": keyring_used_by(p),
        })
        rows[-1]["unused"] = not rows[-1]["used_by"]
    return rows


def master_key_used_by(fingerprint: str) -> List[Dict[str, Any]]:
    fp = normalize_fingerprint(fingerprint)
    result: Dict[int, Dict[str, Any]] = {}
    assignments = mirror_keyring_assignment_settings()
    with db() as con:
        for mirror_id_s, items in assignments.items() if isinstance(assignments, dict) else []:
            if not isinstance(items, list):
                continue
            matched = False
            for entry in items:
                entry_fp = normalize_fingerprint(entry.get("fingerprint") if isinstance(entry, dict) else "")
                if entry_fp and fingerprint_matches(entry_fp, fp):
                    matched = True
                    break
            if not matched:
                continue
            try:
                mirror_id = int(mirror_id_s)
            except Exception:
                continue
            row = con.execute("SELECT id, name, enabled, keyring, keyring_fingerprint FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
            if row:
                item = row_to_dict(row)
                item["usage_type"] = "zugeordnet"
                result[int(item["id"])] = item
        rows = con.execute(
            "SELECT id, name, enabled, keyring, keyring_fingerprint FROM mirrors WHERE COALESCE(keyring_fingerprint, '') != '' ORDER BY name COLLATE NOCASE"
        ).fetchall()
        for row in rows:
            item = row_to_dict(row)
            if fingerprint_matches(item.get("keyring_fingerprint") or "", fp):
                item["usage_type"] = "Fingerprint"
                result[int(item["id"])] = item
    return sorted(result.values(), key=lambda m: (str(m.get("name") or "").lower(), int(m.get("id") or 0)))


def master_key_rows() -> List[Dict[str, Any]]:
    meta_all = key_fingerprint_metadata_settings()
    rows: List[Dict[str, Any]] = []
    for item in master_keyring_details().get("keys") or []:
        fp = normalize_fingerprint(item.get("fingerprint") or "")
        meta = meta_all.get(fp) if isinstance(meta_all.get(fp), dict) else {}
        rows.append({
            **item,
            "fingerprint": fp,
            "display_name": meta.get("display_name") or ((item.get("uids") or [{}])[0].get("uid") if item.get("uids") else (item.get("key_id") or fp[-16:])),
            "source_url": meta.get("source_url") or "",
            "notes": meta.get("notes") or "",
            "metadata": meta,
            "used_by": master_key_used_by(fp),
            "assignment_value": assignment_value("", fp),
        })
    return rows


def archived_keyring_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    source_dirs = [(ARCHIVE_KEYRING_DIR, "archive", "Archiv"), (KEYSERVER_KEYRING_DIR, "keyserver", "Keyserver")]
    for file in list_keyring_files(include_archived=True):
        p = Path(file)
        source_type = ""
        source_label = "Archiv"
        for directory, stype, label in source_dirs:
            try:
                if directory.resolve(strict=False) == p.parent.resolve(strict=False):
                    source_type = stype
                    source_label = label
                    break
            except Exception:
                continue
        if not source_type:
            continue
        details = archive_keyring_details(p)
        rows.append({
            "name": p.name,
            "path": str(p),
            "source_type": source_type,
            "source_label": source_label,
            "size": p.stat().st_size,
            "fingerprints": details.get("fingerprints") or [],
            "subkey_fingerprints": details.get("subkey_fingerprints") or [],
            "all_fingerprints": details.get("all_fingerprints") or [],
            "master_supplemented": bool(details.get("master_supplemented")),
        })
    return rows


def key_fingerprint_metadata_settings() -> Dict[str, Dict[str, Any]]:
    value = load_settings().get("key_fingerprint_metadata")
    return value if isinstance(value, dict) else {}


def save_key_fingerprint_metadata(filename: str, details: Dict[str, Any], source_url: str = "", display_name: str = "", notes: str = "") -> None:
    settings = load_settings()
    all_meta = settings.get("key_fingerprint_metadata") if isinstance(settings.get("key_fingerprint_metadata"), dict) else {}
    for item in details.get("keys") or []:
        fp = normalize_fingerprint(item.get("fingerprint") or "")
        if not fp:
            continue
        current = all_meta.get(fp) if isinstance(all_meta.get(fp), dict) else {}
        current.update({
            "keyring": filename,
            "key_id": item.get("key_id") or "",
            "uids": [uid.get("uid") for uid in item.get("uids") or [] if uid.get("uid")],
            "algorithm": item.get("algorithm") or "",
            "length": item.get("length") or "",
            "created": item.get("created") or "",
            "expires": item.get("expires") or "",
            "status": item.get("status") or "unbekannt",
            "source_url": source_url or current.get("source_url", ""),
            "display_name": display_name or current.get("display_name", ""),
            "notes": notes or current.get("notes", ""),
            "updated_at": now_iso(),
        })
        all_meta[fp] = current
    settings["key_fingerprint_metadata"] = all_meta
    save_settings(settings)


def remove_key_fingerprint_metadata_for_file(filename: str) -> None:
    settings = load_settings()
    all_meta = settings.get("key_fingerprint_metadata") if isinstance(settings.get("key_fingerprint_metadata"), dict) else {}
    changed = False
    for fp, meta in list(all_meta.items()):
        if isinstance(meta, dict) and meta.get("keyring") == filename:
            all_meta.pop(fp, None)
            changed = True
    if changed:
        settings["key_fingerprint_metadata"] = all_meta
        save_settings(settings)


def keyring_duplicate_matches(fingerprints: Iterable[str], exclude_name: str = "", include_master: bool = True) -> List[Dict[str, Any]]:
    wanted = [normalize_fingerprint(fp) for fp in fingerprints if normalize_fingerprint(fp)]
    if not wanted:
        return []
    matches: List[Dict[str, Any]] = []
    seen = set()
    if include_master:
        for existing_fp in master_keyring_fingerprints():
            for fp in wanted:
                if fingerprint_matches(existing_fp, fp):
                    key = ("Master-Keyring", existing_fp, fp)
                    if key not in seen:
                        seen.add(key)
                        matches.append({"name": "Master-Keyring", "path": str(MASTER_KEYRING_PATH), "existing_fingerprint": existing_fp, "fingerprint": fp})
    for file in list_keyring_files(include_archived=True):
        p = Path(file)
        if exclude_name and p.name == exclude_name:
            continue
        for existing_fp in [normalize_fingerprint(fp) for fp in key_fingerprints(p)]:
            for fp in wanted:
                if fingerprint_matches(existing_fp, fp):
                    key = (p.name, existing_fp, fp)
                    if key not in seen:
                        seen.add(key)
                        matches.append({"name": p.name, "path": str(p), "existing_fingerprint": existing_fp, "fingerprint": fp})
    return matches


def unique_keyring_path(filename: str, directory: Optional[Path] = None) -> Path:
    directory = directory or APP_KEYRING_DIR
    filename = secure_filename(filename or default_keyring_filename("imported"))
    if not filename:
        filename = default_keyring_filename("imported")
    if Path(filename).suffix.lower() not in {".gpg", ".asc", ".key"}:
        filename += ".gpg"
    base = directory.resolve(strict=False)
    candidate = (directory / filename).resolve(strict=False)
    if base != candidate and base not in candidate.parents:
        raise ValueError("Ungültiger Keyring-Dateiname.")
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(2, 1000):
        alt = (directory / f"{stem}-{idx}{suffix}").resolve(strict=False)
        if not alt.exists():
            return alt
    raise ValueError("Kein freier Dateiname für den Keyring gefunden.")


def cleanup_key_import_previews(max_age_seconds: int = 86400) -> None:
    try:
        now = time.time()
        KEY_IMPORT_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        for p in KEY_IMPORT_PREVIEW_DIR.glob("*"):
            if p.is_file() and now - p.stat().st_mtime > max_age_seconds:
                p.unlink(missing_ok=True)
    except Exception:
        pass


def save_key_import_preview(data: bytes, source_name: str, source_url: str = "") -> str:
    cleanup_key_import_previews()
    if not data:
        raise ValueError("Keine Key-Daten vorhanden.")
    if len(data) > app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024):
        raise ValueError("Key-Datei ist zu groß.")
    token = secrets.token_urlsafe(18)
    data_path = KEY_IMPORT_PREVIEW_DIR / f"{token}.key"
    meta_path = KEY_IMPORT_PREVIEW_DIR / f"{token}.json"
    data_path.write_bytes(data)
    meta_path.write_text(json.dumps({"source_name": source_name, "source_url": source_url, "created_at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return token


def load_key_import_preview(token: str) -> Tuple[bytes, Dict[str, Any]]:
    token = re.sub(r"[^A-Za-z0-9_\-]", "", token or "")
    if not token:
        raise ValueError("Ungültiger Vorschau-Token.")
    data_path = KEY_IMPORT_PREVIEW_DIR / f"{token}.key"
    meta_path = KEY_IMPORT_PREVIEW_DIR / f"{token}.json"
    if not data_path.exists():
        raise ValueError("Die Key-Vorschau ist abgelaufen oder nicht mehr vorhanden.")
    meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return data_path.read_bytes(), meta


def delete_key_import_preview(token: str) -> None:
    token = re.sub(r"[^A-Za-z0-9_\-]", "", token or "")
    if not token:
        return
    (KEY_IMPORT_PREVIEW_DIR / f"{token}.key").unlink(missing_ok=True)
    (KEY_IMPORT_PREVIEW_DIR / f"{token}.json").unlink(missing_ok=True)


def keyring_preview_from_bytes(data: bytes, source_name: str, expected: str = "", source_url: str = "") -> Dict[str, Any]:
    token = save_key_import_preview(data, source_name, source_url)
    tmp_dir = Path(tempfile.mkdtemp(prefix="debmirror-key-preview-", dir=str(APP_DATA_DIR)))
    try:
        suffix = Path(source_name or "key.gpg").suffix or ".key"
        tmp_path = tmp_dir / f"preview{suffix}"
        tmp_path.write_bytes(data)
        details = parse_keyring_details(tmp_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    fingerprints = [normalize_fingerprint(fp) for fp in (details.get("fingerprints") or [])]
    expected_n = normalize_fingerprint(expected)
    expected_ok = True if not expected_n else any(fingerprint_matches(fp, expected_n) for fp in fingerprints)
    suggested_base = Path(source_name or "").name or default_keyring_filename(expected_n or (fingerprints[0] if fingerprints else "imported"))
    suggested_filename = secure_filename(suggested_base) or default_keyring_filename(expected_n or (fingerprints[0] if fingerprints else "imported"))
    if Path(suggested_filename).suffix.lower() not in {".gpg", ".asc", ".key"}:
        suggested_filename += ".gpg"
    duplicates = keyring_duplicate_matches(fingerprints)
    return {
        "token": token,
        "source_name": source_name,
        "source_url": source_url,
        "suggested_filename": suggested_filename,
        "expected": expected_n,
        "expected_ok": expected_ok,
        "valid": bool(fingerprints),
        "fingerprints": fingerprints,
        "key_entries": details.get("keys") or [],
        "warnings": details.get("warnings") or [],
        "duplicates": duplicates,
    }


def save_imported_key_bytes(data: bytes, filename: str, expected: str = "", allow_duplicate: bool = False) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="debmirror-key-import-", dir=str(APP_DATA_DIR)))
    dest: Optional[Path] = None
    try:
        candidate = tmp / (secure_filename(filename or "imported.key") or "imported.key")
        candidate.write_bytes(data)
        details = parse_keyring_details(candidate)
        fps = [normalize_fingerprint(fp) for fp in (details.get("fingerprints") or [])]
        if not fps:
            raise ValueError("In den importierten Daten wurde kein gültiger OpenPGP-Key erkannt.")
        expected_n = normalize_fingerprint(expected)
        if expected_n and not any(fingerprint_matches(fp, expected_n) for fp in fps):
            raise ValueError("Fingerprint passt nicht. Key wurde nicht gespeichert.")
        duplicates = keyring_duplicate_matches(fps)
        if duplicates and not allow_duplicate:
            names = ", ".join(sorted({d.get("name", "") for d in duplicates if d.get("name")}))
            raise ValueError(f"Dieser Key ist bereits vorhanden ({names}). Import nur mit Duplikat erlauben möglich.")
        target_name = secure_filename(filename or default_keyring_filename(expected_n or fps[0]))
        if b"-----BEGIN PGP PUBLIC KEY BLOCK-----" in data[:256] and Path(target_name).suffix.lower() in {".asc", ".key"}:
            target_name = str(Path(target_name).with_suffix(".gpg"))
        dest = unique_keyring_path(target_name, ARCHIVE_KEYRING_DIR)
        dest.write_bytes(candidate.read_bytes())
        dest = maybe_dearmor_key_file(dest)
        import_keyring_into_master(dest)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def render_keyrings_page(prefill_fp: str = "", assign_mirror_id: Optional[int] = None, import_preview: Optional[Dict[str, Any]] = None):
    migrate_legacy_keyring_assignments()
    return render_template(
        "keyrings.html",
        keyrings=keyring_rows(),
        master_key_entries=master_key_rows(),
        archived_keyrings=archived_keyring_rows(),
        prefill_fp=prefill_fp,
        assign_mirror_id=assign_mirror_id,
        import_preview=import_preview,
        mirror_choices=mirror_choices_for_keyring_forms(),
        master_keyring_path=str(MASTER_KEYRING_PATH),
        master_fingerprints=master_keyring_fingerprints(),
        master_status=master_keyring_status_summary(),
        master_exists=MASTER_KEYRING_PATH.exists(),
        master_size=MASTER_KEYRING_PATH.stat().st_size if MASTER_KEYRING_PATH.exists() else 0,
    )


@app.route("/keyrings", methods=["GET", "POST"])
@require_admin
def keyrings():
    prefill_fp = normalize_fingerprint(request.args.get("fingerprint", ""))
    assign_mirror_id = request.args.get("mirror_id", "").strip()
    assign_mirror_id_int = int(assign_mirror_id) if assign_mirror_id.isdigit() else None
    import_preview: Optional[Dict[str, Any]] = None
    if request.method == "POST":
        action = request.form.get("action")
        assign_to = request.form.get("assign_mirror_id", "").strip()
        assign_to_int = int(assign_to) if assign_to.isdigit() else None
        try:
            dest: Optional[Path] = None
            expected = normalize_fingerprint(request.form.get("expected_fingerprint", ""))
            allow_duplicate = request.form.get("allow_duplicate") == "on"
            if action == "preview_upload":
                file = request.files.get("keyfile")
                if not file or not file.filename:
                    raise ValueError("Keine Key-Datei ausgewählt.")
                import_preview = keyring_preview_from_bytes(file.read(), file.filename, expected, request.form.get("source_url", "").strip())
                return render_keyrings_page(prefill_fp=expected, assign_mirror_id=assign_to_int, import_preview=import_preview)
            elif action == "preview_url":
                url = request.form.get("url", "").strip()
                if not url.startswith(("https://", "http://")):
                    raise ValueError("Nur http/https URLs sind erlaubt.")
                data = urllib.request.urlopen(url, timeout=30).read(16 * 1024 * 1024)
                source_name = request.form.get("filename", "").strip() or Path(urllib.parse.urlparse(url).path).name or "url-key.gpg"
                import_preview = keyring_preview_from_bytes(data, source_name, expected, url)
                return render_keyrings_page(prefill_fp=expected, assign_mirror_id=assign_to_int, import_preview=import_preview)
            elif action == "preview_text":
                key_text = request.form.get("key_text", "")
                if not key_text.strip():
                    raise ValueError("Kein Key-Text eingefügt.")
                source_name = request.form.get("filename", "").strip() or default_keyring_filename(expected or "pasted", suffix=".asc")
                import_preview = keyring_preview_from_bytes(key_text.encode("utf-8"), source_name, expected, request.form.get("source_url", "").strip())
                return render_keyrings_page(prefill_fp=expected, assign_mirror_id=assign_to_int, import_preview=import_preview)
            elif action == "import_previewed":
                token = request.form.get("preview_token", "")
                data, meta = load_key_import_preview(token)
                filename = request.form.get("filename", "").strip() or meta.get("source_name") or default_keyring_filename(expected or "imported")
                dest = save_imported_key_bytes(data, filename, expected, allow_duplicate=allow_duplicate)
                details = parse_keyring_details(dest)
                save_keyring_metadata(dest.name, {
                    "display_name": request.form.get("display_name", "").strip() or dest.stem,
                    "source_url": request.form.get("source_url", "").strip() or meta.get("source_url", ""),
                    "notes": request.form.get("notes", "").strip(),
                    "active": 1,
                })
                save_key_fingerprint_metadata(dest.name, details, request.form.get("source_url", "").strip() or meta.get("source_url", ""), request.form.get("display_name", "").strip(), request.form.get("notes", "").strip())
                assign_keyring_to_mirror(assign_to_int, dest, expected)
                delete_key_import_preview(token)
                flash("Key wurde nach Vorschau importiert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring nach Vorschau importiert: {dest.name}")
            elif action == "assign_existing":
                keyring_value = request.form.get("keyring", "").strip()
                requested_fp = normalize_fingerprint(request.form.get("fingerprint", "")) or expected
                if not keyring_value:
                    raise ValueError("Kein vorhandener Keyring ausgewählt.")
                keyring_path = Path(allowed_keyring_path(keyring_value))
                if not keyring_path.exists():
                    raise ValueError("Der ausgewählte Keyring existiert nicht mehr.")
                try:
                    is_master_path = keyring_path.resolve(strict=False) == MASTER_KEYRING_PATH.resolve(strict=False)
                except Exception:
                    is_master_path = False
                if is_master_path:
                    full_fp = matching_master_fingerprint(requested_fp)
                    if not full_fp:
                        raise ValueError("Der erwartete Fingerprint wurde im Master-Keyring nicht gefunden.")
                    assign_master_fingerprint_to_mirror(assign_to_int, full_fp)
                    flash("Key aus dem Master-Keyring wurde dem Mirror-Profil zugeordnet und der Profil-Keyring wurde neu erzeugt.", "success")
                    add_event("info", f"Master-Key zu Profil zugeordnet: {full_fp} -> Mirror #{assign_to_int}")
                else:
                    selected_fp = ""
                    if requested_fp:
                        file_match = keyring_file_match(keyring_path, requested_fp)
                        if not file_match:
                            raise ValueError("Der ausgewählte Keyring enthält den erwarteten Fingerprint nicht.")
                        selected_fp = normalize_fingerprint(file_match.get("primary_fingerprint") or requested_fp)
                    else:
                        fps = [normalize_fingerprint(fp) for fp in key_fingerprints(keyring_path)]
                        selected_fp = fps[0] if fps else ""
                    assign_keyring_to_mirror(assign_to_int, keyring_path, selected_fp)
                    flash("Vorhandener Key wurde dem Mirror-Profil zugeordnet und der Profil-Keyring wurde neu erzeugt.", "success")
                    add_event("info", f"Vorhandener Key zu Profil zugeordnet: {keyring_path.name} {selected_fp}")
            elif action == "assign_matching_keys":
                selected = request.form.getlist("selected_match")
                single = request.form.get("single_match", "").strip()
                if single:
                    selected = [single]
                if not assign_to_int:
                    raise ValueError("Kein Mirror-Profil für die Zuordnung angegeben.")
                if not selected:
                    raise ValueError("Kein passender Key ausgewählt.")
                fingerprints_to_assign: List[str] = []
                for idx in selected:
                    safe_idx = re.sub(r"[^0-9]", "", str(idx or ""))
                    if not safe_idx:
                        continue
                    kind = request.form.get(f"match_kind_{safe_idx}", "").strip()
                    match_path = request.form.get(f"match_path_{safe_idx}", "").strip()
                    match_fp = normalize_fingerprint(request.form.get(f"match_fingerprint_{safe_idx}", ""))
                    if kind == "master":
                        primary = matching_master_fingerprint(match_fp)
                        if not primary:
                            raise ValueError(f"Fingerprint {match_fp} wurde im Master-Keyring nicht gefunden.")
                        fingerprints_to_assign.append(primary)
                    elif kind == "file":
                        keyring_path = Path(allowed_keyring_path(match_path))
                        if not keyring_path.exists():
                            raise ValueError(f"Archiv-Keyring existiert nicht mehr: {keyring_path.name}")
                        file_match = keyring_file_match(keyring_path, match_fp)
                        if not file_match:
                            raise ValueError(f"Fingerprint {match_fp} wurde in {keyring_path.name} nicht gefunden.")
                        import_keyring_into_master(keyring_path)
                        primary = matching_master_fingerprint(file_match.get("primary_fingerprint") or match_fp)
                        if not primary:
                            raise ValueError(f"Fingerprint {match_fp} konnte nach dem Import nicht im Master-Keyring gefunden werden.")
                        fingerprints_to_assign.append(primary)
                    else:
                        raise ValueError("Unbekannte Key-Quelle in der Fehlerauswertung.")
                assign_master_fingerprints_to_mirror(assign_to_int, fingerprints_to_assign)
                flash(f"{len(set(fingerprints_to_assign))} Key(s) wurden dem Mirror-Profil zugeordnet und der Profil-Keyring wurde neu erzeugt.", "success")
                add_event("info", f"Fehlerauswertung: Keys zu Profil #{assign_to_int} zugeordnet: {', '.join(fingerprints_to_assign)}")
            elif action == "assign_keyring_to_profile":
                filename = secure_filename(request.form.get("filename", ""))
                fingerprint = normalize_fingerprint(request.form.get("fingerprint", ""))
                profile_id_raw = request.form.get("profile_mirror_id", "").strip()
                if not fingerprint:
                    raise ValueError("Kein Fingerprint ausgewählt.")
                if not profile_id_raw.isdigit():
                    raise ValueError("Kein Mirror-Profil ausgewählt.")
                profile_id = int(profile_id_raw)
                if filename:
                    assign_keyring_filename_to_mirror(profile_id, filename, fingerprint)
                else:
                    assign_master_fingerprint_to_mirror(profile_id, fingerprint)
                mirror = get_mirror(profile_id) or {"name": f"#{profile_id}"}
                flash(f"Key wurde dem Profil {mirror.get('name')} zugeordnet.", "success")
                add_event("info", f"Key zu Profil zugeordnet: {filename} {fingerprint} -> {mirror.get('name')}")
            elif action == "unassign_keyring_from_profile":
                filename = secure_filename(request.form.get("filename", ""))
                fingerprint = normalize_fingerprint(request.form.get("fingerprint", ""))
                profile_id_raw = request.form.get("profile_mirror_id", "").strip()
                if not fingerprint or not profile_id_raw.isdigit():
                    raise ValueError("Fingerprint oder Mirror-Profil fehlt.")
                profile_id = int(profile_id_raw)
                unassign_keyring_filename_from_mirror(profile_id, filename, fingerprint)
                mirror = get_mirror(profile_id) or {"name": f"#{profile_id}"}
                flash(f"Key-Zuordnung für {mirror.get('name')} entfernt.", "success")
                add_event("info", f"Key-Zuordnung entfernt: {filename} {fingerprint} -> {mirror.get('name')}")
            elif action == "rebuild_master_keyring":
                before_removed = len(removed_master_key_fingerprints())
                fps = rebuild_master_keyring(include_removed=False)
                summary = master_keyring_status_summary()
                extra = f" · {summary.get('subkey_count', 0)} Subkeys" if summary.get('subkey_count', 0) else ""
                skipped = f" · {before_removed} entfernte Keys weiter ausgeschlossen" if before_removed else ""
                flash(f"Master-Keyring aus allen Quelldateien neu aufgebaut: {len(fps)} Hauptkeys{extra}{skipped}.", "success")
                add_event("info", f"Master-Keyring neu aufgebaut: {len(fps)} Hauptkeys, Subkeys: {summary.get('subkey_count', 0)}, ausgeschlossen: {before_removed}")
            elif action == "rebuild_master_keyring_full":
                removed_before = len(removed_master_key_fingerprints())
                fps = rebuild_master_keyring(include_removed=True)
                summary = master_keyring_status_summary()
                extra = f" · {summary.get('subkey_count', 0)} Subkeys" if summary.get('subkey_count', 0) else ""
                flash(f"Master-Keyring vollständig aus allen Quelldateien neu aufgebaut: {len(fps)} Hauptkeys{extra}. Entfernsperren gelöscht: {removed_before}.", "success")
                add_event("info", f"Master-Keyring vollständig neu aufgebaut: {len(fps)} Hauptkeys, Subkeys: {summary.get('subkey_count', 0)}, gelöschte Sperren: {removed_before}")
            elif action == "delete_master_key":
                fingerprint = normalize_fingerprint(request.form.get("fingerprint", ""))
                removed_fp = remove_master_key(fingerprint)
                flash(f"Key aus dem Master-Keyring entfernt: {removed_fp}", "success")
                add_event("warning", f"Master-Key entfernt: {removed_fp}")
            elif action == "delete_archived_keyring":
                filename = request.form.get("filename", "")
                source_type = request.form.get("source_type", "")
                removed_name = delete_archived_keyring_file(filename, source_type)
                flash(f"Import-/Quelldatei gelöscht: {removed_name}", "success")
                add_event("warning", f"Key-Quelldatei gelöscht: {removed_name}")
            elif action == "rebuild_all_profile_keyrings":
                migrate_legacy_keyring_assignments()
                count = 0
                errors: List[str] = []
                with db() as con:
                    mids = [int(r["id"]) for r in con.execute("SELECT id FROM mirrors ORDER BY id").fetchall()]
                for mid in mids:
                    if not mirror_keyring_assignment_items(mid):
                        continue
                    try:
                        rebuild_profile_keyring(mid)
                        count += 1
                    except Exception as ex:
                        errors.append(f"#{mid}: {ex}")
                if errors:
                    flash(f"{count} Profil-Keyrings neu erzeugt, {len(errors)} Fehler: " + "; ".join(errors[:3]), "warning")
                else:
                    flash(f"{count} Profil-Keyrings neu erzeugt.", "success")
                add_event("info", f"Profil-Keyrings neu erzeugt: {count}, Fehler: {len(errors)}")
            elif action == "save_metadata":
                filename = secure_filename(request.form.get("filename", ""))
                if not filename:
                    raise ValueError("Kein Keyring ausgewählt.")
                keyring_path = (APP_KEYRING_DIR / filename).resolve(strict=False)
                base = APP_KEYRING_DIR.resolve(strict=False)
                if base != keyring_path and base not in keyring_path.parents:
                    raise ValueError("Ungültiger Pfad.")
                if not keyring_path.exists():
                    raise ValueError("Der Keyring existiert nicht mehr.")
                save_keyring_metadata(filename, {
                    "display_name": request.form.get("display_name", "").strip(),
                    "source_url": request.form.get("source_url", "").strip(),
                    "notes": request.form.get("notes", "").strip(),
                    "active": 1 if request.form.get("active") == "on" else 0,
                })
                import_keyring_into_master(keyring_path)
                save_key_fingerprint_metadata(filename, parse_keyring_details(keyring_path), request.form.get("source_url", "").strip(), request.form.get("display_name", "").strip(), request.form.get("notes", "").strip())
                flash("Keyring-Informationen gespeichert.", "success")
                add_event("info", f"Keyring-Informationen gespeichert: {filename}")
            elif action == "upload":
                file = request.files.get("keyfile")
                if not file or not file.filename:
                    raise ValueError("Keine Key-Datei ausgewählt.")
                dest = save_imported_key_bytes(file.read(), file.filename, expected, allow_duplicate=allow_duplicate)
                details = parse_keyring_details(dest)
                save_keyring_metadata(dest.name, {
                    "display_name": request.form.get("display_name", "").strip() or dest.stem,
                    "source_url": request.form.get("source_url", "").strip(),
                    "notes": request.form.get("notes", "").strip(),
                    "active": 1,
                })
                save_key_fingerprint_metadata(dest.name, details, request.form.get("source_url", "").strip(), request.form.get("display_name", "").strip(), request.form.get("notes", "").strip())
                assign_keyring_to_mirror(assign_to_int, dest, expected)
                flash("Keyring-Datei gespeichert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring hochgeladen: {dest.name}")
            elif action == "url":
                url = request.form.get("url", "").strip()
                filename = secure_filename(request.form.get("filename", "") or Path(urllib.parse.urlparse(url).path).name or default_keyring_filename(expected or "imported"))
                if not url.startswith(("https://", "http://")):
                    raise ValueError("Nur http/https URLs sind erlaubt.")
                data = urllib.request.urlopen(url, timeout=30).read(16 * 1024 * 1024)
                dest = save_imported_key_bytes(data, filename, expected, allow_duplicate=allow_duplicate)
                details = parse_keyring_details(dest)
                save_keyring_metadata(dest.name, {
                    "display_name": request.form.get("display_name", "").strip() or dest.name,
                    "source_url": url,
                    "notes": request.form.get("notes", "").strip(),
                    "active": 1,
                })
                save_key_fingerprint_metadata(dest.name, details, url, request.form.get("display_name", "").strip(), request.form.get("notes", "").strip())
                assign_keyring_to_mirror(assign_to_int, dest, expected)
                flash("Key aus URL importiert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring aus URL importiert: {dest.name}")
            elif action == "keyserver":
                fingerprint = normalize_fingerprint(request.form.get("fingerprint", ""))
                keyserver = request.form.get("keyserver", "hkps://keyserver.ubuntu.com").strip() or "hkps://keyserver.ubuntu.com"
                filename = secure_filename(request.form.get("filename", "") or default_keyring_filename(fingerprint))
                dest = import_key_from_keyserver(fingerprint, filename=filename, keyserver=keyserver)
                details = parse_keyring_details(dest)
                duplicates = keyring_duplicate_matches(details.get("fingerprints") or [], exclude_name=dest.name, include_master=False)
                if duplicates and not allow_duplicate:
                    dest.unlink(missing_ok=True)
                    names = ", ".join(sorted({d.get("name", "") for d in duplicates if d.get("name")}))
                    raise ValueError(f"Dieser Key ist bereits als Quelldatei vorhanden ({names}). Import nur mit Duplikat erlauben möglich.")
                save_keyring_metadata(dest.name, {
                    "display_name": request.form.get("display_name", "").strip() or dest.name,
                    "source_url": keyserver,
                    "notes": request.form.get("notes", "").strip(),
                    "active": 1,
                })
                save_key_fingerprint_metadata(dest.name, details, keyserver, request.form.get("display_name", "").strip(), request.form.get("notes", "").strip())
                assign_keyring_to_mirror(assign_to_int, dest, fingerprint)
                flash("Key vom Keyserver importiert und als Keyserver-Quelldatei gespeichert." + (" Mirror-Profil wurde aktualisiert." if assign_to_int else ""), "success")
                add_event("info", f"Keyring vom Keyserver importiert: {dest.name}")
            else:
                raise ValueError("Unbekannte Keyring-Aktion.")
            if assign_to_int:
                return redirect(url_for("mirror_detail", mirror_id=assign_to_int))
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("keyrings", fingerprint=request.form.get("expected_fingerprint") or request.form.get("fingerprint", ""), mirror_id=assign_to or ""))

    return render_keyrings_page(prefill_fp=prefill_fp, assign_mirror_id=assign_mirror_id_int, import_preview=import_preview)


@app.route("/keyrings/master/export-key/<fingerprint>/<fmt>")
@require_admin
def master_keyring_export_single_key(fingerprint: str, fmt: str):
    try:
        fp = normalize_fingerprint(fingerprint)
        fmt = (fmt or "").lower()
        if fmt == "gpg":
            data = export_fingerprints_from_master([fp], armor=False)
            download_name = f"master-key-{fp[-16:]}.gpg"
            mime = "application/octet-stream"
        elif fmt == "asc":
            data = export_fingerprints_from_master([fp], armor=True)
            download_name = f"master-key-{fp[-16:]}.asc"
            mime = "application/pgp-keys"
        else:
            raise ValueError("Unbekanntes Exportformat.")
        bio = io.BytesIO(data)
        bio.seek(0)
        return send_file(bio, mimetype=mime, as_attachment=True, download_name=download_name)
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("keyrings"))


@app.route("/keyrings/<path:filename>/export/<fmt>")
@require_admin
def keyring_export(filename: str, fmt: str):
    try:
        path = (APP_KEYRING_DIR / secure_filename(filename)).resolve(strict=False)
        base = APP_KEYRING_DIR.resolve(strict=False)
        if base != path and base not in path.parents:
            raise ValueError("Ungültiger Pfad.")
        if not path.exists():
            raise ValueError("Keyring nicht gefunden.")
        fmt = (fmt or "").lower()
        if fmt == "gpg":
            data = path.read_bytes() if path.suffix.lower() == ".gpg" else keyring_binary_bytes_for_client(path)
            download_name = f"{path.stem}.gpg"
            mime = "application/octet-stream"
        elif fmt == "asc":
            data = export_keyring_armored_bytes(path)
            download_name = f"{path.stem}.asc"
            mime = "application/pgp-keys"
        else:
            raise ValueError("Unbekanntes Exportformat.")
        bio = io.BytesIO(data)
        bio.seek(0)
        return send_file(bio, mimetype=mime, as_attachment=True, download_name=download_name)
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("keyrings"))


@app.route("/keyrings/<path:filename>/export-key/<fingerprint>/<fmt>")
@require_admin
def keyring_export_single_key(filename: str, fingerprint: str, fmt: str):
    try:
        path = (APP_KEYRING_DIR / secure_filename(filename)).resolve(strict=False)
        base = APP_KEYRING_DIR.resolve(strict=False)
        if base != path and base not in path.parents:
            raise ValueError("Ungültiger Pfad.")
        if not path.exists():
            raise ValueError("Keyring nicht gefunden.")
        fp = normalize_fingerprint(fingerprint)
        fmt = (fmt or "").lower()
        if fmt == "gpg":
            data = export_keyring_selected_key_bytes(path, fp, armor=False)
            download_name = f"{path.stem}-{fp[-16:]}.gpg"
            mime = "application/octet-stream"
        elif fmt == "asc":
            data = export_keyring_selected_key_bytes(path, fp, armor=True)
            download_name = f"{path.stem}-{fp[-16:]}.asc"
            mime = "application/pgp-keys"
        else:
            raise ValueError("Unbekanntes Exportformat.")
        bio = io.BytesIO(data)
        bio.seek(0)
        return send_file(bio, mimetype=mime, as_attachment=True, download_name=download_name)
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("keyrings"))


@app.route("/keyrings/<path:filename>/delete", methods=["POST"])
@require_admin
def keyring_delete(filename: str):
    try:
        path = (APP_KEYRING_DIR / secure_filename(filename)).resolve(strict=False)
        base = APP_KEYRING_DIR.resolve(strict=False)
        if base != path and base not in path.parents:
            raise ValueError("Ungültiger Pfad.")
        used = keyring_used_by(path)
        if used:
            names = ", ".join(m.get("name") or f"#{m.get('id')}" for m in used)
            raise ValueError(f"Keyring wird noch von Mirror-Profilen verwendet: {names}. Entferne zuerst die Zuordnung im Profil.")
        path.unlink(missing_ok=True)
        settings = load_settings()
        meta = settings.get("keyring_metadata") if isinstance(settings.get("keyring_metadata"), dict) else {}
        if path.name in meta:
            meta.pop(path.name, None)
            settings["keyring_metadata"] = meta
            save_settings(settings)
        remove_key_fingerprint_metadata_for_file(path.name)
        rebuild_master_keyring()
        flash("Keyring gelöscht. Master-Keyring wurde neu aufgebaut.", "success")
        add_event("warning", f"Keyring gelöscht: {path.name}")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("keyrings"))


@app.route("/mirrors/<int:mirror_id>/client-export", methods=["POST"])
@require_admin
def mirror_client_export(mirror_id: int):
    mirror = get_mirror(mirror_id)
    if not mirror:
        flash("Mirror nicht gefunden.", "danger")
        return redirect(url_for("mirrors_page"))
    try:
        if mirror_keyring_assignment_items(mirror_id):
            keyring_path = rebuild_profile_keyring(mirror_id)
            mirror = get_mirror(mirror_id) or mirror
        else:
            keyring_value = mirror.get("keyring") or ""
            if not keyring_value:
                raise ValueError("Für dieses Profil ist kein Keyring hinterlegt.")
            keyring_path = Path(allowed_keyring_path(keyring_value))
        if not keyring_path.exists():
            raise ValueError("Der hinterlegte Keyring existiert nicht mehr.")
        base_url = request.form.get("client_base_url", "").strip()
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Für den Client-Export muss eine erreichbare http/https Mirror-Basis-URL angegeben werden.")
        selected_dists, selected_archs = validate_client_export_selection(
            mirror,
            request.form.getlist("client_dists"),
            request.form.getlist("client_archs"),
        )
        safe_name = secure_filename(mirror.get("name") or f"mirror-{mirror_id}") or f"mirror-{mirror_id}"
        client_key_name = f"{safe_name}-archive-keyring.gpg"
        key_bytes = keyring_binary_bytes_for_client(keyring_path)
        deb822_text, list_text = client_source_lines(mirror, base_url, client_key_name, selected_dists, selected_archs)
        selected_archs_text = ", ".join(selected_archs) if selected_archs else "keine Einschränkung"
        readme = f"""DebMirror Manager Client-Export\n================================\n\nMirror-Profil: {mirror.get('name')}\nClient-Basis-URL: {base_url.rstrip('/')}/\nSuites: {', '.join(selected_dists)}\nArchitekturen: {selected_archs_text}\nKeyring: {client_key_name}\n\nInstallation auf einem Debian/Ubuntu/APT-Client:\n\n1. Key installieren:\n   sudo install -m 0644 keyrings/{client_key_name} /usr/share/keyrings/{client_key_name}\n\n2. Quelle installieren, empfohlen als Deb822-Datei:\n   sudo install -m 0644 sources.list.d/{safe_name}.sources /etc/apt/sources.list.d/{safe_name}.sources\n\n   Alternative klassisch:\n   sudo install -m 0644 sources.list.d/{safe_name}.list /etc/apt/sources.list.d/{safe_name}.list\n\n3. Paketlisten aktualisieren:\n   sudo apt update\n\nHinweis: Die angegebene Client-Basis-URL muss auf den veröffentlichten Mirror zeigen, nicht auf die ursprüngliche Upstream-Quelle.\nDer exportierte Keyring ist profilbezogen und enthält nur die diesem Mirror-Profil zugeordneten Keys.\nDer Client-Export enthält nur die oben ausgewählten Suites und Architekturen.\n"""
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README-client.txt", readme)
            zf.writestr(f"keyrings/{client_key_name}", key_bytes)
            zf.writestr(f"sources.list.d/{safe_name}.sources", deb822_text)
            zf.writestr(f"sources.list.d/{safe_name}.list", list_text)
        bio.seek(0)
        add_event("info", f"Client-Export erstellt: {mirror.get('name')}")
        return send_file(bio, mimetype="application/zip", as_attachment=True, download_name=f"debmirror-client-{safe_name}-{local_now().strftime('%Y%m%d-%H%M%S')}.zip")
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("mirror_detail", mirror_id=mirror_id))



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
            if action == "change_password":
                user = current_user() or {}
                current_password = request.form.get("current_password", "")
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                password2 = request.form.get("password2", "")
                if not verify_admin_login(str(user.get("username") or ""), current_password):
                    raise ValueError("Aktuelles Passwort ist falsch.")
                if not username:
                    raise ValueError("Benutzername darf nicht leer sein.")
                if len(password) < 8:
                    raise ValueError("Das neue Passwort muss mindestens 8 Zeichen lang sein.")
                if password != password2:
                    raise ValueError("Die Passwort-Wiederholung passt nicht.")
                if not user.get("id"):
                    raise ValueError("Der aktuell angemeldete Benutzer konnte nicht eindeutig ermittelt werden.")
                create_or_update_user(username, password, role=user.get("role", "admin"), enabled=1, user_id=int(user["id"]))
                settings = load_settings()
                settings.pop("admin_username", None)
                settings.pop("admin_password_hash", None)
                settings["auth_updated_at"] = now_iso()
                save_settings(settings)
                session.clear()
                flash("Zugang wurde geändert. Bitte neu einloggen.", "success")
                return redirect(url_for("login"))
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
    return render_template(
        "users.html",
        users=list_users(),
        edit_user=edit_user,
        auth_config=admin_config() or {},
        settings_path=str(SETTINGS_PATH),
    )


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


def api_safe_mirror(mirror: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(mirror)
    result.pop("remote_password_enc", None)
    key_name = str(result.pop("rsync_ssh_key", "") or "")
    result["remote_password_set"] = mirror_remote_password_set(mirror)
    result["rsync_ssh_key_set"] = bool(key_name)
    result["rsync_ssh_key_fingerprint"] = ""
    if key_name:
        try:
            result["rsync_ssh_key_fingerprint"] = ssh_key_fingerprint(SSH_KEY_DIR / allowed_ssh_key_name(key_name, must_exist=True))
        except Exception:
            result["rsync_ssh_key_fingerprint"] = "unavailable"
    return result


@app.route("/api/v1/mirrors")
@require_api_auth
def api_mirrors():
    rows = [api_safe_mirror(row) for row in list_mirrors()]
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
    raw_mirror = mirror
    mirror = api_safe_mirror(raw_mirror)
    mirror["last_job"] = get_last_job(mirror_id)
    mirror["size_info"] = mirror_stats(raw_mirror)
    try:
        mirror["command"] = shell_join(display_debmirror_command(raw_mirror, dry_run=False))
        mirror["command_error"] = ""
    except ValueError as exc:
        mirror["command_error"] = str(exc)
        mirror["command"] = shell_join(display_debmirror_command(raw_mirror, dry_run=False, validate_keyring=False))
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
    """Add a directory tree while keeping Unix mode bits in the ZIP entries.

    Python's ZipFile.write already stores the source mode in external_attr.  The
    restore path additionally applies those bits explicitly because extractall()
    intentionally does not restore executable permissions on Unix.
    """
    count = 0
    if not source_dir.exists():
        return count
    for path in source_dir.rglob("*"):
        if path.is_file():
            zf.write(path, f"{arc_prefix}/{path.relative_to(source_dir).as_posix()}")
            count += 1
    return count


def backup_permission_map(paths: Iterable[Tuple[Path, str]]) -> Dict[str, int]:
    """Return portable file-mode metadata for files included in a backup."""
    result: Dict[str, int] = {}
    for source_dir, arc_prefix in paths:
        if not source_dir.exists():
            continue
        for path in source_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                arcname = f"{arc_prefix}/{path.relative_to(source_dir).as_posix()}"
                result[arcname] = stat.S_IMODE(path.stat().st_mode) & 0o777
    return result


def create_full_backup(label: str = "manual") -> Path:
    migrate_notification_secret_storage()
    secret_status = notification_secret_storage_status()
    if secret_status["unreadable_fields"]:
        fields = ", ".join(secret_status["unreadable_fields"])
        raise ValueError(f"Backup abgebrochen: Benachrichtigungs-Geheimwerte können nicht entschlüsselt werden ({fields}). Werte neu setzen und erneut sichern.")
    if secret_status.get("unreadable_mirror_passwords"):
        profiles = ", ".join(secret_status["unreadable_mirror_passwords"])
        raise ValueError(f"Backup abgebrochen: Remote-Passwörter von Mirror-Profilen können nicht entschlüsselt werden ({profiles}). Passwörter neu setzen und erneut sichern.")
    APP_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = APP_BACKUP_DIR / safe_backup_name(label)
    tmp_db = APP_DATA_DIR / f"backup-db-{secrets.token_hex(6)}.sqlite3"
    sqlite_snapshot(tmp_db)
    permission_sources = [
        (APP_KEYRING_DIR, "keyrings"),
        (IMPORT_SCRIPT_DIR, "import-scripts"),
        (USER_SCRIPT_DIR, "user-scripts"),
        (SSH_DIR, "ssh"),
    ]
    permissions = backup_permission_map(permission_sources)
    manifest = {
        "format": BACKUP_FORMAT,
        "app_version": APP_VERSION,
        "created_at": now_iso(),
        "label": label,
        "includes": ["database", "settings", "application_secret_key", "config_export", "keyrings", "import_scripts", "user_scripts", "ssh_keys", "ssh_known_hosts", "file_permissions"],
    }
    try:
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            zf.writestr("permissions.json", json.dumps(permissions, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            zf.writestr("config_export.json", json.dumps(build_config_export(), indent=2, ensure_ascii=False) + "\n")
            if SETTINGS_PATH.exists():
                zf.write(SETTINGS_PATH, "settings.json")
            if NOTIFICATION_SECRET_KEY_PATH.exists():
                zf.write(NOTIFICATION_SECRET_KEY_PATH, "secrets/notification-secrets.key")
            zf.write(tmp_db, "database/debmirror-manager.sqlite3")
            add_dir_to_zip(zf, APP_KEYRING_DIR, "keyrings")
            add_dir_to_zip(zf, IMPORT_SCRIPT_DIR, "import-scripts")
            add_dir_to_zip(zf, USER_SCRIPT_DIR, "user-scripts")
            add_dir_to_zip(zf, SSH_DIR, "ssh")
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
        infos = zf.infolist()
        for info in infos:
            name = info.filename
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Unsicherer ZIP-Pfad: {name}")
        zf.extractall(tmp)
        # ZipFile.extractall() restores file contents but not Unix permission bits.
        # Apply the safe rwx subset recorded by ZipFile.write so executable user
        # scripts also work after restoring backups created by older versions.
        for info in infos:
            mode = (info.external_attr >> 16) & 0o777
            if not mode:
                continue
            extracted = tmp / info.filename
            if extracted.exists() and not extracted.is_symlink():
                try:
                    extracted.chmod(mode)
                except OSError:
                    pass
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
    result = {"mirrors": 0, "healthchecks": 0, "schedules": 0, "users": 0, "api_tokens": 0, "keyrings": 0, "import_scripts": 0, "user_scripts": 0, "ssh_files": 0, "settings": 0, "secret_key": 0, "permissions": 0}
    try:
        manifest_path = tmp / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("format") != BACKUP_FORMAT:
                raise ValueError("Das ZIP ist kein DebMirror-Manager-Vollbackup.")
        # Restore the persistent encryption key before database/settings so
        # encrypted notification and mirror credentials are readable as soon as
        # their records are copied back into the application.
        restored_secret_key = tmp / "secrets" / "notification-secrets.key"
        if restored_secret_key.exists():
            key_bytes = restored_secret_key.read_bytes().strip()
            if Fernet is None:
                raise ValueError("Verschlüsselungsbibliothek fehlt; Benachrichtigungs-Schlüssel kann nicht geprüft werden.")
            try:
                Fernet(key_bytes)
            except Exception as exc:
                raise ValueError("Benachrichtigungs-Schlüssel im Backup ist ungültig.") from exc
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp_key = NOTIFICATION_SECRET_KEY_PATH.with_suffix(".restore-tmp")
            tmp_key.write_bytes(key_bytes + b"\n")
            try:
                tmp_key.chmod(0o600)
            except OSError:
                pass
            tmp_key.replace(NOTIFICATION_SECRET_KEY_PATH)
            try:
                NOTIFICATION_SECRET_KEY_PATH.chmod(0o600)
            except OSError:
                pass
            result["secret_key"] = 1
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
        permission_map: Dict[str, int] = {}
        permissions_path = tmp / "permissions.json"
        if permissions_path.exists():
            try:
                raw_permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
                if isinstance(raw_permissions, dict):
                    for arcname, mode in raw_permissions.items():
                        if isinstance(arcname, str):
                            permission_map[arcname] = int(mode) & 0o777
            except Exception as exc:
                add_event("warning", f"Dateirechte-Metadaten im Backup konnten nicht gelesen werden: {exc}")
        for folder, dest, key, arc_prefix in [
            (tmp / "keyrings", APP_KEYRING_DIR, "keyrings", "keyrings"),
            (tmp / "import-scripts", IMPORT_SCRIPT_DIR, "import_scripts", "import-scripts"),
            (tmp / "user-scripts", USER_SCRIPT_DIR, "user_scripts", "user-scripts"),
            (tmp / "ssh", SSH_DIR, "ssh_files", "ssh"),
        ]:
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
                        arcname = f"{arc_prefix}/{rel.as_posix()}"
                        mode = permission_map.get(arcname)
                        if mode is None:
                            # Backups before v0.1.68 have no permissions.json, but
                            # their ZIP entries usually still contain Unix modes.
                            mode = stat.S_IMODE(src.stat().st_mode) & 0o777
                        if key == "user_scripts" and not (mode & 0o111):
                            # Compatibility fallback for backups produced or
                            # repacked on systems that stripped Unix ZIP attrs.
                            try:
                                first_line = src.open("rb").readline(256)
                            except OSError:
                                first_line = b""
                            if first_line.startswith(b"#!"):
                                mode |= 0o755
                        if mode:
                            try:
                                out.chmod(mode & 0o777)
                                result["permissions"] += 1
                            except OSError:
                                pass
                        result[key] += 1
        if SSH_DIR.exists():
            try:
                SSH_DIR.chmod(0o700)
                SSH_KEY_DIR.mkdir(parents=True, exist_ok=True)
                SSH_KEY_DIR.chmod(0o700)
                for key_path in SSH_KEY_DIR.iterdir():
                    if key_path.is_file() and not key_path.is_symlink():
                        key_path.chmod(0o600)
                if SSH_KNOWN_HOSTS_PATH.exists():
                    SSH_KNOWN_HOSTS_PATH.chmod(0o600)
            except OSError:
                pass
        migrate_notification_secret_storage()
        secret_status = notification_secret_storage_status()
        if secret_status["unreadable_fields"]:
            add_event("warning", "Backup wiederhergestellt, aber Benachrichtigungs-Geheimwerte konnten nicht vollständig entschlüsselt werden.")
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
    "postcleanup", "diff_mode", "progress", "verbose", "getcontents", "i18n", "timeout_seconds", "rsync_extra", "extra_options", "manual_extra_options", "remote_user",
    "rsync_ssh_enabled", "rsync_ssh_user", "rsync_ssh_key", "rsync_ssh_port", "rsync_ssh_accept_new_host_key",
    "include_patterns", "exclude_patterns", "schedule_mode", "schedule_time", "schedule_weekday", "interval_hours",
]


def build_config_export() -> Dict[str, Any]:
    mirrors = []
    for m in list_mirrors():
        mirrors.append({k: m.get(k) for k in EXPORT_MIRROR_COLUMNS if k in m})
    settings = load_settings()
    safe_settings = {k: v for k, v in settings.items() if k in {"appearance", "max_parallel_jobs", "job_retention_days", "job_list_limit", "size_cache_ttl_seconds", "size_calc_timeout_seconds", "size_calc_max_parallel", "auto_size_recalc_enabled", "auto_size_idle_minutes", "storage_guard_enabled", "storage_guard_threshold_percent", "profile_generator_config", "profile_scan_path_variables", "dashboard_recent_jobs_limit", "dashboard_events_limit", "dashboard_layout", "user_script_targets", "keyring_metadata", "key_fingerprint_metadata", "mirror_keyring_assignments"}}
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
            raw_config_root = str(clean.get("root_path") or "")
            clean["root_path"] = validate_rsync_module_path(raw_config_root) if clean.get("method") == "rsync" else normalize_root_path(raw_config_root)
            clean["keyring"] = allowed_keyring_path(str(clean.get("keyring") or "")) if clean.get("keyring") else ""
            clean["keyring_fingerprint"] = normalize_fingerprint(str(clean.get("keyring_fingerprint") or ""))
            clean["remote_password_enc"] = ""
            clean["rsync_ssh_enabled"] = 1 if clean.get("rsync_ssh_enabled") else 0
            clean["rsync_ssh_port"] = int(clean.get("rsync_ssh_port") or 22)
            clean["rsync_ssh_accept_new_host_key"] = 1 if clean.get("rsync_ssh_accept_new_host_key") else 0
            normalize_mirror_option_compatibility(clean)
            validate_mirror_configuration(clean, require_ssh_key=False)
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
        for key in ("appearance", "notify", "max_parallel_jobs", "job_retention_days", "job_list_limit", "dashboard_recent_jobs_limit", "dashboard_events_limit", "size_cache_ttl_seconds", "size_calc_timeout_seconds", "size_calc_max_parallel", "auto_size_recalc_enabled", "auto_size_idle_minutes", "storage_guard_enabled", "storage_guard_threshold_percent", "profile_generator_config", "profile_scan_path_variables", "dashboard_layout", "user_script_targets", "keyring_metadata", "key_fingerprint_metadata", "mirror_keyring_assignments"):
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
    storage = notification_secret_storage_status()
    cfg["encryption_available"] = encryption_available()
    cfg["secret_key_present"] = storage["key_present"]
    cfg["secret_storage_readable"] = storage["readable"]
    cfg["unreadable_secret_fields"] = storage["unreadable_fields"]
    cfg["secret_key_path"] = storage["key_path"]
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


BUILTIN_HELP = "# DebMirror Manager\n\nDie ausführliche Anleitung README.md wurde nicht gefunden. Bitte prüfe die Projektinstallation.\n"
BUILTIN_RELEASE_NOTES = "# Release Notes\n\n## v0.1.77\n\n- Fallback-Release-Notes. Normalerweise wird RELEASE_NOTES.md aus dem Projektordner gelesen.\n"

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def cleanup_stale_job_auth_configs(max_age_seconds: int = 86400) -> None:
    try:
        JOB_AUTH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - max(300, int(max_age_seconds))
        stale_candidates: List[Path] = []
        for pattern in ("job-*.conf", "job-*.rsync-pass", "scan-*.rsync-pass"):
            stale_candidates.extend(JOB_AUTH_CONFIG_DIR.glob(pattern))
        for path in stale_candidates:
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except Exception as exc:
        log_webui_exception("cleanup_stale_job_auth_configs", exc)


def create_app() -> Flask:
    init_db()
    cleanup_stale_job_auth_configs()
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
