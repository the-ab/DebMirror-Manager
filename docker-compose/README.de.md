# DebMirror Manager – Docker-Compose-Installation

Dieser Ordner enthält zwei eigenständige Installationsvarianten für das veröffentlichte Image:

```text
docker-compose/
├── compose.yaml
├── .env.example
├── compose.no-nginx.yaml
├── .env.no-nginx.example
├── README.md
└── README.de.md
```

Beide Varianten verwenden `ghcr.io/the-ab/debmirror-manager:${DMM_IMAGE_TAG:-latest}` und benötigen weder den übrigen Projektordner noch einen lokalen Docker-Build.

## Welche Variante verwenden?

### Mit optionalem nginx-Mirrorserver

Dateien:

```text
compose.yaml
.env.example → .env
```

`compose.yaml` enthält die WebUI und den optionalen nginx-Dienst zur HTTP-Auslieferung der Mirror-Daten. In der Vorlage ist nginx mit `COMPOSE_PROFILES=mirror-http` aktiviert. Für dieselbe Compose-Datei ohne nginx kann dieser Wert leer gesetzt werden.

```bash
cp .env.example .env
chmod 600 .env
nano .env
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d
```

### Nur DebMirror Manager ohne nginx

Dateien:

```text
compose.no-nginx.yaml
.env.no-nginx.example → .env.no-nginx
```

Diese Variante enthält ausschließlich die WebUI und besitzt keine nginx-Variablen oder nginx-Profile.

```bash
cp .env.no-nginx.example .env.no-nginx
chmod 600 .env.no-nginx
nano .env.no-nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml pull
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml up -d
```

## Vor dem ersten Start zwingend prüfen

- `DATA_PATH`: dauerhaftes und beschreibbares Hostverzeichnis für Verwaltungsdaten.
- `MIRROR_PATH`: Hostverzeichnis der Mirror-Daten.
- `WEBUI_BIND_ADDRESS` und `WEBUI_PORT`: gewünschte Erreichbarkeit der WebUI.
- `DMM_IMAGE_TAG`: `latest` oder ein fester Tag wie `v1.0.3`.
- `APP_TIMEZONE`: korrekte IANA-Zeitzone.
- Bei nginx zusätzlich `MIRROR_HTTP_BIND_ADDRESS` und `MIRROR_HTTP_PORT`.
- Bei Migration einer bestehenden Installation `APP_SECRET_KEY` **vor dem ersten Start** übernehmen.

Neue Installationen lassen `APP_SECRET_KEY`, `APP_USERNAME`, `APP_PASSWORD` und `APP_PASSWORD_HASH` leer. Der Container erzeugt den Secret Key dauerhaft unter `DATA_PATH/data/app-secret.key`; der erste Administrator wird anschließend über `http://SERVER-IP:WEBUI_PORT/setup` erstellt.

## Schutz der ENV-Dateien

Echte `.env`-Dateien enthalten lokale Pfade und möglicherweise Geheimnisse. Sie dürfen nicht in Git oder ein öffentliches Repository aufgenommen werden.

```bash
chmod 600 .env
chmod 600 .env.no-nginx
```

Die Projekt-`.gitignore` erlaubt nur die Vorlagen `.env.example` und `.env.no-nginx.example`; echte `.env` und `.env.no-nginx` bleiben ausgeschlossen.

## ENV-Variablen

### Image, Compose und Ports

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `DMM_IMAGE_TAG` | `latest` | empfohlen | Container-Image-Tag. `latest` folgt dem neuesten Release; `v1.0.3` bindet die Installation an diese Version. |
| `COMPOSE_PROFILES` | `mirror-http` | nur Vollvariante | Aktiviert in `compose.yaml` den optionalen nginx-Dienst. Leer lassen, wenn `compose.yaml` ohne nginx gestartet werden soll. In der No-nginx-Variante nicht vorhanden. |
| `WEBUI_BIND_ADDRESS` | `0.0.0.0` | prüfen/anpassen | Host-Adresse, an die der WebUI-Port gebunden wird. Für rein lokalen Zugriff z. B. `127.0.0.1`; für Netzwerkzugriff `0.0.0.0` oder eine konkrete Host-IP. |
| `WEBUI_PORT` | `8111` | prüfen/anpassen | Extern erreichbarer TCP-Port der WebUI. |
| `MIRROR_HTTP_BIND_ADDRESS` | `0.0.0.0` | nur Vollvariante | Bind-Adresse des optionalen nginx-Mirrorservers. Nur `compose.yaml`. |
| `MIRROR_HTTP_PORT` | `8110` | nur Vollvariante | Externer Port des optionalen nginx-Mirrorservers. Nur `compose.yaml`. |

### Persistente Pfade

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `DATA_PATH` | `/docker_data/debmirror-manager` | Pfad prüfen | Persistenter Host-Basispfad für Datenbank, Einstellungen, Logs, Keyrings, Skripte, Secret Key und Backups. Muss beschreibbar und dauerhaft vorhanden sein. |
| `MIRROR_PATH` | `/srv/mirror` | Pfad prüfen | Hostpfad der eigentlichen Mirror-Daten. Wird im Container als `/mirror` eingebunden; nginx bindet denselben Pfad nur lesend ein. |
| `IMPORT_HOST_MIRROR_PATHS` | `/srv/mirror` | prüfen/anpassen | Kommaseparierte alte Host-Basispfade, die beim Skriptimport auf `/mirror` abgebildet werden, z. B. `/srv/mirror,/mnt/linux-mirror`. |

### Ersteinrichtung und Zugang

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `APP_SECRET_KEY` | `leer` | geheim / nur Migration | Bei Neuinstallationen leer lassen: Der Container erzeugt `DATA_PATH/data/app-secret.key` mit Modus `0600`. Nur bei Migration vor dem ersten Start den bisherigen Schlüssel eintragen; mindestens 32 Zeichen. |
| `APP_USERNAME` | `leer` | Legacy / optional | Legacy-Erstzugang. Normalerweise leer lassen und den ersten Administrator über `/setup` erstellen. |
| `APP_PASSWORD` | `leer` | geheim / Legacy | Legacy-Klartextpasswort. Normalerweise leer lassen; niemals veröffentlichen oder committen. |
| `APP_PASSWORD_HASH` | `leer` | geheim / Legacy | Optionaler Legacy-Passworthash anstelle von `APP_PASSWORD`. Normalerweise leer lassen. |

### Sitzung, Reverse Proxy und Sicherheit

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `APP_HTTPS_ONLY` | `0` | Sicherheitswert | `1` setzt sichere Session-Cookies voraus und darf nur verwendet werden, wenn der Zugriff tatsächlich ausschließlich über HTTPS erfolgt. |
| `TRUST_PROXY_HEADERS` | `0` | Sicherheitswert | `1` nur hinter einem korrekt konfigurierten vertrauenswürdigen Reverse Proxy; wertet weitergeleitete Protokoll-/Hostinformationen aus. |
| `TRUSTED_HOSTS` | `leer` | Sicherheitswert | Optional kommaseparierte erlaubte Hostnamen/IPs für Host-Header-Prüfung, z. B. `mirror.example.net,192.0.2.10`. |
| `SESSION_LIFETIME_HOURS` | `12` | optional | Gültigkeitsdauer einer WebUI-Sitzung in Stunden. |
| `MIN_PASSWORD_LENGTH` | `12` | Sicherheitswert | Mindestlänge neuer Passwörter. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Sicherheitswert | Maximale fehlgeschlagene Anmeldeversuche innerhalb des Zeitfensters. |
| `LOGIN_WINDOW_SECONDS` | `900` | Sicherheitswert | Auswertungsfenster der Login-Begrenzung in Sekunden. |
| `LOGIN_LOCK_SECONDS` | `900` | Sicherheitswert | Sperrdauer nach zu vielen Fehlversuchen in Sekunden. |
| `MAX_UPLOAD_BYTES` | `134217728` | optional | Maximale HTTP-Uploadgröße in Byte; Standard 128 MiB. |
| `OUTBOUND_PRIVATE_HOST_ALLOWLIST` | `leer` | Sicherheitswert | Kommaseparierte, bewusst erlaubte private/lokale Ziele für ausgehende Abrufe. Nur exakt benötigte Hosts freigeben. |

### Restore-Schutz

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `RESTORE_MAX_ENTRIES` | `10000` | Sicherheitswert | Maximale Anzahl von Einträgen in einem wiederherzustellenden Archiv. |
| `RESTORE_MAX_UNCOMPRESSED_BYTES` | `536870912` | Sicherheitswert | Maximale gesamte entpackte Restore-Größe in Byte; Standard 512 MiB. |
| `RESTORE_MAX_FILE_BYTES` | `268435456` | Sicherheitswert | Maximale Größe einer einzelnen Restore-Datei in Byte; Standard 256 MiB. |
| `RESTORE_MAX_COMPRESSION_RATIO` | `200` | Sicherheitswert | Maximal zulässiges Verhältnis entpackte/komprimierte Größe zum Schutz vor Kompressionsbomben. |

### Gunicorn

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `WSGI_THREADS` | `8` | Leistung | Parallele Gunicorn-Threads. Die Worker-Anzahl bleibt absichtlich 1; nur bei tatsächlichem Bedarf erhöhen. |
| `WSGI_GRACEFUL_TIMEOUT` | `30` | optional | Zeit in Sekunden für ein kontrolliertes Gunicorn-Herunterfahren. |
| `WSGI_KEEPALIVE` | `5` | optional | HTTP-Keepalive-Zeit in Sekunden. |
| `WSGI_LOG_LEVEL` | `info` | optional | Gunicorn-Loglevel, üblich: `debug`, `info`, `warning`, `error`, `critical`. |
| `WSGI_ACCESS_LOG` | `0` | optional | `1` aktiviert HTTP-Zugriffszeilen im Containerlog; `0` vermeidet besonders bei Live-Logs unnötige Logmenge. |
| `WSGI_LIMIT_REQUEST_LINE` | `4094` | Sicherheitswert | Maximale HTTP-Request-Line-Länge in Byte. |
| `WSGI_LIMIT_REQUEST_FIELDS` | `100` | Sicherheitswert | Maximale Anzahl HTTP-Headerfelder. |
| `WSGI_LIMIT_REQUEST_FIELD_SIZE` | `8190` | Sicherheitswert | Maximale Größe eines einzelnen HTTP-Headers in Byte. |

### Scheduler, Warteschlange und Aufbewahrung

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `SCHEDULER_SCAN_SECONDS` | `60` | optional | Intervall, in dem fällige Zeitpläne geprüft werden. |
| `MAX_PARALLEL_JOBS` | `1` | Leistung | Globale Anzahl gleichzeitig laufender Jobs. Vorsichtig erhöhen, da Mirrors I/O, Netzwerk und Speicher stark belasten. |
| `JOB_RETENTION_DAYS` | `31` | Kompatibilität | Kompatibilitäts-Standardwert älterer Installationen. Die sichtbare Aufbewahrung wird über `LOG_RETENTION_DAYS` bzw. die WebUI verwaltet. |
| `LOG_RETENTION_DAYS` | `31` | prüfen/anpassen | Aufbewahrungsfrist abgeschlossener Job-/Protokolleinträge in Tagen. Datei und Datenbankeintrag werden gemeinsam entfernt. |
| `JOB_LIST_LIMIT` | `100` | optional | Maximale Anzahl geladener Einträge in der vollständigen Jobliste. |
| `DASHBOARD_RECENT_JOBS_LIMIT` | `10` | optional | Anzahl der zuletzt angezeigten Jobs auf dem Dashboard. |
| `DASHBOARD_EVENTS_LIMIT` | `10` | optional | Anzahl der zuletzt angezeigten Ereignisse auf dem Dashboard. |
| `JOB_STOP_GRACE_SECONDS` | `20` | optional | Wartezeit nach Stop-Anforderung, bevor eine Prozessgruppe zwangsweise beendet wird. |

### Mirror-Zeitabgleich

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `MIRROR_TIME_SYNC_WORKERS` | `4` | Leistung | Parallele Anfragen beim HTTP/HTTPS-Zeitabgleich. |
| `MIRROR_TIME_SYNC_TIMEOUT_SECONDS` | `15` | optional | Timeout je Zeitabgleichsanfrage in Sekunden. |
| `MIRROR_TIME_SYNC_RECENT_TOLERANCE_SECONDS` | `5` | optional | Toleranz in Sekunden beim Vergleich sehr neuer Änderungszeiten. |

### Größenberechnung

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `SIZE_CACHE_TTL_SECONDS` | `21600` | optional | Gültigkeitsdauer zwischengespeicherter Größenwerte; Standard 6 Stunden. |
| `SIZE_CALC_TIMEOUT_SECONDS` | `1800` | optional | Maximale Laufzeit einer Größenberechnung; Standard 30 Minuten. |
| `SIZE_CALC_MAX_PARALLEL` | `2` | Leistung | Maximale Anzahl paralleler Größenberechnungen. |
| `AUTO_SIZE_RECALC_ENABLED` | `1` | optional | `1` aktiviert automatische Größenneuberechnung, `0` deaktiviert sie. |
| `AUTO_SIZE_IDLE_MINUTES` | `120` | optional | Automatische Berechnung startet nur, wenn innerhalb dieses Fensters kein geplanter Job fällig ist. |

### Speicherplatz und Zeitzone

| Variable | Standard | Einordnung | Bedeutung |
|---|---:|---|---|
| `STORAGE_GUARD_ENABLED` | `1` | empfohlen | `1` blockiert neue echte Mirror-Jobs bei überschrittenem Grenzwert; Dry-Runs und Benutzerskripte bleiben davon unberührt. |
| `STORAGE_GUARD_THRESHOLD_PERCENT` | `95` | prüfen/anpassen | Grenzwert der Mirror-Speichernutzung in Prozent. |
| `APP_TIMEZONE` | `Europe/Berlin` | prüfen/anpassen | IANA-Zeitzone für WebUI, Zeitpläne und Logs, z. B. `Europe/Berlin`. |

## Betrieb

### Status und Logs

Mit nginx:

```bash
docker compose --env-file .env -f compose.yaml ps
docker compose --env-file .env -f compose.yaml logs -f --tail=200
```

Ohne nginx:

```bash
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml ps
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml logs -f --tail=200
```

### Stoppen und Starten

```bash
# Mit optionalem nginx
docker compose --env-file .env -f compose.yaml stop
docker compose --env-file .env -f compose.yaml start

# Ohne nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml stop
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml start
```

### Aktualisieren

Bei `DMM_IMAGE_TAG=latest`:

```bash
# Mit optionalem nginx
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d

# Ohne nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml pull
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml up -d
```

Bei einem festen Tag zuerst `DMM_IMAGE_TAG` in der verwendeten ENV-Datei auf die neue Version setzen und danach dieselben Befehle ausführen.

### Entfernen der Container

```bash
# Mit optionalem nginx
docker compose --env-file .env -f compose.yaml down

# Ohne nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml down
```

`docker compose down` entfernt die Container und das Compose-Netzwerk, aber nicht die per Hostpfad eingebundenen Daten unter `DATA_PATH` und `MIRROR_PATH`.

## Wechsel zwischen beiden Varianten

Beide Compose-Dateien verwenden denselben Projektnamen und denselben Container `debmirror-manager`. Sie dürfen daher nicht parallel gestartet werden. Vor dem Wechsel die aktive Variante mit `down` beenden und anschließend die andere Variante starten. Werden dieselben `DATA_PATH`- und `MIRROR_PATH`-Werte verwendet, bleiben Daten und Mirror-Inhalte erhalten.
