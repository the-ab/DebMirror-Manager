# Sicherheitsrichtlinie

## Unterstützte Versionen

Nur die jeweils neueste veröffentlichte DebMirror-Manager-Version erhält Sicherheitskorrekturen. Ältere Versionen können bekannte Schwachstellen enthalten und sollten vor der Untersuchung einer Meldung aktualisiert werden.

| Version | Unterstützt |
| --- | --- |
| Neueste Version | Ja |
| Ältere Versionen | Nein |

## Schwachstelle melden

Bitte die private Schwachstellenmeldung von GitHub oder einen privaten Security Advisory des Repositorys verwenden. Ausnutzbare Details dürfen nicht in öffentlichen Issues, Diskussionen, Pull Requests oder Forenbeiträgen veröffentlicht werden.

Falls keine private Meldung möglich ist, nur ein öffentliches Issue mit der Bitte um einen privaten Sicherheitskontakt erstellen. Keine Zugangsdaten, privaten Schlüssel, Produktivdaten, Zugriffstokens oder Proof-of-Concept-Code in dieses Issue aufnehmen.

Nach Möglichkeit folgende Angaben bereitstellen:

- betroffene Version und Installationsmethode;
- Angriffsvoraussetzungen und betroffene Rolle;
- genaue Anfrage, Eingabe oder Ablauf, der den Fehler auslöst;
- Auswirkung und Angabe, ob auf Produktivdaten zugegriffen wurde;
- minimale Reproduktion mit nicht sensiblen Testdaten;
- mögliche Gegenmaßnahmen.

## Koordinierte Offenlegung

Meldungen werden nach Möglichkeit geprüft. Der Projektbetreuer validiert den Fehler, bereitet eine Korrektur vor und stimmt abhängig vom Schweregrad einen Offenlegungstermin ab. Vor Veröffentlichung technischer Einzelheiten sollte Nutzern ausreichend Zeit für ein Update gegeben werden.

## Sicherheitsgrenzen

DebMirror Manager führt administrativ freigegebene Mirror-Jobs und Benutzerskripte im Container aus. Administratoren besitzen daher absichtlich weitreichende Kontrolle über eingebundene Mirror- und Anwendungsdaten. Der Container darf nicht direkt ungeschützten Netzwerken ausgesetzt und weder mit Docker-Socket noch im privilegierten Modus betrieben werden.

Sicherheitsrelevante Betriebshinweise stehen in `README.md` und `README.de.md`.
