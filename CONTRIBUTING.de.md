# Beiträge zum DebMirror Manager

Vielen Dank für die Unterstützung bei der Verbesserung des Projekts.

## Sprachkonvention für Dokumentation

Informations- und Richtliniendateien verwenden Englisch als Standarddatei und Deutsch als passende `*.de.md`-Datei:

- `DOKUMENT.md` — Englisch
- `DOKUMENT.de.md` — Deutsch

Keine `*.en.md`-Dateien anlegen. Wird eine Informationsdatei ergänzt oder geändert, müssen beide Sprachfassungen im selben Pull Request aktualisiert werden.

## Vor dem Erstellen eines Pull Requests

1. Vom aktuellen Versionsstand ausgehen.
2. Zugangsdaten, private Schlüssel, Datenbanken, Logs, Backups, `.env`-Dateien und produktive Pfade nicht committen.
3. Bei benutzerwirksamen Änderungen deutsches und englisches Verhalten sowie die Dokumentation synchron halten.
4. Für Verhaltensänderungen automatische Tests ergänzen oder aktualisieren.
5. Bei releasewirksamen Änderungen sowohl `RELEASE_NOTES.md` als auch `RELEASE_NOTES.de.md` aktualisieren.
6. Drittanbieter-Code und Assets vor dem Hinzufügen prüfen und bei Bedarf `THIRD-PARTY-NOTICES.md` sowie `THIRD-PARTY-NOTICES.de.md` aktualisieren.

## Lokale Prüfungen

Python 3.13 verwenden und die gesperrten Produktionsabhängigkeiten sowie Entwicklungswerkzeuge installieren:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip install -r requirements-dev.txt
```

Die primären Prüfungen lokal ausführen:

```bash
python -m compileall -q app tests scripts
python scripts/repository_audit.py
pytest -q
bandit -q -r app -x tests -lll
pip-audit -r requirements.lock --require-hashes
bash -n install.sh update.sh set-admin-password.sh
```

Auch ein Docker-Build sollte erfolgreich sein:

```bash
docker build --pull=false -t debmirror-manager:test .
docker compose config --quiet
docker compose --env-file docker-compose/.env.example -f docker-compose/compose.yaml config --quiet
docker compose --env-file docker-compose/.env.no-nginx.example -f docker-compose/compose.no-nginx.yaml config --quiet
```

## Code- und Sicherheitsanforderungen

- Parametrisierte SQL-Abfragen und Argumentlisten für Subprozesse verwenden.
- Kein `shell=True` ohne dokumentierte und geprüfte Notwendigkeit einführen.
- URLs, hochgeladene Archive, Schlüsselmaterial, Dateisystempfade und Befehlsoptionen als potenziell feindliche Eingaben behandeln.
- CSRF-Schutz für zustandsändernde WebUI-Routen und Berechtigungsprüfungen für API-Routen beibehalten.
- Keine Passwörter, Tokens, entschlüsselten Geheimnisse, privaten Schlüssel oder Backup-Passwörter protokollieren.
- Restriktive Dateirechte sowie Schutz vor Pfadtraversal bei Update und Restore beibehalten.
- Genau einen Gunicorn-Worker verwenden, solange Scheduler und Prozessregistrierung nicht für mehrere Prozesse neu gestaltet wurden.

## Lizenzierung

Beiträge werden unter der Apache License 2.0 (`Apache-2.0`) angenommen. Mit dem Einreichen eines Beitrags wird bestätigt, dass dieser unter dieser Lizenz bereitgestellt werden darf.

Teile des Projekts wurden mit Unterstützung von OpenAI ChatGPT entwickelt. Alle Beiträge, einschließlich KI-unterstützter Beiträge, müssen vom einreichenden Menschen geprüft, verstanden, bei Bedarf angepasst und getestet werden.
