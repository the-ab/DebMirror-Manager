from __future__ import annotations

from pathlib import Path
import os
import datetime as dt
import email.utils
import http.server
import threading
import stat
import sys
import re

import pytest

from app import main as dmm
from tests.conftest import authenticate, make_user


def test_all_templates_compile():
    for template_name in dmm.app.jinja_env.list_templates():
        dmm.app.jinja_env.get_template(template_name)


def test_repository_publication_files_exist():
    project_root = Path(__file__).resolve().parents[1]
    required = {
        "LICENSE",
        ".gitignore",
        ".dockerignore",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "THIRD-PARTY-NOTICES.md",
        "requirements.lock",
        "README.md",
        "README.de.md",
        "RELEASE_NOTES.md",
        "RELEASE_NOTES.de.md",
    }
    assert all((project_root / name).is_file() for name in required)
    version_file = project_root / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"\d+\.\d+\.\d+", version)
        assert f"Current version: **{version}**" in (project_root / "README.md").read_text(encoding="utf-8")
        assert f"Aktuelle Version: **{version}**" in (project_root / "README.de.md").read_text(encoding="utf-8")


def test_application_container_uses_pinned_trixie_base():
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    first_line = dockerfile.splitlines()[0]
    assert first_line.startswith("FROM python:3.13.14-slim-trixie@sha256:")
    assert "bookworm" not in first_line.lower()
    assert "apt-get upgrade -y" in dockerfile



def test_setup_cannot_be_forced_after_initial_user(client, database_cleanup):
    admin = make_user("existing-admin")
    response = client.get("/setup?force=1", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/login")
    assert dmm.get_user_by_username(admin["username"])


def test_deleted_user_session_is_invalidated_without_admin_fallback(client, database_cleanup):
    make_user("real-admin")
    user = make_user("temporary-reader", role="user")
    authenticate(client, user)
    with dmm.db() as con:
        con.execute("DELETE FROM users WHERE id=?", (int(user["id"]),))
    response = client.get("/users", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/login" in response.headers["Location"]


def test_state_changing_web_request_requires_csrf(client, database_cleanup):
    admin = make_user("csrf-admin")
    authenticate(client, admin)
    with client.session_transaction() as session:
        session.pop("_csrf_token", None)
    response = client.post("/theme/toggle", data={})
    assert response.status_code == 400


def test_user_preferences_are_account_specific(client, database_cleanup):
    admin = make_user("prefs-admin")
    token = authenticate(client, admin)
    response = client.post(
        "/preferences",
        data={"_csrf_token": token, "language": "de", "appearance": "light"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    updated = dmm.get_user_by_username("prefs-admin")
    assert updated["language"] == "de"
    assert updated["appearance"] == "light"


def test_open_redirects_are_rejected():
    assert dmm.safe_redirect_target("//example.invalid/path", "/") == "/"
    assert dmm.safe_redirect_target("https://example.invalid/path", "/") == "/"
    assert dmm.safe_redirect_target("/jobs", "/") == "/jobs"


def test_private_outbound_targets_are_blocked():
    with pytest.raises(ValueError):
        dmm.validate_outbound_url("http://127.0.0.1/internal", allowed_schemes=("http", "https"))


def test_read_only_api_token_cannot_start_jobs(client, database_cleanup):
    admin = make_user("token-admin")
    token = dmm.create_api_token("monitoring", created_by=admin["username"], scopes=("read",), expires_days=30)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/status", headers=headers).status_code == 200
    response = client.post("/api/v1/mirrors/999/run", headers=headers)
    assert response.status_code == 403


def test_security_headers_are_present(client, database_cleanup):
    make_user("headers-admin")
    response = client.get("/login")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_source_download_route_is_removed(client):
    response = client.get("/source", follow_redirects=False)
    assert response.status_code == 404


def test_no_github_automation_or_source_archive_build():
    project_root = Path(__file__).resolve().parents[1]
    assert not (project_root / ".github" / "dependabot.yml").exists()
    assert not (project_root / ".github" / "workflows" / "ci.yml").exists()
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY ." not in dockerfile
    assert "debmirror-manager-source" not in dockerfile
    assert "source_code_download" not in (project_root / "app" / "main.py").read_text(encoding="utf-8")
    license_text = (project_root / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text


def test_compatibility_repository_copies_match():
    project_root = Path(__file__).resolve().parents[1]
    compatibility_root = project_root / "app" / "repository"
    for name in (
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "THIRD-PARTY-NOTICES.md",
        "requirements.lock",
        "requirements-dev.txt",
        "pytest.ini",
        ".gitignore",
        ".dockerignore",
    ):
        assert (project_root / name).read_bytes() == (compatibility_root / name).read_bytes()


def test_management_files_keep_restrictive_process_umask(tmp_path):
    path = tmp_path / "management-secret"
    path.write_text("secret", encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_public_mirror_directory_overrides_restrictive_parent_umask(tmp_path):
    target = dmm.MIRROR_BASE / "permission-target"
    if target.exists():
        import shutil
        shutil.rmtree(target)
    created = dmm.ensure_public_mirror_directory(target)
    assert created == target.resolve(strict=False)
    assert stat.S_IMODE(created.stat().st_mode) & 0o755 == 0o755


def test_mirror_permission_repair_adds_read_bits_without_following_symlinks(tmp_path):
    target = dmm.MIRROR_BASE / "permission-repair"
    nested = target / "dists" / "stable"
    nested.mkdir(parents=True, exist_ok=True)
    release = nested / "InRelease"
    release.write_text("signed metadata", encoding="utf-8")
    target.chmod(0o700)
    (target / "dists").chmod(0o700)
    nested.chmod(0o700)
    release.chmod(0o600)

    outside = tmp_path / "outside-private"
    outside.write_text("private", encoding="utf-8")
    outside.chmod(0o600)
    link = target / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError:
        link = None

    result = dmm.repair_public_mirror_tree_permissions(target)
    assert result["errors"] == 0
    assert stat.S_IMODE(target.stat().st_mode) & 0o755 == 0o755
    assert stat.S_IMODE(nested.stat().st_mode) & 0o755 == 0o755
    assert stat.S_IMODE(release.stat().st_mode) & 0o644 == 0o644
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600


def test_job_subprocess_uses_public_output_umask(tmp_path, monkeypatch):
    output_dir = tmp_path / "job-output-dir"
    output_file = output_dir / "Packages"
    log_path = tmp_path / "job.log"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(output_dir)!r}); p.mkdir(); "
        f"Path({str(output_file)!r}).write_text('data', encoding='utf-8')"
    )
    monkeypatch.setattr(dmm, "get_user_script_target", lambda _name: str(dmm.MIRROR_BASE / "script-output"))
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, script_name, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (NULL, 'umask-test', 'script', 'umask-test', 'starting', 0, ?, ?, ?, ?, 'test')
            """,
            (sys.executable, '[]', str(log_path), dmm.now_iso()),
        )
        job_id = int(cur.lastrowid)
    try:
        dmm.run_job_thread(job_id, [sys.executable, "-c", code], log_path, "test")
        assert stat.S_IMODE(output_dir.stat().st_mode) == 0o755
        assert stat.S_IMODE(output_file.stat().st_mode) == 0o644
        assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))



def test_non_mirror_user_script_keeps_restrictive_umask(tmp_path, monkeypatch):
    output_file = tmp_path / "private-script-output"
    log_path = tmp_path / "private-script.log"
    monkeypatch.setattr(dmm, "get_user_script_target", lambda _name: "")
    code = f"from pathlib import Path; Path({str(output_file)!r}).write_text('private', encoding='utf-8')"
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, script_name, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (NULL, 'private-umask-test', 'script', 'private-umask-test', 'starting', 0, ?, ?, ?, ?, 'test')
            """,
            (sys.executable, '[]', str(log_path), dmm.now_iso()),
        )
        job_id = int(cur.lastrowid)
    try:
        dmm.run_job_thread(job_id, [sys.executable, "-c", code], log_path, "test")
        assert stat.S_IMODE(output_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))



def test_profile_actions_show_timestamp_sync_only_for_http(client, database_cleanup):
    admin = make_user("time-sync-actions-admin")
    authenticate(client, admin)
    now = dmm.now_iso()
    with dmm.db() as con:
        http_cur = con.execute(
            """
            INSERT INTO mirrors(name, method, host, root_path, target_path, dists, sections, archs, created_at, updated_at)
            VALUES ('http-time-sync-action', 'http', 'example.invalid', 'repo', ?, 'stable', 'main', 'amd64', ?, ?)
            """,
            (str(dmm.MIRROR_BASE / "http-time-sync-action"), now, now),
        )
        http_id = int(http_cur.lastrowid)
        rsync_cur = con.execute(
            """
            INSERT INTO mirrors(name, method, host, root_path, target_path, dists, sections, archs, created_at, updated_at)
            VALUES ('rsync-no-time-sync-action', 'rsync', 'example.invalid', 'repo', ?, 'stable', 'main', 'amd64', ?, ?)
            """,
            (str(dmm.MIRROR_BASE / "rsync-no-time-sync-action"), now, now),
        )
        rsync_id = int(rsync_cur.lastrowid)
    response = client.get("/mirrors")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'/mirrors/{http_id}/time-sync' in html
    assert f'/mirrors/{rsync_id}/time-sync' not in html
    assert 'Mirror timestamp sync' in html

class _TimestampTestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "DMMTimestampTest/1.0"

    def log_message(self, _format, *_args):
        return

    def _respond(self):
        path = self.path.split("?", 1)[0]
        self.send_response(200)
        if path.endswith("/InRelease"):
            self.send_header("Last-Modified", "Tue, 02 Jan 2024 03:04:05 GMT")
            self.send_header("Content-Length", "1")
        elif path.endswith("/Release"):
            self.send_header("Last-Modified", "Wed, 03 Jan 2024 04:05:06 GMT")
            self.send_header("Content-Length", "1")
        elif path.endswith("/dists/stable/"):
            self.send_header("Last-Modified", "Thu, 04 Jan 2024 05:06:07 GMT")
            self.send_header("Content-Length", "0")
        else:
            self.send_header("Content-Length", "0")
        self.end_headers()
        if self.command == "GET" and path.endswith(("/InRelease", "/Release")):
            self.wfile.write(b"x")

    do_HEAD = _respond
    do_GET = _respond


def test_http_timestamp_sync_updates_files_and_derives_directories(tmp_path):
    target = dmm.MIRROR_BASE / "timestamp-sync"
    if target.exists():
        import shutil
        shutil.rmtree(target)
    suite_dir = target / "dists" / "stable"
    suite_dir.mkdir(parents=True)
    inrelease = suite_dir / "InRelease"
    release = suite_dir / "Release"
    no_header = suite_dir / "Release.gpg"
    inrelease.write_text("inrelease", encoding="utf-8")
    release.write_text("release", encoding="utf-8")
    no_header.write_text("signature", encoding="utf-8")
    initial_no_header_mtime = 1_700_000_000
    os.utime(no_header, (initial_no_header_mtime, initial_no_header_mtime))

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TimestampTestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        mirror = {
            "method": "http",
            "host": f"127.0.0.1:{server.server_port}",
            "root_path": "repo",
            "target_path": str(target),
            "remote_user": "",
            "remote_password_enc": "",
            "extra_options": "",
        }
        result = dmm.synchronize_mirror_timestamps(mirror)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    expected_inrelease = dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc).timestamp()
    expected_release = dt.datetime(2024, 1, 3, 4, 5, 6, tzinfo=dt.timezone.utc).timestamp()
    expected_directory = dt.datetime(2024, 1, 4, 5, 6, 7, tzinfo=dt.timezone.utc).timestamp()
    assert abs(inrelease.stat().st_mtime - expected_inrelease) < 1
    assert abs(release.stat().st_mtime - expected_release) < 1
    assert abs(no_header.stat().st_mtime - initial_no_header_mtime) < 1
    assert abs(suite_dir.stat().st_mtime - expected_directory) < 1
    assert abs((target / "dists").stat().st_mtime - expected_directory) < 1
    assert result["files_updated"] == 2
    assert result["files_missing_header"] == 1
    assert result["directories_updated"] >= 1
    assert result["directories_derived"] >= 1



def test_timestamp_sync_normalizes_dot_repository_root():
    mirror = {"method": "http", "host": "example.invalid", "root_path": "."}
    assert dmm.mirror_upstream_base_url(mirror) == "http://example.invalid/"
    assert dmm.mirror_upstream_url(mirror, "dists/stable/InRelease") == "http://example.invalid/dists/stable/InRelease"

def test_http_timestamp_sync_remote_failures_are_nonfatal(monkeypatch):
    target = dmm.MIRROR_BASE / "timestamp-sync-failure"
    target.mkdir(parents=True, exist_ok=True)
    local_file = target / "InRelease"
    local_file.write_text("data", encoding="utf-8")
    original_mtime = local_file.stat().st_mtime

    monkeypatch.setattr(dmm, "fetch_remote_last_modified", lambda *_args, **_kwargs: (None, "http-403"))
    mirror = {
        "method": "https",
        "host": "example.invalid",
        "root_path": "debian",
        "target_path": str(target),
        "remote_user": "",
        "remote_password_enc": "",
        "extra_options": "",
    }
    result = dmm.synchronize_mirror_timestamps(mirror)
    assert result["files_failed"] == 1
    assert local_file.stat().st_mtime == original_mtime


def test_time_sync_is_only_available_for_http_and_https():
    assert dmm.mirror_time_sync_supported({"method": "http"})
    assert dmm.mirror_time_sync_supported({"method": "https"})
    assert not dmm.mirror_time_sync_supported({"method": "rsync"})
    assert not dmm.mirror_time_sync_supported({"method": "ftp"})


def test_internal_time_sync_job_runs_without_subprocess(tmp_path, monkeypatch):
    target = dmm.MIRROR_BASE / "internal-time-sync-job"
    target.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "time-sync-job.log"
    now = dmm.now_iso()
    with dmm.db() as con:
        mirror_cur = con.execute(
            """
            INSERT INTO mirrors(name, method, host, root_path, target_path, dists, sections, archs, created_at, updated_at)
            VALUES ('time-sync-test', 'http', 'example.invalid', 'debian', ?, 'stable', 'main', 'amd64', ?, ?)
            """,
            (str(target), now, now),
        )
        mirror_id = int(mirror_cur.lastrowid)
        job_cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (?, 'time-sync-test', 'time_sync', 'starting', 0, 'Mirror-Zeitabgleich', ?, ?, ?, 'test')
            """,
            (mirror_id, '["__debmirror_manager_mirror_time_sync__"]', str(log_path), now),
        )
        job_id = int(job_cur.lastrowid)
    monkeypatch.setattr(
        dmm,
        "synchronize_mirror_timestamps",
        lambda *_args, **_kwargs: {"files_checked": 0, "files_updated": 0},
    )
    try:
        dmm.run_job_thread(job_id, [dmm.INTERNAL_MIRROR_TIME_SYNC_COMMAND, str(mirror_id)], log_path, "test")
        with dmm.db() as con:
            row = con.execute("SELECT status, exit_code, pid FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "success"
        assert row["exit_code"] == 0
        assert row["pid"] is None
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            con.execute("DELETE FROM mirrors WHERE id=?", (mirror_id,))


def test_stop_internal_time_sync_job_sets_cancel_event(tmp_path):
    target = dmm.MIRROR_BASE / "internal-time-sync-stop"
    target.mkdir(parents=True, exist_ok=True)
    now = dmm.now_iso()
    with dmm.db() as con:
        mirror_cur = con.execute(
            """
            INSERT INTO mirrors(name, method, host, root_path, target_path, dists, sections, archs, created_at, updated_at)
            VALUES ('time-sync-stop-test', 'https', 'example.invalid', 'debian', ?, 'stable', 'main', 'amd64', ?, ?)
            """,
            (str(target), now, now),
        )
        mirror_id = int(mirror_cur.lastrowid)
        job_cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (?, 'time-sync-stop-test', 'time_sync', 'running', 0, 'Mirror-Zeitabgleich', ?, ?, ?, 'test')
            """,
            (mirror_id, '["__debmirror_manager_mirror_time_sync__"]', str(tmp_path / "stop.log"), now),
        )
        job_id = int(job_cur.lastrowid)
    cancel_event = threading.Event()
    with dmm.INTERNAL_JOB_CANCEL_EVENTS_LOCK:
        dmm.INTERNAL_JOB_CANCEL_EVENTS[job_id] = cancel_event
    try:
        dmm.stop_job(job_id)
        assert cancel_event.is_set()
        with dmm.db() as con:
            row = con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "stopping"
    finally:
        with dmm.INTERNAL_JOB_CANCEL_EVENTS_LOCK:
            dmm.INTERNAL_JOB_CANCEL_EVENTS.pop(job_id, None)
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            con.execute("DELETE FROM mirrors WHERE id=?", (mirror_id,))



def test_ping_target_validation_blocks_private_by_default_and_allows_explicit():
    with pytest.raises(ValueError):
        dmm.validate_ping_target("127.0.0.1")
    display, address = dmm.validate_ping_target("127.0.0.1", allow_private=True)
    assert display == "127.0.0.1"
    assert address == "127.0.0.1"
    for invalid in ("http://example.org", "example.org:443", "-c", "host/path"):
        with pytest.raises(ValueError):
            dmm.validate_ping_target(invalid, allow_private=True)


def test_ping_healthcheck_success_updates_database(monkeypatch):
    now = dmm.now_iso()
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO healthchecks(name, url, expected_status, method, timeout_seconds, interval_minutes, enabled, allow_private, created_at, updated_at)
            VALUES ('ping-test-success', '127.0.0.1', 200, 'PING', 5, 60, 1, 1, ?, ?)
            """,
            (now, now),
        )
        check_id = int(cur.lastrowid)
    monkeypatch.setattr(
        dmm,
        "_run_ping_healthcheck",
        lambda *_args, **_kwargs: {"ok": True, "status_code": 0, "latency_ms": 7, "error": ""},
    )
    try:
        result = dmm.run_healthcheck_once(dmm.get_healthcheck(check_id))
        assert result["ok"] is True
        assert result["method"] == "PING"
        with dmm.db() as con:
            row = con.execute("SELECT last_ok, last_status_code, last_latency_ms, last_error FROM healthchecks WHERE id=?", (check_id,)).fetchone()
        assert row["last_ok"] == 1
        assert row["last_status_code"] == 0
        assert row["last_latency_ms"] == 7
        assert row["last_error"] == ""
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM healthchecks WHERE id=?", (check_id,))



def test_ftp_healthcheck_success_updates_database(monkeypatch):
    now = dmm.now_iso()
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO healthchecks(name, url, expected_status, method, timeout_seconds, interval_minutes, enabled, allow_private, created_at, updated_at)
            VALUES ('ftp-test-success', 'ftp://ftp.example.org/debian', 200, 'FTP', 5, 60, 1, 0, ?, ?)
            """,
            (now, now),
        )
        check_id = int(cur.lastrowid)
    monkeypatch.setattr(
        dmm,
        "_run_ftp_healthcheck",
        lambda *_args, **_kwargs: {"ok": True, "status_code": 250, "latency_ms": 11, "error": ""},
    )
    try:
        result = dmm.run_healthcheck_once(dmm.get_healthcheck(check_id))
        assert result["ok"] is True
        assert result["method"] == "FTP"
        with dmm.db() as con:
            row = con.execute("SELECT last_ok, last_status_code, last_latency_ms, last_error FROM healthchecks WHERE id=?", (check_id,)).fetchone()
        assert row["last_ok"] == 1
        assert row["last_status_code"] == 250
        assert row["last_latency_ms"] == 11
        assert row["last_error"] == ""
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM healthchecks WHERE id=?", (check_id,))


def test_ftp_healthcheck_only_requires_valid_server_reply(monkeypatch):
    calls = []

    class FakeStream:
        def readline(self, limit):
            calls.append(("readline", limit))
            return b"530 Login incorrect.\r\n"

        def close(self):
            calls.append(("stream-close",))

    class FakeSocket:
        def settimeout(self, timeout):
            calls.append(("settimeout", timeout))

        def makefile(self, mode):
            calls.append(("makefile", mode))
            return FakeStream()

        def close(self):
            calls.append(("socket-close",))

    monkeypatch.setattr(
        dmm,
        "validate_ftp_target",
        lambda target, allow_private=False: (target, "192.0.2.20", 21, "/debian"),
    )
    monkeypatch.setattr(
        dmm.socket,
        "create_connection",
        lambda address, timeout: calls.append(("connect", address, timeout)) or FakeSocket(),
    )
    result = dmm._run_ftp_healthcheck("ftp://ftp.example.org/debian", 5, False)
    assert result["ok"] is True
    assert result["status_code"] == 530
    assert ("connect", ("192.0.2.20", 21), 5) in calls
    assert all(call[0] not in {"login", "cwd"} for call in calls)

def test_healthcheck_recovery_notification_is_sent_once(monkeypatch):
    now = dmm.now_iso()
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO healthchecks(
                name, url, expected_status, method, timeout_seconds,
                interval_minutes, enabled, allow_private, last_notify_state,
                created_at, updated_at
            ) VALUES ('ping-recovery-test', '127.0.0.1', 200, 'PING', 5, 60, 1, 1, 'error', ?, ?)
            """,
            (now, now),
        )
        check_id = int(cur.lastrowid)

    notifications = []
    monkeypatch.setattr(
        dmm,
        "_run_ping_healthcheck",
        lambda *_args, **_kwargs: {"ok": True, "status_code": 0, "latency_ms": 8, "error": ""},
    )
    monkeypatch.setattr(
        dmm,
        "notification_settings",
        lambda: {"enabled": True, "on_healthcheck_error": True, "on_healthcheck_recovery": True},
    )
    monkeypatch.setattr(
        dmm,
        "send_notification",
        lambda subject, message, kind="info": notifications.append((subject, message, kind)) or ["ok"],
    )
    try:
        first = dmm.run_healthcheck_once(dmm.get_healthcheck(check_id))
        assert first["ok"] is True
        assert len(notifications) == 1
        assert "wieder erreichbar" in notifications[0][0]
        assert "Latenz: 8 ms" in notifications[0][1]

        second = dmm.run_healthcheck_once(dmm.get_healthcheck(check_id))
        assert second["ok"] is True
        assert len(notifications) == 1

        with dmm.db() as con:
            row = con.execute("SELECT last_notify_state FROM healthchecks WHERE id=?", (check_id,)).fetchone()
        assert row["last_notify_state"] == "ok"
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM healthchecks WHERE id=?", (check_id,))


def test_healthcheck_recovery_notification_can_be_disabled(monkeypatch):
    now = dmm.now_iso()
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO healthchecks(
                name, url, expected_status, method, timeout_seconds,
                interval_minutes, enabled, allow_private, last_notify_state,
                created_at, updated_at
            ) VALUES ('ping-recovery-disabled-test', '127.0.0.1', 200, 'PING', 5, 60, 1, 1, 'error', ?, ?)
            """,
            (now, now),
        )
        check_id = int(cur.lastrowid)

    notifications = []
    monkeypatch.setattr(
        dmm,
        "_run_ping_healthcheck",
        lambda *_args, **_kwargs: {"ok": True, "status_code": 0, "latency_ms": 4, "error": ""},
    )
    monkeypatch.setattr(
        dmm,
        "notification_settings",
        lambda: {"enabled": True, "on_healthcheck_error": True, "on_healthcheck_recovery": False},
    )
    monkeypatch.setattr(
        dmm,
        "send_notification",
        lambda subject, message, kind="info": notifications.append((subject, message, kind)) or ["ok"],
    )
    try:
        result = dmm.run_healthcheck_once(dmm.get_healthcheck(check_id))
        assert result["ok"] is True
        assert notifications == []
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM healthchecks WHERE id=?", (check_id,))

def test_healthcheck_form_accepts_ping_and_hides_http_status(client, database_cleanup, monkeypatch):
    admin = make_user("ping-healthcheck-admin")
    token = authenticate(client, admin)
    monkeypatch.setattr(dmm, "validate_ping_target", lambda target, allow_private=False: (target, "192.0.2.1"))
    response = client.post(
        "/healthchecks",
        data={
            "_csrf_token": token,
            "action": "save",
            "name": "external-ping",
            "url": "example.org",
            "method": "PING",
            "timeout_seconds": "5",
            "interval_minutes": "10",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    with dmm.db() as con:
        row = con.execute("SELECT method, url, expected_status FROM healthchecks WHERE name='external-ping'").fetchone()
        con.execute("DELETE FROM healthchecks WHERE name='external-ping'")
    assert row["method"] == "PING"
    assert row["url"] == "example.org"
    assert row["expected_status"] == 200
    page = client.get("/healthchecks")
    html = page.get_data(as_text=True)
    assert 'value="PING"' in html
    assert 'Ping (ICMP)' in html


def test_ftp_healthcheck_target_adds_default_scheme(monkeypatch):
    monkeypatch.setattr(
        dmm.socket,
        "getaddrinfo",
        lambda host, port, type=0: [(dmm.socket.AF_INET, dmm.socket.SOCK_STREAM, 6, "", ("203.0.113.20", port))],
    )
    normalized, resolved, port, path = dmm.validate_ftp_target("ftp.example.org:2121", allow_private=True)
    assert normalized == "ftp://ftp.example.org:2121"
    assert resolved == "203.0.113.20"
    assert port == 2121
    assert path == "/"


def test_healthcheck_form_accepts_ftp_and_hides_http_status(client, database_cleanup, monkeypatch):
    admin = make_user("ftp-healthcheck-admin")
    token = authenticate(client, admin)
    monkeypatch.setattr(
        dmm,
        "validate_ftp_target",
        lambda target, allow_private=False: (target, "192.0.2.20", 21, "/debian"),
    )
    response = client.post(
        "/healthchecks",
        data={
            "_csrf_token": token,
            "action": "save",
            "name": "external-ftp",
            "url": "ftp://ftp.example.org/debian",
            "method": "FTP",
            "timeout_seconds": "5",
            "interval_minutes": "10",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    with dmm.db() as con:
        row = con.execute("SELECT method, url, expected_status FROM healthchecks WHERE name='external-ftp'").fetchone()
        con.execute("DELETE FROM healthchecks WHERE name='external-ftp'")
    assert row["method"] == "FTP"
    assert row["url"] == "ftp://ftp.example.org/debian"
    assert row["expected_status"] == 200
    page = client.get("/healthchecks")
    html = page.get_data(as_text=True)
    assert 'value="FTP"' in html
    assert "var ftp = method.value === 'FTP';" in html
    assert "FTP (nur Erreichbarkeit des FTP-Dienstes, kein Login)" in html


def test_dashboard_renders_all_configured_healthchecks(client, database_cleanup):
    admin = make_user("dashboard-healthchecks-admin")
    authenticate(client, admin)
    prefix = "zz-dashboard-healthcheck-"
    created_at = dmm.now_iso()
    with dmm.db() as con:
        con.execute("DELETE FROM healthchecks WHERE name LIKE ?", (prefix + "%",))
        for index in range(12):
            con.execute(
                """
                INSERT INTO healthchecks(
                    name, url, expected_status, method, timeout_seconds,
                    interval_minutes, enabled, allow_private, created_at, updated_at
                ) VALUES (?, ?, 200, 'PING', 5, 60, 1, 0, ?, ?)
                """,
                (f"{prefix}{index:02d}", "example.org", created_at, created_at),
            )
    try:
        response = client.get("/")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        for index in range(12):
            assert f"{prefix}{index:02d}" in html
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM healthchecks WHERE name LIKE ?", (prefix + "%",))




def test_dashboard_failed_jobs_tile_and_jobs_filter(client, database_cleanup):
    admin = make_user("dashboard-failed-jobs-admin")
    authenticate(client, admin)
    prefix = "zz-dashboard-failed-job-"
    started_at = dmm.now_iso()
    with dmm.db() as con:
        con.execute("DELETE FROM jobs WHERE mirror_name LIKE ?", (prefix + "%",))
        before = int(con.execute("SELECT COUNT(*) AS n FROM jobs WHERE status='error'").fetchone()["n"] or 0)
        con.execute(
            "INSERT INTO jobs(mirror_name, status, dry_run, command, log_path, started_at, finished_at, exit_code, error_message, source) VALUES (?, 'error', 0, '', '', ?, ?, 1, 'test', 'manual')",
            (prefix + "error", started_at, started_at),
        )
        con.execute(
            "INSERT INTO jobs(mirror_name, status, dry_run, command, log_path, started_at, finished_at, exit_code, error_message, source) VALUES (?, 'success', 0, '', '', ?, ?, 0, '', 'manual')",
            (prefix + "success", started_at, started_at),
        )
    try:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        html = dashboard.get_data(as_text=True)
        marker = 'data-dashboard-block="failed-jobs-summary"'
        assert marker in html
        fragment = html[html.index(marker):html.index(marker) + 1200]
        assert f'<p class="summary-value">{before + 1}</p>' in fragment
        assert '/jobs?status=error' in fragment.replace('&amp;', '&')

        filtered = client.get("/jobs?status=error")
        assert filtered.status_code == 200
        filtered_html = filtered.get_data(as_text=True)
        assert prefix + "error" in filtered_html
        assert prefix + "success" not in filtered_html
        assert "Es werden nur fehlgeschlagene Läufe angezeigt." in filtered_html or "Only failed runs are shown." in filtered_html

        all_jobs = client.get("/jobs")
        all_html = all_jobs.get_data(as_text=True)
        assert prefix + "error" in all_html
        assert prefix + "success" in all_html
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE mirror_name LIKE ?", (prefix + "%",))


def test_dashboard_layout_migrates_for_failed_jobs_tile():
    old_layout = {
        "zones": {
            "summary": {
                "order": ["storage", "queue", "profile-script-summary", "health-summary"],
                "sizes": {},
                "widths": {"storage": 3, "queue": 3, "profile-script-summary": 3, "health-summary": 3},
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
    migrated = dmm.sanitize_dashboard_layout(old_layout)
    summary = migrated["zones"]["summary"]
    assert migrated["schema_version"] == 2
    assert summary["order"] == ["storage", "queue", "profile-script-summary", "health-summary", "failed-jobs-summary"]
    assert summary["widths"] == {
        "storage": 6,
        "queue": 6,
        "profile-script-summary": 3,
        "health-summary": 3,
        "failed-jobs-summary": 6,
    }


def test_dashboard_layout_preserves_custom_summary_widths_proportionally():
    custom_layout = {
        "zones": {
            "summary": {
                "order": ["storage", "queue", "profile-script-summary", "health-summary"],
                "sizes": {},
                "widths": {"storage": 6, "queue": 4, "profile-script-summary": 5, "health-summary": 3},
                "heights": {},
            },
            "main": {"order": [], "sizes": {}, "widths": {}, "heights": {}},
        }
    }
    migrated = dmm.sanitize_dashboard_layout(custom_layout)["zones"]["summary"]
    assert migrated["widths"]["storage"] == 12
    assert migrated["widths"]["queue"] == 8
    assert migrated["widths"]["profile-script-summary"] == 10
    assert migrated["widths"]["health-summary"] == 6
    assert migrated["widths"]["failed-jobs-summary"] == 6


def test_release_footer_is_present_on_app_login_and_setup_templates(client, database_cleanup):
    admin = make_user("footer-admin")
    authenticate(client, admin)
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert f"v{dmm.APP_VERSION}" in html
    release_date_de = dt.date.fromisoformat(dmm.APP_RELEASE_DATE).strftime("%d.%m.%Y")
    assert dmm.APP_RELEASE_DATE in html or release_date_de in html

    with client.session_transaction() as session:
        session.clear()
    login = client.get("/login")
    assert login.status_code == 200
    login_html = login.get_data(as_text=True)
    assert f"v{dmm.APP_VERSION}" in login_html
    assert dmm.APP_RELEASE_DATE in login_html or release_date_de in login_html


def test_ping_runtime_dependencies_are_declared():
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "iputils-ping" in dockerfile
    assert "NET_RAW" in compose


def test_manual_update_check_button_is_present():
    project_root = Path(__file__).resolve().parents[1]
    template = (project_root / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
    assert "url_for('update_check_now')" in template
    assert "Jetzt prüfen" in template


def test_manual_update_check_can_bypass_disabled_automation():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "app" / "main.py").read_text(encoding="utf-8")
    assert "def update_check_scan(force: bool = False, allow_disabled: bool = False)" in source
    assert "update_check_scan(force=True, allow_disabled=True)" in source


def test_badsig_is_metadata_mismatch_not_missing_key():
    log_text = """[GNUPG:] NEWSIG
[GNUPG:] KEY_CONSIDERED 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 0
[GNUPG:] BADSIG 7EA0A9C3F273FCD8 Docker Release (CE deb) <docker@docker.com>
gpgv: BAD signature from \"Docker Release (CE deb) <docker@docker.com>\"
.temp/.tmp/dists/noble/Release.gpg signature does not verify.
"""
    assert dmm.has_badsig_failure(log_text) is True
    assert dmm.should_retry_badsig(log_text) is True
    assert dmm.extract_missing_pubkeys(log_text) == []
    diagnosis = dmm.classify_job_error(log_text, 1, "debmirror wurde mit Exit-Code 1 beendet.")
    assert diagnosis["type"] == "gpg-metadata-sync"
    assert diagnosis["missing_keys"] == []
    assert "erneuter Import" in diagnosis["action"]


def test_badsig_retry_is_blocked_by_real_key_error():
    log_text = """[GNUPG:] BADSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
[GNUPG:] NO_PUBKEY 871920D1991BC93C
"""
    assert dmm.should_retry_badsig(log_text) is False
    missing = dmm.extract_missing_pubkeys(log_text)
    assert missing
    assert missing[0]["key_id"].endswith("871920D1991BC93C")


def test_success_after_badsig_retry_has_no_stale_diagnosis():
    log_text = """[GNUPG:] BADSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
[2026-07-27T15:00:00+02:00] BADSIG-Retry 1/2 wird gestartet.
gpgv: Good signature from \"Ubuntu Archive Automatic Signing Key (2018) <ftpmaster@ubuntu.com>\"
"""
    diagnosis = dmm.classify_job_error(log_text, 0, "")
    assert diagnosis["type"] == ""
    assert diagnosis["title"] == ""


def test_diagnosis_uses_latest_badsig_retry_attempt():
    log_text = """[GNUPG:] BADSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
[2026-07-27T15:00:00+02:00] BADSIG-Retry 1/2 wird gestartet.
rsync: connection refused
"""
    assert "BADSIG" not in dmm.latest_badsig_attempt_log(log_text)
    diagnosis = dmm.classify_job_error(log_text, 1, "debmirror wurde mit Exit-Code 1 beendet.")
    assert diagnosis["type"] == "network"


def test_dry_run_job_never_sends_job_notification(tmp_path, monkeypatch):
    log_path = tmp_path / "dry-run-notification.log"
    log_path.write_text("simulated dry-run failure\n", encoding="utf-8")
    sent = []
    monkeypatch.setattr(
        dmm,
        "notification_settings",
        lambda: {"enabled": True, "on_success": True, "on_error": True},
    )
    monkeypatch.setattr(
        dmm,
        "send_notification",
        lambda subject, message, kind="info": sent.append((subject, message, kind)) or ["ok"],
    )

    dmm.notify_job_finished(
        12345,
        "error",
        1,
        "dry-run-test",
        str(log_path),
        "simulated failure",
        dry_run=True,
    )

    assert sent == []


def test_run_job_thread_passes_dry_run_to_notification(tmp_path, monkeypatch):
    log_path = tmp_path / "dry-run-job.log"
    now = dmm.now_iso()
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, job_type, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (NULL, 'dry-run-integration', 'mirror', 'starting', 1, 'false', '[\"/bin/sh\",\"-c\",\"exit 1\"]', ?, ?, 'test')
            """,
            (str(log_path), now),
        )
        job_id = int(cur.lastrowid)

    captured = []
    monkeypatch.setattr(dmm, "runtime_dependency_checks", lambda: [])
    monkeypatch.setattr(
        dmm,
        "notify_job_finished",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    try:
        dmm.run_job_thread(job_id, ["/bin/sh", "-c", "exit 1"], log_path, "test")
        assert len(captured) == 1
        assert captured[0][1].get("dry_run") is True
        with dmm.db() as con:
            row = con.execute("SELECT status, dry_run FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "error"
        assert int(row["dry_run"]) == 1
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def test_log_retention_removes_complete_protocol_entry(monkeypatch, tmp_path):
    log_path = dmm.APP_LOG_DIR / "retention-complete.log"
    log_path.write_text("old log", encoding="utf-8")
    old_time = (dmm.local_now() - dt.timedelta(days=40)).isoformat(sep=" ", timespec="seconds")
    with dmm.db() as con:
        cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, finished_at, exit_code, source)
            VALUES (NULL, 'retention-complete', 'success', 0, '', '[]', ?, ?, ?, 0, 'test')
            """,
            (str(log_path), old_time, old_time),
        )
        job_id = int(cur.lastrowid)
    monkeypatch.setattr(dmm, "log_retention_days", lambda: 30)
    try:
        result = dmm.cleanup_old_jobs_and_logs()
        assert result["deleted_logs"] == 1
        assert result["deleted_jobs"] == 1
        assert not log_path.exists()
        with dmm.db() as con:
            row = con.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row is None
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        log_path.unlink(missing_ok=True)


def test_targeted_log_cleanup_removes_job_record_and_skips_active(tmp_path):
    finished_log = dmm.APP_LOG_DIR / "targeted-finished.log"
    active_log = dmm.APP_LOG_DIR / "targeted-active.log"
    finished_log.write_text("finished", encoding="utf-8")
    active_log.write_text("active", encoding="utf-8")
    now = dmm.now_iso()
    with dmm.db() as con:
        finished_cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, finished_at, exit_code, source)
            VALUES (NULL, 'targeted-finished', 'success', 0, '', '[]', ?, ?, ?, 0, 'test')
            """,
            (str(finished_log), now, now),
        )
        active_cur = con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, source)
            VALUES (NULL, 'targeted-active', 'running', 0, '', '[]', ?, ?, 'test')
            """,
            (str(active_log), now),
        )
        finished_id = int(finished_cur.lastrowid)
        active_id = int(active_cur.lastrowid)
    try:
        result = dmm.delete_job_log_files([finished_id, active_id])
        assert result["deleted_logs"] == 1
        assert result["deleted_jobs"] == 1
        assert result["skipped_active"] == 1
        assert not finished_log.exists()
        assert active_log.exists()
        with dmm.db() as con:
            finished_row = con.execute("SELECT id FROM jobs WHERE id=?", (finished_id,)).fetchone()
            active_row = con.execute("SELECT id FROM jobs WHERE id=?", (active_id,)).fetchone()
        assert finished_row is None
        assert active_row is not None
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE id IN (?, ?)", (finished_id, active_id))
        finished_log.unlink(missing_ok=True)
        active_log.unlink(missing_ok=True)


def test_complete_protocol_deletion_keeps_job_ids_monotonic(tmp_path):
    first_log = dmm.APP_LOG_DIR / "monotonic-first.log"
    second_log = dmm.APP_LOG_DIR / "monotonic-second.log"
    first_log.write_text("first", encoding="utf-8")
    now = dmm.now_iso()
    with dmm.db() as con:
        first_id = int(con.execute(
            """
            INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, finished_at, exit_code, source)
            VALUES (NULL, 'monotonic-first', 'error', 0, '', '[]', ?, ?, ?, 1, 'test')
            """,
            (str(first_log), now, now),
        ).lastrowid)
    try:
        result = dmm.delete_job_log_files([first_id])
        assert result["deleted_jobs"] == 1
        second_log.write_text("second", encoding="utf-8")
        with dmm.db() as con:
            second_id = int(con.execute(
                """
                INSERT INTO jobs(mirror_id, mirror_name, status, dry_run, command, command_json, log_path, started_at, finished_at, exit_code, source)
                VALUES (NULL, 'monotonic-second', 'success', 0, '', '[]', ?, ?, ?, 0, 'test')
                """,
                (str(second_log), now, now),
            ).lastrowid)
        assert second_id > first_id
    finally:
        with dmm.db() as con:
            con.execute("DELETE FROM jobs WHERE mirror_name IN ('monotonic-first','monotonic-second')")
        first_log.unlink(missing_ok=True)
        second_log.unlink(missing_ok=True)


def test_jobs_page_exposes_targeted_log_cleanup(client, database_cleanup):
    admin = make_user("log-cleanup-admin")
    authenticate(client, admin)
    response = client.get("/jobs")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/jobs/logs/delete" in html
    assert "vollständig löschen" in html or "completely" in html.lower()
    assert "Protokoll" in html or "log" in html.lower()


def test_new_log_retention_inherits_existing_job_retention(monkeypatch):
    original = dmm.load_settings()
    try:
        changed = dict(original)
        changed.pop("log_retention_days", None)
        changed["job_retention_days"] = 77
        dmm.save_settings(changed)
        assert dmm.log_retention_days() == 77
        assert int(dmm.load_settings()["log_retention_days"]) == 77
    finally:
        dmm.save_settings(original)
