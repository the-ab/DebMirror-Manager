# Release Notes

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
