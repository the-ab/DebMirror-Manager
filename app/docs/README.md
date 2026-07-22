# DebMirror Manager

DebMirror Manager is a Docker-based web interface for managing local APT repository mirrors. It focuses on `debmirror`, while custom `lftp`, `rsync`, vendor synchronization, and maintenance scripts can also be uploaded, scheduled, executed, and monitored as controlled jobs.

Current version: **0.1.86**

## Project status, affiliation, and licensing

DebMirror Manager is an **independent third-party community project**. It is not affiliated with, endorsed by, or maintained by the Debian Project or the maintainers of `debmirror`. Debian and other product names are trademarks of their respective owners.

The project source is licensed under the **Apache License 2.0** (`Apache-2.0`). See `LICENSE`. Third-party components retain their own licenses; see `THIRD-PARTY-NOTICES.md`.

Portions of this project were developed with assistance from OpenAI ChatGPT. All generated code was reviewed, adapted, and tested by the project maintainer, who assumes responsibility for the published software.

Repository policies and development information are available in `SECURITY.md` and `CONTRIBUTING.md`. The WebUI does not create or publish a local source archive and does not expose project or runtime files through a source-download route.

## Core concept

- Mirror profiles generate validated `debmirror` commands.
- User scripts can only be started from a dedicated managed directory.
- Mirror and script jobs share one queue, log system, live output, and history.
- Configuration is stored in SQLite and `settings.json`.
- Large directories are measured asynchronously and cached instead of being scanned during every page request.
- GPG keys are managed centrally in a master keyring; cleaned profile keyrings are generated for individual mirror profiles.
- Every user has independent language and appearance preferences.

## Default paths

```text
updates/                                      update ZIP files in the project directory
backup/                                       backups created by update.sh
/docker_data/debmirror-manager/data           SQLite database, settings.json, encryption key, SSH data
/docker_data/debmirror-manager/logs           WebUI and job logs
/docker_data/debmirror-manager/keyrings       master, archive, key-server, and profile keyrings
/docker_data/debmirror-manager/import-scripts scripts available to the import assistant
/docker_data/debmirror-manager/user-scripts   managed custom scripts
/docker_data/debmirror-manager/backup         encrypted WebUI full backups
/srv/mirror or /mnt/linux-mirror              local repository and mirror data
```

The selected host mirror directory is mounted as `/mirror` inside the application container. Profile targets and script size targets must therefore be below `/mirror`, for example `/mirror/debian` or `/mirror/ubuntu`.

## Installation

```bash
unzip debmirror-manager-v0.1.86.zip
cd debmirror-manager
chmod +x install.sh update.sh set-admin-password.sh
./install.sh
```

`install.sh` asks for the persistent data directory, local mirror directory, WebUI port, optional nginx mirror HTTP service, update and backup directories, job queue settings, retention, dashboard limits, size calculation, storage guard, time zone, and initial administrator credentials. On later runs it reads the existing `.env` file and proposes the current values as defaults.

### Container operating system

The application image uses the Docker Official Image `python:3.13.14-slim-trixie` and therefore Debian 13 (Trixie) as its operating-system base. The image is pinned to a multi-platform digest. During each image build, available Trixie package updates are installed before `debmirror`, GnuPG, Rsync, OpenSSH, ping and the other runtime packages are added. The optional mirror web server remains a separate nginx Alpine container.

### Web server and container logs

The WebUI runs through **Gunicorn**, not the Flask/Werkzeug development server. DebMirror Manager deliberately uses exactly **one Gunicorn worker** with multiple threads because the scheduler, queue, and active process registry live inside the application process. Do not configure multiple workers.

Common WSGI settings:

```text
WSGI_THREADS=8
WSGI_ACCESS_LOG=0
WSGI_LOG_LEVEL=info
```

HTTP access lines are disabled by default so frequent live-log requests do not flood the container log. Set `WSGI_ACCESS_LOG=1` when access logging is needed.

Live logs use Server-Sent Events. Heartbeats keep quiet, long-running jobs connected. Leaving or reloading a job page is treated as a normal client disconnect and does not create a traceback.

The locally built image has the fixed name `debmirror-manager:latest`. The former Compose-generated image name `debmirror-manager-debmirror-manager:latest` is no longer created and is removed by maintenance scripts when it is unused.

## Updating

Copy both the release ZIP and its trusted SHA-256 sidecar file into `updates/`:

```bash
cd debmirror-manager
cp /path/to/debmirror-manager-vNEW.zip updates/
cp /path/to/debmirror-manager-vNEW.zip.sha256 updates/
./update.sh
```

`update.sh` verifies the checksum and package structure, creates a backup, replaces project files, merges missing `.env` entries, rebuilds the image, and restarts the containers. Update archives are checked for path traversal, special files, excessive entry counts, excessive extracted size, and suspicious compression ratios.

A rebuild without a newer release can be forced with:

```bash
./update.sh --rebuild
```

## Language and appearance

The WebUI supports **German** and **English**. Language and appearance are stored on the individual user account and do not change settings for other users.

Open the user name in the top bar to access **Personal settings**. Each user can select:

- German or English
- light mode
- dark mode
- automatic mode based on the browser or operating system

The theme toggle in the top bar updates only the current user's account. Administrators can also choose initial language and appearance when creating or editing another user.

The documentation follows the selected language:

```text
README.md              English documentation and default project file
README.de.md           German documentation
RELEASE_NOTES.md       English release notes and default project file
RELEASE_NOTES.de.md    German release notes
```

## Navigation

The main navigation is divided into these areas:

- **Overview**: dashboard, storage, queue, status, recent jobs, events, and health checks.
- **Mirror**: profiles, profile generator, user scripts, script import, and keyrings.
- **Operations**: jobs/logs, schedules, health checks, and notifications.
- **System**: system settings, generator settings, backup/restore, configuration export/import, user management, and API tokens.
- **Help**: documentation and release notes in the current user's language.

## Dashboard

The dashboard shows storage usage, queue state, mirror profiles, user scripts, recent jobs, events, and health checks.

Important behavior:

- Profile and script rows show type, state, size, schedule, last job, and available actions.
- The complete last-job entry is clickable and opens the matching job and log page.
- Name, status, type, and size columns can be sorted in either direction.
- Size sorting uses raw byte values rather than formatted KiB/GiB/TiB text.
- Administrators see a refresh button next to every configured mirror or script target size.
- **Refresh all** processes every existing configured target directory, removes duplicate paths, skips missing paths, and uses the background size queue.
- Dashboard blocks can be repositioned and resized. The saved layout applies across browsers.

Size states are shown consistently:

```text
current                     no real job has finished for the target since the last check
stale                       a real job finished after the last completed size check
updating                    a new calculation is running; the previous value remains visible
queued / scheduled          waiting for calculation capacity or the configured idle window
not calculated              no completed size check exists
error / timeout             the latest calculation failed
last check                  timestamp of the last completed size calculation
```

A cache entry does not become stale merely because it is old. `stale` is set only when a non-dry-run mirror or user-script job actually started and finished after the last size check.

Common dashboard status values:

```text
idle       no active or queued job
active #ID a job is running; the ID opens its details
queue #ID  a job is waiting; the ID opens its details
no key     a mirror profile has no generated or assigned profile keyring
inactive   profile or script is disabled
error      start is blocked by invalid or missing requirements
```

## Mirror profiles

Mirror profiles contain the validated values required for a `debmirror` run:

- method: `rsync`, `http`, `https`, or `ftp`
- host and repository root path
- distributions/suites
- sections/components
- architectures
- target directory below `/mirror`
- optional source packages
- controlled additional debmirror options
- validated expert field for unsupported additional options
- optional HTTP/HTTPS Basic Auth or FTP credentials
- optional SSH-key transport for appropriately configured rsync modules
- rsync extras: `doc`, `indices`, `tools`, `trace`, or `none`
- include and exclude patterns
- GPG and keyring assignment
- optional profile schedule
- enabled state

Disabled profiles cannot be started normally through the WebUI, schedules, or API. Dry runs remain available for diagnostics.

### Option validation

The form prevents contradictory or unsafe combinations. Examples include:

- FTP passive mode only with FTP
- TLS verification exceptions only with HTTPS
- rsync package options only with rsync as the main method
- gzip options only with diff processing enabled
- `--slow-cpu` only with the compatible diff mode
- mutually exclusive cleanup and GPG modes
- duplicate options rejected
- shell metacharacters rejected from manual options
- credentials and SSH settings restricted to matching transfer methods
- host, port, module path, and schedule fields validated independently

Passwords are encrypted in SQLite, never returned to forms or APIs, and are not written to job command displays or logs.

### HTTP/HTTPS timestamps and mirror timestamp sync

After a successful non-dry-run HTTP or HTTPS mirror job, DebMirror Manager attempts to apply the upstream `Last-Modified` timestamp to files created or changed during that specific run. The automatic pass only scans files whose local modification time changed since the job started, so it does not perform a complete additional traversal of an existing mirror.

Each file is checked with HTTP `HEAD` first. If the upstream server does not support or blocks `HEAD`, or if the header is absent, one minimal `GET` request with `Range: bytes=0-0` is attempted. A valid `Last-Modified` value changes only the local modification time. File contents, signatures, ownership, and permissions are not changed. Missing or invalid headers, HTTP errors, and individual network failures are logged and skipped and never turn an otherwise successful mirror job into an error.

Directories are included as well. If the directory URL ending in `/` exposes a valid `Last-Modified` header, that timestamp is used directly. Otherwise the directory may inherit the newest timestamp of a directly contained file or directory that was successfully synchronized. If neither source is available, the existing directory timestamp remains unchanged.

A full one-time pass for existing content is available under **Profiles → Actions → Mirror timestamp sync** and on the profile detail page. It runs as a separate queued job with a live log and stop support and is available only for HTTP and HTTPS profiles. A full pass over a large mirror can generate many HTTP requests; concurrency and request timeout can be limited with `MIRROR_TIME_SYNC_WORKERS` and `MIRROR_TIME_SYNC_TIMEOUT_SECONDS`.

## Profile generator

The profile generator can analyze HTTP, HTTPS, FTP, and `rsync://` repositories, detect repository bases, suites, components, and architectures, and prepare a normal mirror profile.

The credentials section is collapsed by default. HTTP/HTTPS and FTP credentials are kept separate from rsync SSH-key settings. Conflicting combinations are disabled in the form and rejected again by the backend.

For rsync repositories the generator reads `dists/` plus `InRelease` or `Release` metadata and also recognizes suite aliases such as `stable`.

The search path variables and generator JSON are configured under **System → Generator settings**. Built-in search paths are always visible as plain text.

## User scripts

Administrators can upload executable scripts into the managed user-script directory. Scripts can be enabled or disabled, started manually, assigned to schedules, and monitored with the same queue and log system as mirror jobs.

An optional target directory can be assigned for size tracking. The script list and dashboard then show the cached size, current/stale state, last check, and a refresh button.

The WebUI executes only files from the configured user-script directory. Uploaded scripts are still trusted administrator code and run inside the application container; review them before execution.

## Script import

The import assistant analyzes existing debmirror shell scripts, extracts supported values, shows a preview, and prepares a normal mirror profile. Host mirror paths can be mapped to the container path `/mirror` through `IMPORT_HOST_MIRROR_PATHS`.

Unsafe or ambiguous values are not silently accepted. Review the generated profile before saving it.

## Keyring management

### Master keyring

The master keyring combines archived upload sources and key-server sources. The compact summary shows primary keys, subkeys, fingerprints, source files, file size, exclusions, and warnings. Detailed paths and fingerprints are available in expandable sections.

### Import

Keys can be added from an uploaded file, a validated public URL, or a key server. Trust assignments require full 40-character OpenPGP fingerprints. Short key IDs are not accepted as trust anchors.

Verify a fingerprint against the repository owner's official documentation before assigning it.

### Profile keyrings

A profile keyring is generated from only the fingerprints assigned to a mirror profile. Rebuilding the master keyring does not silently broaden profile trust.

### Missing-key diagnosis

Job diagnosis recognizes common GPG errors such as `NO_PUBKEY`, `ERRSIG`, `EXPKEYSIG`, `REVKEYSIG`, and `BADSIG`. Matching master and archive keys can be selected and applied together before the profile keyring is rebuilt.

## Client export

A mirror profile can generate a client ZIP containing:

- a profile-specific keyring
- a Deb822 `.sources` file
- a classic `.list` file
- client installation instructions

Suites and architectures can be selected before export. The client base URL must point to the published local mirror rather than the upstream repository.

## Jobs and logs

Jobs show source, status, start/end time, runtime, exit code, command summary, diagnostics, and complete logs. Active jobs provide live output through SSE.

Stopping a job sends a controlled termination signal and releases queue state and repository locks after completion. Jobs ending with warnings retain their exit code and expose relevant diagnostics instead of being presented as unexplained failures.

## Schedules

Schedules can start mirror profiles, individual user scripts, multiple scripts, or configured selections. They can be enabled or disabled independently and support daily times, weekdays, intervals, and dry runs.

Profile schedules are visible in the central schedule list. Removing a profile schedule returns that profile to manual operation.

## Size calculation

Size calculation runs independently from page rendering. Configurable values include:

```text
SIZE_CACHE_TTL_SECONDS=21600
SIZE_CALC_TIMEOUT_SECONDS=1800
SIZE_CALC_MAX_PARALLEL=2
AUTO_SIZE_RECALC_ENABLED=1
AUTO_SIZE_IDLE_MINUTES=120
```

The TTL controls when automatic recalculation may be useful. It does not by itself mark a value stale.

## Storage guard

The storage guard blocks real mirror jobs when the mirror base exceeds the configured threshold:

```text
STORAGE_GUARD_ENABLED=1
STORAGE_GUARD_THRESHOLD_PERCENT=95
```

Dry runs and user scripts are not blocked. Queued mirror jobs resume only after storage usage falls below the threshold.

## Health checks

Health checks support HTTP/HTTPS GET or HEAD requests as well as ICMP ping checks. HTTP checks record the expected status and latency; ping checks accept a hostname or IP address and record reachability and round-trip latency. Private or local targets must be explicitly allowed per health check. Ping uses the container-installed `iputils-ping` utility with only the `NET_RAW` Linux capability. Scheduling, manual execution, notifications, and API execution work for both check types. Other outbound import and webhook functions block local, private, link-local, reserved, and metadata-network destinations unless narrowly allowlisted.

## Notifications

SMTP email, Telegram, and Discord can be configured under **Operations → Notifications**. Secret values are never returned to the form. Empty secret fields retain the stored value; a new value replaces it.

Secrets and mirror-profile passwords are encrypted with the persistent key `/app/data/notification-secrets.key`, which is included in encrypted full backups and restored before the database and settings.

## System settings

System settings control queue concurrency, job and log retention, list limits, time zone, size calculation, automatic size refresh, storage guard, and dependency checks.

Language and appearance are not global system settings. They are stored per user under **Personal settings**.

## Generator settings

The page has two separate responsive cards:

- **Search path variables**: one validated relative path per line, with built-in defaults always visible.
- **Generator configuration**: validated JSON for predefined distribution groups using `label`, `method`, `host`, `root_path`, `releases`, `components`, and `archs`.

A validation error in one card does not alter the other card.

## Backup and restore

New full backups use the `.dmmbackup` format with AES-256-GCM encryption. The backup password must contain at least twelve characters, is never stored, and is required again during restore.

A full backup includes:

- SQLite database
- `settings.json`
- persistent secret encryption key
- keyrings and key sources
- import and user scripts
- managed SSH private keys and `known_hosts`
- saved permissions metadata

Mirror content below `/mirror` is intentionally excluded.

Legacy unencrypted ZIP backups remain readable for migration and are clearly marked. Restore limits the number of entries, individual and total extracted size, and compression ratio; path traversal, symbolic links, and special files are rejected. Restoring users or API tokens ends the current session for security reasons.

## Configuration export and import

The normal JSON export includes mirror profiles, health checks, schedules, generator configuration, and non-sensitive settings. It excludes users, password hashes, API token values, notification secrets, remote passwords, and private-key contents.

A full encrypted backup should be used for complete server migration.

## User management

Roles:

```text
admin  full administration and job control
user   read-only access
```

Administrators can create and edit users, choose each user's language and appearance, change roles, enable or disable accounts, and reset their own credentials. The final active administrator cannot be deleted, disabled, or demoted.

Sessions are bound to the exact user ID, user name, enabled state, and server-side session version. Password, role, state, and user-name changes revoke existing sessions immediately.

## API

API tokens are displayed only once and stored as hashes. New tokens support an expiration date and independent scopes:

- read
- start mirror jobs
- start user scripts
- stop jobs
- run health checks

Existing pre-0.1.78 tokens remain available as clearly marked broad-permission legacy tokens and should be replaced with minimum-scope tokens.

Endpoints:

```text
GET  /api/v1/status
GET  /api/v1/mirrors
GET  /api/v1/mirrors/<id>
POST /api/v1/mirrors/<id>/run
GET  /api/v1/jobs
GET  /api/v1/jobs/<id>
POST /api/v1/jobs/<id>/stop
GET  /api/v1/user-scripts
POST /api/v1/user-scripts/<name>/run
GET  /api/v1/schedules
GET  /api/v1/healthchecks
POST /api/v1/healthchecks/<id>/run
```

Write operations enforce the same enabled-state, storage, conflict, and start restrictions as the WebUI. Encrypted passwords and private SSH-key contents are never returned.

## Security model

- Initial setup closes permanently after the first user is created.
- All state-changing WebUI requests use CSRF tokens.
- Login attempts are limited by user and source IP.
- Sessions expire and are revocable through account changes.
- Passwords use modern hashes; API tokens are stored only as hashes.
- Secrets and remote passwords are encrypted at rest.
- New full backups are password-encrypted.
- Update packages require a trusted SHA-256 checksum.
- Full OpenPGP fingerprints are required for trust assignments.
- New SSH host keys are not accepted automatically by default.
- Management files and directories use restrictive owner permissions and `umask 077`.
- Mirror jobs and user scripts whose configured target is below `MIRROR_BASE` use a separate `umask 022`, so repository files are created readable by the optional nginx service (`0644` files, `0755` directories). Other user scripts retain `umask 077`. The complete existing `MIRROR_BASE` tree is repaired once after upgrading to v0.1.82; paths outside it are not changed.
- The container uses `no-new-privileges`, reduced Linux capabilities, an init process, and a PID limit.
- The Docker socket is not mounted and privileged mode is not used.

Direct HTTP operation is technically possible in an isolated management network but sends credentials and cookies without transport encryption. Production deployments should use an HTTPS reverse proxy and restrict the WebUI port with a firewall. Configure `APP_HTTPS_ONLY`, `TRUST_PROXY_HEADERS`, and `TRUSTED_HOSTS` consistently with the proxy setup.

## Emergency administrator password reset

```bash
cd debmirror-manager
./set-admin-password.sh
```

The script updates the administrator account directly in the SQLite user database.

## Documentation files

The WebUI opens `README.md` and `RELEASE_NOTES.md` for English users and `README.de.md` and `RELEASE_NOTES.de.md` for German users. If a localized file is missing, the English default file is used.

## Public repository and pinned dependencies

The repository contains `.gitignore` and `.dockerignore` rules that exclude local configuration, databases, logs, backups, update archives, virtual environments, and other generated data. Do not initialize or publish a repository from a production installation directory.

Production Python dependencies are resolved in `requirements.lock` with exact versions and package hashes. The Docker build installs this lock file with `--require-hashes`. Base images are pinned by version and digest. Debian packages inside the image continue to come from the signed distribution repositories and are therefore not claimed to be bit-for-bit reproducible.

Tests, repository audits, dependency checks, shell validation, Compose validation, and Docker builds are run manually using the local commands documented in `CONTRIBUTING.md`.


Every Web UI page footer displays the installed version, release date, and project license.
