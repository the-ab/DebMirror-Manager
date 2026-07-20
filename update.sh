#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
set -Eeuo pipefail
umask 077

APP_NAME="DebMirror Manager"
PROJECT_NAME="debmirror-manager"
PROJECT_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
env_value_or_default() {
  local key="$1" default="$2"
  if [ -f ".env" ] && grep -qE "^${key}=" ".env"; then
    grep -E "^${key}=" ".env" | tail -n1 | cut -d= -f2-
  else
    printf '%s' "$default"
  fi
}

BASE_DATA="${BASE_DATA:-$(env_value_or_default DATA_PATH /docker_data/debmirror-manager)}"
BACKUP_DIR="${UPDATE_BACKUP_DIR:-$(env_value_or_default UPDATE_BACKUP_DIR backup)}"
UPDATE_DIR="${UPDATE_DIR:-$(env_value_or_default UPDATE_DIR updates)}"
TS="$(date +%Y%m%d-%H%M%S)"
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
ASSUME_YES=0
NO_BUILD=0

log() {
  printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"
}

error_exit() {
  log "FEHLER: $1"
  exit 1
}

trap 'error_exit "Update wurde unerwartet abgebrochen (Zeile $LINENO)."' ERR

usage() {
  cat <<USAGE
$APP_NAME Update

Verwendung:
  ./update.sh                 Prüft ${UPDATE_DIR}/ auf ein neues ZIP, aktualisiert falls vorhanden, baut/startet Container
  ./update.sh --rebuild       Kein Paketupdate, nur .env prüfen, Backup, Container neu bauen/starten
  ./update.sh --file DATEI    Angegebene ZIP-Datei verwenden
  ./update.sh --yes           Keine Rückfragen
  ./update.sh --no-build      Nur Dateien aktualisieren, Container nicht bauen/starten

Update-Paket:
  ZIP und zugehörige SHA-256-Datei nach ${UPDATE_DIR}/ kopieren, z. B.:
    ${UPDATE_DIR}/${PROJECT_NAME}-v0.1.79.zip
    ${UPDATE_DIR}/${PROJECT_NAME}-v0.1.79.zip.sha256
  Danach nur noch ausführen:
    ./update.sh
USAGE
}

UPDATE_FILE=""
FORCE_REBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --file)
      shift
      [ $# -gt 0 ] || error_exit "--file benötigt einen Dateipfad."
      UPDATE_FILE="$1"
      ;;
    --yes|-y)
      ASSUME_YES=1
      ;;
    --rebuild)
      FORCE_REBUILD=1
      ;;
    --no-build)
      NO_BUILD=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      error_exit "Unbekannter Parameter: $1"
      ;;
  esac
  shift
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || error_exit "$1 wurde nicht gefunden."
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    error_exit "Weder 'docker compose' noch 'docker-compose' wurde gefunden."
  fi
}

confirm() {
  local prompt="$1"
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  read -rp "$prompt [J/n]: " answer
  answer="${answer:-J}"
  [[ "$answer" =~ ^[JjYy]$ ]]
}

version_gt() {
  python3 - "$1" "$2" <<'PY'
import re, sys

def parts(v):
    nums = [int(x) for x in re.findall(r'\d+', v or '')[:4]]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)

sys.exit(0 if parts(sys.argv[1]) > parts(sys.argv[2]) else 1)
PY
}

find_env_candidates() {
  local current_dir parent
  current_dir="$(pwd -P)"
  parent="$(dirname "$current_dir")"
  {
    find "$parent" -maxdepth 2 -type f -path "*/debmirror-manager*/.env" 2>/dev/null || true
    [ -f "/opt/debmirror-manager/.env" ] && printf '%s\n' "/opt/debmirror-manager/.env"
    [ -f "/root/debmirror-manager/.env" ] && printf '%s\n' "/root/debmirror-manager/.env"
  } | awk '!seen[$0]++' | grep -v "^$(pwd -P)/.env$" || true
}

import_env_if_missing() {
  if [ -f "$ENV_FILE" ]; then
    log ".env vorhanden, bestehende Einstellungen bleiben erhalten."
    return
  fi

  log ".env fehlt im aktuellen Projektordner. Suche nach älteren Installationen..."
  mapfile -t candidates < <(find_env_candidates)

  if [ "${#candidates[@]}" -gt 0 ]; then
    log "Gefundene .env-Dateien:"
    local i=1
    for c in "${candidates[@]}"; do
      printf '  [%s] %s\n' "$i" "$c"
      i=$((i+1))
    done
    printf '  [0] Keine übernehmen, .env.example verwenden\n'
    read -rp "Welche .env übernehmen? [1]: " choice
    choice="${choice:-1}"
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -gt 0 ] && [ "$choice" -le "${#candidates[@]}" ]; then
      cp "${candidates[$((choice-1))]}" "$ENV_FILE"
      chmod 600 "$ENV_FILE"
      log ".env wurde aus ${candidates[$((choice-1))]} übernommen."
      return
    fi
  fi

  [ -f "$ENV_EXAMPLE" ] || error_exit "$ENV_EXAMPLE fehlt."
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  log ".env wurde aus .env.example erstellt. Bitte danach Zugang/Ports prüfen."
}

merge_env_example() {
  [ -f "$ENV_EXAMPLE" ] || return
  [ -f "$ENV_FILE" ] || return
  python3 - "$ENV_FILE" "$ENV_EXAMPLE" "$PROJECT_VERSION" <<'PY'
from pathlib import Path
import re, sys

env = Path(sys.argv[1])
example = Path(sys.argv[2])
version = sys.argv[3]
current = env.read_text(encoding='utf-8').splitlines()
example_lines = example.read_text(encoding='utf-8').splitlines()
key_re = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=')
existing = set()
for line in current:
    m = key_re.match(line.strip())
    if m:
        existing.add(m.group(1))
missing = []
for line in example_lines:
    m = key_re.match(line.strip())
    if m and m.group(1) not in existing:
        missing.append(line)
        existing.add(m.group(1))
if missing:
    out = current[:]
    if out and out[-1] != '':
        out.append('')
    out.append(f'# --- Automatisch ergänzt durch update.sh auf Version {version} ---')
    out.extend(missing)
    env.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(f'{len(missing)} fehlende .env-Werte ergänzt.')
else:
    print('Keine fehlenden .env-Werte gefunden.')
PY
}

create_backups() {
  mkdir -p "$BACKUP_DIR"

  local backup_base="$BACKUP_DIR/update-${TS}-v${PROJECT_VERSION}"
  mkdir -p "$backup_base"

  if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$backup_base/.env"
    chmod 600 "$backup_base/.env"
  fi
  [ -f "docker-compose.yml" ] && cp docker-compose.yml "$backup_base/docker-compose.yml"
  [ -f "VERSION" ] && cp VERSION "$backup_base/VERSION"
  for name in LICENSE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md .gitignore .dockerignore requirements.lock requirements-dev.txt pytest.ini; do
    [ -f "$name" ] && cp "$name" "$backup_base/$name"
  done
  [ -d tests ] && cp -a tests "$backup_base/tests"
  [ -d scripts ] && cp -a scripts "$backup_base/scripts"
  [ -d .github ] && cp -a .github "$backup_base/.github"
  [ -d "app" ] && tar -czf "$backup_base/app-project-files.tar.gz" app
  [ -d "nginx" ] && tar -czf "$backup_base/nginx-config.tar.gz" nginx
  [ -f "README.md" ] && cp README.md "$backup_base/README.md"
  [ -f "README.de.md" ] && cp README.de.md "$backup_base/README.de.md"
  [ -f "RELEASE_NOTES.md" ] && cp RELEASE_NOTES.md "$backup_base/RELEASE_NOTES.md"
  [ -f "RELEASE_NOTES.de.md" ] && cp RELEASE_NOTES.de.md "$backup_base/RELEASE_NOTES.de.md"

  log "Projekt-Konfiguration gesichert: $backup_base"

  local persistent_items=()
  [ -d "$BASE_DATA/data" ] && persistent_items+=(data)
  [ -d "$BASE_DATA/keyrings" ] && persistent_items+=(keyrings)
  [ -d "$BASE_DATA/import-scripts" ] && persistent_items+=(import-scripts)
  [ -d "$BASE_DATA/user-scripts" ] && persistent_items+=(user-scripts)

  if [ "${#persistent_items[@]}" -gt 0 ]; then
    tar -czf "$BACKUP_DIR/update-${TS}-persistent-v${PROJECT_VERSION}.tar.gz" -C "$BASE_DATA" "${persistent_items[@]}"
    log "Persistente Daten gesichert: $BACKUP_DIR/update-${TS}-persistent-v${PROJECT_VERSION}.tar.gz"
  else
    log "Keine persistenten Daten unter $BASE_DATA/data, $BASE_DATA/keyrings oder $BASE_DATA/import-scripts gefunden."
  fi
}

verify_update_checksum() {
  local zip_file="$1"
  local expected="${UPDATE_EXPECTED_SHA256:-}"
  local sidecar="${zip_file}.sha256"
  local require_checksum
  require_checksum="$(env_value_or_default UPDATE_REQUIRE_CHECKSUM 1)"

  if [ -z "$expected" ] && [ -f "$sidecar" ]; then
    expected="$(awk 'match(tolower($0), /[0-9a-f]{64}/) {print substr(tolower($0), RSTART, RLENGTH); exit}' "$sidecar")"
  fi
  if [ -z "$expected" ] && [ "$ASSUME_YES" -eq 0 ]; then
    printf 'Erwarteten SHA-256-Wert des Update-ZIPs eingeben (leer = Abbruch, wenn Prüfung erforderlich): '
    read -r expected
  fi
  expected="$(printf '%s' "$expected" | tr 'A-F' 'a-f' | grep -oE '[0-9a-f]{64}' | head -n1 || true)"

  case "${require_checksum,,}" in
    0|false|no|off|n|nein)
      if [ -z "$expected" ]; then
        log "WARNUNG: SHA-256-Prüfung wurde ausdrücklich deaktiviert."
        return 0
      fi
      ;;
    *)
      [ -n "$expected" ] || error_exit "Für das Update fehlt der vertrauenswürdig bezogene SHA-256-Wert. Lege ${sidecar} ab oder setze UPDATE_EXPECTED_SHA256."
      ;;
  esac

  if [ -n "$expected" ]; then
    local actual
    actual="$(sha256sum "$zip_file" | awk '{print $1}')"
    [ "$actual" = "$expected" ] || error_exit "SHA-256-Prüfung fehlgeschlagen. Erwartet: $expected, erhalten: $actual"
    log "SHA-256-Prüfung erfolgreich: $actual"
  fi
}

read_zip_version() {
  local zip_file="$1"
  python3 - "$zip_file" <<'PY'
from pathlib import Path
import sys, zipfile
zip_path = Path(sys.argv[1])
try:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        candidates = [n for n in names if n.rstrip('/').endswith('/VERSION') or n == 'VERSION']
        for name in candidates:
            value = zf.read(name).decode('utf-8', 'replace').strip()
            if value:
                print(value)
                raise SystemExit(0)
except Exception:
    pass
raise SystemExit(1)
PY
}

find_newest_update_zip() {
  mkdir -p "$UPDATE_DIR"
  python3 - "$UPDATE_DIR" "$PROJECT_VERSION" <<'PY'
from pathlib import Path
import re, sys, zipfile

update_dir = Path(sys.argv[1])
current = sys.argv[2]

def parts(v):
    nums = [int(x) for x in re.findall(r'\d+', v or '')[:4]]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)

def zip_version(path):
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.rstrip('/').endswith('/VERSION') or name == 'VERSION':
                    value = zf.read(name).decode('utf-8', 'replace').strip()
                    if value:
                        return value
    except Exception:
        return None
    return None

items = []
for path in update_dir.glob('*.zip'):
    version = zip_version(path)
    if version and parts(version) > parts(current):
        items.append((parts(version), version, path))
items.sort(reverse=True)
if items:
    _, version, path = items[0]
    print(f'{path}\t{version}')
PY
}

safe_extract_and_copy_update() {
  local zip_file="$1"
  local tmp_dir="$2"
  python3 - "$zip_file" "$tmp_dir" "$(pwd -P)" <<'PYZIP'
from pathlib import Path
import shutil, stat, sys, zipfile

zip_file = Path(sys.argv[1]).resolve()
tmp_dir = Path(sys.argv[2]).resolve()
target_root = Path(sys.argv[3]).resolve()
extract_root = tmp_dir / 'extract'
extract_root.mkdir(parents=True, exist_ok=True, mode=0o700)
max_entries = 10000
max_total = 512 * 1024 * 1024
max_file = 256 * 1024 * 1024
max_ratio = 200

with zipfile.ZipFile(zip_file) as zf:
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise SystemExit(f'Update-ZIP enthält zu viele Einträge: {len(infos)} > {max_entries}')
    total = 0
    for info in infos:
        name = info.filename
        mode = (info.external_attr >> 16) & 0o170000
        if not name or name.startswith('/') or '..' in Path(name).parts:
            raise SystemExit(f'Unsicherer ZIP-Pfad: {name}')
        if mode and mode not in {stat.S_IFREG, stat.S_IFDIR}:
            raise SystemExit(f'Sonderdatei oder symbolischer Link im ZIP nicht erlaubt: {name}')
        if info.file_size > max_file:
            raise SystemExit(f'ZIP-Eintrag ist zu groß: {name}')
        total += info.file_size
        if total > max_total:
            raise SystemExit('Update-ZIP überschreitet die erlaubte entpackte Gesamtgröße.')
        if info.compress_size and info.file_size / max(1, info.compress_size) > max_ratio:
            raise SystemExit(f'Verdächtiges Kompressionsverhältnis bei: {name}')
        destination = (extract_root / name).resolve()
        if extract_root not in destination.parents and destination != extract_root:
            raise SystemExit(f'ZIP-Pfad verlässt das Ziel: {name}')
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with zf.open(info) as src, destination.open('wb') as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        destination.chmod(0o600)

candidates = []
for path in extract_root.rglob('VERSION'):
    root = path.parent
    if (root / 'docker-compose.yml').exists() and (root / 'app').is_dir():
        candidates.append(root)
if len(candidates) != 1:
    raise SystemExit('Im ZIP wurde nicht genau ein gültiger debmirror-manager Projektordner gefunden.')
source_root = candidates[0]

items_to_copy = [
    '.env.example', '.gitignore', '.dockerignore', 'Dockerfile', 'docker-compose.yml', 'requirements.txt', 'requirements.lock', 'requirements-dev.txt', 'pytest.ini',
    'install.sh', 'set-admin-password.sh', 'update.sh', 'README.md', 'README.de.md',
    'RELEASE_NOTES.md', 'RELEASE_NOTES.de.md', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md', 'THIRD-PARTY-NOTICES.md', 'VERSION', 'app', 'nginx', 'tests', 'scripts', '.github'
]
for name in items_to_copy:
    src = source_root / name
    if not src.exists():
        continue
    dst = target_root / name
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)

for script in ['install.sh', 'set-admin-password.sh', 'update.sh']:
    path = target_root / script
    if path.exists():
        path.chmod(0o755)
path = target_root / '.env'
if path.exists():
    path.chmod(0o600)
PYZIP
}

compose_has_containers() {
  local dc="$1"
  # shellcheck disable=SC2086
  $dc ps -q 2>/dev/null | grep -q .
}

compose_has_running_containers() {
  local dc="$1"
  # shellcheck disable=SC2086
  $dc ps --status running -q 2>/dev/null | grep -q .
}

use_nginx_enabled() {
  local value
  value="$(env_value_or_default USE_NGINX_MIRROR_HTTP 1)"
  case "${value,,}" in
    1|true|yes|on|j|ja) return 0 ;;
    *) return 1 ;;
  esac
}

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
    return 0
  fi

  if docker image rm "$legacy_image" >/dev/null 2>&1; then
    log "Nicht mehr verwendetes Alt-Image entfernt: ${legacy_image}"
  else
    log "Hinweis: Alt-Image ${legacy_image} ist noch in Benutzung und wurde nicht entfernt."
  fi
}

build_and_start() {
  local dc="$1"
  if [ "$NO_BUILD" -eq 1 ]; then
    log "--no-build gesetzt: Container werden nicht gebaut/gestartet."
    return
  fi

  if compose_has_running_containers "$dc"; then
    log "Laufende Container gefunden. Sie werden mit --force-recreate ersetzt."
  elif compose_has_containers "$dc"; then
    log "Vorhandene, aber nicht laufende Container gefunden. Sie werden neu erstellt."
  else
    log "Keine bestehenden Container gefunden. Installation wird neu gestartet."
  fi

  if use_nginx_enabled; then
    log "Container werden mit optionalem nginx-Mirror-HTTP gebaut und gestartet..."
    $dc --profile mirror-http up -d --build --remove-orphans --force-recreate
  else
    log "Nur WebUI/Worker wird gebaut und gestartet. Optionaler nginx-Container wird entfernt, falls vorhanden..."
    $dc up -d --build --remove-orphans --force-recreate debmirror-manager
    $dc rm -sf mirror-nginx >/dev/null 2>&1 || true
  fi
  cleanup_legacy_image_name
}

perform_package_update() {
  local zip_file="$1"
  local target_version="$2"
  [ -f "$zip_file" ] || error_exit "Update-ZIP nicht gefunden: $zip_file"

  log "Update-Paket gefunden: $zip_file"
  log "Aktuelle Version: ${PROJECT_VERSION}"
  log "Paket-Version: ${target_version}"
  verify_update_checksum "$zip_file"

  if ! version_gt "$target_version" "$PROJECT_VERSION"; then
    log "Keine neuere Version im Paket. Es wird kein Datei-Update durchgeführt."
    return 1
  fi

  if ! confirm "Update auf v${target_version} ausführen?"; then
    log "Update abgebrochen."
    exit 0
  fi

  create_backups

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"; error_exit "Update wurde unerwartet abgebrochen (Zeile $LINENO)."' ERR

  log "Entpacke Update intern in temporäres Verzeichnis..."
  safe_extract_and_copy_update "$zip_file" "$tmp_dir"
  rm -rf "$tmp_dir"
  trap 'error_exit "Update wurde unerwartet abgebrochen (Zeile $LINENO)."' ERR

  PROJECT_VERSION="$(cat VERSION 2>/dev/null || echo "$target_version")"
  log "Projektdateien wurden auf v${PROJECT_VERSION} aktualisiert."
  merge_env_example

  mkdir -p "${UPDATE_DIR}/installed"
  local installed_zip="${UPDATE_DIR}/installed/$(basename "$zip_file" .zip)-installed-${TS}.zip"
  mv "$zip_file" "$installed_zip"
  if [ -f "${zip_file}.sha256" ]; then
    mv "${zip_file}.sha256" "${installed_zip}.sha256"
  fi
  log "Update-ZIP wurde nach ${UPDATE_DIR}/installed verschoben."
  return 0
}


sync_localized_document_files() {
  local name
  for name in README.de.md RELEASE_NOTES.de.md; do
    if [ ! -f "$name" ] && [ -f "app/docs/$name" ]; then
      cp "app/docs/$name" "$name"
      chmod 600 "$name"
      log "Lokalisierte Dokumentdatei ergänzt: $name"
    fi
  done
  if [ -d app/repository ]; then
    for name in LICENSE SECURITY.md CONTRIBUTING.md THIRD-PARTY-NOTICES.md requirements.lock requirements-dev.txt pytest.ini .gitignore .dockerignore; do
      if [ ! -f "$name" ] && [ -f "app/repository/$name" ]; then
        cp "app/repository/$name" "$name"
        log "Repository-Datei ergänzt: $name"
      fi
    done
    if [ ! -d tests ] && [ -d app/repository/tests ]; then
      cp -a app/repository/tests tests
      log "Automatisierte Tests ergänzt."
    fi
    if [ ! -d scripts ] && [ -d app/repository/scripts ]; then
      cp -a app/repository/scripts scripts
      log "Repository-Prüfskripte ergänzt."
    fi
    if [ ! -d .github ] && [ -d app/repository/.github ]; then
      cp -a app/repository/.github .github
      log "GitHub-Konfiguration ergänzt."
    fi
  fi
}

print_update_notes() {
  cat <<UPDATE_TEXT

$APP_NAME Update
========================
Aktuelle Projektversion: v${PROJECT_VERSION}
Projektordner: $(pwd -P)
Persistente Daten: ${BASE_DATA}
Update-Backups: ${BACKUP_DIR}
Update-Verzeichnis: $(pwd -P)/${UPDATE_DIR}

Neuer Standardablauf:
  1. Neues Release-ZIP und die gleichnamige .sha256-Datei nach ${UPDATE_DIR}/ kopieren
  2. ./update.sh ausführen
  3. update.sh prüft SHA-256 und Version, sichert Daten, ersetzt Projektdateien und baut/startet Container

UPDATE_TEXT
}

main() {
  sync_localized_document_files
  print_update_notes
  need_cmd python3
  need_cmd docker
  local dc
  dc="$(compose_cmd)"

  mkdir -p "$UPDATE_DIR" "$BACKUP_DIR"

  local did_package_update=0
  local should_rebuild=0
  if [ -n "$UPDATE_FILE" ]; then
    target_version="$(read_zip_version "$UPDATE_FILE")" || error_exit "Version aus ZIP konnte nicht gelesen werden: $UPDATE_FILE"
    perform_package_update "$UPDATE_FILE" "$target_version" && did_package_update=1 || true
    should_rebuild=1
  elif [ "$FORCE_REBUILD" -eq 0 ]; then
    newest="$(find_newest_update_zip || true)"
    if [ -n "$newest" ]; then
      zip_file="${newest%%$'\t'*}"
      target_version="${newest#*$'\t'}"
      perform_package_update "$zip_file" "$target_version" && did_package_update=1 || true
      should_rebuild=1
    else
      log "Kein neueres ZIP in ${UPDATE_DIR}/ gefunden."
      if confirm "Trotzdem Backup erstellen und Container neu bauen/starten?"; then
        should_rebuild=1
      else
        should_rebuild=0
      fi
    fi
  else
    should_rebuild=1
  fi

  import_env_if_missing
  merge_env_example

  if [ "$should_rebuild" -eq 1 ]; then
    if [ "$did_package_update" -eq 0 ]; then
      create_backups
    fi
    build_and_start "$dc"
  else
    log "Kein Rebuild angefordert. Projektdateien und Container bleiben unverändert."
  fi

  log "Update-/Wartungsprozess abgeschlossen."
  printf '\nStatus prüfen:\n'
  printf '  %s ps\n' "$dc"
  printf '  %s logs -f debmirror-manager\n' "$dc"
  printf '\nBackup-Verzeichnis:\n  %s\n' "$BACKUP_DIR"
  printf '\nUpdate-Verzeichnis:\n  %s\n' "$(pwd -P)/${UPDATE_DIR}"
}

main "$@"
