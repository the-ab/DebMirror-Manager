from __future__ import annotations

from pathlib import Path
import os
import datetime as dt
import email.utils
import http.server
import threading
import stat
import sys

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
    assert (project_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.83"


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
