#!/usr/bin/env bash
set -euo pipefail
umask 077

ENV_FILE=".env"
get_env_value() {
  local key="$1" default="$2"
  if [ -f "$ENV_FILE" ] && grep -qE "^${key}=" "$ENV_FILE"; then
    grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-
  else
    printf '%s' "$default"
  fi
}

BASE_DATA="${BASE_DATA:-$(get_env_value DATA_PATH /docker_data/debmirror-manager)}"
SETTINGS_FILE="$BASE_DATA/data/settings.json"
DB_FILE="$BASE_DATA/data/debmirror-manager.sqlite3"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FEHLER: python3 wird benötigt." >&2
  exit 1
fi

mkdir -p "$BASE_DATA/data"

read -rp "Admin-Benutzername [admin]: " admin_user
admin_user="${admin_user:-admin}"
while true; do
  read -rsp "Neues Admin-Passwort: " admin_pass; printf '\n'
  read -rsp "Neues Admin-Passwort wiederholen: " admin_pass2; printf '\n'
  if [ "$admin_pass" != "$admin_pass2" ]; then
    echo "Passwörter stimmen nicht überein."
    continue
  fi
  if [ "${#admin_pass}" -lt 12 ]; then
    echo "Passwort muss mindestens 12 Zeichen lang sein."
    continue
  fi
  break
done

ADMIN_USERNAME="$admin_user" ADMIN_PASSWORD="$admin_pass" SETTINGS_FILE="$SETTINGS_FILE" DB_FILE="$DB_FILE" python3 - <<'PY'
import base64, hashlib, json, os, secrets, sqlite3
from datetime import datetime
from pathlib import Path
settings_file = Path(os.environ['SETTINGS_FILE'])
db_path = Path(os.environ['DB_FILE'])
username = os.environ['ADMIN_USERNAME']
password = os.environ['ADMIN_PASSWORD']
salt = secrets.token_urlsafe(24)
iterations = 310_000
digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
password_hash = f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode('ascii')}"
settings = {}
settings_file.parent.mkdir(parents=True, exist_ok=True)
if settings_file.exists():
    try:
        settings = json.loads(settings_file.read_text(encoding='utf-8'))
    except Exception:
        settings = {}
# Nicht mehr als Legacy-Klartextwerte in settings.json speichern.
settings.pop('admin_username', None)
settings.pop('admin_password_hash', None)
settings['auth_updated_at'] = datetime.now().replace(microsecond=0).isoformat(sep=' ')
settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
settings_file.chmod(0o600)
with sqlite3.connect(db_path) as con:
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'admin',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT DEFAULT '',
        session_version INTEGER NOT NULL DEFAULT 1
    )""")
    now = datetime.now().replace(microsecond=0).isoformat(sep=' ')
    columns = {row[1] for row in con.execute('PRAGMA table_info(users)').fetchall()}
    if 'session_version' not in columns:
        con.execute('ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1')
    row = con.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
    if row:
        con.execute("UPDATE users SET password_hash=?, role='admin', enabled=1, updated_at=?, session_version=session_version+1 WHERE username=?", (password_hash, now, username))
    else:
        con.execute("INSERT INTO users(username, password_hash, role, enabled, created_at, updated_at, session_version) VALUES (?, ?, 'admin', 1, ?, ?, 1)", (username, password_hash, now, now))
PY
chmod 700 "$BASE_DATA" "$BASE_DATA/data" 2>/dev/null || true
chmod 600 "$SETTINGS_FILE" "$DB_FILE" 2>/dev/null || true

echo "Admin-Zugang wurde in der SQLite-Benutzerverwaltung gesetzt."
echo "settings.json enthält keine Legacy-Admin-Zugangswerte mehr."
echo "Falls du noch eingeloggt bist, bitte ausloggen oder den Browser-Tab neu laden."
