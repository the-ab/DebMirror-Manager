# Release Notes

## v0.1.77

- Update-Kompatibilitätsfehler aus v0.1.76 behoben: `gunicorn.conf.py` liegt jetzt innerhalb von `app/` und wird dadurch auch vom älteren v0.1.75-Updater sicher übernommen.
- Dockerfile lädt die Gunicorn-Konfiguration aus `/app/app/gunicorn.conf.py`; eine separate neue Datei im Projektstamm ist für den Build nicht mehr erforderlich.
- Update aus v0.1.75 sowie aus einer nach dem fehlgeschlagenen v0.1.76-Build teilweise aktualisierten Installation unterstützt.
- Expliziten Image-Namen `debmirror-manager:latest` in Docker Compose gesetzt; die automatische Doppelbezeichnung `debmirror-manager-debmirror-manager:latest` entsteht nicht mehr.
- `install.sh` und der neue v0.1.77-Updater bereinigen die frühere doppelte Image-Bezeichnung bei späteren Rebuilds/Updates; nach dem erstmaligen Wechsel mit einem älteren Updater kann das ungenutzte Alt-Image einmalig manuell entfernt werden.
- Anleitung um Update-Wiederherstellung und eindeutige Image-Bezeichnung ergänzt.
- VERSION auf 0.1.77 gesetzt.

## v0.1.76

- Flask-/Werkzeug-Entwicklungsserver durch den produktiven WSGI-Server Gunicorn ersetzt.
- Gunicorn bewusst mit einem Worker und mehreren Threads konfiguriert, damit Scheduler, Job-Warteschlange und In-Process-Prozessstatus nicht mehrfach gestartet werden.
- Lang laufende Live-Log-Verbindungen durch deaktivierten Worker-Timeout und SSE-Heartbeats abgesichert.
- HTTP-Zugriffslog standardmäßig deaktiviert, damit periodische Live-Log-Aufrufe das Containerlog nicht füllen; über `WSGI_ACCESS_LOG=1` optional aktivierbar.
- Live-Log-Abbruch beim Jobende behoben: nicht vorhandenen Aufruf `format_job_duration()` durch die zentrale Dauerberechnung `enrich_job_duration()` ersetzt.
- Dauer, Ende-Status und Fehlerdiagnose werden nach Jobende wieder zuverlässig über das `done`-Ereignis an die offene Jobseite übertragen.
- Normale Browser-Abbrüche und Verbindungs-Resets des Live-Logs werden ohne Traceback beendet.
- SSE-Antworten um Cache-Sperre und `X-Accel-Buffering: no` ergänzt.
- `gunicorn.conf.py`, WSGI-Einstellungen, Update-Sicherung und Anleitung ergänzt.
- VERSION auf 0.1.76 gesetzt.

## v0.1.75

- Hover-Designfehler am Größen-Refresh behoben: die bisherige Drehung des Buttons konnte in der Benutzerskript-Tabelle kurzzeitig einen horizontalen Scrollbalken erzeugen.
- Refresh-Buttons direkt neben der Mirror-Größe jetzt durchgängig im Dashboard, in der Profilübersicht und in der Mirror-Detailansicht vorhanden.
- Dashboard um „Alle Größen aktualisieren“ oberhalb der Spalte Größe ergänzt.
- Die Sammelaktualisierung berücksichtigt alle vorhandenen konfigurierten Mirror- und Benutzerskript-Zielverzeichnisse, entfernt doppelte Pfade und überspringt fehlende Verzeichnisse.
- Mehr Ziele als gleichzeitig berechnet werden können, werden über die vorhandene Größenwarteschlange nacheinander verarbeitet.
- Dashboard-Tabelle: Spalten Name, Status, Art und Größe per Mausklick oder Tastatur auf- und absteigend sortierbar.
- Profilübersicht: Spalten Name, Status, Mirror-Größe und Repository per Mausklick oder Tastatur auf- und absteigend sortierbar.
- Numerische Größensortierung verwendet Bytewerte statt der formatierten Texte KiB/GiB/TiB; unbekannte Werte werden konsistent einsortiert.
- Anleitung an Sammelaktualisierung, durchgängige Refresh-Aktionen und sortierbare Tabellen angepasst.
- VERSION auf 0.1.75 gesetzt.

## v0.1.74

- Größenstatus fachlich korrigiert: `veraltet` erscheint nur, wenn nach der letzten Größenprüfung ein echter, nicht als Dry-Run ausgeführter Job für dasselbe Ziel beendet wurde.
- Reines Überschreiten der Cache-Gültigkeit markiert einen Größenwert nicht mehr als veraltet; die Gültigkeit bleibt ausschließlich für automatische Aktualisierungen relevant.
- Bezeichnung „letzter bekannter Wert“ durch die eindeutige Angabe „letzte Prüfung“ mit Zeitstempel ersetzt.
- Größenstatus an Dashboard, Profilübersicht, Mirror-Detail und Benutzerskripten einheitlich als farbige Badges dargestellt: aktuell grün, veraltet gelb.
- Dashboard: Aktualisieren-Button neben den Zielgrößen der Benutzerskripte ergänzt.
- Benutzerskripte: vorhandenen Größen-Aktualisieren-Button kompakt und einheitlich als Refresh-Symbol dargestellt.
- Generator-Einstellungen: eingebaute Standard-Suchpfade werden dauerhaft als Text angezeigt; der aufklappbare Bereich wurde entfernt.
- Anleitung an die neue Aktualitätslogik, Refresh-Funktionen und dauerhaft sichtbaren Generator-Standardwerte angepasst.
- VERSION auf 0.1.74 gesetzt.

## v0.1.73

- Dashboard: Aktualisieren-Button direkt neben jeder Mirror-Größe ergänzt.
- Größenstatus vereinheitlicht und verständlich lokalisiert; Status und Prüfzeitpunkt werden getrennt und mit erklärendem Tooltip angezeigt.
- Interne Größenstatuswerte bleiben unverändert, damit API, Cache und Hintergrundberechnung kompatibel bleiben.
- Dashboard: letzter Job von Mirror-Profilen und Benutzerskripten ist vollständig anklickbar und führt direkt zur Job-/Logseite.
- Keyrings: oberen Master-Keyring-Block in eine kompakte Kennzahlenübersicht umgebaut; Pfad, Fingerprints und Neuaufbau-Erklärung sind einklappbar.
- Generator-Einstellungen: Suchpfad-Variablen und Generator-Konfiguration nebeneinander angeordnet; responsive Darstellung für schmale Displays ergänzt.
- Anleitung vollständig gegen Navigation, WebUI-Funktionen, Größenberechnung, Keyring-Verwaltung, Generator-Einstellungen und API-Endpunkte abgeglichen.
- Release Notes vereinheitlicht: Versionsüberschriften normalisiert, doppelte Einträge entfernt und verschachtelte Listen für die WebUI-Darstellung bereinigt.
- Allgemeiner Prüfungsdurchgang für Templates, Routen, Rollenansichten, Formularziele, Statusdarstellung, Skripte und Paketstruktur durchgeführt.
- VERSION auf 0.1.73 gesetzt.

## v0.1.72

- Irreführende Rsync-Benutzer/Passwort-Anmeldung aus Profilen und Profilgenerator entfernt.
- Vorhandene v0.1.71-Rsync-Zugangsdaten werden bei der Datenbankmigration entfernt und als Ereignis protokolliert.
- SSH-Schlüsselanmeldung für Rsync-Module ergänzt: SSH-Benutzer, privater Schlüssel, Port und Hostschlüsselprüfung.
- debmirror-kompatible Umsetzung über `--rsync-options` und eine explizite `--rsh`-Remote-Shell; SSH-Benutzer wird mit `ssh -l` gesetzt.
- Private Schlüssel werden beim Upload mit `ssh-keygen` geprüft, passphrasegeschützte Schlüssel für unbeaufsichtigte Jobs abgewiesen und mit Modus `0600` gespeichert.
- Persistente `known_hosts`-Datei ergänzt; optionales `StrictHostKeyChecking=accept-new`, geänderte bekannte Hostschlüssel bleiben gesperrt.
- Profilgenerator-Zugangsdaten wieder standardmäßig eingeklappt; separate Rsync-Modulprüfung über SSH-Schlüssel ergänzt.
- `rsync://`-Scans lesen jetzt `dists/` sowie `InRelease`/`Release` aus und können daraus direkt ein Profil mit Suites, Komponenten und Architekturen vorbereiten.
- HTTP/FTP-Zugangsdaten und Rsync-SSH-Anmeldung sind im Generator gegenseitig gesperrt; Zugangsdaten in der URL sowie SSH-Portangaben in der Rsync-URL werden abgewiesen.
- Nicht bestätigte Transferarten sind bei der Profilerzeugung nicht auswählbar; bei HTTP/FTP ohne erreichbaren Rsync-Zusatztransfer wird `Rsync Extra` automatisch auf `none` gesetzt.
- Abweichende direkte Rsync-Daemon-Ports werden beim Erzeugen eines Rsync-Profils sicher in `--rsync-options` übernommen.
- Host- und Modulpfadvalidierung gilt für alle Rsync-Profile und verhindert Ports im Host-Feld, Pfadtraversal, absolute Pfade und Shell-Sonderzeichen.
- Zeitplan-Uhrzeiten werden beim Speichern strikt als gültiges `HH:MM` geprüft; widersprüchliche Importprofile durchlaufen dieselbe zentrale Profilvalidierung.
- Konfliktprüfung erweitert: Methode/Optionen, GPG-Schalter, Diff/Gzip/Slow-CPU, Bereinigungsmodi und Rsync-Paketoptionen.
- Ungültige Standardprofil-Kombination `HTTP + --passive` entfernt.
- SSH-Schlüssel und `known_hosts` in Vollbackup/Restore aufgenommen; sichere Dateirechte werden wiederhergestellt.
- Normaler Konfigurations-Export enthält SSH-Zuordnung, aber keinen Schlüsselinhalt; API zeigt nur Schlüsselstatus und Fingerprint.
- Docker-Image um `openssh-client` ergänzt; Laufzeitdiagnose prüft `ssh` und `ssh-keygen`.
- Anleitung und Beschriftungen aktualisiert.
- VERSION auf 0.1.72 gesetzt.

## v0.1.71

- Zugangsdaten im Profilgenerator standardmäßig sichtbar geöffnet und eindeutig für HTTP/HTTPS, FTP und rsync beschriftet.
- Profilgenerator prüft geschützte rsync-Daemons mit Benutzername und temporärer Passwortdatei.
- Mirror-Profile erlauben Remote-Benutzer und verschlüsselte Passwörter jetzt auch bei der Methode `rsync`.
- Rsync-Benutzer wird über die geschützte debmirror-Konfiguration an das Rsync-Ziel übergeben.
- Rsync-Passwort wird nicht über `--passwd`, Prozessumgebung oder Klartextargumente übergeben, sondern über eine temporäre Datei mit Modus `0600`.
- Vorhandene `--rsync-options` werden bei der Jobausführung um die temporäre Passwortdatei ergänzt.
- Temporäre Rsync-Passwortdateien werden nach Jobende und beim Start als Altdateien bereinigt.
- Hinweise grenzen rsync-Daemon-Authentifizierung klar von Rsync über SSH ab.
- Anleitung und Beschriftungen aktualisiert.
- VERSION auf 0.1.71 gesetzt.

## v0.1.70

- Mirror-Profile um optionale Remote-Anmeldung mit separatem Benutzer- und Passwortfeld erweitert.
- Remote-Passwörter werden mit dem persistenten Datenschlüssel verschlüsselt in SQLite gespeichert und im Formular nicht zurückgegeben.
- Jobausführung übergibt Zugangsdaten über eine temporäre debmirror-Konfigurationsdatei mit Modus `0600`; Prozessanzeige, Job-Datenbank und Logs enthalten kein Klartextpasswort.
- Temporäre Auth-Dateien werden nach dem Job entfernt; veraltete Restdateien werden beim Start bereinigt.
- Profilgenerator um optionale HTTP-Basic-/FTP-Zugangsdaten erweitert und kann diese verschlüsselt an ein vorbereitetes Profil übergeben.
- Bei Zugangsdaten wird kein automatischer HTTPS-zu-HTTP-Fallback ausgeführt.
- Transportfehler des Profilgenerators werden vor der Statusausgabe von FTP-Zugangsdaten bereinigt.
- Validiertes Expertenfeld für manuelle, noch nicht in der Auswahl enthaltene debmirror-Optionen ergänzt.
- Normale Konfigurations-Exporte enthalten Remote-Benutzer und manuelle Optionen, aber keine Remote-Passwörter.
- Vollbackup-Prüfung berücksichtigt zusätzlich verschlüsselte Remote-Passwörter von Mirror-Profilen.
- API-Ausgabe entfernt verschlüsselte Remote-Passwortwerte und zeigt nur `remote_password_set`.
- Anleitung und Beschriftungen aktualisiert.
- VERSION auf 0.1.70 gesetzt.

## v0.1.69

- Mirror-Profil: `Rsync Extra` durch Auswahl der gültigen Werte `doc`, `indices`, `tools`, `trace` und `none` ersetzt.
- Mirror-Profil: zusätzliche debmirror-Flags als kontrollierte Auswahlliste umgesetzt; Optionen mit Parameter erhalten ein zugehöriges Eingabefeld.
- Erweiterte Validierung für zusätzliche Optionen, Zahlenwerte, Konflikte und sicherheitsrelevante Schalter ergänzt.
- Frühere fälschlich im Feld `Rsync Extra` gespeicherte Rsync-Parameter werden beim Bearbeiten zu `--rsync-options` migriert beziehungsweise beim Start kompatibel behandelt.
- Include-/Exclude-Patterns mit verständlichen Beispielen ergänzt.
- Benutzerskripte, Healthchecks und Benutzerliste für mobile Geräte als Kartenansicht optimiert.
- Healthcheck-Formular auf schmalen Displays kompakter gestaltet.
- `Admin-Zugang` aus den allgemeinen Einstellungen in die `Benutzerverwaltung` verschoben.
- Menüeintrag `Benutzer` in `Benutzerverwaltung` umbenannt.
- Anleitung und Beschriftungen an die neue Struktur angepasst.
- VERSION auf 0.1.69 gesetzt.

## v0.1.68

- Release-ZIP enthält das Projekt jetzt im obersten Ordner `debmirror-manager/`; normales `unzip` erzeugt dadurch direkt den Projektordner.
- `update.sh` bleibt mit alten flachen und neuen ZIPs mit Projektordner kompatibel.
- Vollbackups speichern Dateirechte zusätzlich in `permissions.json`.
- Restore wendet Unix-Rechte aus ZIP-Metadaten und `permissions.json` wieder an; ausführbare Benutzerskripte bleiben dadurch ausführbar.
- Kompatibilitäts-Fallback für ältere oder neu gepackte Backups ergänzt, deren Skript-Rechte fehlen.
- Navigation und Seitenbeschriftungen geprüft und vereinheitlicht, unter anderem `Benachrichtigungen` und `Generator-Einstellungen`.
- README-Navigation an die tatsächlichen Menübereiche angepasst und Backup-/Restore-Beschreibung ergänzt.
- VERSION auf 0.1.68 gesetzt.

## v0.1.67

- Benachrichtigungs-Geheimwerte verwenden jetzt einen separaten persistenten Datenschlüssel unter `data/notification-secrets.key` statt ausschließlich `APP_SECRET_KEY`.
- Vollbackups sichern den Datenschlüssel und Restores spielen ihn vor `settings.json` wieder ein.
- Bestehende `enc:v1`-Geheimwerte werden beim Start auf das neue backup-sichere Format migriert, sofern sie noch entschlüsselbar sind.
- Backups werden abgebrochen, wenn gespeicherte Benachrichtigungs-Geheimwerte nicht entschlüsselt werden können.
- Benachrichtigungsseite zeigt einen Warnhinweis bei nicht lesbaren Geheimwerten.
- Dashboard-Healthchecks zeigen zusätzlich die zuletzt gemessene Latenz.
- Master-Keyring-Liste kompakter gestaltet: filterbare, einklappbare Hauptkey-Einträge mit Detailansicht.
- VERSION auf 0.1.67 gesetzt.

## v0.1.66

- Client-Export: Suites können vor dem Export ausgewählt werden.
- Client-Export: Architekturen können vor dem Export ausgewählt werden.
- Exportierte Deb822-`.sources`-Datei und klassische `.list`-Datei enthalten nur die ausgewählten Suites und Architekturen.
- Client-Export-README enthält die ausgewählten Suites und Architekturen.
- VERSION auf 0.1.66 gesetzt.

## v0.1.65

- Profilgenerator: gefundene Repository-Basen sind jetzt auswählbar; Suites, Komponenten und Architekturen werden passend zur ausgewählten Basis gefiltert.
- Profilgenerator: versteckte Profilwerte wie Source-URL und Root-Pfad werden beim Wechsel der Repository-Basis aktualisiert.
- Keyserver-Imports werden jetzt zusätzlich als eigene Quelldateien unter `keyrings/keyserver/` gespeichert.
- Master-Keyring-Neuaufbau liest jetzt Archiv- und Keyserver-Quelldateien ein.
- Keyrings-Seite: Unterschied zwischen normalem und vollständigem Master-Keyring-Neuaufbau klarer beschrieben.
- Import-/Quelldatei-Übersicht zeigt jetzt Archiv- und Keyserver-Quellen getrennt an.
- VERSION auf 0.1.65 gesetzt.

## v0.1.64

- Profilgenerator: vorbereitete Profile speichern jetzt korrekt über den normalen Pfad `/mirrors/new`.
- Formularziel für aus Repository-Scan und Standardgenerator vorbereitete Profile korrigiert.
- Behebt den Fall, dass beim Klick auf „Speichern“ erneut nur die Generator-Vorbereitung angezeigt wurde und kein Mirror-Profil angelegt wurde.
- VERSION auf 0.1.64 gesetzt.

## v0.1.63

- Dokumentation und Formatierung geprüft.
- Doppelte Zwischenüberschrift `Release Notes` vor v0.1.45 entfernt.
- Versionsüberschriften in dieser Datei auf ein einheitliches Format gebracht.
- README auf Funktionsbeschreibung geprüft und Versionsstand auf 0.1.63 gesetzt.
- VERSION auf 0.1.63 gesetzt.

## v0.1.62

- Fehlerdiagnose: Fingerprint-/Key-ID-Auflösung für Master- und Archiv-Keyrings robuster gemacht.
- NO_PUBKEY, ERRSIG, EXPKEYSIG, REVKEYSIG und BADSIG werden jetzt als Key-relevante Fehler ausgewertet.
- Master-Keyring-Abgleich nutzt zusätzlich Kurz-ID, Long-ID, Hauptkey-Fingerprint und Subkey-Fingerprint.
- Archiv-Keyring-Abgleich nutzt bei Master-Treffern auch alle Archiv-Fingerprints/Subkeys als Crosscheck.
- Behebt Fälle, in denen ein vorhandener Key beim Keyserver-Import als bereits vorhanden erkannt wurde, aber in der Fehlerdiagnose nicht zur Auswahl stand.
- VERSION auf 0.1.62 gesetzt.

## v0.1.61

- Fehlerdiagnose: Archiv-Keyring-Treffer werden jetzt zusätzlich über den passenden Master-Hauptkey abgeglichen. Wenn ein Subkey im Master erkannt wird und die Archivdatei denselben Hauptkey enthält, wird die Archivdatei weiterhin als Treffer angezeigt.
- Archivübersicht: Subkey-/Fingerprint-Anzeige wird bei vorhandenem Master-Keyring mit der Master-Sicht ergänzt, damit Archiv- und Master-Anzeige konsistenter sind.
- Profilansicht: die mobile/kompakte Änderung aus v0.1.60 für den Profil-Keyring-Block wurde zurückgenommen.
- Profilübersicht: Status-Badges bleiben ohne Zeilenbruch; die Tabelle wurde für mobile Geräte als Kartenansicht optimiert.
- README bereinigt: die Anleitung enthält keine eingebettete Release-Historie mehr, sondern beschreibt wieder die Funktionen des gesamten Projekts.
- VERSION auf 0.1.61 gesetzt.

## v0.1.60

- Fehlerdiagnose: Archiv-Keyring-Erkennung robuster gemacht. Archivdateien werden jetzt über mehrere GPG-Lesewege ausgewertet, damit Subkeys/Fingerprints nicht fehlen, wenn sie im Master-Keyring bereits korrekt erkannt werden.
- Fehlerdiagnose: Archiv-Keyring-Treffer nutzen zusätzliche GPG-Fallbacks für kurze Signing-Subkey-IDs.
- Profilansicht: Profil-Keyring-Status kompakter dargestellt, ohne Zeilenbruch in der Status-/Aktionszeile.
- Profilansicht: Profil-Keyring-Block für mobile Ansichten optimiert.

## v0.1.59

- Fehlerdiagnose gleicht fehlende GPG-Key-IDs jetzt zusätzlich per direkter GnuPG-Abfrage gegen den Master-Keyring ab.
- Behebt Fälle, in denen ein Key im Master-Keyring vorhanden war, aber wegen einer kurzen Signing-Subkey-ID nicht zur Auswahl angeboten wurde.
- Wenn ein passender Key sowohl im Archiv als auch im Master-Keyring vorhanden ist, wird jetzt bevorzugt der Master-Keyring-Treffer zur direkten Profil-Zuordnung angeboten.
- Archivtreffer bleiben als Fallback sichtbar.
- VERSION auf 0.1.59 gesetzt.

## v0.1.58

- Fehlerdiagnose bei fehlenden GPG-Keys klarer getrennt:
- Master-Keyring-Treffer werden in einem eigenen Block angezeigt.
- Archiv-Keyring-Treffer werden in einem eigenen Block angezeigt.
- erwarteter Fingerprint/Key-ID und tatsächlich gefundener Haupt-/Subkey werden getrennt sichtbar.
- Mehrfachauswahl vereinfacht:
- Einzel-Buttons pro Fingerprint entfernt.
- nur noch ein Button „Ausgewählte Keys übernehmen + Profil-Keyring erzeugen“.
- ausgewählte Master- und Archivtreffer werden gemeinsam verarbeitet.
- Checkbox-Auswahl stabilisiert:
- manuell abgewählte Treffer bleiben abgewählt, auch wenn die Live-Fehlerdiagnose erneut gerendert wird.
- verhindert das automatische erneute Auswählen aller Treffer nach Fokuswechsel/Refresh.
- VERSION auf 0.1.58 gesetzt.

## v0.1.57

- Fehlerauswertung bei fehlenden GPG-Keys erweitert:
- Master-Keyring-Treffer werden jetzt auch gefunden, wenn im Log nur ein Signing-Subkey oder eine kurze Key-ID gemeldet wird.
- der gefundene Subkey wird auf den passenden Hauptkey im Master-Keyring abgebildet.
- daraus wird weiterhin ein bereinigter Profil-Keyring erzeugt, nicht der komplette Master-Keyring zugewiesen.
- Mehrfachzuordnung ergänzt:
- mehrere benötigte Fingerprints können in der Fehlerauswertung gemeinsam ausgewählt werden.
- ausgewählte Keys werden in einem Schritt dem Mirror-Profil zugeordnet.
- danach wird der Profil-Keyring einmal neu erzeugt.
- Archiv-Treffer werden beim Zuweisen zuerst in den Master-Keyring importiert und danach ebenfalls als Fingerprint-Zuordnung gespeichert.
- VERSION auf 0.1.57 gesetzt.

## v0.1.56

- Master-Keyring-Status erweitert:
- Hauptkeys, Subkeys und Gesamt-Fingerprints werden getrennt angezeigt.
- Archivdateien und daraus erkannte Hauptkey-Fingerprints werden angezeigt.
- entfernte/ausgeschlossene Fingerprints werden sichtbar gemacht.
- Neuer Button „Vollständig neu aufbauen“:
- baut den Master-Keyring aus allen Archivdateien neu auf.
- entfernt vorherige Entfernsperren, falls bewusst gelöschte Keys wieder importiert werden sollen.
- Normales „Master-Keyring neu aufbauen“ behält das bisherige Schutzverhalten bei und importiert bewusst entfernte Keys nicht automatisch erneut.
- Archivübersicht zeigt Hauptkeys und Subkey-Anzahl getrennt an.

## v0.1.55

- Profil-Keyrings: Button „Profil-Keyring gezielt erzeugen“ in „Profil-Keyring erzeugen“ umbenannt.
- Profil-Keyrings: „Profil-Keyring neu erzeugen“ ist deaktiviert, solange noch kein Profil-Keyring bzw. keine Key-Zuordnung vorhanden ist.
- Dashboard: Mirror-Status zeigt jetzt „no key“, wenn kein Keyring zugeordnet oder kein Profil-Keyring erzeugt ist.
- VERSION auf 0.1.55 gesetzt.

## v0.1.54

- Profil-Keyring-Entfernen korrigiert: Master-Fingerprint-Zuordnungen werden jetzt wirklich entfernt, statt durch das alte Feld „Master-Keyring“ wieder erhalten zu bleiben.
- Profilformular und neue Fingerprint-Zuordnung synchronisiert: Wenn im Profilformular „Kein zusätzlicher Keyring“ gespeichert wird, werden auch die zentralen Profil-Keyring-Zuordnungen und erzeugten Profil-Keyring-Dateien entfernt.
- Aktuell erzeugte Profil-Keyrings bleiben im Profilformular als ausgewählter Wert sichtbar, damit sie bei normalen Profiländerungen nicht versehentlich entfernt werden.
- VERSION auf 0.1.54 gesetzt.

## v0.1.53

- Fehlerauswertung bei fehlenden GPG-Keys korrigiert:
- Treffer aus dem Master-Keyring werden nicht mehr als komplette Keyring-Datei zugewiesen.
- der passende Fingerprint wird direkt dem Mirror-Profil zugeordnet.
- danach wird automatisch ein bereinigter Profil-Keyring erzeugt.
- behebt die Meldung „Der ausgewählte Keyring enthält den erwarteten Fingerprint nicht.“ beim Klick auf „vorhandenen Keyring zuweisen“.
- Anzeige in der Fehlerauswertung präzisiert:
- Button jetzt „Master-Key zuweisen + Profil-Keyring erzeugen“ bei Master-Treffern.
- Archiv-Treffer werden getrennt als Archiv-Key angezeigt.
- VERSION auf 0.1.53 gesetzt.

## v0.1.52

- Master-Keyring-Verwaltung erweitert:
- einzelne Keys können aus dem Master-Keyring entfernt werden.
- das Entfernen wird blockiert, wenn der Key noch einem Mirror-Profil zugeordnet ist.
- entfernte Fingerprints werden gemerkt und beim späteren Neuaufbau nicht automatisch wieder aus Archivdateien importiert.
- Archivverwaltung ergänzt:
- archivierte Importdateien können jetzt einzeln gelöscht werden.
- zugehörige Archiv-Metadaten werden beim Löschen bereinigt.
- der aktuelle Master-Keyring bleibt beim Löschen einer Archivdatei unverändert.
- Keyring-Oberfläche ergänzt:
- Button „Aus Master entfernen“ pro Master-Key.
- Button „Archivdatei löschen“ pro archivierter Importdatei.
- VERSION auf 0.1.52 gesetzt.

## v0.1.51

- Master-Keyring-Status korrigiert:
- Key-Anzahl und Key-Details werden jetzt mit `gpg --no-default-keyring --keyring ... --list-keys` aus der echten Master-Keyring-Datei gelesen.
- dadurch wird nach „Master-Keyring neu aufgebaut“ nicht mehr fälschlich `Keys 0` angezeigt.
- Keyring-Verwaltung umgestellt:
- Hauptübersicht zeigt jetzt die Keys im Master-Keyring.
- einzelne Importdateien werden nach dem Import als Archiv-/Quelldateien behandelt.
- neue Importdateien werden unter `keyrings/archive/` abgelegt und nicht mehr als aktive Keyrings gelistet.
- Profil-Zuordnung verbessert:
- Zuordnung erfolgt direkt per Fingerprint aus dem Master-Keyring.
- Mirror-Detailseite nutzt die Master-Key-Liste für die Fingerprint-Auswahl.
- Profil-Keyrings und Client-Exports bleiben dadurch auf die wirklich zugeordneten Keys begrenzt.
- VERSION auf 0.1.51 gesetzt.

## v0.1.50

- Master-Keyring ergänzt:
- alle importierten Keyrings werden zusätzlich in einen zentralen Master-Keyring importiert.
- vorhandene Key-Dateien bleiben als Verwaltungs-/Importdateien erhalten.
- der Master-Keyring kann in der Keyring-Verwaltung neu aufgebaut werden.
- Profil-Keyring-Erzeugung umgebaut:
- keine einfache Kopie ganzer Keyring-Dateien mehr.
- zugeordnete Fingerprints werden gezielt aus dem Master-Keyring exportiert.
- Profil-Keyrings enthalten dadurch nur noch die Keys, die dem jeweiligen Mirror-Profil zugeordnet sind.
- alte Dateizuordnungen ohne Fingerprint bleiben kompatibel und werden als Altzuordnung angezeigt.
- Client-Export verbessert:
- verwendet den bereinigten Profil-Keyring.
- Export-ZIP enthält damit nur die für dieses Mirror-Profil benötigten Keys.
- Mirror-Detailseite erweitert:
- Zuordnung einzelner Fingerprints möglich.
- Profil-Keyrings können aus den Fingerprint-Zuordnungen neu erzeugt werden.
- VERSION auf 0.1.50 gesetzt.

## v0.1.49

- Keyring-Zuordnung zu Mirror-Profilen erweitert:
- Keyrings können direkt aus der Keyring-Verwaltung einem Profil zugeordnet werden.
- Mirror-Detailseite enthält einen eigenen Block für Profil-Keyrings.
- Mehrere Keys pro Profil sind möglich.
- Automatische Profil-Keyrings ergänzt:
- aus den zugeordneten Keys wird ein generierter Profil-Keyring unter `keyrings/profiles/` erstellt.
- debmirror verwendet diesen Profil-Keyring automatisch.
- Profil-Keyring kann manuell neu erzeugt werden.
- Migration ergänzt:
- alte direkte Keyring-Pfade werden als Profil-Zuordnung sichtbar gemacht.
- ungenutzte Keyrings werden markiert.
- Zuordnungen werden im Konfig-Export/-Import berücksichtigt.
- VERSION auf 0.1.49 gesetzt.

## v0.1.48

- Keyring-Import erweitert:
- Datei-, URL- und Textimport können vor dem Speichern geprüft werden.
- Import-Vorschau zeigt UID, Key-ID, Fingerprint, Algorithmus, Erstellung, Ablauf, Status und Subkeys.
- Duplikaterkennung per Fingerprint ergänzt.
- Importierte Fingerprints werden zusätzlich als zentrale Metadaten in `settings.json` gepflegt.
- vorhandene Keyring-Dateien werden beim Import nicht mehr automatisch überschrieben.
- VERSION auf 0.1.48 gesetzt.

## v0.1.47

- Keyrings-Seite korrigiert:
- Internal Server Error durch Jinja-Konflikt mit `k.keys` behoben.
- Key-Detailtabelle nutzt jetzt ein eindeutiges Datenfeld.
- VERSION auf 0.1.47 gesetzt.

## v0.1.46

- Keyring-Verwaltung erweitert:
- UID, Key-ID, Fingerprint, Algorithmus, Erstellung, Ablauf und Status werden angezeigt.
- Anzeigename, Quelle, Notiz und Aktiv-Marker können pro Keyring gespeichert werden.
- Zuordnung zu Mirror-Profilen wird direkt in der Keyring-Übersicht angezeigt.
- einzelne Keyrings und einzelne Hauptkeys können als `.gpg` oder `.asc` exportiert werden.
- Client-Export pro Mirror-Profil ergänzt:
- erzeugt ZIP mit Keyring, Deb822-Quelle, klassischer `.list` und README.
- Client-Basis-URL wird beim Export abgefragt.
- `VERSION` geprüft: 0.1.46.

## v0.1.45

- Dashboard: Status-Badges mit Job-ID (`aktiv #ID`, `queue #ID`, weitere Jobzustände) sind jetzt direkt anklickbar und öffnen den zugehörigen Job.
- Normale Mirror-Starts werden zentral blockiert, wenn das Profil deaktiviert oder offensichtlich fehlerhaft ist.
- Dry-Run bleibt für deaktivierte Mirror-Profile weiterhin startbar.
- Start-Schaltflächen für gesperrte Mirror-Profile werden deaktiviert und als durchgestrichen angezeigt.
- Benutzerskripte besitzen jetzt einen gespeicherten Aktiv-Status in `settings.json`.
- Deaktivierte oder nicht ausführbare Benutzerskripte können nicht mehr manuell oder per Zeitplan gestartet werden.
- Beim Löschen eines Benutzerskripts wird dessen Aktiv-Status auf inaktiv gesetzt.
- Zeitpläne: Die Job-Zeitplanliste steht jetzt direkt unter **Aktuelle Regeln**.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.45.

## v0.1.44

- Dashboard: Statusanzeige in der gemeinsamen Tabelle **Mirror-Profile / Benutzerskripte** vereinheitlicht.
- Kein laufender oder wartender Job wird jetzt als `idle` angezeigt.
- Laufende, startende oder stoppende Jobs werden als `aktiv #ID` angezeigt.
- Wartende Jobs werden als `queue #ID` angezeigt.
- Nicht startfähige Einträge werden als `error` angezeigt, z. B. bei nicht ausführbarem Benutzerskript oder offensichtlich unvollständigem Mirror-Profil.
- Mobile Darstellung der gemeinsamen Mirror-/Script-Tabelle optimiert: Tabellenzeilen werden auf kleinen Displays als kompakter Kartenblock dargestellt.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.44.

## v0.1.43

- Dashboard-Bearbeitung verbessert: Blockbreiten werden jetzt feiner über ein 12-Spalten-Raster gespeichert.
- Größenänderung über den Griff unten rechts passt jetzt Breite und Höhe an.
- Bei vergrößerter Blockhöhe wachsen interne Scrollbereiche von Tabellen-, Job-, Ereignis- und Healthcheck-Blöcken mit.
- Dashboard-Layout-Speicherung in `settings.json` wurde um gespeicherte Blockbreiten erweitert.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.43.

## v0.1.42

- Dashboard-Bearbeitung überarbeitet: Blöcke werden jetzt per Maus/Drag & Drop verschoben.
- Blockgröße kann im Bearbeitungsmodus über einen Griff unten rechts verändert werden.
- Dashboard-Layout wird zentral in `settings.json` gespeichert statt nur lokal im Browser.
- Neue Backend-Endpunkte für Laden, Speichern und Zurücksetzen des Dashboard-Layouts ergänzt.
- Dashboard-Bearbeitung ist wegen der zentralen Einstellung nur noch für Admin-Benutzer sichtbar.
- Menü angepasst: **Profilgenerator** steht im Bereich **Mirror** jetzt direkt unter **Profile**.
- Kopfzeile angepasst: **Mirror-Basis**, **Zeit** und **Auth** stehen jetzt oben neben dem Benutzer; die untere Statuszeile wurde entfernt.
- Dashboard-Tabelle nutzt für Mirror/Profile und Script jetzt die Spalte **Art**.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.42.

## v0.1.41

- Navigation angepasst: **Benutzerskripte** wurden in den Bereich **Mirror** verschoben.
- **Generator-Einstellungen** wurden aus **Mirror** entfernt und in den Bereich **System** verschoben.
- Dashboard: Mirror-Profile und Benutzerskripte werden jetzt in einer gemeinsamen Tabelle angezeigt.
- In der gemeinsamen Tabelle wurde die neue Spalte **Typ** ergänzt; Einträge werden als **Mirror** oder **Script** gekennzeichnet.
- Dashboard-Kachel **Profile / Benutzerskripte** bereinigt: Die Bezeichnungen **Mirror-Profile** und **Benutzerskripte** sind direkt anklickbar, die zusätzliche Linkzeile darunter wurde entfernt.
- Dashboard-Bearbeitungsmodus ergänzt: Über **Dashboard bearbeiten** können Blöcke verschoben und auf **Normal**, **Breit** oder **Voll** gesetzt werden.
- Das Dashboard-Layout wird lokal im Browser gespeichert und kann über **Layout zurücksetzen** zurückgesetzt werden.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.41.

## v0.1.40

- Profilgenerator: Zusatzprüfung für Suchpfad-Variablen mit direkt angehängtem `dists/` ergänzt.
- Wenn Hauptadresse und normale Suchpfad-Variablen kein Repository liefern, prüft der Scanner nun zusätzlich z. B. `<basis>/<variable>/dists/`.
- Direkt gefundene `dists/`-Verzeichnisse werden jetzt als Repository-Struktur erkannt; die aktive Repository-Basis wird dabei automatisch auf die Ebene oberhalb von `dists/` gesetzt.
- Live-Status zeigt die neue Zusatzprüfung inklusive vollständiger Prüf-URL an.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.40.

## v0.1.39

- Profilgenerator: Protokoll-Fallback für Eingaben ohne Schema korrigiert.
- Wenn der Benutzer z. B. nur `ftp.at.debian.org` eingibt, wird weiterhin zuerst HTTPS geprüft; falls dort kein Repository gefunden wird, wird die Inhaltsprüfung zusätzlich mit HTTP wiederholt.
- Wird das Repository über HTTP gefunden, wird die aktive Repository-Basis auf HTTP gesetzt und kann direkt für die Profilerzeugung genutzt werden.
- Transferprüfung bleibt erhalten und zeigt HTTP, HTTPS und rsync getrennt an.
- Suchpfad-Variablen wurden wieder aus dem direkten Profilgenerator-Scanformular entfernt.
- Suchpfad-Variablen bleiben zentral unter `Mirror -> Generator-Einstellungen` bearbeitbar und werden beim Scan aus diesen Einstellungen verwendet.
- Live-Status zeigt jetzt an, wenn wegen fehlender Protokollangabe ein HTTP-Fallback-Scan gestartet wird.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.39.

## v0.1.38

- Profilgenerator: Suchpfad-Variablen sind jetzt direkt im Repository-Scan sichtbar und bearbeitbar.
- Live-Scan übergibt die Suchpfad-Variablen jetzt zuverlässig an das Backend und speichert geänderte Werte.
- Suchpfad-Variablen werden relativ zur eingegebenen Repository-Adresse geprüft und im Live-Status mit kompletter Prüf-URL ausgegeben.
- Korrektur: Fallback-Pfade wie `deb/`, `debian/`, `repo/` und `repository/` werden beim Scan nachvollziehbar an die Basisadresse angehängt.
- CSS für das neue Suchpfad-Feld im Profilgenerator ergänzt.

## v0.1.37

- Profilgenerator um konfigurierbare Suchpfad-Variablen erweitert. Standardwerte sind unter anderem `deb`, `debian`, `repo`, `repository`, `apt`, `packages`, `mirror`, `download` und `public`.
- Wenn an der Hauptadresse kein verwendbares Repository gefunden wird, prüft der Scanner automatisch diese zusätzlichen relativen Pfade innerhalb der eingegebenen Basisadresse.
- Unter `Mirror -> Generator-Einstellungen` können Suchpfad-Variablen zeilenweise ergänzt, gespeichert oder auf Standard zurückgesetzt werden.
- Live-Scan kann jetzt über **Prüfung stoppen** abgebrochen werden. Der Scanner setzt ein Abbruchsignal und stoppt nach dem laufenden HTTP-/rsync-Prüfschritt.
- Live-Statusausgabe zeigt zusätzlich, wenn die Hauptprüfung ohne Ergebnis blieb und die Suchpfad-Variablen geprüft werden.
- Konfigurations-Export/-Import enthält jetzt auch die Suchpfad-Variablen des Profilgenerators.
- Geplante Erweiterungen aus dem Profilgenerator-Ausbau wurden in die erste Ausbaustufe übernommen: automatische Pfadsuche, HTML-Verzeichnislisting-Auswertung, rsync-Transferprüfung, GPG-Key-Erkennung und genauere Warnungen.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.37.

## v0.1.36

- Profilgenerator-Prüfung um eine echte Live-Statusausgabe erweitert: Der Scan läuft im Hintergrund und die WebUI zeigt fortlaufend neue Prüfschritte an.
- Neue Scan-Status-Endpunkte ergänzt, damit die Ausgabe während der Prüfung per Polling aktualisiert wird.
- Erkennung für normale `dists/<suite>/InRelease`-Repository-Strukturen korrigiert, wenn der Scanner direkt auf eine Suite wie `dists/stable/` stößt.
- `dists/`-Verzeichnisse ohne auswertbares Listing werden jetzt zusätzlich mit typischen Suite-Namen wie `stable`, `testing` oder `unstable` direkt geprüft.
- Normale APT-Repositories werden dadurch nicht mehr versehentlich als flache APT-Struktur eingestuft, wenn `dists/<suite>/InRelease` erreichbar ist.
- Statusausgabe und Hinweise im Profilgenerator aktualisiert.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.36.

## v0.1.35

- Profilgenerator-Prüfung um ein sichtbares Statusfenster mit detaillierter Ausgabe ergänzt.
- Verzeichnistiefe für Repository-Scans ist jetzt einstellbar; Standardwert ist `5`, maximal `10`.
- Der Repository-Scan durchsucht begrenzt Unterverzeichnisse innerhalb der eingegebenen Basisadresse und prüft dort mögliche `dists/`-Repository-Basen.
- Gefundene Repository-Basen werden im Prüfergebnis zusätzlich aufgelistet.
- GPG-Key-Suche berücksichtigt nun auch Links und typische Key-Pfade aus den gescannten Verzeichnissen.
- Flache APT-Strukturen können ebenfalls in tiefer liegenden Verzeichnissen erkannt werden.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.35.

## v0.1.34

- Profilgenerator um allgemeinen Repository-Scan erweitert.
- URL-Prüfung ist nicht auf Debian oder Ubuntu beschränkt und erkennt generische APT-Strukturen über `dists/`, `Release`, `InRelease` und `Packages`-Dateien.
- Gefundene Suites, Komponenten und Architekturen werden aufgelistet und können zur Profilerzeugung ausgewählt werden.
- HTTP/HTTPS werden geprüft; rsync wird soweit möglich als Transferart getestet.
- Mögliche GPG-Key-Dateien werden an typischen Speicherorten und über Verzeichnislinks gesucht und im Prüfergebnis angezeigt.
- Flache APT-Repositories werden erkannt und mit Hinweis angezeigt; automatische Profilerzeugung bleibt dafür vorerst deaktiviert.
- Der bisherige Standardgenerator bleibt erhalten.
- Anleitung und Release Notes aktualisiert.
- `VERSION` geprüft: 0.1.34.

## v0.1.33

- Größenberechnung nach Jobs neu aufgebaut: Manuell gestartete Jobs lösen keine automatische Größenberechnung mehr aus.
- Automatische Größenberechnungen werden nur noch nach beendeten Zeitplan-Jobs vorgemerkt.
- Pro beendetem Zeitplan-Job wird nur das konkrete Ziel markiert: genau dieses Mirror-Profil oder genau dieses Benutzerskript-Zielverzeichnis.
- Die automatische Berechnung startet erst, wenn keine Jobs laufen oder warten und innerhalb des eingestellten Ruhefensters kein weiterer geplanter Job fällig ist.
- Während laufender oder wartender Jobs startet keine Größenberechnung; manuelle Berechnungen werden für genau das gewählte Ziel wartend eingetragen.
- Die frühere Sammellogik über den letzten Mirror-Job wurde entfernt, damit nicht mehr alle Profile berechnet werden.
- Dashboard-Kachel **Warteschlange** zeigt jetzt zusätzlich laufende, wartende und vorgemerkte Größenberechnungen.
- Dashboard-Kachel **Profile** wurde in **Profile / Benutzerskripte** zweigeteilt.
- Anleitung und Release Notes auf die neue Marker-/Ruhefenster-Logik aktualisiert.
- `VERSION` geprüft: 0.1.33.

## v0.1.32

- **Benutzerskripte -> Vorhandene Skripte**: Button **Größe neu berechnen** steht jetzt direkt rechts neben Status/Stand der letzten Größenberechnung.
- Die Zielverzeichnis-Eingabe bleibt darunter separat und kompakt.
- **System -> Einstellungen**: Optionen **Speicherplatz-Sperre für Mirror-Jobs** und **Grenzwert Mirror-Speichernutzung in Prozent** wurden aus **Jobs / Warteschlange / Logs** in den Block **Mirror-Speicher** verschoben.
- Neuer eigener Speichern-Button im Block **Mirror-Speicher** für diese beiden Speicher-Sperrwerte.
- Anleitung auf die geänderte Platzierung geprüft und aktualisiert.
- `VERSION` geprüft: 0.1.32.

## v0.1.31

- Gespeicherte Einträge in der **Job-Zeitplanliste** können jetzt einzeln aktiviert oder deaktiviert werden.
- Zeitpläne aus Mirror-Profilen werden beim Speichern automatisch als **Profilzeitplan** in der Job-Zeitplanliste angelegt oder aktualisiert.
- Wird ein Profilzeitplan über die Job-Zeitplanliste gelöscht, wird das zugehörige Mirror-Profil automatisch auf **Manuell** gestellt.
- Profilzeitpläne sind in der Job-Zeitplanliste sichtbar gekennzeichnet.
- Die Zeitplanliste bietet jetzt neben **Bearbeiten** und **Löschen** auch **Aktivieren/Deaktivieren**.
- Konfigurations-Export/-Import enthält das neue Zeitplan-Feld `origin`.
- Anleitung zu Profilzeitplänen und Zeitplanverwaltung aktualisiert.
- `VERSION` geprüft: 0.1.31.

## v0.1.30

- Dashboard-Tabellen für **Mirror-Profile** und **Benutzerskripte** auf dieselbe Spaltenbreite, Ausrichtung und Zeilenlogik gebracht.
- Benutzerskript-Zielgrößen zeigen Größe, Status und Berechnungszeit kompakt in einer Zeile.
- Button **Größe neu** in **Größe neu berechnen** umbenannt.
- Einstellungen kompakter gestaltet; Statuskarten wie **Mirror-Speicher** werden in einer platzsparenden Kachel-/Spaltenansicht dargestellt und strecken sich nicht mehr auf die Höhe langer Formularblöcke.
- Versionsanzeige oben neben **DebMirror Manager** ist jetzt direkt mit den Release Notes verlinkt.
- Anleitung erneut geprüft und die Beschreibungen zu Dashboard, Benutzerskripten und Einstellungen präzisiert.
- `VERSION` geprüft: 0.1.30.

## v0.1.29

- Dashboard-Block **Benutzerskripte** an Inhalt und Spaltenlogik von **Mirror-Profile** angeglichen.
- Benutzerskripte zeigen jetzt ebenfalls Zeitplan, Größe, letzten Job und Aktion in derselben Spaltenstruktur.
- Benutzerskript-Zielverzeichnis bleibt ausdrücklich nur für Größenberechnung; es wird nicht an das Skript übergeben.
- Eingabefeld und Buttons für Benutzerskript-Zielverzeichnisse kompakter und rechts neben dem Verzeichnisblock angeordnet.
- SMTP-Passwort, Telegram-Bot-Token und Discord-Webhook werden nicht mehr im Formular angezeigt.
- Benachrichtigungs-Geheimwerte werden verschlüsselt gespeichert, sofern `cryptography` verfügbar ist.
- Legacy-Adminwerte werden aus `settings.json` entfernt und in die SQLite-Benutzerverwaltung migriert.
- `set-admin-password.sh` schreibt jetzt direkt in die SQLite-Benutzerverwaltung und bleibt als Notfallwerkzeug nutzbar.
- Konfig-Export entfernt Benachrichtigungs-Geheimwerte.
- Anleitung vollständig neu strukturiert und alle Menüpunkte/Funktionen eindeutiger beschrieben.
- `VERSION` geprüft: 0.1.29.

## v0.1.28

- Fehler „Unbekannte Aktion“ beim Speichern des Benutzerskript-Zielverzeichnisses behoben.
- Benutzerskripte erhalten einen eigenen Dashboard-Block.
- Zielverzeichnis für Benutzerskripte dient nur der Größenberechnung.
- SVG-Favicon im Linux-Pinguin-Stil ergänzt.

## v0.1.27

- Login-Seite bereinigt.
- Dashboard-Limits für letzte Jobs und Ereignisse ergänzt.
- Benutzerskripte um Zielverzeichnis für Größenberechnung erweitert.
- Dashboard zeigt Jobquelle/Zeitplan aussagekräftiger an.

## v0.1.26

- Zeitplaner unterscheidet Mirror-Jobs und Benutzerskript-Jobs.
- Benutzerskripte können als alle/einzeln/selektiert geplant werden.
- Zeitpläne können bearbeitet werden.

## v0.1.25

- `lftp` in das Container-Image aufgenommen.

## v0.1.24

- Linke Navigation einklappbar gemacht.
- Backup-Bereich in „Backup / Wiederherstellen“ umbenannt und kompakter gestaltet.
- Manuelle Größenberechnung betrifft nur das ausgewählte Profil.
- Lokale Zeitzone über `APP_TIMEZONE` / `TZ` ergänzt.

## v0.1.23

- Fehler beim Upload/Anzeigen von Benutzerskripten durch fehlende `human_size()`-Funktion behoben.

## v0.1.22

- Linke Seitennavigation und kompakteres Dashboard eingeführt.
- Letzte Jobs und Ereignisse in Scrollbereiche gesetzt.

## v0.1.21

- Fehlerauswertung wird nach Job-Ende ohne kompletten Reload nachgeladen.
- Speicherplatz-Sperre für echte Mirror-Jobs ergänzt.
- Release Notes bereinigt.

## v0.1.20

- GPG-Key-Hilfe erscheint nach abgeschlossenem Job wieder oberhalb des Logs.
- Vorhandene passende Keyrings werden bei `NO_PUBKEY` angeboten.

## v0.1.19

- Live-Log springt nach Job-Ende nicht mehr.
- Vorhandene Keyrings werden bei GPG-Fehlern geprüft.

## v0.1.18

- Mirror-Detailseite bricht bei Keyring-Fingerprint-Mismatch nicht mehr mit HTTP 500 ab.

## v0.1.17

- Job-Dauer in Listen und Details ergänzt.
- GPG-Fehlerauswertung korrigiert: `using RSA key` allein ist kein Fehler.

## v0.1.16

- Fehler `size_calc_max_parallel` behoben.
- Automatische Größenberechnung nach ruhigem Job-Fenster ergänzt.

## v0.1.15

- Dashboard und Größen-Cache robuster gegen WebUI-Fehler gemacht.
- `webui-error.log` eingeführt.

## v0.1.14

- Keyring-Auswahl beim Skript-Import ergänzt.
- Größenberechnung für große Mirrors auf Cache/Hintergrundberechnung umgestellt.

## v0.1.13

- `install.sh` nutzt vorhandene `.env`-Werte als Defaults.
- Rollen/Rechte für Admin und betrachtende Benutzer verschärft.

## v0.1.12

- Optionaler nginx-Container.
- Benutzerskripte als Job-Typ eingeführt.
- `update.sh` fragt bei fehlendem ZIP nach Rebuild.

## v0.1.11

- Einstellbare Job-Parallelität.
- Flexible Zeitpläne und globale Zeitpläne.
- Job-/Log-Retention.
- Profilgenerator-Einstellungen.

## v0.1.10

- Globale Job-Warteschlange.
- Backup/Wiederherstellen in der WebUI.
- Profilgenerator.
- Versionsanzeige aus `VERSION` zentralisiert.

## v0.1.9

- Navigation und Profilübersicht verbessert.
- Zurück-/Detailnavigation ergänzt.

## v0.1.8

- SQLite-Locking verbessert.
- GPG-Key-Fehlerauswertung und Keyserver-Aktionen ergänzt.

## v0.1.7

- Container-Abhängigkeiten `gpgv`, `patch`, `ed` und `dirmngr` ergänzt.

## v0.1.6

- Konfig Export/Import, Benachrichtigungen, Benutzerverwaltung, API und Healthchecks ergänzt.

## v0.1.5

- Script-Import für vorhandene `DEB_*`-Skripte verbessert.
- Dark Mode ergänzt.

## v0.1.4

- Import bestehender debmirror-Skripte.
- Speicherplatzanzeige, Mirror-Größe, Fehlerauswertung und Beispiel-/Generatorgrundlagen.

## v0.1.3

- Update-Verzeichnis `updates/` und automatischer Update-Ablauf.

## v0.1.2

- ZIP entpackt dauerhaft nach `debmirror-manager/`.
- Update-Prozess vorbereitet.

## v0.1.1

- Login-/Setup-Korrekturen und Ports `8111`/`8110`.

## v0.1.0

- Erste funktionsfähige Docker-WebUI mit Mirror-Profilen, Jobs, Logs, Keyrings, Anleitung und Release Notes.
