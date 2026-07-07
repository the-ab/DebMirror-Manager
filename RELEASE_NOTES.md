# Release Notes

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
