# Contributing to DebMirror Manager

Thank you for helping improve the project.

## Before opening a pull request

1. Start from the latest version.
2. Keep credentials, private keys, databases, logs, backups, `.env` files, and production paths out of commits.
3. Preserve German and English behavior and documentation where a user-facing change is involved.
4. Add or update automated tests for behavioral changes.
5. Update both `RELEASE_NOTES.md` and `RELEASE_NOTES.de.md` for release-visible changes.
6. Review third-party code or assets before adding them and update `THIRD-PARTY-NOTICES.md` when required.

## Local checks

Use Python 3.12 and install the locked production dependencies plus the development tools:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip install -r requirements-dev.txt
```

Run the same primary checks as CI:

```bash
python -m compileall -q app tests scripts
python scripts/repository_audit.py
pytest -q
bandit -q -r app -x tests -lll
pip-audit -r requirements.lock --require-hashes
bash -n install.sh update.sh set-admin-password.sh
```

A Docker build should also complete successfully:

```bash
docker build --pull=false -t debmirror-manager:test .
docker compose config --quiet
```

## Code and security expectations

- Use parameterized SQL and argument lists for subprocesses.
- Do not introduce `shell=True` without a documented, reviewed necessity.
- Treat URLs, uploaded archives, key material, filesystem paths, and command options as hostile input.
- Keep CSRF protection on state-changing WebUI routes and scope checks on API routes.
- Never log passwords, tokens, decrypted secrets, private keys, or backup passwords.
- Preserve restrictive file permissions and update/restore traversal protections.
- Keep one Gunicorn worker unless the scheduler and process registry are redesigned for multi-process operation.

## Licensing

Contributions are accepted under `AGPL-3.0-or-later`, the license of this project. By submitting a contribution, you confirm that you have the right to provide it under that license.

Portions of the project were developed with assistance from OpenAI ChatGPT. All contributions, including AI-assisted contributions, must be reviewed, understood, adapted where necessary, and tested by the submitting human.
