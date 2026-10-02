# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import warnings
import zipfile

import pytest

from app import main as dmm


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    snapshot = data / "debmirror-manager.sqlite3"
    dmm.sqlite_snapshot(snapshot)
    dirs = {
        "APP_DATA_DIR": data,
        "APP_BACKUP_DIR": tmp_path / "backups",
        "APP_KEYRING_DIR": tmp_path / "keyrings",
        "APP_LOG_DIR": tmp_path / "logs",
        "IMPORT_SCRIPT_DIR": tmp_path / "imports",
        "USER_SCRIPT_DIR": tmp_path / "scripts",
        "MIRROR_BASE": tmp_path / "mirror",
        "SSH_DIR": data / "ssh",
        "SSH_KEY_DIR": data / "ssh/keys",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(dmm, name, path)
    monkeypatch.setattr(dmm, "DB_PATH", snapshot)
    monkeypatch.setattr(dmm, "SETTINGS_PATH", data / "settings.json")
    monkeypatch.setattr(dmm, "NOTIFICATION_SECRET_KEY_PATH", data / "notification-secrets.key")
    monkeypatch.setattr(dmm, "SSH_KNOWN_HOSTS_PATH", data / "ssh/known_hosts")
    return tmp_path


@pytest.mark.parametrize("fail", [False, True])
def test_database_context_closes_and_preserves_transaction(runtime, fail):
    marker = "quality-db-rollback" if fail else "quality-db-commit"
    if fail:
        with pytest.raises(ValueError):
            with dmm.db() as connection:
                connection.execute("INSERT INTO app_events(level,message,created_at) VALUES ('info',?,?)", (marker, dmm.now_iso()))
                raise ValueError("test rollback")
    else:
        with dmm.db() as connection:
            connection.execute("INSERT INTO app_events(level,message,created_at) VALUES ('info',?,?)", (marker, dmm.now_iso()))
    try:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with dmm.db() as current:
            count = current.execute("SELECT COUNT(*) FROM app_events WHERE message=?", (marker,)).fetchone()[0]
        assert count == (0 if fail else 1)
    finally:
        connection.close()


def test_concurrent_settings_writes_use_independent_atomic_files(runtime, monkeypatch):
    barrier = threading.Barrier(2)
    original = Path.replace

    def synchronized_replace(path, target):
        if Path(target) == dmm.SETTINGS_PATH:
            barrier.wait(timeout=5)
        return original(path, target)

    monkeypatch.setattr(Path, "replace", synchronized_replace)
    payloads = [{"writer": i, "content": "x" * 4096} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(dmm.save_settings, payloads))
    assert json.loads(dmm.SETTINGS_PATH.read_text()) in payloads
    assert not list(dmm.APP_DATA_DIR.glob("*.tmp"))


def test_backups_created_in_same_second_have_distinct_names(monkeypatch):
    monkeypatch.setattr(dmm, "local_now", lambda: dt.datetime(2026, 10, 2, 12, 0, 0))
    assert dmm.safe_backup_name("same") != dmm.safe_backup_name("same")


@pytest.mark.parametrize("name", ["../outside", "manifest.json"])
def test_rejected_encrypted_restore_removes_plaintext_and_extraction(runtime, name):
    plain = runtime / "input.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": dmm.BACKUP_FORMAT}))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr(name, "rejected input")
    encrypted = runtime / "input.dmmbackup"
    password = "isolated-backup-password"
    dmm.encrypt_backup_zip(plain, encrypted, password, {})
    with pytest.raises((ValueError, FileExistsError)):
        dmm.restore_full_backup_from_path(encrypted, backup_password=password)
    assert not list(dmm.APP_DATA_DIR.glob("restore-decrypted-*"))
    restore_dir = dmm.APP_DATA_DIR / "restore-tmp"
    assert not restore_dir.exists() or not list(restore_dir.iterdir())


def test_failed_backup_snapshot_removes_partial_database(runtime, monkeypatch):
    def fail_snapshot(path):
        path.write_bytes(b"partial snapshot")
        raise OSError("snapshot failed")

    monkeypatch.setattr(dmm, "sqlite_snapshot", fail_snapshot)
    with pytest.raises(OSError, match="snapshot failed"):
        dmm.create_full_backup(backup_password="isolated-backup-password")
    assert not list(dmm.APP_DATA_DIR.glob("backup-db-*"))
    assert not list(dmm.APP_DATA_DIR.glob("backup-plain-*"))


def add_mirror(name):
    with dmm.db() as connection:
        cursor = connection.execute(
            "INSERT INTO mirrors(name,host,target_path,dists,sections,archs,created_at,updated_at) VALUES (?, 'example.invalid', ?, 'stable','main','amd64',?,?)",
            (name, str(dmm.MIRROR_BASE / name), dmm.now_iso(), dmm.now_iso()),
        )
        return cursor.lastrowid


def test_failed_database_restore_preserves_existing_data_and_key(runtime):
    kept_id = add_mirror("keep-existing")
    encrypted_value = dmm.encrypt_secret("fixture-value")
    original_key = dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes()
    snapshot = runtime / "invalid.sqlite3"
    dmm.sqlite_snapshot(snapshot)
    with sqlite3.connect(snapshot) as source:
        source.execute("UPDATE mirrors SET name='replacement' WHERE id=?", (kept_id,))
        # Keep the columns, but emulate a malformed legacy snapshot with a NULL required URL.
        source.execute("CREATE TABLE unsafe_healthchecks AS SELECT * FROM healthchecks")
        source.execute("DROP TABLE healthchecks")
        source.execute("ALTER TABLE unsafe_healthchecks RENAME TO healthchecks")
        source.execute("INSERT INTO healthchecks(id,name,url) VALUES (9999,'bad-check',NULL)")
    source.close()
    archive_path = runtime / "invalid-backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": dmm.BACKUP_FORMAT}))
        archive.writestr("secrets/notification-secrets.key", dmm.Fernet.generate_key())
        archive.write(snapshot, "database/debmirror-manager.sqlite3")
    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        dmm.restore_full_backup_from_path(archive_path, replace=True, include_users=False)
    with dmm.db() as connection:
        row = connection.execute("SELECT name FROM mirrors WHERE id=?", (kept_id,)).fetchone()
    assert row is not None and row["name"] == "keep-existing"
    assert dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes() == original_key
    assert dmm.decrypt_secret(encrypted_value) == "fixture-value"


def test_encrypted_backup_roundtrip_preserves_profile_and_secret(runtime):
    mirror_id = add_mirror("roundtrip")
    with dmm.db() as connection:
        connection.execute("UPDATE mirrors SET remote_password_enc=? WHERE id=?", (dmm.encrypt_secret("fixture-value"), mirror_id))
    backup = dmm.create_full_backup(backup_password="isolated-backup-password")
    with dmm.db() as connection:
        connection.execute("UPDATE mirrors SET name='changed' WHERE id=?", (mirror_id,))
    result = dmm.restore_full_backup_from_path(backup, replace=True, include_users=False, backup_password="isolated-backup-password")
    with dmm.db() as connection:
        row = connection.execute("SELECT name,remote_password_enc FROM mirrors WHERE id=?", (mirror_id,)).fetchone()
    assert result["mirrors"] >= 1
    assert row["name"] == "roundtrip"
    assert dmm.decrypt_secret(row["remote_password_enc"]) == "fixture-value"
    assert not list(dmm.APP_DATA_DIR.glob("restore-decrypted-*"))


def test_zip_updater_copies_bilingual_docs_and_preserves_env(tmp_path):
    root = Path(__file__).resolve().parents[1]
    updater = (root / "update.sh").read_text()
    script = updater.split("<<'PYZIP'\n", 1)[1].split("\nPYZIP", 1)[0]
    target = tmp_path / "installed"
    target.mkdir()
    for rel in [".env", "docker-compose/.env", "docker-compose/.env.no-nginx"]:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture-preserved")
        path.chmod(0o600)
    docs = ["SECURITY.de.md", "CONTRIBUTING.de.md", "THIRD-PARTY-NOTICES.de.md", "docs/README.md", "docs/README.de.md"]
    for rel in docs:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old document")
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for rel, content in {"VERSION": "1.0.4", "docker-compose.yml": "services: {}", "app/__init__.py": "", "docker-compose/compose.yaml": "services: {}", **{rel: "new document" for rel in docs}}.items():
            archive.writestr("debmirror-manager/" + rel, content)
    subprocess.run([sys.executable, "-c", script, str(package), str(tmp_path / "extract-work"), str(target)], check=True)
    for rel in docs:
        assert (target / rel).read_text() == "new document"
    for rel in [".env", "docker-compose/.env", "docker-compose/.env.no-nginx"]:
        assert (target / rel).read_text() == "fixture-preserved"
        assert (target / rel).stat().st_mode & 0o777 == 0o600


def test_merging_foreign_key_backup_preserves_existing_credentials(runtime):
    mirror_id = add_mirror("existing-credential")
    with dmm.db() as connection:
        connection.execute("UPDATE mirrors SET remote_password_enc=? WHERE id=?", (dmm.encrypt_secret("fixture-value"), mirror_id))
    old_key = dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes()
    snapshot = runtime / "snapshot.sqlite3"
    dmm.sqlite_snapshot(snapshot)
    archive_path = runtime / "foreign-key.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": dmm.BACKUP_FORMAT}))
        archive.writestr("secrets/notification-secrets.key", dmm.Fernet.generate_key())
        archive.write(snapshot, "database/debmirror-manager.sqlite3")
    with pytest.raises(ValueError, match="Verschlüsselungsschlüssel"):
        dmm.restore_full_backup_from_path(archive_path, replace=False, include_users=False)
    assert dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes() == old_key
    with dmm.db() as connection:
        value = connection.execute("SELECT remote_password_enc FROM mirrors WHERE id=?", (mirror_id,)).fetchone()[0]
    assert dmm.decrypt_secret(value) == "fixture-value"


def test_backup_manifest_without_configuration_cannot_replace_key(runtime):
    original = dmm.encrypt_secret("fixture-value")
    old_key = dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes()
    archive_path = runtime / "missing-data.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": dmm.BACKUP_FORMAT}))
        archive.writestr("secrets/notification-secrets.key", dmm.Fernet.generate_key())
    with pytest.raises(ValueError):
        dmm.restore_full_backup_from_path(archive_path, replace=True, include_users=False)
    assert dmm.NOTIFICATION_SECRET_KEY_PATH.read_bytes() == old_key
    assert dmm.decrypt_secret(original) == "fixture-value"


def test_empty_incompatible_table_cannot_erase_existing_profiles(runtime):
    kept_id = add_mirror("keep-schema-validation")
    snapshot = runtime / "incompatible.sqlite3"
    dmm.sqlite_snapshot(snapshot)
    with sqlite3.connect(snapshot) as source:
        source.execute("UPDATE mirrors SET name='replacement' WHERE id=?", (kept_id,))
        source.execute("DROP TABLE healthchecks")
        source.execute("CREATE TABLE healthchecks(id INTEGER PRIMARY KEY)")
    source.close()
    archive_path = runtime / "incompatible-backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": dmm.BACKUP_FORMAT}))
        archive.write(snapshot, "database/debmirror-manager.sqlite3")
    with pytest.raises(ValueError, match="Spalten"):
        dmm.restore_full_backup_from_path(archive_path, replace=True, include_users=False)
    with dmm.db() as connection:
        row = connection.execute("SELECT name FROM mirrors WHERE id=?", (kept_id,)).fetchone()
    assert row is not None and row["name"] == "keep-schema-validation"
