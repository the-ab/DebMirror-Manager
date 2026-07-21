#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -Eeuo pipefail
umask 077

PROJECT_NAME="debmirror-manager"
PROJECT_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
ASSUME_YES=0
NO_BUILD=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-build) NO_BUILD=1 ;;
    --help|-h)
      cat <<USAGE
DebMirror Manager Installation

Verwendung:
  ./install.sh              Alle relevanten Werte abfragen, Verzeichnisse erstellen, Container bauen/starten
  ./install.sh --yes        Vorhandene/Standardwerte übernehmen
  ./install.sh --no-build   Nur konfigurieren, nicht bauen/starten
USAGE
      exit 0 ;;
    *) echo "FEHLER: Unbekannter Parameter: $1" >&2; exit 1 ;;
  esac
  shift
done

log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"; }
error_exit() { log "FEHLER: $1" >&2; exit 1; }
trap 'error_exit "Installation wurde unerwartet abgebrochen (Zeile $LINENO)."' ERR

need_cmd() { command -v "$1" >/dev/null 2>&1 || error_exit "$1 wurde nicht gefunden."; }
compose_cmd() {
  if docker compose version >/dev/null 2>&1; then echo "docker compose";
  elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose";
  else error_exit "Weder 'docker compose' noch 'docker-compose' wurde gefunden."; fi
}
rand_secret() { python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}

get_env_value() {
  local key="$1" default="${2:-}"
  if [ -f "$ENV_FILE" ] && grep -qE "^${key}=" "$ENV_FILE"; then
    grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-
  else
    printf '%s' "$default"
  fi
}
set_env_value() {
  local key="$1" value="$2"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); key = sys.argv[2]; value = sys.argv[3]
lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
out=[]; seen=False
for line in lines:
    if line.startswith(key + '='):
        out.append(f'{key}={value}'); seen=True
    else:
        out.append(line)
if not seen:
    if out and out[-1] != '': out.append('')
    out.append(f'{key}={value}')
path.write_text('\n'.join(out) + '\n', encoding='utf-8')
PY
}
ask_value() {
  local prompt="$1" default="$2" value
  if [ "$ASSUME_YES" -eq 1 ]; then printf '%s' "$default"; else read -rp "$prompt [$default]: " value; printf '%s' "${value:-$default}"; fi
}
ask_yes_no() {
  local prompt="$1" default="$2" answer
  if [ "$ASSUME_YES" -eq 1 ]; then printf '%s' "$default"; return; fi
  if [ "$default" = "1" ]; then
    read -rp "$prompt [J/n]: " answer; answer="${answer:-J}"; [[ "$answer" =~ ^[JjYy]$ ]] && printf '1' || printf '0'
  else
    read -rp "$prompt [j/N]: " answer; answer="${answer:-N}"; [[ "$answer" =~ ^[JjYy]$ ]] && printf '1' || printf '0'
  fi
}

trim_value() {
  python3 -c 'import sys; print(sys.argv[1].strip())' "${1:-}"
}
clean_path_value() {
  python3 -c 'import sys; v=sys.argv[1].strip(); v=v.rstrip();
while len(v)>1 and v.endswith(":"): v=v[:-1].rstrip();
print(v)' "${1:-}"
}
clean_csv_paths() {
  python3 -c 'import sys
seen=[]
for raw in sys.argv[1].split(","):
    v=raw.strip()
    while len(v)>1 and v.endswith(":"):
        v=v[:-1].rstrip()
    if v and v not in seen:
        seen.append(v)
print(",".join(seen))' "${1:-}"
}

write_admin_settings() {
  local base_data="$1" username="$2" password="$3"
  ADMIN_USERNAME="$username" ADMIN_PASSWORD="$password" SETTINGS_FILE="$base_data/data/settings.json" python3 - <<'INNER_PY'
import base64, hashlib, json, os, secrets, sqlite3
from datetime import datetime
from pathlib import Path
username = os.environ['ADMIN_USERNAME']
password = os.environ['ADMIN_PASSWORD']
settings_file = Path(os.environ['SETTINGS_FILE'])
db_path = settings_file.parent / 'debmirror-manager.sqlite3'
settings_file.parent.mkdir(parents=True, exist_ok=True)
salt = secrets.token_urlsafe(24)
iterations = 310_000
digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
password_hash = f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode('ascii')}"
settings = {}
if settings_file.exists():
    try:
        settings = json.loads(settings_file.read_text(encoding='utf-8'))
    except Exception:
        settings = {}
# Keine Klartext-/Legacy-Adminwerte mehr in settings.json speichern. Benutzer
# liegen in SQLite, Passwörter dort nur als Hash.
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
INNER_PY
}
compose_has_containers() { local dc="$1"; $dc ps -q 2>/dev/null | grep -q .; }
compose_has_running_containers() { local dc="$1"; $dc ps --status running -q 2>/dev/null | grep -q .; }
cleanup_legacy_image_name() {
  local legacy_image="${PROJECT_NAME}-${PROJECT_NAME}:latest"
  local current_image="${PROJECT_NAME}:latest"
  local legacy_id current_id
  legacy_id="$(docker image inspect --format '{{.Id}}' "$legacy_image" 2>/dev/null || true)"
  [ -n "$legacy_id" ] || return 0
  current_id="$(docker image inspect --format '{{.Id}}' "$current_image" 2>/dev/null || true)"
  if [ -n "$current_id" ] && [ "$legacy_id" = "$current_id" ]; then
    docker image rm "$legacy_image" >/dev/null 2>&1 || true
    log "Alte doppelte Image-Bezeichnung entfernt: ${legacy_image}"
  elif docker image rm "$legacy_image" >/dev/null 2>&1; then
    log "Nicht mehr verwendetes Alt-Image entfernt: ${legacy_image}"
  else
    log "Hinweis: Alt-Image ${legacy_image} ist noch in Benutzung und wurde nicht entfernt."
  fi
}
build_and_start() {
  local dc="$1" use_nginx="$2"
  if [ "$NO_BUILD" -eq 1 ]; then log "--no-build gesetzt: Container werden nicht gebaut/gestartet."; return; fi
  if compose_has_running_containers "$dc"; then log "Laufende Container gefunden. Sie werden mit --force-recreate ersetzt.";
  elif compose_has_containers "$dc"; then log "Vorhandene Container gefunden. Sie werden neu erstellt.";
  else log "Keine bestehenden Container gefunden. Container werden neu erstellt."; fi
  if [ "$use_nginx" = "1" ]; then
    log "Container werden mit optionalem nginx-Mirror-HTTP gebaut und gestartet..."
    $dc --profile mirror-http up -d --build --remove-orphans --force-recreate
  else
    log "Nur WebUI/Worker wird gebaut und gestartet. Optionaler nginx-Container wird entfernt, falls vorhanden..."
    $dc up -d --build --remove-orphans --force-recreate debmirror-manager
    $dc rm -sf mirror-nginx >/dev/null 2>&1 || true
  fi
  cleanup_legacy_image_name
}

need_cmd python3
need_cmd docker
dc="$(compose_cmd)"

printf 'DebMirror Manager Installation / Konfiguration\n'
printf '============================================\n'
printf 'Version: %s\n\n' "$PROJECT_VERSION"

if [ ! -f "$ENV_FILE" ]; then
  [ -f "$ENV_EXAMPLE" ] || error_exit "$ENV_EXAMPLE fehlt."
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  log ".env wurde aus .env.example erstellt."
else
  chmod 600 "$ENV_FILE" || true
  log ".env existiert bereits und wird nicht komplett überschrieben."
fi

current_data_path="$(get_env_value DATA_PATH /docker_data/debmirror-manager)"
current_mirror_path="$(get_env_value MIRROR_PATH /srv/mirror)"
current_webui_port="$(get_env_value WEBUI_PORT 8111)"
current_mirror_port="$(get_env_value MIRROR_HTTP_PORT 8110)"
current_use_nginx="$(get_env_value USE_NGINX_MIRROR_HTTP 1)"
current_update_dir="$(get_env_value UPDATE_DIR updates)"
current_update_backup_dir="$(get_env_value UPDATE_BACKUP_DIR backup)"
current_scan="$(get_env_value SCHEDULER_SCAN_SECONDS 60)"
current_stop="$(get_env_value JOB_STOP_GRACE_SECONDS 20)"
current_max_jobs="$(get_env_value MAX_PARALLEL_JOBS 1)"
current_retention="$(get_env_value JOB_RETENTION_DAYS 31)"
current_list_limit="$(get_env_value JOB_LIST_LIMIT 100)"
current_dashboard_jobs_limit="$(get_env_value DASHBOARD_RECENT_JOBS_LIMIT 10)"
current_dashboard_events_limit="$(get_env_value DASHBOARD_EVENTS_LIMIT 10)"
current_size_ttl="$(get_env_value SIZE_CACHE_TTL_SECONDS 21600)"
current_size_timeout="$(get_env_value SIZE_CALC_TIMEOUT_SECONDS 1800)"
current_size_parallel="$(get_env_value SIZE_CALC_MAX_PARALLEL 2)"
current_auto_size_enabled="$(get_env_value AUTO_SIZE_RECALC_ENABLED 1)"
current_auto_size_idle="$(get_env_value AUTO_SIZE_IDLE_MINUTES 120)"
current_storage_guard_enabled="$(get_env_value STORAGE_GUARD_ENABLED 1)"
current_storage_guard_threshold="$(get_env_value STORAGE_GUARD_THRESHOLD_PERCENT 95)"
current_app_timezone="$(get_env_value APP_TIMEZONE Europe/Berlin)"

printf '\nPfade und Ports\n'
data_path="$(clean_path_value "$(ask_value 'Persistenter Datenpfad für DB/Logs/Keyrings/Backups/Skripte' "$current_data_path")")"
mirror_path="$(clean_path_value "$(ask_value 'Lokales Mirror-Verzeichnis auf dem Host' "$current_mirror_path")")"
webui_port="$(trim_value "$(ask_value 'WebUI Host-Port' "$current_webui_port")")"
use_nginx="$(ask_yes_no 'Optionalen nginx-Container für Mirror-HTTP starten?' "$current_use_nginx")"
if [ "$use_nginx" = "1" ]; then
  mirror_port="$(trim_value "$(ask_value 'Mirror HTTP Host-Port für optionalen nginx' "$current_mirror_port")")"
else
  mirror_port="$current_mirror_port"
  log "Optionaler nginx deaktiviert: Mirror-HTTP-Port wird nicht abgefragt."
fi
update_dir="$(clean_path_value "$(ask_value 'Update-Verzeichnis im Projektordner' "$current_update_dir")")"
update_backup_dir="$(clean_path_value "$(ask_value 'Update-Backup-Verzeichnis' "$current_update_backup_dir")")"
import_paths_default="$mirror_path"
import_paths="$(clean_csv_paths "$(ask_value 'Host-Pfade, die beim Skript-Import auf /mirror gemappt werden' "$import_paths_default")")"

printf '\nScheduler / Jobs / Logs\n'
scan_seconds="$(trim_value "$(ask_value 'Scheduler-/Queue-Scanintervall in Sekunden' "$current_scan")")"
stop_grace="$(trim_value "$(ask_value 'Sekunden bis Kill nach Stop-Anforderung' "$current_stop")")"
max_jobs="$(trim_value "$(ask_value 'Maximal gleichzeitig laufende Jobs' "$current_max_jobs")")"
retention_days="$(trim_value "$(ask_value 'Job-/Log-Aufbewahrung in Tagen' "$current_retention")")"
list_limit="$(trim_value "$(ask_value 'Anzahl Jobs in Listen' "$current_list_limit")")"
dashboard_jobs_limit="$(trim_value "$(ask_value 'Anzahl Letzte Jobs im Dashboard' "$current_dashboard_jobs_limit")")"
dashboard_events_limit="$(trim_value "$(ask_value 'Anzahl Ereignisse im Dashboard' "$current_dashboard_events_limit")")"
size_ttl="$(trim_value "$(ask_value 'Mirror-Größen-Cache in Sekunden' "$current_size_ttl")")"
size_timeout="$(trim_value "$(ask_value 'Timeout je Mirror-Größenberechnung in Sekunden' "$current_size_timeout")")"
size_parallel="$(trim_value "$(ask_value 'Maximal parallele Mirror-Größenberechnungen' "$current_size_parallel")")"
auto_size_enabled="$(ask_yes_no 'Automatische Größenberechnung nach Job-Ruhefenster aktivieren?' "$current_auto_size_enabled")"
auto_size_idle="$(trim_value "$(ask_value 'Ruhefenster ohne geplante Jobs in Minuten' "$current_auto_size_idle")")"
storage_guard_enabled="$(ask_yes_no 'Speicherplatz-Sperre für echte Mirror-Jobs aktivieren?' "$current_storage_guard_enabled")"
storage_guard_threshold="$(trim_value "$(ask_value 'Grenzwert Mirror-Speichernutzung in Prozent' "$current_storage_guard_threshold")")"
app_timezone="$(trim_value "$(ask_value 'Lokale Zeitzone für WebUI und Logs' "$current_app_timezone")")"

[ -n "$data_path" ] || error_exit "Datenpfad darf nicht leer sein."
[ -n "$mirror_path" ] || error_exit "Mirror-Verzeichnis darf nicht leer sein."
[ -n "$webui_port" ] || error_exit "WebUI-Port darf nicht leer sein."
[ -n "$update_dir" ] || error_exit "Update-Verzeichnis darf nicht leer sein."
[ -n "$update_backup_dir" ] || error_exit "Update-Backup-Verzeichnis darf nicht leer sein."
[ -n "$import_paths" ] || import_paths="$mirror_path"
[ -n "$app_timezone" ] || app_timezone="Europe/Berlin"

set_env_value DATA_PATH "$data_path"
set_env_value MIRROR_PATH "$mirror_path"
set_env_value WEBUI_PORT "$webui_port"
set_env_value USE_NGINX_MIRROR_HTTP "$use_nginx"
set_env_value MIRROR_HTTP_PORT "$mirror_port"
set_env_value UPDATE_DIR "$update_dir"
set_env_value UPDATE_BACKUP_DIR "$update_backup_dir"
set_env_value IMPORT_HOST_MIRROR_PATHS "$import_paths"
set_env_value SCHEDULER_SCAN_SECONDS "$scan_seconds"
set_env_value JOB_STOP_GRACE_SECONDS "$stop_grace"
set_env_value MAX_PARALLEL_JOBS "$max_jobs"
set_env_value JOB_RETENTION_DAYS "$retention_days"
set_env_value JOB_LIST_LIMIT "$list_limit"
set_env_value DASHBOARD_RECENT_JOBS_LIMIT "$dashboard_jobs_limit"
set_env_value DASHBOARD_EVENTS_LIMIT "$dashboard_events_limit"
set_env_value SIZE_CACHE_TTL_SECONDS "$size_ttl"
set_env_value SIZE_CALC_TIMEOUT_SECONDS "$size_timeout"
set_env_value SIZE_CALC_MAX_PARALLEL "$size_parallel"
set_env_value AUTO_SIZE_RECALC_ENABLED "$auto_size_enabled"
set_env_value AUTO_SIZE_IDLE_MINUTES "$auto_size_idle"
set_env_value STORAGE_GUARD_ENABLED "$storage_guard_enabled"
set_env_value STORAGE_GUARD_THRESHOLD_PERCENT "$storage_guard_threshold"
set_env_value APP_TIMEZONE "$app_timezone"
set_env_value TZ "$app_timezone"
set_env_value APP_BACKUP_DIR "$(get_env_value APP_BACKUP_DIR /app/backups)"
set_env_value USER_SCRIPT_DIR "$(get_env_value USER_SCRIPT_DIR /user-scripts)"

mkdir -p "$data_path/data" "$data_path/logs" "$data_path/keyrings" "$data_path/import-scripts" "$data_path/user-scripts" "$data_path/backup" "$mirror_path" "$update_dir" "$update_backup_dir"
chmod 700 "$data_path" "$data_path/data" "$data_path/logs" "$data_path/keyrings" "$data_path/import-scripts" "$data_path/user-scripts" "$data_path/backup" "$update_dir" "$update_backup_dir" 2>/dev/null || true
chmod 600 "$ENV_FILE" 2>/dev/null || true

secret="$(get_env_value APP_SECRET_KEY '')"
if [ -z "$secret" ] || [ "$secret" = "please-change-this-secret" ]; then
  set_env_value APP_SECRET_KEY "$(rand_secret)"
  log "APP_SECRET_KEY wurde neu generiert."
fi

printf '\nAdmin-Zugang\n'
printf 'Der Zugang kann jetzt in der Shell gesetzt werden. Alternativ beim ersten Webaufruf über /setup.\n'
if [ "$ASSUME_YES" -eq 1 ]; then set_admin="n"; else read -rp "Admin-Zugang jetzt setzen? [J/n]: " set_admin; set_admin="${set_admin:-J}"; fi
if [[ "$set_admin" =~ ^[JjYy] ]]; then
  current_user="$(get_env_value APP_USERNAME admin)"
  read -rp "Admin-Benutzername [${current_user}]: " admin_user
  admin_user="${admin_user:-$current_user}"
  while true; do
    read -rsp "Admin-Passwort: " admin_pass; printf '\n'
    read -rsp "Admin-Passwort wiederholen: " admin_pass2; printf '\n'
    if [ "$admin_pass" != "$admin_pass2" ]; then printf 'Passwörter stimmen nicht überein.\n'; continue; fi
    if [ "${#admin_pass}" -lt 12 ]; then printf 'Passwort muss mindestens 12 Zeichen lang sein.\n'; continue; fi
    break
  done
  write_admin_settings "$data_path" "$admin_user" "$admin_pass"
  set_env_value APP_USERNAME ""
  set_env_value APP_PASSWORD ""
  set_env_value APP_PASSWORD_HASH ""
  log "Admin-Zugang wurde in der SQLite-Benutzerverwaltung gespeichert."
else
  log "Kein Admin-Zugang gesetzt. Beim ersten Webaufruf erscheint die Ersteinrichtung."
fi

build_and_start "$dc" "$use_nginx"

printf '\nInstallation/Konfiguration abgeschlossen.\n'
printf 'WebUI:        http://SERVER-IP:%s\n' "$webui_port"
if [ "$use_nginx" = "1" ]; then
  printf 'Mirror-HTTP: http://SERVER-IP:%s\n' "$mirror_port"
else
  printf 'Mirror-HTTP: deaktiviert. Nutze deinen vorhandenen Webserver für %s.\n' "$mirror_path"
fi
printf '\nKünftige Updates:\n'
printf '  cp debmirror-manager-vNEU.zip %s/\n' "$update_dir"
printf '  ./update.sh\n'
