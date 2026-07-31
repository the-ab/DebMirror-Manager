# DebMirror Manager – Docker Compose installation

This directory contains two standalone installation variants for the published image:

```text
docker-compose/
├── compose.yaml
├── .env.example
├── compose.no-nginx.yaml
├── .env.no-nginx.example
├── README.md
└── README.de.md
```

Both variants use `ghcr.io/the-ab/debmirror-manager:${DMM_IMAGE_TAG:-latest}` and require neither the rest of the project directory nor a local Docker build.

## Which variant should be used?

### With optional nginx mirror server

Files:

```text
compose.yaml
.env.example → .env
```

`compose.yaml` contains the WebUI and the optional nginx service used to serve mirror data over HTTP. The template enables nginx through `COMPOSE_PROFILES=mirror-http`. Leave that value empty to use the same Compose file without nginx.

```bash
cp .env.example .env
chmod 600 .env
nano .env
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d
```

### DebMirror Manager only, without nginx

Files:

```text
compose.no-nginx.yaml
.env.no-nginx.example → .env.no-nginx
```

This variant contains only the WebUI and has no nginx variables or nginx profile.

```bash
cp .env.no-nginx.example .env.no-nginx
chmod 600 .env.no-nginx
nano .env.no-nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml pull
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml up -d
```

## Values that must be reviewed before first start

- `DATA_PATH`: persistent writable host directory for management data.
- `MIRROR_PATH`: host directory containing the mirror data.
- `WEBUI_BIND_ADDRESS` and `WEBUI_PORT`: required WebUI reachability.
- `DMM_IMAGE_TAG`: `latest` or a pinned tag such as `v1.0.3`.
- `APP_TIMEZONE`: correct IANA time zone.
- With nginx, also review `MIRROR_HTTP_BIND_ADDRESS` and `MIRROR_HTTP_PORT`.
- When migrating an existing installation, copy `APP_SECRET_KEY` **before the first start**.

Fresh installations leave `APP_SECRET_KEY`, `APP_USERNAME`, `APP_PASSWORD`, and `APP_PASSWORD_HASH` empty. The container persistently creates the secret key under `DATA_PATH/data/app-secret.key`; create the first administrator afterwards at `http://SERVER-IP:WEBUI_PORT/setup`.

## Protecting ENV files

Real `.env` files contain local paths and may contain secrets. Never add them to Git or a public repository.

```bash
chmod 600 .env
chmod 600 .env.no-nginx
```

The project `.gitignore` permits only the `.env.example` and `.env.no-nginx.example` templates; real `.env` and `.env.no-nginx` files remain ignored.

## ENV variables

### Image, Compose, and ports

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `DMM_IMAGE_TAG` | `latest` | recommended | Container image tag. `latest` follows the newest release; `v1.0.3` pins the installation to this release. |
| `COMPOSE_PROFILES` | `mirror-http` | full variant only | Enables the optional nginx service in `compose.yaml`. Leave empty to run `compose.yaml` without nginx. Not present in the no-nginx variant. |
| `WEBUI_BIND_ADDRESS` | `0.0.0.0` | review/change | Host address used to bind the WebUI port. Use `127.0.0.1` for local-only access, or `0.0.0.0` / a specific host IP for network access. |
| `WEBUI_PORT` | `8111` | review/change | Externally reachable TCP port for the WebUI. |
| `MIRROR_HTTP_BIND_ADDRESS` | `0.0.0.0` | full variant only | Bind address of the optional nginx mirror server. `compose.yaml` only. |
| `MIRROR_HTTP_PORT` | `8110` | full variant only | External port of the optional nginx mirror server. `compose.yaml` only. |

### Persistent paths

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `DATA_PATH` | `/docker_data/debmirror-manager` | review path | Persistent host base path for database, settings, logs, keyrings, scripts, secret key, and backups. Must be writable and persistent. |
| `MIRROR_PATH` | `/srv/mirror` | review path | Host path containing the mirror data. Mounted as `/mirror` in the application container; nginx mounts the same path read-only. |
| `IMPORT_HOST_MIRROR_PATHS` | `/srv/mirror` | review/change | Comma-separated legacy host base paths mapped to `/mirror` during script import, for example `/srv/mirror,/mnt/linux-mirror`. |

### Initial setup and account

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `APP_SECRET_KEY` | `leer` | secret / migration only | Leave empty for fresh installations: the container creates `DATA_PATH/data/app-secret.key` with mode `0600`. For migration only, enter the previous key before the first start; minimum 32 characters. |
| `APP_USERNAME` | `leer` | legacy / optional | Legacy initial account value. Normally leave empty and create the first administrator through `/setup`. |
| `APP_PASSWORD` | `leer` | secret / legacy | Legacy plaintext password. Normally leave empty; never publish or commit it. |
| `APP_PASSWORD_HASH` | `leer` | secret / legacy | Optional legacy password hash instead of `APP_PASSWORD`. Normally leave empty. |

### Session, reverse proxy, and security

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `APP_HTTPS_ONLY` | `0` | security control | `1` requires secure session cookies and must only be used when access is exclusively through HTTPS. |
| `TRUST_PROXY_HEADERS` | `0` | security control | Set to `1` only behind a correctly configured trusted reverse proxy; honors forwarded protocol/host information. |
| `TRUSTED_HOSTS` | `leer` | security control | Optional comma-separated allowed host names/IPs for Host-header validation, e.g. `mirror.example.net,192.0.2.10`. |
| `SESSION_LIFETIME_HOURS` | `12` | optional | WebUI session lifetime in hours. |
| `MIN_PASSWORD_LENGTH` | `12` | security control | Minimum length for new passwords. |
| `LOGIN_MAX_ATTEMPTS` | `5` | security control | Maximum failed login attempts within the configured window. |
| `LOGIN_WINDOW_SECONDS` | `900` | security control | Login-rate-limit evaluation window in seconds. |
| `LOGIN_LOCK_SECONDS` | `900` | security control | Lock duration after too many failed attempts, in seconds. |
| `MAX_UPLOAD_BYTES` | `134217728` | optional | Maximum HTTP upload size in bytes; default 128 MiB. |
| `OUTBOUND_PRIVATE_HOST_ALLOWLIST` | `leer` | security control | Comma-separated private/local destinations explicitly allowed for outbound fetches. Allow only the exact hosts required. |

### Restore protection

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `RESTORE_MAX_ENTRIES` | `10000` | security control | Maximum number of entries in a restore archive. |
| `RESTORE_MAX_UNCOMPRESSED_BYTES` | `536870912` | security control | Maximum total uncompressed restore size in bytes; default 512 MiB. |
| `RESTORE_MAX_FILE_BYTES` | `268435456` | security control | Maximum size of one restored file in bytes; default 256 MiB. |
| `RESTORE_MAX_COMPRESSION_RATIO` | `200` | security control | Maximum allowed uncompressed/compressed ratio to protect against compression bombs. |

### Gunicorn

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `WSGI_THREADS` | `8` | performance | Parallel Gunicorn threads. Worker count intentionally remains 1; increase only when necessary. |
| `WSGI_GRACEFUL_TIMEOUT` | `30` | optional | Seconds allowed for graceful Gunicorn shutdown. |
| `WSGI_KEEPALIVE` | `5` | optional | HTTP keep-alive duration in seconds. |
| `WSGI_LOG_LEVEL` | `info` | optional | Gunicorn log level, commonly `debug`, `info`, `warning`, `error`, or `critical`. |
| `WSGI_ACCESS_LOG` | `0` | optional | `1` enables HTTP access lines in container logs; `0` avoids unnecessary volume, especially from live logs. |
| `WSGI_LIMIT_REQUEST_LINE` | `4094` | security control | Maximum HTTP request-line length in bytes. |
| `WSGI_LIMIT_REQUEST_FIELDS` | `100` | security control | Maximum number of HTTP header fields. |
| `WSGI_LIMIT_REQUEST_FIELD_SIZE` | `8190` | security control | Maximum size of one HTTP header field in bytes. |

### Scheduler, queue, and retention

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `SCHEDULER_SCAN_SECONDS` | `60` | optional | Interval used to scan for due schedules. |
| `MAX_PARALLEL_JOBS` | `1` | performance | Global number of concurrently running jobs. Increase cautiously because mirrors heavily use I/O, network, and storage. |
| `JOB_RETENTION_DAYS` | `31` | compatibility | Compatibility default for older installations. Visible retention is managed through `LOG_RETENTION_DAYS` or the WebUI. |
| `LOG_RETENTION_DAYS` | `31` | review/change | Retention period for completed job/log entries in days. Log file and database row are removed together. |
| `JOB_LIST_LIMIT` | `100` | optional | Maximum number of entries loaded in the full job list. |
| `DASHBOARD_RECENT_JOBS_LIMIT` | `10` | optional | Number of recent jobs shown on the dashboard. |
| `DASHBOARD_EVENTS_LIMIT` | `10` | optional | Number of recent events shown on the dashboard. |
| `JOB_STOP_GRACE_SECONDS` | `20` | optional | Delay after a stop request before a process group is force-killed. |

### Mirror timestamp synchronization

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `MIRROR_TIME_SYNC_WORKERS` | `4` | performance | Parallel requests used for HTTP/HTTPS timestamp synchronization. |
| `MIRROR_TIME_SYNC_TIMEOUT_SECONDS` | `15` | optional | Timeout per timestamp synchronization request, in seconds. |
| `MIRROR_TIME_SYNC_RECENT_TOLERANCE_SECONDS` | `5` | optional | Tolerance in seconds when comparing very recent modification times. |

### Size calculation

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `SIZE_CACHE_TTL_SECONDS` | `21600` | optional | Lifetime of cached size values; default 6 hours. |
| `SIZE_CALC_TIMEOUT_SECONDS` | `1800` | optional | Maximum duration of a size calculation; default 30 minutes. |
| `SIZE_CALC_MAX_PARALLEL` | `2` | performance | Maximum number of concurrent size calculations. |
| `AUTO_SIZE_RECALC_ENABLED` | `1` | optional | `1` enables automatic size recalculation; `0` disables it. |
| `AUTO_SIZE_IDLE_MINUTES` | `120` | optional | Automatic calculation starts only when no scheduled job is due within this window. |

### Storage and time zone

| Variable | Default | Classification | Purpose |
|---|---:|---|---|
| `STORAGE_GUARD_ENABLED` | `1` | recommended | `1` blocks new real mirror jobs when the threshold is exceeded; dry-runs and user scripts remain unaffected. |
| `STORAGE_GUARD_THRESHOLD_PERCENT` | `95` | review/change | Mirror storage usage threshold in percent. |
| `APP_TIMEZONE` | `Europe/Berlin` | review/change | IANA time zone used by the WebUI, schedules, and logs, e.g. `Europe/Berlin`. |

## Operation

### Status and logs

With nginx:

```bash
docker compose --env-file .env -f compose.yaml ps
docker compose --env-file .env -f compose.yaml logs -f --tail=200
```

Without nginx:

```bash
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml ps
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml logs -f --tail=200
```

### Stop and start

```bash
# With optional nginx
docker compose --env-file .env -f compose.yaml stop
docker compose --env-file .env -f compose.yaml start

# Without nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml stop
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml start
```

### Update

With `DMM_IMAGE_TAG=latest`:

```bash
# With optional nginx
docker compose --env-file .env -f compose.yaml pull
docker compose --env-file .env -f compose.yaml up -d

# Without nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml pull
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml up -d
```

For a pinned tag, first change `DMM_IMAGE_TAG` in the selected ENV file to the new version, then run the same commands.

### Remove the containers

```bash
# With optional nginx
docker compose --env-file .env -f compose.yaml down

# Without nginx
docker compose --env-file .env.no-nginx -f compose.no-nginx.yaml down
```

`docker compose down` removes the containers and Compose network, but not bind-mounted data below `DATA_PATH` and `MIRROR_PATH`.

## Switching between variants

Both Compose files use the same project name and the same `debmirror-manager` container. They must not run in parallel. Stop the active variant with `down` before starting the other variant. Data and mirror contents remain available when both variants use the same `DATA_PATH` and `MIRROR_PATH` values.
