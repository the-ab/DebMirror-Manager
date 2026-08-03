# DebMirror Manager – Project Handover

This is the entry point for a new development chat or another person taking over project work.

## Read first in a new session

1. `docs/PROJECT_STATUS.md`
2. `docs/HANDOVER.md`
3. `docs/RELEASE_CHECKLIST.md`
4. `CONTRIBUTING.md`
5. `README.md`
6. `RELEASE_NOTES.md`
7. `VERSION`
8. current `main`, open branches, and open pull requests

Repository files and the current GitHub state are the binding technical source of truth. Do not rely on chat history or memory alone.

## Starter text for a new chat

```text
Project: the-ab/DebMirror-Manager
Baseline: current main branch and VERSION
Read first:
- docs/PROJECT_STATUS.md
- docs/HANDOVER.md
- docs/RELEASE_CHECKLIST.md

Workflow:
- dedicated branch
- draft pull request against main
- complete German and English changes
- verify tests, audit, security, mobile layout, versions, and update path
- no GitHub Actions, Dependabot, or release automation without explicit approval
```

## Binding workflow

- Check `main`, `VERSION`, open PRs, and project status before changing code.
- Keep each branch limited to one coherent scope.
- Maintain all user-facing text, help, README files, and release notes in German and English.
- Use `docs/RELEASE_CHECKLIST.md` for every release.
- Never commit real `.env` files, databases, logs, backups, keys, or credentials.
- Keep `app/docs/` synchronized with public documentation.
- Synchronize affected files under `app/repository/`.
- Do not disable security or GPG verification to bypass errors.
- Publish changes as draft PRs by default; merge only after approval.

## GitHub workflow

Repository: `the-ab/DebMirror-Manager`  
Default branch: `main`

1. Create `agent/<short-description>`.
2. Implement changes and matching tests.
3. Run available checks.
4. Open a draft PR describing cause, changes, impact, and validation.
5. Address review findings and revalidate.
6. Merge after approval.

ZIP and checksum files are GitHub Release assets and are not committed as normal files to `main`.

## Release artifacts

```text
debmirror-manager-vX.Y.Z.zip
debmirror-manager-vX.Y.Z.zip.sha256
ghcr.io/the-ab/debmirror-manager:vX.Y.Z
ghcr.io/the-ab/debmirror-manager:latest
```

The version tag and `latest` must point to the same image build.

## Before an active work chat ends

- update open work in both project-status files
- document open branches and PRs
- record checks performed and checks that could not run
- for release work, record version, date, ZIP, SHA-256, release tag, and GHCR state
- ensure the next chat can continue from repository documents alone

## Current constraints

- No GitHub Actions, Dependabot, or automated release pipeline without explicit maintainer approval.
- Local-build and GHCR installations have separate update paths.
- Both GHCR Compose variants and both real ENV files must be considered during updates.
- Release assets require a suitable GitHub Release upload interface or an authenticated CLI workflow.
