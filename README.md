# DebMirror Manager

DebMirror Manager ist eine Docker-basierte WebUI für lokale APT-Repository-Spiegel. Der Schwerpunkt liegt auf `debmirror`; zusätzlich können eigene Benutzerskripte wie `lftp`-, `rsync`- oder Hersteller-Sync-Skripte als Jobs ausgeführt, geplant und überwacht werden.

Aktuelle Version: **0.1.65**

## Grundprinzip

- Mirror-Profile erzeugen kontrollierte `debmirror`-Befehle.
- Benutzerskripte werden nur aus einem fest definierten Verzeichnis gestartet.
- Alle Mirror- und Script-Jobs laufen über Warteschlange, Logs und Historie.
- Konfigurationen liegen in SQLite und `settings.json`.
- Große Verzeichnisse werden nicht bei jedem Seitenaufruf berechnet, sondern über einen Größen-Cache gepflegt.
- GPG-Keys werden zentral im Master-Keyring verwaltet; pro Mirror-Profil werden bereinigte Profil-Keyrings erzeugt.

## Standardpfade

```text
updates/                                      Update-ZIPs im Projektordner
backup/                                       update.sh-Backups im Projektordner
/docker_data/debmirror-manager/data           SQLite-Datenbank und settings.json
/docker_data/debmirror-manager/logs           WebUI- und Job-Logs
/docker_data/debmirror-manager/keyrings       GPG-Keyrings, Master-Keyring, Archiv, Keyserver-Quellen und Profil-Keyrings
/docker_data/debmirror-manager/import-scripts Import alter debmirror-Skripte
/docker_data/debmirror-manager/user-scripts   eigene Benutzerskripte
/docker_data/debmirror-manager/backup         WebUI-Vollbackups
/srv/mirror oder /mnt/linux-mirror            lokale Repository-/Mirror-Daten
```

Im Container wird das lokale Mirror-Verzeichnis als `/mirror` eingebunden. Zielpfade in Profilen und Script-Größenzielen müssen deshalb innerhalb von `/mirror` liegen, z. B. `/mirror/debian` oder `/mirror/ubuntu`.

## Installation

```bash
unzip debmirror-manager-v0.1.65.zip
cd debmirror-manager
chmod +x install.sh update.sh set-admin-password.sh
./install.sh
```

`install.sh` fragt die relevanten Werte ab, darunter persistenter Datenpfad, lokales Mirror-Verzeichnis, WebUI-Port, optionaler nginx-Mirror-HTTP-Container, Update-/Backup-Verzeichnisse, Job-Warteschlange, Retention, Dashboard-Limits, Größenberechnung, Speicherplatz-Sperre, Zeitzone und Admin-Zugang. Bei erneutem Aufruf liest `install.sh` vorhandene `.env`-Werte und schlägt sie als Defaults vor.

## Update

Zukünftige Updates werden in `updates/` kopiert:

```bash
cd debmirror-manager
cp /pfad/zur/debmirror-manager-vNEU.zip updates/
./update.sh
```

`update.sh` prüft ZIP-Versionen, erstellt ein Backup, ersetzt Projektdateien und baut/startet Container automatisch neu. Wenn kein neues ZIP vorhanden ist, fragt `update.sh`, ob trotzdem Backup und Rebuild durchgeführt werden sollen. Direkter Rebuild:

```bash
./update.sh --rebuild
```

## Navigation

Die Hauptnavigation ist in Bereiche gegliedert:

- **Dashboard**: zentrale Übersicht, Warteschlange, Status, letzte Jobs und Healthchecks.
- **Mirror**: Profile, Profilgenerator, Benutzerskripte, Skript-Import, Zeitpläne und Healthchecks.
- **Betrieb**: Jobs, Ereignisse, Benachrichtigungen und laufende Auswertungen.
- **System**: Einstellungen, Generator-Einstellungen, Keyrings, Backup/Wiederherstellen, Konfig Export/Import, Benutzer und API.

## Dashboard

Das Dashboard zeigt Speicher, Warteschlange, Mirror-Profile, Benutzerskripte, letzte Jobs, Ereignisse und Healthchecks.

Wichtige Bereiche:

- **Speicher**: Auslastung des Mirror-Basisverzeichnisses.
- **Warteschlange**: laufende/wartende Jobs sowie laufende, wartende oder vorgemerkte Größenberechnungen.
- **Profile / Benutzerskripte**: zweigeteilte Schnellübersicht; die Überschriften sind direkt anklickbar.
- **Mirror-Profile / Benutzerskripte**: gemeinsame Tabelle mit Art, Status, Größe, Zeitplan, letztem Job und Aktion.
- **Letzte Jobs**: jüngste Jobs mit Status, Quelle, Dauer und Exit-Code.
- **Ereignisse**: aktuelle System- und WebUI-Meldungen.
- **Healthchecks**: zuletzt geprüfte Mirror-URLs.

Über **Dashboard bearbeiten** können Blöcke mit der Maus verschoben und über den Griff unten rechts in Breite und Höhe angepasst werden. Das Layout wird zentral in `settings.json` gespeichert und gilt dadurch browserübergreifend.

Statuswerte in der gemeinsamen Tabelle **Mirror-Profile / Benutzerskripte**:

```text
idle       kein laufender oder wartender Job
aktiv #ID  Job läuft; die Job-ID ist anklickbar
queue #ID  Job wartet; die Job-ID ist anklickbar
no key     Mirror-Profil hat keinen erzeugten/zugeordneten Profil-Keyring
inaktiv    Profil oder Skript ist deaktiviert
error      Start nicht möglich, z. B. Pflichtwerte fehlen oder Skript ist nicht ausführbar
```

## Mirror-Profile

Mirror-Profile enthalten alle Werte, die für einen `debmirror`-Lauf benötigt werden:

- Methode: `rsync`, `http`, `https` oder `ftp`
- Host und Repository-Wurzelpfad
- Distributionen/Suites
- Sektionen/Komponenten
- Architekturen
- Zielverzeichnis unter `/mirror`
- Quellpakete optional aktivierbar
- zusätzliche debmirror-Optionen
- GPG-/Keyring-Zuordnung
- Profilzeitplan
- Aktiv-Status

Deaktivierte Profile können nicht normal gestartet werden, weder manuell noch per Zeitplan oder API. Dry-Runs bleiben möglich. In Listen wird ein gesperrter Start als deaktivierter/durchgestrichener Start-Button dargestellt.

## Profilgenerator

Der Profilgenerator prüft allgemeine APT-Repository-Adressen und ist nicht auf Debian oder Ubuntu beschränkt.

Die Prüfung erkennt unter anderem:

- `dists/`
- `Release` und `InRelease`
- `Packages`, `Packages.gz`, `Packages.xz`
- Suites/Distributionen
- Komponenten/Sektionen
- Architekturen
- mögliche GPG-Key-Dateien wie `.gpg`, `.asc`, `Release.key`, `archive-keyring.gpg`
- flache APT-Repositories
- direkte Suite-Pfade wie `dists/stable/InRelease`

Die Verzeichnistiefe ist einstellbar; Standard ist `5`, maximal `10`. Während der Prüfung zeigt ein Live-Statusfenster die geprüften Verzeichnisse, `dists/`-Pfade, Release-Dateien, Packages-Dateien und GPG-Key-Kandidaten. Der Scan kann über **Prüfung stoppen** abgebrochen werden.

Wird eine Adresse ohne Protokoll eingegeben, prüft der Scanner zuerst HTTPS und bei Bedarf zusätzlich HTTP. Wenn an der Hauptadresse kein Repository gefunden wird, werden die Suchpfad-Variablen aus **System -> Generator-Einstellungen** relativ zur eingegebenen Adresse geprüft, z. B. `deb`, `debian`, `repo`, `repository`, `apt`, `packages`, `mirror`, `download` oder `public`. Bleibt auch das ohne Treffer, wird je Suchvariable zusätzlich ein direkt angehängtes `dists/` geprüft. Werden mehrere Repository-Basen gefunden, kann die gewünschte Basis im Prüfergebnis ausgewählt werden; Suites, Komponenten und Architekturen werden danach passend zu dieser Basis gefiltert.

## Benutzerskripte

Benutzerskripte werden aus `/docker_data/debmirror-manager/user-scripts` geladen. Die WebUI führt nur Dateien direkt in diesem Verzeichnis aus; freie Shell-Eingabe ist nicht vorgesehen.

Funktionen:

- Skripte hochladen oder vorhandene Dateien erkennen
- Aktiv-Schalter pro Skript
- Start nur, wenn Skript aktiv und ausführbar ist
- Zeitpläne für einzelne, mehrere oder alle aktiven Skripte
- Joblogs und Historie wie bei Mirror-Profilen
- Zielverzeichnis nur für Größenberechnung
- manuelle Größenberechnung nur für dieses eine Skriptziel

Beim Löschen eines Skripts wird der gespeicherte Aktiv-Status auf inaktiv gesetzt.

## Skript-Import

Der Skript-Import hilft beim Übernehmen bestehender debmirror-Skripte. Unterstützt werden direkte `debmirror`-Befehle sowie Variablenstrukturen wie:

```text
DEB_HOST
DEB_ROOT
DEB_DIST
DEB_SECT
DEB_ARCH
DEB_OPT
DEB_KEYRING
DEB_KEY_FINGERPRINT
```

Gefundene Werte werden in ein Mirror-Profil übernommen und können vor dem Speichern geprüft werden.

## Keyring-Verwaltung

Die Keyring-Verwaltung arbeitet mit drei Ebenen:

```text
Master-Keyring
├── zentrale Arbeitsdatei mit allen verwalteten Keys
Archiv / Keyserver-Quellen
├── importierte Originaldateien und Keyserver-Exports als Quelle/Backup
Profil-Keyrings
└── automatisch erzeugte Keyrings pro Mirror-Profil mit nur den zugeordneten Keys
```

### Master-Keyring

Der Master-Keyring liegt unter:

```text
/app/keyrings/master/debmirror-manager-master.gpg
```

Die Oberfläche zeigt Hauptkeys, Subkeys, Gesamt-Fingerprints, Größe, Pfad und GPG-Hinweise. Einzelne Master-Keys können exportiert oder entfernt werden. Das Entfernen wird blockiert, solange der Key noch einem Mirror-Profil zugeordnet ist.

Es gibt zwei Neuaufbau-Arten:

- **Master-Keyring neu aufbauen**: baut aus allen Quelldateien neu auf, also aus `archive/` und `keyserver/`, lässt bewusst entfernte Keys aber weiter ausgeschlossen.
- **Vollständig neu aufbauen**: baut aus denselben Quelldateien neu auf und hebt zusätzlich vorherige Entfernsperren auf.

### Import

Keys können importiert werden über:

- Datei-Upload
- URL
- eingefügten ASCII-Key
- Keyserver

Vor dem Import wird eine Vorschau angezeigt mit UID, Key-ID, Fingerprint, Algorithmus, Schlüssellänge, Erstellungsdatum, Ablaufdatum, Status und Subkeys. Bereits vorhandene Fingerprints werden als Duplikate erkannt; ein Import ist dann nur bewusst mit **Duplikate erlauben** möglich.

Neue Datei-/URL-/Text-Importe werden im Archiv abgelegt und zusätzlich in den Master-Keyring übernommen. Keyserver-Importe werden zusätzlich als eigene Quelldateien unter `keyrings/keyserver/` gespeichert. Archiv- und Keyserver-Quelldateien können einzeln gelöscht werden; das Löschen einer Quelldatei entfernt nicht automatisch den aktuell vorhandenen Master-Key.

### Profil-Keyrings

Mirror-Profile bekommen keine komplette Importdatei und nicht den kompletten Master-Keyring zugewiesen. Stattdessen werden einzelne Fingerprints aus dem Master-Keyring ausgewählt. Daraus erzeugt die WebUI einen bereinigten Profil-Keyring unter:

```text
/app/keyrings/profiles/
```

Dieser Profil-Keyring enthält nur die zugeordneten Hauptkeys inklusive der benötigten Subkeys. Dadurch enthalten auch Client-Exports nur die Keys, die für dieses Profil nötig sind.

### Fehlerdiagnose für fehlende Keys

Wenn ein Dry-Run oder Job fehlende GPG-Keys meldet, prüft die Fehlerdiagnose:

- gemeldete `NO_PUBKEY`-IDs
- Hauptkey-Fingerprints
- Signing-Subkeys
- Master-Keyring-Treffer
- Archiv-Keyring-Treffer

Master-Keyring und Archiv-Keyring werden getrennt angezeigt. Mehrere benötigte Fingerprints können gemeinsam ausgewählt und mit einem einzigen Button dem Profil zugeordnet werden. Archiv-Treffer werden zuerst in den Master-Keyring übernommen; danach wird ein bereinigter Profil-Keyring erzeugt.

## Client-Export

Auf der Mirror-Detailseite kann ein Client-Export erzeugt werden. Der Export enthält:

- bereinigten Profil-Keyring als `.gpg`
- Deb822-`.sources`-Datei
- klassische `.list`-Datei
- README mit Installationsbefehlen für den Client

Der Client-Export verwendet nur den Profil-Keyring des ausgewählten Mirror-Profils und enthält dadurch keine unnötigen Zusatzkeys.

## Jobs und Logs

Alle Jobs laufen über dieselbe Warteschlange. Jobseiten zeigen Status, Quelle, Startzeit, Endzeit, Dauer, Exit-Code und Logausgabe. Laufende Jobs streamen Live-Logs. Nach Job-Ende wird die Fehlerauswertung oberhalb des Logs aktualisiert, ohne die komplette Seite neu zu laden.

Statusbeispiele:

```text
queued       wartet
running      läuft
success      erfolgreich beendet
error        Fehler
stopping     Stop angefordert
stopped      gestoppt
```

## Zeitpläne

Zeitpläne unterstützen:

- tägliche Uhrzeiten, auch mehrere pro Tag, z. B. `06:00,18:00`
- Wochentage
- Intervalle in Stunden
- globale Mirror-Zeitpläne für alle aktiven Profile
- Zeitpläne für einzelne oder ausgewählte Profile
- Benutzerskript-Zeitpläne für einzelne, mehrere oder alle aktiven Skripte
- Aktivieren/Deaktivieren einzelner gespeicherter Zeitpläne
- Bearbeiten und Löschen bestehender Zeitpläne
- Profilzeitpläne aus dem Mirror-Profilformular

Die Job-Zeitplanliste steht direkt unter **Aktuelle Regeln**, damit gespeicherte Jobs schnell erreichbar sind. Wird ein Profilzeitplan in der Zeitplanliste gelöscht, wird das zugehörige Mirror-Profil automatisch wieder auf **Manuell** gestellt.

## Größenberechnung

Die Größenberechnung nutzt einen Cache und wird nicht automatisch für alle Profile gestartet.

Regeln:

- manuelle Größenberechnung betrifft nur das ausgewählte Profil oder Skriptziel
- manuell gestartete Jobs lösen keine automatische Größenberechnung aus
- automatische Größenberechnung entsteht nur nach beendeten Zeitplan-Jobs
- pro beendetem Zeitplan-Job wird nur das betroffene Profil oder Skriptziel vorgemerkt
- Berechnung startet nur, wenn keine Jobs laufen oder warten
- eingestelltes Ruhefenster wird berücksichtigt
- laufende oder wartende Größenberechnungen werden in der Warteschlange sichtbar

Wichtige Einstellungen:

```text
SIZE_CACHE_TTL_SECONDS=21600
SIZE_CALC_TIMEOUT_SECONDS=1800
SIZE_CALC_MAX_PARALLEL=2
AUTO_SIZE_RECALC_ENABLED=1
AUTO_SIZE_IDLE_MINUTES=120
```

## Speicherplatz-Sperre

Die Speicherplatz-Sperre blockiert echte Mirror-Jobs, wenn das Mirror-Basisverzeichnis einen Grenzwert überschreitet. Standard:

```text
STORAGE_GUARD_ENABLED=1
STORAGE_GUARD_THRESHOLD_PERCENT=95
```

Dry-Runs und Benutzerskripte bleiben erlaubt. Die Einstellungen befinden sich unter **System -> Einstellungen -> Mirror-Speicher**.

## Healthchecks

Healthchecks prüfen lokale Repository-URLs wie:

```text
http://mirror.local/debian/dists/bookworm/Release
```

Sie können regelmäßig laufen und bei Fehlern Benachrichtigungen auslösen.

## Benachrichtigungen

Unter **Betrieb -> Benachrichtigung** können SMTP-Mail, Telegram und Discord konfiguriert werden. Geheimwerte wie SMTP-Passwort, Telegram-Bot-Token und Discord-Webhook werden nicht im Formular angezeigt. Neue Eingaben ersetzen den gespeicherten Wert; leere Felder behalten den vorhandenen Wert. Gespeichert werden diese Werte verschlüsselt, sofern der Container mit dem normalen Image inklusive `cryptography` läuft.

## Systembereiche

### Einstellungen

Zentrale Einstellungen für Darstellung, Jobs, Warteschlange, Log-Aufbewahrung, Dashboard-Limits, Größenberechnung, Zeitzone, Container-Prüfung und Mirror-Speicher.

### Generator-Einstellungen

Verwaltet Generator-Daten und Suchpfad-Variablen für den Profilgenerator.

### Backup / Wiederherstellen

Erstellt und verwaltet WebUI-Vollbackups. Enthalten sind Datenbank, Einstellungen, Keyrings, Import-Skripte und Benutzerskripte. Große Mirror-Daten unter `/mirror` werden bewusst nicht gesichert.

### Konfig Export/Import

Exportiert und importiert Konfigurationsdaten wie Mirror-Profile, Healthchecks, Zeitpläne, Generator-Konfiguration und nicht-sensitive Einstellungen. Geheimwerte aus Benachrichtigungen werden nicht exportiert.

### Benutzer

Rollen:

```text
admin  volle Verwaltung
user   rein betrachtender Zugriff
```

Normale Benutzer dürfen keine kritischen Änderungen durchführen und keine Jobs starten oder stoppen.

### API

API-Tokens werden nur einmal beim Erstellen angezeigt und danach gehasht gespeichert. Erste REST-Endpunkte liefern Status, Mirror, Jobs, Healthchecks und Benutzerskripte.

## Sicherheit

- keine freie Shell-Eingabe in der WebUI
- Benutzerskripte nur aus festem Verzeichnis
- Start-Sperren greifen im Backend, nicht nur in der Oberfläche
- Benutzerrollen trennen Admin- und Lesezugriff
- Benutzerpasswörter werden gehasht gespeichert
- Legacy-Adminwerte werden aus `settings.json` entfernt und in die SQLite-Benutzerverwaltung migriert
- Benachrichtigungs-Geheimwerte werden verschlüsselt gespeichert
- API-Tokens werden nur gehasht gespeichert
- Key-Fingerprints sollten gegen Hersteller-/Projekt-Dokumentation geprüft werden

Wichtig: Für die Entschlüsselung von Benachrichtigungs-Geheimwerten wird `APP_SECRET_KEY` verwendet. Dieser Wert muss bei Migration oder Restore erhalten bleiben.

## Notfall: Admin-Passwort zurücksetzen

```bash
cd debmirror-manager
./set-admin-password.sh
```

Das Skript schreibt den Admin-Zugang direkt in die SQLite-Benutzerverwaltung.

## Hilfe

Die WebUI enthält eine Anleitung und separate Release Notes. Die Anleitung beschreibt die Funktionen des Projekts; die Versionshistorie steht ausschließlich in den Release Notes.
