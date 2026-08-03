# Hinweise zu Drittkomponenten

Der eigene Quellcode des DebMirror Managers steht unter der Apache License 2.0 (`Apache-2.0`); maßgeblich ist `LICENSE`.

Diese Datei ergänzt die englische Standardfassung `THIRD-PARTY-NOTICES.md`. Die technischen Bezeichnungen, Versionsnummern und SPDX-Lizenzkennungen müssen in beiden Fassungen identisch bleiben.

## Python-Laufzeitabhängigkeiten

| Komponente | Version | Lizenz |
| --- | ---: | --- |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.8 | BSD-3-Clause |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause |
| Gunicorn | 26.0.0 | MIT |
| Jinja | gesperrte transitive Version | BSD-3-Clause |
| Click | gesperrte transitive Version | BSD-3-Clause |
| itsdangerous | gesperrte transitive Version | BSD-3-Clause |
| MarkupSafe | gesperrte transitive Version | BSD-3-Clause |
| blinker | gesperrte transitive Version | MIT |
| cffi | gesperrte transitive Version | MIT |
| pycparser | gesperrte transitive Version | BSD-3-Clause |
| packaging | gesperrte transitive Version | Apache-2.0 OR BSD-2-Clause |

Die exakt aufgelösten Versionen und Hashes stehen in `requirements.lock`.

## Container und Betriebssystempakete

Das Anwendungsimage basiert auf dem offiziellen Python-3.13-Image für Debian 13 (Trixie). Der optionale Mirror-Webserver verwendet das offizielle nginx-Image auf Alpine Linux. Alle enthaltenen Pakete behalten ihre jeweiligen Lizenzen.

Das Image installiert unter anderem `debmirror`, GnuPG, `gpgv`, `rsync`, OpenSSH-Client, `lftp`, `curl`, `iputils-ping` und Kompressionswerkzeuge. `debmirror` steht unter GPL-2.0-or-later und wird von der WebUI als separates Programm aufgerufen.

Maßgebliche Paketlizenztexte befinden sich im gebauten Container unter `/usr/share/doc/<paket>/copyright`.

## Frontend und Marken

Das Projekt bindet derzeit kein externes JavaScript-/CSS-Framework in den Quellbaum ein. Dateien unter `app/static/` sind Projektdateien, sofern ihre Kopfzeilen nichts anderes angeben.

DebMirror Manager ist ein unabhängiges Drittanbieterprojekt und weder mit dem Debian-Projekt noch mit den Betreuern von `debmirror` verbunden oder von ihnen unterstützt.
