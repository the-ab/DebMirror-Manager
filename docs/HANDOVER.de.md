# DebMirror Manager – Projekt-Handover

Dieses Dokument ist der Einstiegspunkt für einen neuen Entwicklungs-Chat oder eine neue Person, die die Projektarbeit übernimmt.

## In einer neuen Sitzung zuerst lesen

1. `docs/PROJECT_STATUS.de.md`
2. `docs/HANDOVER.de.md`
3. `docs/RELEASE_CHECKLIST.de.md`
4. `CONTRIBUTING.md`
5. `README.de.md`
6. `RELEASE_NOTES.de.md`
7. `VERSION`
8. aktuellen Stand von `main`, offenen Branches und Pull Requests

Repository-Dateien und aktueller GitHub-Stand sind die verbindliche technische Grundlage. Nicht ausschließlich auf Chatverlauf oder Erinnerung vertrauen.

## Starttext für einen neuen Chat

```text
Projekt: the-ab/DebMirror-Manager
Basis: aktueller main-Branch und VERSION
Bitte zuerst lesen:
- docs/PROJECT_STATUS.de.md
- docs/HANDOVER.de.md
- docs/RELEASE_CHECKLIST.de.md

Arbeitsweise:
- Änderungen auf eigenem Branch
- Draft-Pull-Request gegen main
- Deutsch und Englisch vollständig
- Tests, Audit, Sicherheit, Mobilansicht, Versionen und Updatepfad prüfen
- keine GitHub Actions, Dependabot oder Release-Automatik ohne ausdrückliche Freigabe
```

## Verbindliche Abläufe

- Vor Änderungen `main`, `VERSION`, offene PRs und Projektstatus prüfen.
- Nur zusammengehörige Änderungen in einen Branch aufnehmen.
- Benutzerwirksame Texte, Hilfe, README und Release Notes immer DE/EN pflegen.
- Bei Releasearbeiten `docs/RELEASE_CHECKLIST.de.md` vollständig abarbeiten.
- Bestehende `.env`-Dateien, Datenbanken, Logs, Backups, Schlüssel und Zugangsdaten niemals committen.
- `app/docs/` mit öffentlicher Dokumentation synchron halten.
- Betroffene Dateien unter `app/repository/` ebenfalls synchronisieren.
- Sicherheitsprüfungen und GPG-Prüfungen nicht zur Umgehung eines Fehlers deaktivieren.
- Änderungen standardmäßig als Draft-PR bereitstellen; Merge erst nach Freigabe.

## GitHub-Arbeitsweise

Repository: `the-ab/DebMirror-Manager`  
Standardbranch: `main`

Empfohlener Ablauf:

1. Branch `agent/<kurze-beschreibung>` erstellen.
2. Änderungen und passende Tests umsetzen.
3. Lokale beziehungsweise verfügbare Prüfungen ausführen.
4. Draft-PR mit Ursache, Änderungen, Auswirkungen und Prüfungen erstellen.
5. Reviewpunkte bearbeiten und PR erneut prüfen.
6. Nach Freigabe mergen.

ZIP und SHA-256-Datei gehören als Assets zu einem GitHub Release. Sie werden nicht als normale Dateien nach `main` committed.

## Release-Artefakte

Pro Version werden benötigt:

```text
debmirror-manager-vX.Y.Z.zip
debmirror-manager-vX.Y.Z.zip.sha256
ghcr.io/the-ab/debmirror-manager:vX.Y.Z
ghcr.io/the-ab/debmirror-manager:latest
```

Der Versions-Tag und `latest` müssen auf demselben Image-Build basieren.

## Vor Ende eines Arbeits-Chats

- aktuellen Stand und offene Punkte in `docs/PROJECT_STATUS.de.md` und `.md` aktualisieren
- offene Branches/PRs und deren Zweck dokumentieren
- durchgeführte und nicht mögliche Prüfungen festhalten
- bei Releasearbeiten Version, Datum, ZIP, SHA-256, Tag und GHCR-Stand notieren
- sicherstellen, dass der nächste Chat ausschließlich mit den Repository-Dokumenten fortfahren kann

## Aktuelle Besonderheiten

- Keine GitHub Actions, Dependabot- oder automatische Release-Pipeline ohne ausdrückliche Maintainer-Entscheidung.
- Lokaler Build und GHCR-Installation besitzen getrennte Updatewege.
- Beide GHCR-Compose-Varianten und beide echten ENV-Dateien müssen beim Update berücksichtigt werden.
- Release-Assets können erst hochgeladen werden, wenn eine geeignete GitHub-Release-Schnittstelle oder ein authentifizierter CLI-Ablauf verfügbar ist.
