from __future__ import annotations

from pathlib import Path

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
        ".github/dependabot.yml",
        ".github/workflows/ci.yml",
        "README.md",
        "README.de.md",
        "RELEASE_NOTES.md",
        "RELEASE_NOTES.de.md",
    }
    assert all((project_root / name).is_file() for name in required)
    assert (project_root / "VERSION").read_text(encoding="utf-8").strip() == "0.1.80"


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


def test_source_offer_route_exists(client):
    response = client.get("/source", follow_redirects=False)
    assert response.status_code in {200, 302, 404}
    assert response.status_code != 401


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
