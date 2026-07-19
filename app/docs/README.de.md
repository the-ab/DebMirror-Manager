# DebMirror Manager

DebMirror Manager ist eine Docker-basierte WebUI für lokale APT-Repository-Spiegel. Der Schwerpunkt liegt auf `debmirror`; zusätzlich können eigene Benutzerskripte wie `lftp`-, `rsync`- oder Hersteller-Sync-Skripte als Jobs ausgeführt, geplant und überwacht werden.

Aktuelle Version: **0.1.79**

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
/docker_data/debmirror-manager/data           SQLite-Datenbank, settings.json und notification-secrets.key
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
unzip debmirror-manager-v0.1.79.zip
cd debmirror-manager
chmod +x install.sh update.sh set-admin-password.sh
./install.sh
```

`install.sh` fragt die relevanten Werte ab, darunter persistenter Datenpfad, lokales Mirror-Verzeichnis, WebUI-Port, optionaler nginx-Mirror-HTTP-Container, Update-/Backup-Verzeichnisse, Job-Warteschlange, Retention, Dashboard-Limits, Größenberechnung, Speicherplatz-Sperre, Zeitzone und Admin-Zugang. Bei erneutem Aufruf liest `install.sh` vorhandene `.env`-Werte und schlägt sie als Defaults vor.

### Webserver und Container-Logs

Die WebUI läuft produktiv über **Gunicorn** und nicht über den Flask-/Werkzeug-Entwicklungsserver. Wegen des internen Schedulers, der Job-Warteschlange und der laufenden Prozessverwaltung verwendet DebMirror Manager genau **einen Gunicorn-Worker** mit mehreren Threads. Die Anzahl paralleler WebUI-/Live-Log-Verbindungen lässt sich mit `WSGI_THREADS` anpassen; mehrere Worker dürfen nicht konfiguriert werden.

HTTP-Zugriffszeilen sind standardmäßig deaktiviert, damit die regelmäßigen Live-Log-Verbindungen das Containerlog nicht füllen. Bei Bedarf kann das Zugriffslog aktiviert werden:

```text
WSGI_THREADS=8
WSGI_ACCESS_LOG=1
WSGI_LOG_LEVEL=info
```

Live-Logs verwenden Server-Sent Events. Heartbeats halten auch ausgabearme, lange Jobs offen; ein normales Verlassen oder Neuladen der Jobseite wird nicht als Anwendungsfehler protokolliert.

Das lokal gebaute WebUI-Image besitzt fest den eindeutigen Namen `debmirror-manager:latest`. Die frühere automatisch erzeugte Doppelbezeichnung `debmirror-manager-debmirror-manager:latest` wird vom neuen Wartungsskript bei späteren Rebuilds oder Updates entfernt, sofern sie nicht mehr von einem alten Container verwendet wird. Beim erstmaligen Wechsel von einem älteren Updater kann das ungenutzte Alt-Image noch vorhanden bleiben; es kann dann einmalig mit `docker image rm debmirror-manager-debmirror-manager:latest` entfernt werden.

## Update

Zukünftige Updates werden in `updates/` kopiert:

```bash
cd debmirror-manager
cp /pfad/zur/debmirror-manager-vNEU.zip updates/
cp /pfad/zur/debmirror-manager-vNEU.zip.sha256 updates/
./update.sh
```

`update.sh` prüft ZIP-Versionen, erstellt ein Backup, ersetzt Projektdateien und baut/startet Container automatisch neu. Ab v0.1.78 verlangt der Updater zusätzlich einen vertrauenswürdig bezogenen SHA-256-Wert. Am einfachsten werden ZIP und gleichnamige Datei `<paket>.zip.sha256` gemeinsam nach `updates/` kopiert. Alternativ kann der Wert interaktiv eingegeben oder einmalig über `UPDATE_EXPECTED_SHA256` gesetzt werden. Update-ZIPs werden außerdem vor dem Entpacken auf Pfadtraversal, Sonderdateien, Eintragsanzahl, entpackte Gesamtgröße und verdächtige Kompressionsverhältnisse geprüft. Wenn kein neues ZIP vorhanden ist, fragt `update.sh`, ob trotzdem Backup und Rebuild durchgeführt werden sollen. Direkter Rebuild:

```bash
./update.sh --rebuild
```


## Sprache und Darstellung

Die WebUI unterstützt **Deutsch** und **Englisch**. Sprache und Darstellung werden direkt am jeweiligen Benutzerkonto gespeichert. Eine Änderung wirkt daher nicht auf andere Benutzer.

Über den Benutzernamen in der Kopfzeile öffnet sich **Persönliche Einstellungen**. Dort können gewählt werden:

- Deutsch oder Englisch
- helle Darstellung
- dunkle Darstellung
- automatische Darstellung nach Browser beziehungsweise Betriebssystem

Der Theme-Umschalter in der Kopfzeile aktualisiert ebenfalls nur das aktuelle Benutzerkonto. Administratoren können Sprache und Darstellung zusätzlich beim Anlegen oder Bearbeiten eines Benutzers vorgeben.

Die Dokumentationsdateien sind sprachlich getrennt:

```text
README.md              englische Standardanleitung
README.de.md           deutsche Anleitung
RELEASE_NOTES.md       englische Standard-Release-Notes
RELEASE_NOTES.de.md    deutsche Release Notes
```

Die WebUI öffnet automatisch die zur Benutzersprache passende Datei. Fehlt eine lokalisierte Datei, wird die englische Standarddatei verwendet.

## Navigation

Die Hauptnavigation ist in Bereiche gegliedert:

- **Übersicht**: Dashboard, Speicher, Warteschlange, Status, letzte Jobs, Ereignisse und Healthchecks.
- **Mirror**: Profile, Profilgenerator, Benutzerskripte, Skript-Import und Keyrings.
- **Betrieb**: Jobs/Logs, Zeitpläne, Healthchecks und Benachrichtigungen.
- **System**: Einstellungen, Generator-Einstellungen, Backup/Wiederherstellen, Konfig Export/Import, Benutzerverwaltung und API.

## Dashboard

Das Dashboard zeigt Speicher, Warteschlange, Mirror-Profile, Benutzerskripte, letzte Jobs, Ereignisse und Healthchecks.

Wichtige Bereiche:

- **Speicher**: Auslastung des Mirror-Basisverzeichnisses.
- **Warteschlange**: laufende/wartende Jobs sowie laufende, wartende oder vorgemerkte Größenberechnungen.
- **Profile / Benutzerskripte**: zweigeteilte Schnellübersicht; die Überschriften sind direkt anklickbar.
- **Mirror-Profile / Benutzerskripte**: gemeinsame Tabelle mit Art, Status, Größe, Zeitplan, letztem Job und Aktion. Der letzte Job ist vollständig anklickbar und öffnet direkt die zugehörige Job-/Logseite. Name, Status, Art und Größe können über die jeweilige Spaltenüberschrift auf- oder absteigend sortiert werden.
- **Letzte Jobs**: jüngste Jobs mit Status, Quelle, Dauer und Exit-Code.
- **Ereignisse**: aktuelle System- und WebUI-Meldungen.
- **Healthchecks**: zuletzt geprüfte Mirror-URLs.

Über **Dashboard bearbeiten** können Blöcke mit der Maus verschoben und über den Griff unten rechts in Breite und Höhe angepasst werden. Das Layout wird zentral in `settings.json` gespeichert und gilt dadurch browserübergreifend.

Neben jeder Mirror-Größe und jeder konfigurierten Benutzerskript-Zielgröße befindet sich für Admin-Benutzer ein Aktualisieren-Button. Das gilt im Dashboard, in der Profilübersicht, in der Mirror-Detailansicht und in der Benutzerskript-Übersicht. Über **↻ Alle** in der Dashboard-Spalte **Größe** werden alle vorhandenen konfigurierten Mirror- und Skript-Zielverzeichnisse gemeinsam aktualisiert. Doppelt konfigurierte Pfade werden nur einmal berechnet; nicht vorhandene Verzeichnisse werden übersprungen. Die Berechnungen laufen im Hintergrund beziehungsweise nacheinander über die Größenwarteschlange und blockieren keinen Seitenaufruf. Status und Zeitpunkt werden an allen Stellen einheitlich dargestellt:

```text
aktuell                      Seit der letzten Prüfung wurde kein echter Job für dieses Ziel beendet
veraltet                     Nach der letzten Prüfung wurde ein echter Job beendet
wird aktualisiert            Neuberechnung läuft; der Wert der letzten Prüfung bleibt sichtbar
wartet / vorgemerkt          Berechnung wartet auf Kapazität oder das Ruhefenster
noch nicht berechnet         für das Ziel existiert noch kein Prüfwert
Fehler / Zeitüberschreitung  letzte Berechnung ist fehlgeschlagen
letzte Prüfung               Zeitpunkt der zuletzt abgeschlossenen Größenberechnung
```

„Veraltet“ wird nicht mehr allein durch das Alter des Cache-Eintrags gesetzt. Der Status erscheint nur, wenn nach der letzten Größenprüfung ein nicht als Dry-Run ausgeführter Mirror- oder Benutzerskript-Job tatsächlich gestartet und beendet wurde. Ein Tooltip erklärt die jeweilige Bedeutung. Der interne Statuswert bleibt für API und Programmlogik unverändert.

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

Die Profilübersicht bietet neben jedem Größenwert einen kompakten Refresh-Button. Die Spalten **Name**, **Status**, **Mirror-Größe** und **Repository** sind durch Anklicken der Überschrift sortierbar. Ein zweiter Klick kehrt die Sortierreihenfolge um. Bei der Größen-Spalte wird intern der Bytewert verwendet, damit zum Beispiel `900 MiB` korrekt vor `2 GiB` einsortiert wird.

Mirror-Profile enthalten alle Werte, die für einen `debmirror`-Lauf benötigt werden:

- Methode: `rsync`, `http`, `https` oder `ftp`
- Host und Repository-Wurzelpfad
- Distributionen/Suites
- Sektionen/Komponenten
- Architekturen
- Zielverzeichnis unter `/mirror`
- Quellpakete optional aktivierbar
- zusätzliche debmirror-Optionen über kontrollierte Auswahlfelder
- manuelle Zusatzoptionen im validierten Expertenfeld
- optionale Remote-Anmeldung mit verschlüsselt gespeichertem Passwort
- Rsync-Extras `doc`, `indices`, `tools`, `trace` oder `none`
- Include-/Exclude-Patterns mit RegEx-Beispielen
- GPG-/Keyring-Zuordnung
- Profilzeitplan
- Aktiv-Status

Deaktivierte Profile können nicht normal gestartet werden, weder manuell noch per Zeitplan oder API. Dry-Runs bleiben möglich. In Listen wird ein gesperrter Start als deaktivierter/durchgestrichener Start-Button dargestellt.

### debmirror-Optionen im Profil

Die wichtigsten Werte wie Transfermethode, Host, Root-Pfad, Suites, Komponenten, Architekturen, Quellpakete, Keyring, Cleanup, Diff-Modus, Timeout und Include-/Exclude-Patterns besitzen eigene Formularfelder. Weitere profilgeeignete debmirror-Optionen werden über eine kontrollierte Auswahlliste aktiviert. Optionen mit Parameter zeigen direkt daneben ein Eingabefeld, zum Beispiel:

```text
--proxy=http://proxy.example:3128/
--rsync-options=-aIL --partial --bwlimit=50000
--state-cache-days=7
--exclude-field=Package=^linux-image-debug
```

`Rsync Extra` ist getrennt davon und bietet ausschließlich die von debmirror unterstützten Werte `doc`, `indices`, `tools`, `trace` und `none`. `none` kann nicht mit weiteren Rsync-Extras kombiniert werden. Frühere Profile, bei denen ein Rsync-Parameter versehentlich in `Rsync Extra` gespeichert wurde, werden beim Bearbeiten als `--rsync-options` übernommen.

Include- und Exclude-Patterns sind kommagetrennte Perl-RegEx. Beispiele:

```text
Include: /Translation-(de|en).*
Exclude: /Translation-.*,/.*-dbg_.*
```

Sicherheitskritische Optionen wie `--no-check-gpg` und `--disable-ssl-verification` sind sichtbar gekennzeichnet. Für seltene oder neuere debmirror-Optionen gibt es zusätzlich **Manuelle Zusatzoptionen (Expertenmodus)**. Das Feld akzeptiert nur lange Optionen, führt sie ohne Shell als einzelne Prozessargumente aus und blockiert Basisoptionen, Zugangsdaten, `--config-file` sowie bereits in der Auswahlliste vorhandene Flags. Optionen mit Wert werden im Format `--option=wert` eingetragen.

Die Profilprüfung verhindert oder bereinigt widersprüchliche Kombinationen: `--passive` nur bei FTP, deaktivierte TLS-Prüfung nur bei HTTPS, Rsync-Paketoptionen nur bei Hauptmethode Rsync, `--gzip-options` nur bei aktivem Diff-Modus, `--slow-cpu` nur mit `diff=none`, genau ein Bereinigungsmodus sowie keine Keyring-/Fingerprint-Zuordnung bei `--no-check-gpg`. `Rsync Extra=none` sperrt Rsync-Optionen, wenn die Hauptmethode ebenfalls nicht Rsync ist. Für Rsync werden Host und Modulpfad zentral geprüft; Ports gehören entweder in die Rsync-Option `--port=...` oder bei SSH in das separate SSH-Port-Feld. Zeitplan-Uhrzeiten müssen als gültiges `HH:MM` angegeben werden. Diese Regeln werden im Formular, im Backend sowie beim Skript- und Konfigurationsimport angewendet.

Für geschützte HTTP/HTTPS- oder FTP-Quellen besitzt das Profil optionale Felder für Remote-Benutzer und Remote-Passwort. Das Passwort wird verschlüsselt in der SQLite-Datenbank gespeichert und im Formular nie zurückgegeben. Beim Jobstart erzeugt die Anwendung dafür eine temporäre debmirror-Konfigurationsdatei mit Dateimodus `0600`; Job-Datenbank, gespeicherter Befehl und Logs enthalten kein Klartextpasswort. Bei der Methode `rsync` sind Benutzer/Passwort-Felder gesperrt.

Für geschützte Rsync-Quellen steht stattdessen **Rsync-Modul über SSH-Schlüssel** bereit. debmirror verwendet Rsync-Ziele im Format `host::modul`; die Anwendung ergänzt dafür eine explizite SSH-Remote-Shell mit privatem Schlüssel, `BatchMode`, `IdentitiesOnly`, eigenem SSH-Port und persistenter `known_hosts`-Datei. Unterstützt wird damit ein Rsync-Modul über eine SSH-Remote-Shell. Ein allgemeiner Dateipfad wie `user@host:/srv/mirror` kann mit debmirror nicht als Mirror-Profil verwendet werden; dafür ist ein Benutzerskript geeigneter. Private Schlüssel müssen für unbeaufsichtigte Jobs ohne Passphrase vorliegen, werden geprüft und mit Modus `0600` gespeichert.

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

Wird eine Adresse ohne Protokoll eingegeben, prüft der Scanner zuerst HTTPS und ohne Zugangsdaten bei Bedarf zusätzlich HTTP. Sind HTTP/FTP-Zugangsdaten gesetzt, wird aus Sicherheitsgründen kein automatischer Wechsel von HTTPS auf unverschlüsseltes HTTP durchgeführt; HTTP muss dann ausdrücklich angegeben werden. Der Bereich für Benutzername und Passwort ist standardmäßig eingeklappt. HTTP/HTTPS-Scans unterstützen Basic Auth und FTP-Scans Benutzer/Passwort.

Eine ausdrücklich angegebene `rsync://`-Adresse wird nicht nur auf Erreichbarkeit geprüft: Der Generator liest gezielt `dists/` sowie die dortigen `InRelease`-/`Release`-Dateien und kann daraus Suites, Komponenten und Architekturen für ein neues Profil übernehmen. Ein abweichender Port für einen direkten Rsync-Daemon wird beim vorbereiteten Profil über `--rsync-options` übernommen.

Die separate Rsync-Prüfung kann ein Rsync-Modul zusätzlich über SSH-Schlüssel testen. Dafür werden SSH-Benutzer, privater Schlüssel, SSH-Port und Hostschlüsselverhalten angegeben. SSH-Passwörter und Rsync-Daemon-Passwörter werden nicht unterstützt. HTTP/FTP-Zugangsdaten und Rsync-SSH-Anmeldung sind gegenseitig ausgeschlossen und werden bei unpassendem Protokoll bereits im Formular deaktiviert sowie im Backend abgewiesen. Zugangsdaten in der Repository-URL sind ebenfalls nicht zulässig. SSH-Werte werden nur in ein vorbereitetes Rsync-Profil übernommen.

Wenn an der Hauptadresse kein Repository gefunden wird, werden die Suchpfad-Variablen aus **System -> Generator-Einstellungen** relativ zur eingegebenen Adresse geprüft, z. B. `deb`, `debian`, `repo`, `repository`, `apt`, `packages`, `mirror`, `download` oder `public`. Bleibt auch das ohne Treffer, wird je Suchvariable zusätzlich ein direkt angehängtes `dists/` geprüft. Werden mehrere Repository-Basen gefunden, kann die gewünschte Basis im Prüfergebnis ausgewählt werden; Suites, Komponenten und Architekturen werden danach passend zu dieser Basis gefiltert. Beim Scan verwendete Zugangsdaten können verschlüsselt an das vorbereitete Profil übergeben oder im Profil neu gesetzt werden.

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

Beim Löschen eines Skripts wird der gespeicherte Aktiv-Status auf inaktiv gesetzt. Die Skriptübersicht wechselt auf kleinen Displays in eine Kartenansicht, damit Zielverzeichnis, Status und Aktionen ohne horizontales Verschieben bedienbar bleiben.

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

Der obere Master-Keyring-Block zeigt Status, Hauptkeys, Subkeys, Fingerprints, Quelldateien, Dateigröße und ausgeschlossene Keys in einer kompakten Kennzahlenübersicht. Pfad, vollständige Fingerprint-Liste und die Erläuterung der beiden Neuaufbau-Arten sind standardmäßig eingeklappt. Die Aktionen zum normalen Neuaufbau, vollständigen Neuaufbau und Neuerzeugen aller Profil-Keyrings bleiben direkt erreichbar.

Darunter zeigt die WebUI die einzelnen Master-Keys in einer kompakten, filterbaren Liste. Jeder Hauptkey kann für Details, Subkeys, Export und Profil-Zuordnung aufgeklappt werden.

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

Der Client-Export verwendet nur den Profil-Keyring des ausgewählten Mirror-Profils und enthält dadurch keine unnötigen Zusatzkeys. Vor dem Export können die Suites und Architekturen ausgewählt werden, die der Client wirklich verwenden soll. Dadurch muss ein Client nicht automatisch alle im Mirror-Profil gespiegelten Suites gleichzeitig als Paketquelle aktivieren.

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

Die Größenberechnung nutzt einen Cache. Die automatische Berechnung nach Zeitplan-Jobs bleibt zielbezogen; zusätzlich kann ein Administrator im Dashboard alle vorhandenen konfigurierten Zielverzeichnisse bewusst gemeinsam aktualisieren.

Regeln:

- einzelner Refresh betrifft nur das ausgewählte Profil oder Skriptziel
- **↻ Alle** im Dashboard fordert eine Berechnung aller vorhandenen, eindeutig aufgelösten Mirror- und Skript-Zielverzeichnisse an
- manuell gestartete Jobs lösen keine automatische Größenberechnung aus
- automatische Größenberechnung entsteht nur nach beendeten Zeitplan-Jobs
- pro beendetem Zeitplan-Job wird nur das betroffene Profil oder Skriptziel vorgemerkt
- Berechnung startet nur, wenn keine Jobs laufen oder warten
- eingestelltes Ruhefenster wird berücksichtigt
- laufende oder wartende Größenberechnungen werden in der Warteschlange sichtbar
- ein Größenwert wird nur dann als **veraltet** markiert, wenn nach seiner letzten Prüfung ein echter, nicht als Dry-Run ausgeführter Job für dasselbe Ziel beendet wurde
- die Cache-Gültigkeit steuert weiterhin automatische Aktualisierungen, markiert einen Wert aber nicht allein wegen seines Alters als veraltet

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

Sie können regelmäßig laufen und bei Fehlern Benachrichtigungen auslösen. Auf dem Dashboard werden Status, letzte Prüfung, URL und die zuletzt gemessene Latenz angezeigt. Die Healthcheck-Liste und das Bearbeitungsformular sind für schmale Displays kompakt angeordnet.

## Benachrichtigungen

Unter **Betrieb -> Benachrichtigungen** können SMTP-Mail, Telegram und Discord konfiguriert werden. Geheimwerte wie SMTP-Passwort, Telegram-Bot-Token und Discord-Webhook werden nicht im Formular angezeigt. Neue Eingaben ersetzen den gespeicherten Wert; leere Felder behalten den vorhandenen Wert. Die Verschlüsselung verwendet einen separaten Datenschlüssel unter `/app/data/notification-secrets.key`. Derselbe persistente Schlüssel schützt auch gespeicherte Remote-Passwörter von Mirror-Profilen. Er liegt im Datenverzeichnis, wird in Vollbackups aufgenommen und beim Restore vor Datenbank und Einstellungen wiederhergestellt. Bestehende ältere `enc:v1`-Werte werden beim Start auf das neue Format migriert, sofern sie mit dem bisherigen `APP_SECRET_KEY` noch entschlüsselt werden können.

## Systembereiche

### Einstellungen

Zentrale Systemeinstellungen für Jobs, Warteschlange, Log-Aufbewahrung, Dashboard-Limits, Größenberechnung, Zeitzone, Container-Prüfung und Mirror-Speicher. Sprache und Darstellung werden benutzerbezogen unter **Persönliche Einstellungen** gespeichert.

### Generator-Einstellungen

Die Seite ist in zwei gleichwertige Bereiche geteilt: links **Suchpfad-Variablen**, rechts **Generator-Konfiguration**. Auf schmalen Displays werden beide Blöcke untereinander dargestellt.

- **Suchpfad-Variablen**: ein relativer Pfad pro Zeile; nur Pfade innerhalb der geprüften Basisadresse sind zulässig. Speichern und Zurücksetzen wirken ausschließlich auf diese Liste. Die eingebauten Standardwerte werden unter dem Eingabefeld dauerhaft als Text angezeigt und müssen nicht aufgeklappt werden.
- **Generator-Konfiguration**: JSON-Definition der vorbereiteten Distributionsgruppen mit `label`, `method`, `host`, `root_path`, `releases`, `components` und `archs`. Speichern und Zurücksetzen wirken ausschließlich auf die JSON-Konfiguration.

Beide Eingaben werden serverseitig validiert. Fehler in einem Block verändern den jeweils anderen Block nicht.

### Backup / Wiederherstellen

Erstellt und verwaltet WebUI-Vollbackups. Neue Backups werden als `.dmmbackup` mit AES-256-GCM verschlüsselt; das notwendige Backup-Passwort muss mindestens zwölf Zeichen lang sein, wird nicht gespeichert und ist beim Restore erneut erforderlich. Enthalten sind Datenbank, Einstellungen, der separate Verschlüsselungs-Schlüssel für Benachrichtigungs- und Mirror-Zugangsdaten, Keyrings, Import-Skripte, Benutzerskripte sowie die verwalteten SSH-Privatschlüssel und `known_hosts`. Beim Restore wird der Verschlüsselungs-Schlüssel vor Datenbank und `settings.json` eingespielt. SSH-Verzeichnisse werden mit Modus `0700`, private Schlüssel und `known_hosts` mit `0600` wiederhergestellt. Vor dem Backup werden gespeicherte Geheimwerte geprüft; bei nicht entschlüsselbaren Werten wird das Backup abgebrochen. Alte unverschlüsselte `.zip`-Backups bleiben lesbar, werden in der Oberfläche jedoch deutlich als Legacy-Backup markiert. Der Restore begrenzt Anzahl, Einzelgröße, Gesamtgröße und Kompressionsverhältnis der Einträge und weist symbolische Links sowie Sonderdateien ab. Große Mirror-Daten unter `/mirror` werden bewusst nicht gesichert.

### Konfig Export/Import

Exportiert und importiert Konfigurationsdaten wie Mirror-Profile, Healthchecks, Zeitpläne, Generator-Konfiguration und nicht-sensitive Einstellungen. Benachrichtigungs-Geheimwerte, Remote-Passwörter und der Inhalt privater SSH-Schlüssel werden nicht in den normalen Konfigurations-Export aufgenommen. SSH-Profilzuordnungen werden exportiert; nach einem reinen Konfigurationsimport muss der referenzierte Schlüssel vorhanden sein. Für einen vollständigen Serverwechsel ist das Vollbackup vorgesehen.

### Benutzerverwaltung

Rollen:

```text
admin  volle Verwaltung
user   rein betrachtender Zugriff
```

Normale Benutzer dürfen keine kritischen Änderungen durchführen und keine Jobs starten oder stoppen. Im Bereich **System -> Benutzerverwaltung** befinden sich zusätzlich der eigene Admin-Zugang, die Passwortänderung und der Hinweis zum Shell-Notfallskript. Sprache und Darstellung können beim Anlegen oder Bearbeiten jedes Benutzers individuell gesetzt werden.

### API

API-Tokens werden nur einmal beim Erstellen angezeigt und danach gehasht gespeichert. Neue Tokens besitzen eine frei wählbare Ablaufzeit und getrennte Berechtigungen für Lesen, Mirror-Jobs starten, Benutzerskripte starten, Jobs stoppen und Healthchecks ausführen. Tokens können aktiviert, deaktiviert und gelöscht werden. Bestehende Tokens aus Versionen vor v0.1.78 werden aus Kompatibilitätsgründen als weitreichende Legacy-Tokens übernommen und sollten nach dem Update durch minimal berechtigte Tokens ersetzt werden. Die REST-Schnittstelle umfasst:

```text
GET  /api/v1/status
GET  /api/v1/mirrors
GET  /api/v1/mirrors/<id>
POST /api/v1/mirrors/<id>/run
GET  /api/v1/jobs
GET  /api/v1/jobs/<id>
POST /api/v1/jobs/<id>/stop
GET  /api/v1/user-scripts
POST /api/v1/user-scripts/<name>/run
GET  /api/v1/schedules
GET  /api/v1/healthchecks
POST /api/v1/healthchecks/<id>/run
```

Schreibende API-Aktionen prüfen dieselben Aktiv-, Rollen-, Speicher- und Konfliktsperren wie die WebUI. Verschlüsselte Passwörter und Inhalte privater SSH-Schlüssel werden nicht ausgegeben.

## Sicherheit

- keine freie Shell-Eingabe in der WebUI
- Benutzerskripte nur aus festem Verzeichnis
- Start-Sperren greifen im Backend, nicht nur in der Oberfläche
- Benutzerrollen trennen Admin- und Lesezugriff
- Benutzerpasswörter werden gehasht gespeichert
- Legacy-Adminwerte werden aus `settings.json` entfernt und in die SQLite-Benutzerverwaltung migriert
- Benachrichtigungs-Geheimwerte und Remote-Passwörter werden verschlüsselt gespeichert
- API-Tokens werden nur gehasht gespeichert
- Key-Fingerprints sollten gegen Hersteller-/Projekt-Dokumentation geprüft werden

Wichtig: Ab v0.1.67 verwendet die Anwendung für verschlüsselte Geheimwerte nicht mehr ausschließlich `APP_SECRET_KEY`, sondern den persistenten Schlüssel `/app/data/notification-secrets.key`. Ab v0.1.70 schützt dieser Schlüssel zusätzlich Remote-Passwörter von Mirror-Profilen. Er ist Bestandteil neu erstellter Vollbackups. Alte Backups ohne diesen Schlüssel können verschlüsselte Zugangsdaten nach einer Neuinstallation nur dann lesen, wenn der damalige `APP_SECRET_KEY` noch vorhanden ist; andernfalls müssen die betroffenen Geheimwerte einmal neu gesetzt und danach erneut gesichert werden.

### Sicherheitsmodell ab v0.1.78

- Die Ersteinrichtung unter `/setup` ist nach Anlage des ersten Benutzers endgültig geschlossen; URL-Parameter können sie nicht erneut öffnen.
- Jede Sitzung ist an Benutzer-ID, Benutzername, Aktivstatus und eine serverseitige Sitzungsversionsnummer gebunden. Löschen, Deaktivieren, Rollenänderung oder Passwortänderung widerrufen bestehende Sitzungen sofort.
- Der letzte aktive Administrator kann nicht gelöscht, deaktiviert oder herabgestuft werden.
- Alle schreibenden WebUI-Anfragen sind durch CSRF-Tokens geschützt. API-Aufrufe verwenden stattdessen Bearer-Tokens mit Scopes.
- Fehlgeschlagene Anmeldungen werden pro Benutzer und Quell-IP begrenzt und im Ereignisprotokoll erfasst.
- Sitzungen laufen standardmäßig nach zwölf Stunden ab. `APP_HTTPS_ONLY=1` setzt sichere Cookies und erzwingt den vorgesehenen HTTPS-Betrieb; bei einem Reverse-Proxy müssen `TRUST_PROXY_HEADERS` und `TRUSTED_HOSTS` korrekt gesetzt sein.
- Sicherheitsheader verhindern Framing, MIME-Sniffing und unnötige Browserberechtigungen. Dynamische Antworten werden nicht zwischengespeichert.
- URL-Importe und externe Webhooks blockieren standardmäßig private, lokale, Link-Local- und reservierte Zieladressen. Lokale Healthchecks müssen pro Eintrag ausdrücklich erlaubt werden; weitere interne Ziele können eng über `OUTBOUND_PRIVATE_HOST_ALLOWLIST` freigegeben werden.
- OpenPGP-Vertrauensbindungen verwenden ausschließlich vollständige 40-stellige Fingerprints. Eindeutig auflösbare ältere Kurz-IDs werden automatisch migriert, unklare Kurz-IDs entfernt und als Ereignis gemeldet.
- Die automatische Annahme neuer SSH-Hostschlüssel ist für neue Profile standardmäßig aus. Der erste Hostschlüssel sollte kontrolliert in `known_hosts` aufgenommen werden.
- Verwaltungs-, Datenbank-, Schlüssel-, Log- und Backup-Dateien werden mit restriktiver `umask` und Besitzerrechten angelegt. Der Container startet mit `no-new-privileges`, begrenzten Linux-Capabilities und PID-Limit.
- Direkter HTTP-Betrieb bleibt für abgeschottete Verwaltungsnetze technisch möglich, überträgt Zugangsdaten jedoch unverschlüsselt. Für produktive Nutzung ist ein HTTPS-Reverse-Proxy und eine Firewall-Begrenzung des WebUI-Ports erforderlich.

## Notfall: Admin-Passwort zurücksetzen

```bash
cd debmirror-manager
./set-admin-password.sh
```

Das Skript schreibt den Admin-Zugang direkt in die SQLite-Benutzerverwaltung.

## Hilfe

Die WebUI enthält eine Anleitung und separate Release Notes. Die Anleitung beschreibt die Funktionen des Projekts; die Versionshistorie steht ausschließlich in den Release Notes.
