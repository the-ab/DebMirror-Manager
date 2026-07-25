# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def test_update_check_ui_and_defaults():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    settings = (root / "app/templates/settings.html").read_text(encoding="utf-8")
    assert 'DEFAULT_UPDATE_CHECK_INTERVAL_HOURS = 24' in main
    assert 'UPDATE_CHECK_REPOSITORY = "the-ab/DebMirror-Manager"' in main
    assert 'update_check_scan()' in main
    assert 'Update verfügbar' in base
    assert 'Version Aktuell' in base
    assert 'target="_blank"' in base
    assert 'name="update_check_enabled"' in settings
    assert 'name="update_check_interval_hours"' in settings


def test_update_release_url_is_fixed_to_expected_repository():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert 'https://api.github.com/repos/{UPDATE_CHECK_REPOSITORY}/releases/latest' in main
    assert 'https://github.com/{UPDATE_CHECK_REPOSITORY}/releases/tag/' in main
    assert 'payload.get("html_url")' not in main
