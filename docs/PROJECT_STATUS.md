# DebMirror Manager – Project Status

Status date: **2026-08-03**  
Released baseline: **v1.0.3**  
Repository: **the-ab/DebMirror-Manager**  
Default branch: **main**  
Container registry: **ghcr.io/the-ab/debmirror-manager**

This file is the public source of truth for the current maintenance state and must be updated for every release.

## Distribution

- Local-build release assets:
  - `debmirror-manager-vX.Y.Z.zip`
  - `debmirror-manager-vX.Y.Z.zip.sha256`
- Container images:
  - `ghcr.io/the-ab/debmirror-manager:latest`
  - `ghcr.io/the-ab/debmirror-manager:vX.Y.Z`

ZIP and checksum files belong to GitHub Releases and should not be committed to normal Git history.

## Installation variants

- Local build: root `docker-compose.yml`, `install.sh`, and `update.sh`
- GHCR with optional nginx: `docker-compose/compose.yaml` and `.env.example`
- GHCR without nginx: `docker-compose/compose.no-nginx.yaml` and `.env.no-nginx.example`

The image ENV files are documented in `docker-compose/README.md` and `docker-compose/README.de.md`.

## Binding rules

- User-facing changes require German and English implementation and documentation.
- README, WebUI help, and release notes must match actual behavior.
- `VERSION`, `APP_RELEASE_DATE`, visible version strings, image tags, and release notes must be consistent.
- `app/docs/` and affected files under `app/repository/` must remain synchronized.
- Update, migration, backup, restore, security, desktop, and mobile impact must be checked before release.
- Do not add GitHub Actions, Dependabot, or automated release workflows without explicit maintainer approval.
- Use a dedicated branch and preferably a draft pull request.
- Never commit real `.env` files, credentials, private keys, databases, logs, or backups.

## Release flow

1. Implement on a dedicated branch.
2. Run tests, syntax checks, security checks, repository audit, and documentation checks.
3. Open a draft PR against `main` and review the diff.
4. Merge only after approval.
5. Build and verify ZIP and SHA-256 assets.
6. Publish a GitHub Release and upload both assets.
7. Publish GHCR tags `vX.Y.Z` and `latest` from the same build.
8. Spot-check installation and update paths.
9. Update project status and handover documents.

## Current state

- Released baseline: v1.0.3
- Both GHCR Compose variants are present.
- Local-build and image installations are documented separately.
- No automated CI, Dependabot, or release pipeline is present.
- Pull requests can be created and managed through the connected GitHub access.
- Release assets require a GitHub Release upload interface or manual upload.

## Open work

- No open implementation items are currently recorded here.
