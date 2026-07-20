# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gunicorn-Konfiguration für DebMirror Manager.

Die Anwendung besitzt einen internen Scheduler und In-Process-Jobstatus. Deshalb
wird bewusst genau ein Worker mit mehreren Threads verwendet. Mehrere Worker
würden Scheduler und Warteschlange mehrfach starten.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "j", "ja"}


bind = f"0.0.0.0:{_int_env('APP_PORT', 8080, 1)}"
workers = 1
worker_class = "gthread"
threads = _int_env("WSGI_THREADS", 8, 2)

# Live-Logs verwenden Server-Sent Events und dürfen auch bei sehr langen Jobs
# nicht durch einen Worker-Timeout beendet werden.
timeout = 0
graceful_timeout = _int_env("WSGI_GRACEFUL_TIMEOUT", 30, 1)
keepalive = _int_env("WSGI_KEEPALIVE", 5, 1)

# HTTP-Zugriffszeilen sind standardmäßig aus, damit periodische Live-Log-Aufrufe
# nicht das Containerlog füllen. Fehler und Anwendungs-Ausgaben bleiben sichtbar.
accesslog = "-" if _bool_env("WSGI_ACCESS_LOG", False) else None
errorlog = "-"
loglevel = os.environ.get("WSGI_LOG_LEVEL", "info").strip().lower() or "info"
capture_output = True
preload_app = False

# Begrenzungen gegen übergroße oder missbräuchliche HTTP-Header.
limit_request_line = _int_env("WSGI_LIMIT_REQUEST_LINE", 4094, 256)
limit_request_fields = _int_env("WSGI_LIMIT_REQUEST_FIELDS", 100, 10)
limit_request_field_size = _int_env("WSGI_LIMIT_REQUEST_FIELD_SIZE", 8190, 1024)
