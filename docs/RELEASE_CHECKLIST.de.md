# DebMirror Manager – Release-Checkliste

Diese Checkliste ist für jede veröffentlichte Version verbindlich. Nicht betroffene Punkte werden ausdrücklich als „nicht betroffen“ dokumentiert.

## 1. Basis und Umfang

- [ ] aktuellen `main`-Stand und `VERSION` geprüft
- [ ] offene PRs und parallele Arbeiten geprüft
- [ ] Release-Umfang festgelegt
- [ ] eigener Branch verwendet
- [ ] keine sachfremden Dateien im Diff
- [ ] Projektstatus und offene Punkte geprüft

## 2. Code und Verhalten

- [ ] Python-Syntax/Bytecode geprüft
- [ ] Shell-Syntax von `install.sh`, `update.sh`, `set-admin-password.sh` geprüft
- [ ] Regressionstests für geändertes Verhalten ergänzt
- [ ] vollständiger Pytest-Lauf erfolgreich oder Einschränkung genau dokumentiert
- [ ] Fehler-, Abbruch- und Retrypfade geprüft
- [ ] Queue, Zeitpläne, Parallelität und Live-Logs geprüft, sofern betroffen

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

## 3. Sicherheit

- [ ] `python scripts/repository_audit.py` erfolgreich
- [ ] Bandit und Abhängigkeitsprüfung ausgeführt oder Befunde geprüft
- [ ] keine Passwörter, Tokens, privaten Schlüssel oder entschlüsselten Geheimnisse enthalten
- [ ] keine echte `.env`, Datenbank, Logs oder Backups im Release
- [ ] CSRF- und Berechtigungsprüfung für neue schreibende Routen
- [ ] SQL parametrisiert
- [ ] Subprozesse ohne neues ungeprüftes `shell=True`
- [ ] Pfad-, Archiv-, Upload- und URL-Eingaben abgesichert
- [ ] GPG-Prüfung weiterhin aktiviert

## 4. Datenbank, Migration, Backup und Restore

- [ ] Schemaänderung migriert und mit vorheriger Version geprüft
- [ ] vorhandene Daten bleiben erhalten
- [ ] Backup enthält alle nötigen persistenten Dateien
- [ ] Restore geprüft, sofern betroffen
- [ ] Dateirechte nach Update/Restore geprüft
- [ ] unterbrochene Migration/Restore berücksichtigt

## 5. Installation und Update

- [ ] Neuinstallation lokaler Build geprüft
- [ ] Update von der unmittelbar vorherigen Version geprüft
- [ ] ZIP und SHA-256 werden geprüft
- [ ] Projekt-`.env` bleibt erhalten und sicher
- [ ] `docker-compose/.env` bleibt erhalten
- [ ] `docker-compose/.env.no-nginx` bleibt erhalten
- [ ] Update-Backup geprüft
- [ ] Einmalhinweise/Migration dokumentiert
- [ ] `updates/installed` geprüft

## 6. Container und Compose

- [ ] Docker-Build erfolgreich
- [ ] Root-Compose gültig
- [ ] GHCR-Compose mit optionalem nginx gültig
- [ ] GHCR-Compose ohne nginx gültig
- [ ] beide GHCR-Varianten verwenden dieselbe WebUI-Konfiguration
- [ ] kein lokaler `build:`-Abschnitt in Image-Compose-Dateien
- [ ] alle Variablen in passender ENV-Vorlage vorhanden und dokumentiert
- [ ] Healthchecks und persistente Mounts geprüft
- [ ] weiterhin genau ein Gunicorn-Worker

```bash
docker build --pull=false -t debmirror-manager:test .
docker compose config --quiet
docker compose --env-file docker-compose/.env.example -f docker-compose/compose.yaml config --quiet
docker compose --env-file docker-compose/.env.no-nginx.example -f docker-compose/compose.no-nginx.yaml config --quiet
```

## 7. Übersetzungen und Dokumentation

- [ ] alle sichtbaren Texte DE/EN vorhanden
- [ ] keine fehlenden oder verwaisten Übersetzungsschlüssel
- [ ] README DE/EN vollständig
- [ ] Release Notes DE/EN vollständig
- [ ] WebUI-Hilfe aktualisiert
- [ ] `app/docs/` synchron
- [ ] betroffene `app/repository/`-Dateien synchron
- [ ] Docker-Compose-README DE/EN vollständig
- [ ] historische Release Notes nicht unbeabsichtigt verändert
- [ ] Projektstatus DE/EN aktualisiert

## 8. Oberfläche und Mobilgeräte

- [ ] Desktop geprüft
- [ ] Mobilansicht bei mindestens 360 px und 390 px geprüft
- [ ] Tabletansicht geprüft
- [ ] kein horizontaler Seitenüberlauf
- [ ] Tabellen, Logs und Codeblöcke besitzen eigene Scrollbereiche
- [ ] Dialoge auf Mobilgeräten vertikal scrollbar
- [ ] Buttons und Formulare erreichbar
- [ ] Dark/Light Mode geprüft, sofern betroffen

## 9. Version und Datum

- [ ] `VERSION` korrekt
- [ ] `APP_RELEASE_DATE` korrekt
- [ ] README DE/EN, Release Notes, Fallbacks, Footer, GHCR-Beispiele und ENV-Vorlagen konsistent
- [ ] `update.sh --help` verwendet nur `vX.Y.Z`
- [ ] Repository-Audit meldet keine Versionsabweichung
- [ ] historische Versionen bleiben historische Angaben

## 10. Release-Paket

- [ ] genau ein Top-Level-Ordner `debmirror-manager/`
- [ ] ZIP-Integrität geprüft
- [ ] keine echten ENV-Dateien, Datenbanken, Logs, Backups, Caches oder Bytecode-Dateien
- [ ] Ausführungsrechte der Shellskripte geprüft
- [ ] `debmirror-manager-vX.Y.Z.zip` erzeugt
- [ ] `debmirror-manager-vX.Y.Z.zip.sha256` erzeugt
- [ ] `sha256sum -c` erfolgreich

## 11. GitHub und GHCR

- [ ] Draft-PR beschrieben und Diff geprüft
- [ ] Reviewpunkte erledigt und PR gemergt
- [ ] Release-Tag `vX.Y.Z` erstellt
- [ ] GitHub Release veröffentlicht
- [ ] ZIP und SHA-256 als Release-Assets hochgeladen
- [ ] ZIP nicht in `main` eingecheckt
- [ ] GHCR-Image `vX.Y.Z` veröffentlicht
- [ ] `latest` zeigt auf denselben Build
- [ ] Image-Pull und Containerstart geprüft
- [ ] keine unbeabsichtigte CI-, Dependabot- oder Release-Automatik hinzugefügt

## 12. Abschluss und Handover

- [ ] Downloadlinks, SHA-256 und Updatebefehle dokumentiert
- [ ] Änderungen und tatsächlich durchgeführte Prüfungen präzise genannt
- [ ] nicht mögliche Prüfungen transparent genannt
- [ ] Projektstatus DE/EN und offene Punkte aktualisiert
- [ ] PR, Merge-Commit, Release-Tag und GHCR-Tags dokumentiert
- [ ] nächster Chat kann nur mit Repository-Dokumenten weiterarbeiten
