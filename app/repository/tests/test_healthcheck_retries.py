from __future__ import annotations

import errno
import io
import socket
import ssl
import subprocess
import urllib.error

import pytest

from app import main as dmm
from tests.conftest import make_user


@pytest.fixture()
def probe_state(monkeypatch):
    ids = []
    notifications = []
    delays = []

    def create(method="GET", expected_status=200, previous_state="ok", target=None, allow_private=0):
        now = dmm.now_iso()
        with dmm.db() as con:
            cur = con.execute(
                """
                INSERT INTO healthchecks(
                    name, url, expected_status, method, timeout_seconds,
                    interval_minutes, enabled, allow_private, last_notify_state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 5, 60, 1, ?, ?, ?, ?)
                """,
                (f"retry-test-{method}-{len(ids)}", target or "https://example.org/health",
                 expected_status, method, allow_private, previous_state, now, now),
            )
            ids.append(int(cur.lastrowid))
        return dmm.get_healthcheck(ids[-1])

    monkeypatch.setattr(dmm.time, "sleep", lambda delay: delays.append(delay))
    monkeypatch.setattr(
        dmm, "notification_settings",
        lambda: {"enabled": True, "on_healthcheck_error": True, "on_healthcheck_recovery": True},
    )
    monkeypatch.setattr(
        dmm, "send_notification",
        lambda subject, message, kind="info": notifications.append((subject, message, kind)) or ["ok"],
    )
    yield create, notifications, delays
    with dmm.db() as con:
        for check_id in ids:
            con.execute("DELETE FROM healthchecks WHERE id=?", (check_id,))


class Response:
    def __init__(self, status=200):
        self.status = status
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_route_failure_then_success_does_not_notify(monkeypatch, probe_state, method):
    create, notifications, delays = probe_state
    check = create(method)
    calls = []
    response = Response()

    def open_url(req, **kwargs):
        calls.append((req.get_method(), kwargs))
        if len(calls) == 1:
            raise urllib.error.URLError(OSError(errno.ENETUNREACH, "Network is unreachable"))
        return response

    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is True
    assert result["attempts"] == 2
    assert delays == [1]
    assert notifications == []
    assert response.closed
    assert all(method_seen == method for method_seen, _kwargs in calls)
    assert all(kwargs["timeout"] == 5 and not kwargs["allow_private"] for _, kwargs in calls)
    row = dmm.get_healthcheck(check["id"])
    assert row["last_ok"] == 1 and row["last_error"] == ""
    assert row["last_notify_state"] == "ok"


def test_persistent_network_failure_alerts_once_then_recovers(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create()
    attempts = []

    def unavailable(*_args, **_kwargs):
        attempts.append(1)
        raise urllib.error.URLError(OSError(errno.ENETUNREACH, "Network is unreachable"))

    monkeypatch.setattr(dmm, "safe_urlopen", unavailable)
    first = dmm.run_healthcheck_once(check)
    assert first["ok"] is False and first["attempts"] == 3
    assert len(attempts) == 3 and delays == [1, 2]
    assert len(notifications) == 1 and "Network is unreachable" in notifications[0][1]
    assert "attempts: 3" in first["error"]
    assert dmm.get_healthcheck(check["id"])["last_notify_state"] == "error"
    dmm.run_healthcheck_once(dmm.get_healthcheck(check["id"]))
    assert len(attempts) == 6 and len(notifications) == 1
    monkeypatch.setattr(dmm, "safe_urlopen", lambda *_args, **_kwargs: Response())
    dmm.run_healthcheck_once(dmm.get_healthcheck(check["id"]))
    dmm.run_healthcheck_once(dmm.get_healthcheck(check["id"]))
    assert len(notifications) == 2 and "wieder erreichbar" in notifications[1][0]


@pytest.mark.parametrize("status", [502, 503, 504])
def test_temporary_http_error_is_retried_and_response_closed(monkeypatch, probe_state, status):
    create, notifications, delays = probe_state
    check = create()
    body = io.BytesIO(b"temporarily unavailable")
    error = urllib.error.HTTPError(check["url"], status, "upstream failure", {}, body)
    calls = []

    def open_url(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return Response()

    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is True and result["attempts"] == 2
    assert body.closed and notifications == [] and delays == [1]


@pytest.mark.parametrize("status,expected,ok", [(404, 200, False), (401, 200, False), (404, 404, True), (503, 503, True)])
def test_http_status_expectation_is_preserved(monkeypatch, probe_state, status, expected, ok):
    create, notifications, delays = probe_state
    check = create(expected_status=expected)
    body = io.BytesIO(b"status")
    error = urllib.error.HTTPError(check["url"], status, "status", {}, body)

    def open_url(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is ok and result["status_code"] == status
    assert result["attempts"] == 1 and delays == []
    assert body.closed
    assert len(notifications) == (0 if ok else 1)


def test_certificate_failure_is_not_retried_or_ignored(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create()
    calls = []

    def open_url(*_args, **_kwargs):
        calls.append(1)
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is False and result["attempts"] == 1
    assert len(calls) == 1 and delays == [] and len(notifications) == 1


def test_private_target_validation_remains_active_on_retry(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create()
    original_open = dmm.safe_urlopen
    requests = []

    def resolve(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    def open_url(req, **kwargs):
        requests.append(1)
        if len(requests) == 1:
            raise urllib.error.URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        return original_open(req, **kwargs)

    monkeypatch.setattr(dmm.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is False and result["attempts"] == 2
    assert "nicht erlaubt" in result["error"]
    assert len(requests) == 2 and delays == [1] and len(notifications) == 1


@pytest.mark.parametrize("code,output", [(1, "100% packet loss"), (2, "ping: connect: Network is unreachable")])
def test_ping_single_lost_packet_or_route_error_is_confirmed(monkeypatch, probe_state, code, output):
    create, notifications, delays = probe_state
    check = create("PING", target="192.0.2.1")
    calls = []
    monkeypatch.setattr(dmm, "validate_ping_target", lambda *_args, **_kwargs: ("example.org", "192.0.2.1"))
    monkeypatch.setattr(dmm.shutil, "which", lambda _name: "/usr/bin/ping")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, code, output, "")
        return subprocess.CompletedProcess(command, 0, "64 bytes: time=4.0 ms", "")

    monkeypatch.setattr(dmm.subprocess, "run", run)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is True and result["attempts"] == 2
    assert result["latency_ms"] == 4
    assert notifications == [] and delays == [1]
    assert all(command[-2:] == ["--", "192.0.2.1"] for command, _kwargs in calls)
    assert all(command[command.index("-c") + 1] == "1" for command, _kwargs in calls)
    assert all(kwargs["timeout"] == 7 for _command, kwargs in calls)


def test_ping_permission_error_is_not_retried(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create("PING", target="192.0.2.1")
    monkeypatch.setattr(dmm, "validate_ping_target", lambda *_args, **_kwargs: ("example.org", "192.0.2.1"))
    monkeypatch.setattr(dmm.shutil, "which", lambda _name: "/usr/bin/ping")
    monkeypatch.setattr(
        dmm.subprocess, "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 2, "", "ping: socket: Operation not permitted"),
    )
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is False and result["attempts"] == 1
    assert delays == [] and len(notifications) == 1


def test_ping_timeout_stays_bounded_and_errors_after_confirmation(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create("PING", target="192.0.2.1")
    calls = []
    monkeypatch.setattr(dmm, "validate_ping_target", lambda *_args, **_kwargs: ("example.org", "192.0.2.1"))
    monkeypatch.setattr(dmm.shutil, "which", lambda _name: "/usr/bin/ping")

    def timeout(command, **kwargs):
        calls.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(dmm.subprocess, "run", timeout)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is False and result["attempts"] == 3
    assert calls == [7, 7, 7] and delays == [1, 2]
    assert len(notifications) == 1


def test_ftp_transport_failure_then_valid_reply_does_not_login(monkeypatch, probe_state):
    create, notifications, delays = probe_state
    check = create("FTP", target="ftp://example.org/debian")
    calls = []

    class Stream:
        def readline(self, _limit):
            return b"530 Login required.\r\n"

        def close(self):
            calls.append("stream-close")

    class Socket:
        def settimeout(self, _timeout):
            pass

        def makefile(self, _mode):
            return Stream()

        def close(self):
            calls.append("socket-close")

    def connect(_address, timeout):
        calls.append("connect")
        if calls.count("connect") == 1:
            raise TimeoutError("timed out")
        return Socket()

    monkeypatch.setattr(dmm, "validate_ftp_target", lambda *_args, **_kwargs: (check["url"], "192.0.2.1", 21, "/debian"))
    monkeypatch.setattr(dmm.socket, "create_connection", connect)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is True and result["attempts"] == 2 and result["status_code"] == 530
    assert calls == ["connect", "connect", "stream-close", "socket-close"]
    assert notifications == [] and delays == [1]


@pytest.mark.parametrize("reason", [socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure"), TimeoutError("timed out")])
def test_temporary_dns_and_timeout_recover(monkeypatch, probe_state, reason):
    create, notifications, delays = probe_state
    check = create()
    calls = []

    def open_url(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            try:
                raise reason
            except OSError as exc:
                raise ValueError("DNS/transport lookup failed") from exc
        return Response()

    monkeypatch.setattr(dmm, "safe_urlopen", open_url)
    result = dmm.run_healthcheck_once(check)
    assert result["ok"] is True and result["attempts"] == 2
    assert notifications == [] and delays == [1]


@pytest.mark.parametrize("language", ["de", "en"])
def test_login_serves_existing_favicon_without_authentication(client, database_cleanup, language):
    make_user("favicon-login-user")
    with client.session_transaction() as session:
        session["language"] = language
    page = client.get("/login")
    assert page.status_code == 200
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in page.get_data(as_text=True)
    icon = client.get("/static/favicon.svg")
    assert icon.status_code == 200 and icon.mimetype == "image/svg+xml"
    assert b"<svg" in icon.data
