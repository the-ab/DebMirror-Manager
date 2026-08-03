# DebMirror Manager – Release Checklist

This checklist is mandatory for every published version. Items that do not apply are documented explicitly as “not affected.”

## 1. Baseline and scope

- [ ] current `main` and `VERSION` verified
- [ ] open PRs and parallel work reviewed
- [ ] release scope defined
- [ ] dedicated branch used
- [ ] no unrelated files in the diff
- [ ] project status and open work reviewed

## 2. Code and behavior

- [ ] Python syntax/bytecode check passed
- [ ] shell syntax of `install.sh`, `update.sh`, and `set-admin-password.sh` passed
- [ ] regression tests added for changed behavior
- [ ] full pytest run passed or the limitation is documented precisely
- [ ] error, cancellation, and retry paths tested
- [ ] queue, scheduler, concurrency, and live logs tested when affected

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip install -r requirements-dev.txt
python -m compileall -q app tests scripts
pytest -q
bash -n install.sh update.sh set-admin-password.sh
```

## 3. Security

- [ ] `python scripts/repository_audit.py` passed
- [ ] Bandit and dependency audit run or findings reviewed
- [ ] no passwords, tokens, private keys, or decrypted secrets included
- [ ] no real `.env`, database, logs, or backups in the release
- [ ] CSRF and authorization checks exist for new state-changing routes
- [ ] SQL is parameterized
- [ ] subprocesses contain no new unreviewed `shell=True`
- [ ] path, archive, upload, and URL inputs are protected
- [ ] GPG verification remains enabled

## 4. Database, migration, backup, and restore

- [ ] schema changes migrated and tested with the previous version
- [ ] existing data remains intact
- [ ] backup contains all required persistent files
- [ ] restore tested when affected
- [ ] file permissions verified after update/restore
- [ ] interrupted migration/restore considered

## 5. Installation and update

- [ ] fresh local-build installation tested
- [ ] update from the immediately previous release tested
- [ ] ZIP and SHA-256 verification passed
- [ ] project `.env` remains intact and secure
- [ ] `docker-compose/.env` remains intact
- [ ] `docker-compose/.env.no-nginx` remains intact
- [ ] update backup verified
- [ ] one-time migration guidance documented
- [ ] `updates/installed` behavior verified

## 6. Containers and Compose

- [ ] Docker build passed
- [ ] root Compose is valid
- [ ] GHCR Compose with optional nginx is valid
- [ ] GHCR Compose without nginx is valid
- [ ] both GHCR variants use the same WebUI configuration
- [ ] no local `build:` section in image Compose files
- [ ] all variables exist in and are documented for the matching ENV template
- [ ] healthchecks and persistent mounts verified
- [ ] exactly one Gunicorn worker remains configured

```bash
docker build --pull=false -t debmirror-manager:test .
docker compose config --quiet
docker compose --env-file docker-compose/.env.example -f docker-compose/compose.yaml config --quiet
docker compose --env-file docker-compose/.env.no-nginx.example -f docker-compose/compose.no-nginx.yaml config --quiet
```

## 7. Translations and documentation

- [ ] all user-visible text exists in German and English
- [ ] no missing or orphaned translation keys
- [ ] README DE/EN complete
- [ ] release notes DE/EN complete
- [ ] WebUI help updated
- [ ] `app/docs/` synchronized
- [ ] affected `app/repository/` files synchronized
- [ ] Docker Compose README DE/EN complete
- [ ] historical release notes not changed unintentionally
- [ ] project status DE/EN updated

## 8. UI and mobile devices

- [ ] desktop tested
- [ ] mobile layout tested at least at 360 px and 390 px
- [ ] tablet layout tested
- [ ] no horizontal page overflow
- [ ] tables, logs, and code blocks have dedicated scroll areas
- [ ] dialogs have vertical scrolling on mobile
- [ ] buttons and forms remain reachable
- [ ] dark/light mode tested when affected

## 9. Version and date

- [ ] `VERSION` correct
- [ ] `APP_RELEASE_DATE` correct
- [ ] README DE/EN, release notes, fallbacks, footer, GHCR examples, and ENV templates are consistent
- [ ] `update.sh --help` only uses `vX.Y.Z`
- [ ] repository audit reports no version mismatch
- [ ] historical versions remain historical references

## 10. Release package

- [ ] exactly one top-level `debmirror-manager/` directory
- [ ] ZIP integrity verified
- [ ] no real ENV files, databases, logs, backups, caches, or bytecode files
- [ ] shell-script executable bits verified
- [ ] `debmirror-manager-vX.Y.Z.zip` generated
- [ ] `debmirror-manager-vX.Y.Z.zip.sha256` generated
- [ ] `sha256sum -c` passed

## 11. GitHub and GHCR

- [ ] draft PR described and diff reviewed
- [ ] review items resolved and PR merged
- [ ] release tag `vX.Y.Z` created
- [ ] GitHub Release published
- [ ] ZIP and SHA-256 uploaded as release assets
- [ ] ZIP not committed to `main`
- [ ] GHCR image `vX.Y.Z` published
- [ ] `latest` points to the same build
- [ ] image pull and container startup spot-checked
- [ ] no unintended CI, Dependabot, or release automation added

## 12. Completion and handover

- [ ] download links, SHA-256, and update commands documented
- [ ] changes and checks actually performed listed precisely
- [ ] checks that could not run disclosed clearly
- [ ] project status DE/EN and open work updated
- [ ] PR, merge commit, release tag, and GHCR tags recorded
- [ ] next chat can continue using repository documents alone
