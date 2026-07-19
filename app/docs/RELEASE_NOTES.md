# Release Notes

## v0.1.79

- Added per-user language selection for German and English.
- Language is stored on each SQLite user record; existing users are migrated safely with German as their default language.
- Added per-user appearance settings for light, dark, and automatic browser/system mode.
- Removed the global appearance preference from system settings. Existing users inherit the previously configured appearance during migration.
- Added a **Personal settings** page available to every authenticated user.
- Enabled the top-bar theme toggle for administrators and read-only users; it changes only the current account.
- Extended user management with individual language and appearance fields when creating or editing users.
- Added language selection to the login page and initial setup. Initial setup stores language and appearance on the first administrator account.
- Localized WebUI navigation, forms, status labels, and flash messages for English. Technical API values, paths, commands, and job logs remain unchanged.
- Documentation pages automatically select the file matching the user's language.
- `README.md` and `RELEASE_NOTES.md` are now the default English files.
- Added `README.de.md` and `RELEASE_NOTES.de.md` for the German versions.
- Extended Docker builds, update validation, and update backups to include both German documentation files.
- Set VERSION to 0.1.79.

## v0.1.78

- Closed the critical initial-setup issue: `/setup` cannot be reopened after the first account is created, regardless of URL parameters.
- Closed the critical session fallback issue. Sessions are bound to the exact user ID, enabled state, user name, and server-side session version; deleted or disabled users never fall back to an administrator.
- Account, role, password, and enabled-state changes revoke existing sessions immediately. The final active administrator is protected against deletion, disabling, and demotion.
- Added CSRF protection to all state-changing WebUI forms and internal JavaScript POST requests.
- Added login rate limiting by account and source IP, temporary lockouts, security events, and a twelve-character minimum password length.
- Blocked open redirects after login and setup.
- Added API token scopes, expiration, last-use time, and source IP. New tokens start with minimum permissions; older tokens remain as clearly marked legacy tokens.
- Added encrypted `.dmmbackup` full backups using AES-256-GCM and Scrypt-derived keys. Backup passwords are never stored.
- Hardened restore against path traversal, ZIP bombs, symbolic links, special files, and excessive entry or extracted sizes. API-token restore is opt-in.
- Added SSRF protection to profile scans, key URL imports, Discord webhooks, and health checks. Private targets require explicit permission where supported.
- Added secure cookies, session expiry, HTTP security headers, optional trusted proxy/host configuration, and HTTPS-only operation.
- Hardened permissions for `.env`, SQLite, settings, keys, logs, backups, and script directories.
- Added mandatory SHA-256 verification and safe extraction limits to the update process.
- Required full 40-character OpenPGP fingerprints for trust assignments and added safe migration of older short IDs.
- Disabled automatic acceptance of new SSH host keys for new profiles by default.
- Hardened the container with `no-new-privileges`, reduced capabilities, an init process, a PID limit, and Gunicorn request-header limits.
- Updated Flask, Werkzeug, and cryptography dependencies.
- Set VERSION to 0.1.78.

## v0.1.77

- Fixed the v0.1.76 update compatibility issue by moving `gunicorn.conf.py` into `app/`, which older update scripts already copy.
- Updated the Dockerfile to load `/app/app/gunicorn.conf.py`.
- Supported updates directly from v0.1.75 and recovery from the partially updated v0.1.76 state.
- Set the explicit image name `debmirror-manager:latest`, preventing the duplicated Compose image name.
- Added cleanup guidance and maintenance handling for the former duplicate image.
- Set VERSION to 0.1.77.

## v0.1.76

- Replaced the Flask/Werkzeug development server with the production Gunicorn WSGI server.
- Configured one worker with multiple threads so the scheduler, queue, and process registry are not duplicated.
- Added SSE heartbeats and long-running live-log support without worker timeouts.
- Disabled HTTP access logging by default; it can be enabled with `WSGI_ACCESS_LOG=1`.
- Fixed the live-log `NameError` at job completion by using the central duration calculation.
- Suppressed normal client disconnect tracebacks and disabled proxy buffering for SSE.
- Set VERSION to 0.1.76.

## v0.1.75

- Fixed the refresh-button hover effect that could create a temporary horizontal scrollbar.
- Added consistent size refresh buttons to the dashboard, profile list, and mirror details.
- Added **Refresh all sizes** to the dashboard, with duplicate-path removal and missing-directory handling.
- Added ascending and descending sorting for dashboard columns Name, Status, Type, and Size.
- Added sorting for mirror profile columns Name, Status, Mirror size, and Repository.
- Size sorting uses raw byte values rather than formatted text.
- Set VERSION to 0.1.75.

## v0.1.74

- Corrected size freshness logic: `stale` is shown only when a real non-dry-run job finishes after the last size check.
- Cache age alone no longer marks a size stale.
- Renamed “last known value” to “last check”.
- Standardized green `current` and yellow `stale` badges across all size displays.
- Added dashboard refresh actions for user-script target sizes.
- Made generator default search paths permanently visible as text.
- Set VERSION to 0.1.74.

## v0.1.73

- Added a refresh button next to every dashboard mirror size.
- Standardized human-readable size states and separated the state from the check timestamp.
- Made the complete last-job entry clickable for profiles and user scripts.
- Compacted the master-keyring summary and moved detailed paths and fingerprints into expandable areas.
- Split generator settings into responsive Search path variables and Generator configuration cards.
- Reviewed routes, templates, role views, documentation, and release-note formatting.
- Set VERSION to 0.1.73.

## v0.1.72

- Removed misleading rsync username/password authentication from profiles and the profile generator.
- Added SSH-key authentication for appropriately configured rsync modules, including user, private key, port, and host-key verification.
- Validated uploaded private keys and rejected passphrase-protected keys for unattended jobs.
- Added persistent `known_hosts` handling and safe file permissions.
- Extended `rsync://` scans to inspect `dists/`, `InRelease`, and `Release` metadata and prepare profiles automatically.
- Added central conflict validation for transfer methods, credentials, GPG, diff, cleanup, paths, ports, and schedules.
- Included managed SSH files in full backups and restores without exposing private-key contents through APIs or normal exports.
- Set VERSION to 0.1.72.

## v0.1.71

- Initially added rsync daemon username/password support using temporary password files.
- Made generator credentials visible by default and documented HTTP, FTP, and rsync cases.
- Added password-safe job execution, temporary file cleanup, and clear process/log redaction.
- This approach was superseded by the SSH-key design in v0.1.72.
- Set VERSION to 0.1.71.

## v0.1.70

- Added optional remote user and password fields to mirror profiles.
- Stored remote passwords encrypted in SQLite and never returned them to edit forms.
- Passed credentials through temporary protected debmirror configuration files rather than process arguments or logs.
- Added HTTP Basic Auth and FTP credentials to the profile generator.
- Added a validated expert field for additional debmirror options.
- Excluded remote passwords from normal configuration exports and API output.
- Included encrypted profile credentials and their persistent encryption key in full-backup validation and restore order.
- Set VERSION to 0.1.70.

## v0.1.69

- Replaced free-form Rsync Extra values with the valid selections `doc`, `indices`, `tools`, `trace`, and `none`; expanded validated debmirror option selection and mobile layouts.

## v0.1.68

- Packaged releases with a top-level `debmirror-manager/` directory and preserved executable permissions in full backups and restores.

## v0.1.67

- Moved notification secrets to a dedicated persistent encryption key and included that key in full backups; added dashboard health-check latency and a more compact master-key list.

## v0.1.66

- Added suite and architecture selection to client export and generated matching Deb822 and classic source files.

## v0.1.65

- Made detected repository bases selectable in the profile generator and persisted key-server imports as rebuildable source files.

## v0.1.64

- Fixed saving prepared generator profiles through the normal `/mirrors/new` workflow.

## v0.1.63

- Reviewed documentation and release-note structure, removed duplicate headings, and normalized version formatting.

## v0.1.62

- Improved missing-key diagnosis and fingerprint/subkey matching across master and archive keyrings.

## v0.1.61

- Added archive-keyring matching through the corresponding master primary key when a subkey is detected.

## v0.1.60

- Made archive-keyring detection more robust by using multiple GPG reading paths.

## v0.1.59

- Added direct GnuPG checks against the master keyring when resolving missing key IDs.

## v0.1.58

- Separated missing-GPG-key diagnosis into clearer master, archive, and import actions.

## v0.1.57

- Extended missing-key analysis and guided key import and profile assignment.

## v0.1.56

- Expanded master-keyring status and source-file information.

## v0.1.55

- Simplified the profile-keyring generation action and related wording.

## v0.1.54

- Fixed removal of master-fingerprint assignments from profile keyrings.

## v0.1.53

- Corrected missing-key diagnosis and matching behavior.

## v0.1.52

- Expanded master-keyring management and key-source controls.

## v0.1.51

- Corrected master-keyring status reporting.

## v0.1.50

- Introduced the central master-keyring workflow.

## v0.1.49

- Expanded assigning keyrings and fingerprints to mirror profiles.

## v0.1.48

- Extended keyring import capabilities.

## v0.1.47

- Corrected the keyrings page and its actions.

## v0.1.46

- Expanded keyring administration.

## v0.1.45

- Made dashboard job-state badges such as `active #ID` and `queue #ID` open the corresponding job.

## v0.1.44

- Standardized dashboard status display for mirror profiles and user scripts.

## v0.1.43

- Improved dashboard editing with a finer twelve-column width grid.

## v0.1.42

- Added mouse-based drag-and-drop dashboard block positioning.

## v0.1.41

- Moved User scripts into the Mirror navigation section.

## v0.1.40

- Added repository-scan validation for search-path variables ending directly in `dists/`.

## v0.1.39

- Corrected protocol fallback for profile-generator input without a URL scheme.

## v0.1.38

- Made search-path variables visible and editable directly in repository scans.

## v0.1.37

- Added configurable repository search-path variables and built-in defaults.

## v0.1.36

- Added continuously updating live status to background profile-generator scans.

## v0.1.35

- Added a visible detailed status window to profile-generator checks.

## v0.1.34

- Introduced the general repository scan in the profile generator.

## v0.1.33

- Reworked post-job size calculation so manually started jobs do not automatically trigger a scan.

## v0.1.32

- Moved the user-script size refresh action next to the last calculation state.

## v0.1.31

- Added enable/disable controls for individual saved schedule entries.

## v0.1.30

- Standardized dashboard column widths and row alignment for profiles and user scripts.

## v0.1.29

- Aligned the user-script dashboard block with the mirror-profile block.

## v0.1.28

- Fixed the “Unknown action” error when saving a user-script target directory.

## v0.1.27

- Cleaned up the login page.

## v0.1.26

- Added separate scheduler handling for mirror and user-script jobs.

## v0.1.25

- Added `lftp` to the application image.

## v0.1.24

- Made the left navigation collapsible.

## v0.1.23

- Fixed user-script upload and display failures caused by a missing size formatter.

## v0.1.22

- Introduced the left sidebar and a more compact dashboard.

## v0.1.21

- Reloaded job diagnosis after completion without requiring a full page refresh.

## v0.1.20

- Restored GPG key assistance above the log after job completion.

## v0.1.19

- Prevented live-log scrolling jumps when a job finishes.

## v0.1.18

- Prevented HTTP 500 errors on mirror details when keyring fingerprints do not match.

## v0.1.17

- Added job runtime to lists and detail views.

## v0.1.16

- Fixed the `size_calc_max_parallel` setting.

## v0.1.15

- Hardened the dashboard and size cache against WebUI errors.

## v0.1.14

- Added keyring selection to script import.

## v0.1.13

- Made `install.sh` reuse existing `.env` values as defaults.

## v0.1.12

- Added the optional nginx mirror HTTP container.

## v0.1.11

- Added configurable parallel job execution.

## v0.1.10

- Introduced the global job queue.

## v0.1.9

- Improved navigation and the profile overview.

## v0.1.8

- Improved SQLite locking behavior.

## v0.1.7

- Added required container dependencies including `gpgv`, `patch`, `ed`, and `dirmngr`.

## v0.1.6

- Added configuration export/import, notifications, user management, API access, and health checks.

## v0.1.5

- Improved importing existing `DEB_*` scripts.

## v0.1.4

- Added import of existing debmirror scripts.

## v0.1.3

- Introduced the `updates/` directory and automated update workflow.

## v0.1.2

- Made ZIP extraction consistently create the `debmirror-manager/` directory.

## v0.1.1

- Fixed login/setup behavior and standardized ports 8111 and 8110.

## v0.1.0

- First functional Docker WebUI with mirror profiles, jobs, logs, keyrings, documentation, and release notes.
