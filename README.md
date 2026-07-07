# DebMirror Manager

### Änderung v0.1.45

Die Status-Badges `aktiv #ID` und `queue #ID` in der gemeinsamen Dashboard-Tabelle sind jetzt direkt anklickbar und öffnen den zugehörigen Job. Deaktivierte Mirror-Profile und deaktivierte bzw. nicht ausführbare Benutzerskripte können nicht mehr normal gestartet werden; Dry-Run bleibt für deaktivierte Mirror-Profile möglich.


DebMirror Manager ist eine Docker-basierte WebUI für lokale APT-Repository-Spiegel. Der Schwerpunkt liegt auf `debmirror`, zusätzlich können eigene Benutzerskripte wie `lftp`- oder `rsync`-Synchronisationen als Jobs ausgeführt und geplant werden.

Aktuelle Version: **0.1.45**

## Grundprinzip

- Mirror-Profile erzeugen kontrollierte `debmirror`-Befehle.
- Benutzerskripte werden als Dateien aus einem fest definierten Verzeichnis ausgeführt.
- Alle Jobs laufen über Warteschlange, Logs und Historie weiter, auch wenn die WebUI geschlossen ist.
- Die WebUI speichert Konfigurationen in SQLite und `settings.json`.
- Große Verzeichnisse werden nicht blockierend berechnet, sondern über einen Größen-Cache im Hintergrund.

## Standardpfade

```text
updates/                                  Update-ZIPs im Projektordner
backup/                                   update.sh-Backups im Projektordner
/docker_data/debmirror-manager/data        SQLite-Datenbank und settings.json
/docker_data/debmirror-manager/logs        WebUI- und Job-Logs
/docker_data/debmirror-manager/keyrings    GPG-Keyrings
/docker_data/debmirror-manager/import-scripts  Import alter debmirror-Skripte
/docker_data/debmirror-manager/user-scripts    eigene Benutzerskripte
/docker_data/debmirror-manager/backup      WebUI-Vollbackups
/srv/mirror oder /mnt/linux-mirror         lokale Repository-/Mirror-Daten
```

Im Container wird das lokale Mirror-Verzeichnis als `/mirror` eingebunden. Zielpfade in Profilen und Script-Größenzielen müssen deshalb innerhalb von `/mirror` liegen, z. B. `/mirror/debian` oder `/mirror/ubuntu`.

## Installation

```bash
unzip debmirror-manager-v0.1.45.zip
cd debmirror-manager
chmod +x install.sh update.sh set-admin-password.sh
./install.sh
```

`install.sh` fragt die relevanten Werte ab, darunter:

- persistenter Datenpfad
- lokales Mirror-Verzeichnis
- WebUI-Port
- optionaler nginx-Mirror-HTTP-Container
- Update- und Backup-Verzeichnisse
- Job-Warteschlange und Retention
- Dashboard-Limits
- Größenberechnung
- Speicherplatz-Sperre direkt im Block **Mirror-Speicher**
- Zeitzone
- Admin-Zugang

Bei erneutem Aufruf liest `install.sh` vorhandene `.env`-Werte und schlägt sie als Defaults vor.

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

## Navigation und Menüpunkte

### Übersicht -> Dashboard

Zeigt Speicherplatz, Warteschlange, Mirror-Profile, Benutzerskripte, letzte Jobs, Ereignisse und Healthchecks. Das Feld **Warteschlange** zeigt neben laufenden/wartenden Jobs auch laufende, wartende und vorgemerkte Größenberechnungen. Die Kachel **Profile / Benutzerskripte** ist zweigeteilt; die Bezeichnungen **Mirror-Profile** und **Benutzerskripte** sind direkt anklickbar. Mirror-Profile und Benutzerskripte werden darunter in einer gemeinsamen Tabelle mit der Spalte **Art** angezeigt. Über **Dashboard bearbeiten** können Blöcke per Maus verschoben und über den Griff unten rechts vergrößert oder verkleinert werden; das Layout wird zentral in `settings.json` gespeichert und gilt dadurch browserübergreifend. Die Bereiche **Letzte Jobs** und **Ereignisse** bleiben in Scrollboxen; die Anzahl der geladenen Einträge ist unter `System -> Einstellungen` konfigurierbar.

### Mirror -> Profile

Liste aller debmirror-Profile. Pro Profil werden Status, Ziel, Größe, Zeitplan, letzter Job und Aktionen angezeigt. Die Größe stammt aus dem Größen-Cache.

Im Bearbeiten-Dialog kann im Bereich **Zeitplan** ein einfacher Profilzeitplan gesetzt werden. Wird dort nicht **Manuell** gewählt, legt die WebUI automatisch einen Eintrag in **Betrieb -> Zeitpläne** an. Dieser Eintrag ist dort als **Profilzeitplan** gekennzeichnet, kann einzeln aktiviert/deaktiviert und gelöscht werden. Beim Löschen eines Profilzeitplans wird das zugehörige Mirror-Profil automatisch wieder auf **Manuell** gestellt.

### Mirror -> Profilgenerator

Prüft allgemeine APT-Repository-Adressen und ist nicht auf Debian oder Ubuntu beschränkt. Die URL-Prüfung sucht nach `dists/`, `Release`, `InRelease`, `Packages`-Dateien, vorhandenen Suites, Komponenten, Architekturen und möglichen GPG-Key-Dateien wie `.gpg`, `.asc`, `Release.key` oder `archive-keyring.gpg`. Die Verzeichnistiefe ist einstellbar; Standard ist `5`, maximal `10`. Während der Prüfung zeigt ein Live-Statusfenster fortlaufend, welche Verzeichnisse, `dists/`-Pfade, Release-Dateien, Packages-Dateien und GPG-Key-Kandidaten geprüft werden. Wird eine Adresse ohne Protokoll eingegeben, prüft der Scanner bei Bedarf zusätzlich HTTP, wenn über HTTPS kein Repository gefunden wurde. Der Scan kann über **Prüfung stoppen** abgebrochen werden; ein laufender HTTP-Aufruf wird dabei noch beendet, danach stoppt die Prüfung.

Wenn an der eingegebenen Hauptadresse kein verwendbares Repository gefunden wird, prüft der Generator automatisch konfigurierbare Suchpfad-Variablen wie `deb`, `debian`, `repo`, `repository`, `apt` oder `packages`. Diese Liste wird zentral unter `System -> Generator-Einstellungen` gepflegt und kann dort erweitert werden, damit auch Hersteller-Repositories mit eigenen Pfaden später besser erkannt werden. Bleibt auch diese Prüfung ohne Treffer, wird zusätzlich je Suchvariable ein direkt angehängtes `dists/` geprüft, zum Beispiel `<basis>/repository/dists/`. Auch direkte Suite-Pfade wie `dists/stable/InRelease` oder direkt gefundene `dists/`-Verzeichnisse werden als normale Repository-Struktur erkannt und nicht mehr als flaches Repository behandelt. Aus erkannten `dists/`-Repositories kann ein neues Mirror-Profil vorbereitet werden. Gefundene GPG-Keys werden angezeigt, aber noch nicht automatisch importiert.

Der bisherige Standardgenerator für bekannte Debian-/Ubuntu-Profile bleibt darunter erhalten. Die Generator-Daten und Suchpfad-Variablen sind unter `System -> Generator-Einstellungen` erweiterbar.

### Mirror -> Skript-Import

Importiert bestehende debmirror-Skripte. Unterstützt direkte `debmirror`-Befehle und Variablenstrukturen wie `DEB_HOST`, `DEB_ROOT`, `DEB_DIST`, `DEB_SECT`, `DEB_ARCH`, `DEB_OPT` und Keyring-/Fingerprint-Variablen.

### Mirror -> Keyrings

Verwaltet GPG-Keyrings. Keys können per Datei, URL oder Keyserver importiert werden. Fingerprints können geprüft und Profilen zugewiesen werden.

### Betrieb -> Jobs / Logs

Zeigt Jobhistorie, Status, Exit-Code, Startzeit, Endzeit, Dauer und Logs. Laufende Jobs streamen Live-Logs. Nach Job-Ende wird die Fehlerauswertung oberhalb des Logs aktualisiert, ohne die komplette Seite neu zu laden.

### Betrieb -> Zeitpläne

Flexible Jobplanung für Mirror-Profile und Benutzerskripte. Die Job-Zeitplanliste steht direkt unter den aktuellen Regeln, damit gespeicherte Jobs schneller erreichbar sind. Unterstützt:

- tägliche Uhrzeiten, auch mehrere pro Tag, z. B. `06:00,18:00`
- Wochentage
- Intervalle in Stunden
- globale Mirror-Zeitpläne für alle aktiven Profile
- Benutzerskript-Zeitpläne für alle, einzelne oder selektierte Skripte
- Bearbeiten und Löschen bestehender Zeitpläne
- einzelnes Aktivieren/Deaktivieren gespeicherter Zeitpläne
- Profilzeitpläne aus Mirror-Profilen; beim Löschen wird das Profil auf manuell zurückgesetzt

### Mirror -> Benutzerskripte

Benutzerskripte besitzen einen eigenen Aktiv-Schalter. Nur aktive und ausführbare Skripte können manuell oder per Zeitplan gestartet werden. Beim Löschen eines Skripts wird sein gespeicherter Aktiv-Status auf inaktiv gesetzt.

Eigene Skripte werden aus `/docker_data/debmirror-manager/user-scripts` geladen. Die WebUI führt nur Dateien direkt in diesem Verzeichnis aus, keine freie Shell-Eingabe.

Pro Skript kann ein **Zielverzeichnis nur für Größenberechnung** gesetzt werden. Dieses Ziel wird nicht an das Skript übergeben und verändert die Skriptausführung nicht. Es dient ausschließlich dazu, die Größe eines durch das Skript erzeugten Sync-/Mirror-Verzeichnisses anzuzeigen. Größe, Status, Berechnungszeit und der Button **Größe neu berechnen** werden in einer kompakten Zeile dargestellt. Eine manuelle Größenberechnung betrifft nur dieses eine Skriptziel. Nach beendeten Zeitplan-Skript-Jobs wird die automatische Größenberechnung nur vorgemerkt und erst nach Ruhefenster sowie ohne aktive/wartende Jobs gestartet.

### Betrieb -> Healthchecks

Prüft lokale Repository-URLs wie `http://mirror.local/debian/dists/bookworm/Release`. Healthchecks können regelmäßig laufen und bei Fehlern Benachrichtigungen auslösen.

### Betrieb -> Benachrichtigung

Konfiguriert SMTP-Mail, Telegram und Discord. Geheimwerte wie SMTP-Passwort, Telegram-Bot-Token und Discord-Webhook werden nicht im Formular angezeigt. Neue Eingaben ersetzen den gespeicherten Wert; leere Felder behalten den vorhandenen Wert. Gespeichert werden diese Werte verschlüsselt, sofern der Container mit dem normalen Image inklusive `cryptography` läuft.

### System -> Einstellungen

Zentrale Einstellungen für Darstellung, Jobs, Warteschlange, Log-Aufbewahrung, Dashboard-Limits, Größenberechnung, Zeitzone und Container-Prüfung. Die Seite ist bewusst in kompakte Blöcke geteilt, damit lange Formulare und Statusbereiche wie **Mirror-Speicher** nicht unnötig viel Leerraum erzeugen. Die Optionen **Speicherplatz-Sperre für Mirror-Jobs** und **Grenzwert Mirror-Speichernutzung** befinden sich direkt im Block **Mirror-Speicher**, weil sie sich auf genau dieses Basisverzeichnis beziehen:

- Darstellung und Dark Mode
- maximale parallele Jobs
- Job-/Log-Aufbewahrung
- Dashboard-Limits
- Größenberechnung und Cache
- automatische Größenberechnung nach ruhigem Job-Fenster
- Speicherplatz-Sperre direkt im Block **Mirror-Speicher**
- Zeitzone
- Container-/Programmprüfung

### System -> Generator-Einstellungen

Verwaltet die Generator-Daten und Suchpfad-Variablen für den Profilgenerator. Suchpfade wie `deb`, `debian`, `repo`, `repository`, `apt` oder `packages` werden bei erfolgloser Hauptprüfung automatisch relativ zur eingegebenen Repository-Adresse geprüft.

### System -> Backup / Wiederherstellen

Erstellt und verwaltet WebUI-Vollbackups. Enthalten sind Datenbank, Einstellungen, Keyrings, Import-Skripte und Benutzerskripte. Große Mirror-Daten unter `/mirror` werden bewusst nicht gesichert.

### System -> Konfig Export/Import

Exportiert/importiert Konfigurationsdaten wie Mirror-Profile, Healthchecks, Zeitpläne, Generator-Konfiguration und nicht-sensitive Einstellungen. Geheimwerte aus Benachrichtigungen werden dabei nicht exportiert.

### System -> Benutzer

Verwaltet Benutzer und Rollen:

- `admin`: volle Verwaltung
- `user`: rein betrachtender Zugriff

Normale Benutzer dürfen keine kritischen Änderungen durchführen und keine Jobs starten/stoppen.

### System -> API

Verwaltet API-Tokens. Tokens werden nur einmal beim Erstellen angezeigt und danach nur gehasht gespeichert. Erste REST-Endpunkte liefern Status, Mirror, Jobs, Healthchecks und Benutzerskripte.

### Hilfe -> Anleitung / Release Notes

Zeigt diese Anleitung und die Versionshistorie innerhalb der WebUI an. Die Versionsnummer oben in der Kopfzeile ist ebenfalls direkt mit den Release Notes verlinkt.

## Warteschlange und Parallelität

Alle Mirror- und Benutzerskript-Jobs laufen über dieselbe Warteschlange. `MAX_PARALLEL_JOBS` legt fest, wie viele Jobs gleichzeitig laufen dürfen. Standard ist `1`. Weitere Jobs bleiben mit Status `queued` in der Warteschlange.

## Größenberechnung

Die Größe wird über einen Cache verwaltet. Dashboard und Listen starten keine Massenberechnung. Eine manuelle Berechnung auf einer Profil- oder Skriptseite betrifft nur dieses konkrete Ziel. Manuell gestartete Mirror- oder Benutzerskript-Jobs lösen keine automatische Größenberechnung mehr aus.

Automatische Größenberechnungen entstehen ausschließlich durch Marker nach beendeten Zeitplan-Jobs. Dabei wird nur das Ziel vorgemerkt, das zu diesem beendeten Zeitplan-Job gehört: das Mirror-Profil oder das Benutzerskript-Zielverzeichnis. Die Berechnung startet erst, wenn keine Jobs laufen oder warten und innerhalb des eingestellten Ruhefensters kein weiterer geplanter Job fällig ist. Während laufender oder wartender Jobs wird keine Größenberechnung gestartet; sie bleibt sichtbar als wartend/vorgemerkt.

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

Dry-Runs und Benutzerskripte bleiben erlaubt. Die Einstellungen dazu werden in der WebUI im Block **System -> Einstellungen -> Mirror-Speicher** gepflegt.

## Sicherheit

- keine freie Shell-Eingabe in der WebUI
- Benutzerskripte nur aus einem festen Verzeichnis
- Benutzerrollen trennen Admin- und Lesezugriff
- Passwörter von Benutzern werden gehasht gespeichert
- Legacy-Adminwerte werden aus `settings.json` entfernt und in die SQLite-Benutzerverwaltung migriert
- SMTP-Passwort, Telegram-Token und Discord-Webhook werden nicht im Formular angezeigt und verschlüsselt in `settings.json` gespeichert
- API-Tokens werden nur gehasht gespeichert
- Key-Fingerprints sollten gegen Hersteller-/Projekt-Dokumentation geprüft werden

Wichtig: Für die Entschlüsselung von Benachrichtigungs-Geheimwerten wird `APP_SECRET_KEY` verwendet. Dieser Wert muss bei Migration oder Restore erhalten bleiben.

## Notfall: Admin-Passwort zurücksetzen

```bash
cd debmirror-manager
./set-admin-password.sh
```

Das Skript schreibt den Admin-Zugang direkt in die SQLite-Benutzerverwaltung. `settings.json` enthält danach keine Legacy-Admin-Zugangswerte mehr.
