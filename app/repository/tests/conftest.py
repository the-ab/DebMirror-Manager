from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="dmm-tests-"))
for name in ("data", "logs", "keyrings", "backups", "imports", "scripts", "mirror", "auth"):
    (TEST_ROOT / name).mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "APP_SECRET_KEY": "test-only-secret-key-" + "x" * 48,
        "APP_DATA_DIR": str(TEST_ROOT / "data"),
        "APP_LOG_DIR": str(TEST_ROOT / "logs"),
        "APP_KEYRING_DIR": str(TEST_ROOT / "keyrings"),
        "APP_BACKUP_DIR": str(TEST_ROOT / "backups"),
        "IMPORT_SCRIPT_DIR": str(TEST_ROOT / "imports"),
        "USER_SCRIPT_DIR": str(TEST_ROOT / "scripts"),
        "MIRROR_BASE": str(TEST_ROOT / "mirror"),
        "JOB_AUTH_CONFIG_DIR": str(TEST_ROOT / "auth"),
        "SCHEDULER_SCAN_SECONDS": "3600",
        "APP_HTTPS_ONLY": "0",
        "TRUST_PROXY_HEADERS": "0",
        "MIN_PASSWORD_LENGTH": "12",
    }
)

from app import main as dmm  # noqa: E402


@pytest.fixture()
def client():
    dmm.app.config.update(TESTING=True)
    return dmm.app.test_client()


@pytest.fixture()
def database_cleanup():
    tables = ["api_tokens", "login_attempts", "users"]
    with dmm.db() as con:
        for table in tables:
            con.execute(f"DELETE FROM {table}")
    yield
    with dmm.db() as con:
        for table in tables:
            con.execute(f"DELETE FROM {table}")


def make_user(username: str, role: str = "admin"):
    dmm.create_or_update_user(
        username,
        "Correct-Horse-Battery-Staple-42",
        role=role,
        enabled=1,
        language="en",
        appearance="dark",
    )
    return dmm.get_user_by_username(username)


def authenticate(client, user, csrf: str = "test-csrf-token"):
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["user_id"] = int(user["id"])
        session["username"] = str(user["username"])
        session["role"] = str(user["role"])
        session["session_version"] = int(user.get("session_version") or 1)
        session["language"] = str(user.get("language") or "en")
        session["_csrf_token"] = csrf
    return csrf
