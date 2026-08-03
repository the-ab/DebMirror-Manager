# DebMirror Manager – Projektstatus

Stand: **03.08.2026**  
Freigegebene Basisversion: **v1.0.3**  
Repository: **the-ab/DebMirror-Manager**  
Standardbranch: **main**  
Container-Registry: **ghcr.io/the-ab/debmirror-manager**

Dieses Dokument hält den aktuellen, öffentlich dokumentierbaren Projektstand fest. Es muss bei jeder Veröffentlichung und bei wesentlichen Änderungen am Entwicklungs- oder Veröffentlichungsablauf aktualisiert werden.

## Veröffentlichungsformen

DebMirror Manager wird in zwei Formen bereitgestellt:

1. Release-ZIP für lokale Builds:
   - `debmirror-manager-vX.Y.Z.zip`
   - `debmirror-manager-vX.Y.Z.zip.sha256`
2. Fertiges Container-Image:
   - `ghcr.io/the-ab/debmirror-manager:latest`
   - `ghcr.io/the-ab/debmirror-manager:vX.Y.Z`

Release-ZIP und SHA-256-Datei gehören als Assets zu einem GitHub Release. Sie sollen nicht dauerhaft in den normalen Git-Verlauf eingecheckt werden.

## Installationsvarianten

- Lokaler Build mit Root-`docker-compose.yml`, `install.sh` und `update.sh`
- GHCR-Installation mit optionalem nginx:
  - `docker-compose/compose.yaml`
  - `docker-compose/.env.example`
- GHCR-Installation ohne nginx:
  - `docker-compose/compose.no-nginx.yaml`
  - `docker-compose/.env.no-nginx.example`

Die lokalen Erklärungen aller Image-Variablen liegen in:

- `docker-compose/README.de.md`
- `docker-compose/README.md`

## Technische Basis

- Python 3.13
- Debian 13/Trixie im Anwendungscontainer
- Flask mit Gunicorn
- genau ein Gunicorn-Worker mit mehreren Threads
- SQLite und `settings.json` für persistente Konfiguration
- `debmirror`, GnuPG, Rsync, OpenSSH und optionale Benutzerskripte
- Server-Sent Events für Live-Protokolle
- deutsche und englische WebUI und Dokumentation

## Persistente Bereiche

- `DATA_PATH`: Datenbank, Einstellungen, Schlüsselmaterial und Anwendungsdaten
- `MIRROR_PATH`: gespiegelte Repository-Daten
- `docker-compose/.env` und `docker-compose/.env.no-nginx`: lokale Image-Konfigurationen
- Projekt-`.env`: lokale Build-Konfiguration

Echte `.env`-Dateien, Datenbanken, Protokolle, Backups, private Schlüssel und Zugangsdaten dürfen niemals eingecheckt oder in Release-ZIPs aufgenommen werden.

## Verbindliche Projektregeln

- Benutzerwirksame Änderungen müssen in Deutsch und Englisch umgesetzt werden.
- README, WebUI-Hilfe und Release Notes müssen zum tatsächlichen Funktionsstand passen.
- `VERSION`, `APP_RELEASE_DATE`, Image-Beispiele, Release Notes und sichtbare Versionsangaben müssen konsistent sein.
- `app/docs/` muss mit den öffentlichen README- und Release-Notes-Dateien synchron bleiben.
- `app/repository/` enthält den reduzierten Repository-/Policy-Snapshot und muss bei betroffenen Dateien synchronisiert werden.
- Sicherheitsprüfungen dürfen nicht zur Bequemlichkeit deaktiviert werden.
- Update-, Backup-, Restore- und Migrationsauswirkungen müssen vor jedem Release geprüft werden.
- Mobile Darstellung und Desktopdarstellung sind beide Teil der Abnahme.
- GitHub Actions, Dependabot und automatische Release-Workflows werden nicht ohne ausdrückliche Entscheidung des Projektbetreuers eingeführt.
- Änderungen sollen über einen Branch und vorzugsweise einen Draft-Pull-Request geprüft werden.

## Aktueller Veröffentlichungsablauf

1. Änderungen auf einem separaten Branch umsetzen.
2. Relevante Tests und Audits ausführen.
3. Draft-PR gegen `main` erstellen.
4. PR-Diff prüfen und freigeben.
5. Nach dem Merge Release-Version und Veröffentlichungsdatum final kontrollieren.
6. Release-ZIP und SHA-256-Datei erzeugen und prüfen.
7. GitHub Release mit beiden Assets veröffentlichen.
8. GHCR-Image mit Versions-Tag und `latest` bereitstellen.
9. Installation und Updatepfad stichprobenartig prüfen.
10. Dieses Statusdokument und die Handover-Dokumente aktualisieren.

## Aktueller Wartungsstand

- Aktive freigegebene Basis: v1.0.3
- Beide GHCR-Compose-Varianten sind vorhanden.
- Die lokale Build- und die Image-Installation sind getrennt dokumentiert.
- Es existiert keine automatische CI-, Dependabot- oder Release-Pipeline.
- Pull Requests können über den verbundenen GitHub-Zugang erstellt und verwaltet werden.
- Release-Assets müssen über eine dafür geeignete GitHub-Release-Schnittstelle oder manuell hochgeladen werden.

## Offene Arbeiten

Neue offene Punkte werden hier vor dem Ende eines Arbeits-Chats als kurze, konkrete Liste ergänzt. Erledigte Punkte werden beim nächsten Release entfernt oder in die Release Notes überführt.

- Derzeit keine in diesem Dokument festgehaltenen offenen Implementierungspunkte.
