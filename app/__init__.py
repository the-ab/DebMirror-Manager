# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

APP_NAME = "DebMirror Manager"
_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
try:
    APP_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
except OSError:
    APP_VERSION = "0.0.0"

# ISO date of this packaged release; shown consistently in every page footer.
APP_RELEASE_DATE = "2026-07-22"
