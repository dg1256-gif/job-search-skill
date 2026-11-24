# Nach der Bewerbung: Archiv, Nachfassen, Auswertung

Alles hier liest den Bestand in `02_State/` und sendet nichts. Skript: `08_Scripts/after_apply.py`.

## Archiv: was genau gesendet wurde

Sobald eine Stelle den Status „beworben“ bekommt (`set-status … APPLIED`, Dashboard,
Bestätigungsmail), friert das System den Stand ein: die Dateien aus
`07_Logs/apply_local/<key>/` (Anschreiben, Lebenslauf, Formularangaben), den Text des
Anschreibens und den Anzeigentext. Ziel: `07_Logs/apply_local/<key>/gesendet/` mit
`gesendet.json` (Datum, Dateien mit Prüfsumme) und `anzeige.txt`. Der Ordner liegt nicht in Git.

- Das erste Archiv bleibt. Ein späterer Neubau des Anschreibens ändert es nicht.
- Hat der Nutzer etwas anderes gesendet als im Ordner lag (eigene Datei, Text geändert): die
  richtigen Dateien nach `07_Logs/apply_local/<key>/` legen lassen und
  `$PY 08_Scripts/after_apply.py archive --key KEY --force`.
- Ohne Bewerbungspaket (außerhalb beworben) enthält das Archiv nur, was vorhanden ist. Das in
  der Meldung sagen, nichts nachträglich als „gesendet“ ablegen, was nicht sicher gesendet wurde.

## Nachfassen (`/jobsuche nachfassen`)

```
$PY 08_Scripts/after_apply.py followups
```

listet Bewerbungen, die seit `followup.days` Tagen (Standard 14) ohne Einladung, Zusage oder
Absage sind. Je Bewerbung gibt es höchstens `followup.max` Erinnerungen (Standard 2); die
Frist läuft nach jedem Nachfassen neu. Dieselbe Liste zeigt das Dashboard im Reiter
„Beworben“ und in der Auswertung.

1. Die Liste zeigen (Firma, Rolle, beworben am, Tage). Der Nutzer wählt, wo er nachfassen will.
   Bei „Anzeige nicht mehr online“ dazusagen, dass die Stelle vermutlich besetzt oder
   zurückgezogen ist.
2. Für jede gewählte Bewerbung einen kurzen Entwurf schreiben (3–5 Sätze): Bezug auf Rolle
   und Bewerbungsdatum, eine Zeile, warum die Stelle weiter interessiert (nur Belegtes aus
   `gesendet.json` → `letter_text` und dem Profil), Frage nach dem Stand. Kein Druck, keine
   neue Behauptung, kein zweites Anschreiben. Sprache der Anzeige. Empfänger nur, wenn die
   Anzeige oder eine Mail der Firma eine Ansprechperson nennt; sonst offen lassen und fragen.
3. Humanizer wie bei jedem Text an Arbeitgeber (`references/humanizer.md`), dann
   `humanizer.py check`.
4. Entwurf nach `07_Logs/apply_local/<key>/Nachfassen_<Datum>.md` und im Chat zeigen.
   **Gesendet wird nie etwas** (Regel 1); der Nutzer schickt die Nachricht selbst.
5. Sagt der Nutzer, dass er nachgefasst hat (oder klickt er im Dashboard „Nachgefasst“):
   `$PY 08_Scripts/after_apply.py followup-done --key KEY [--date YYYY-MM-DD]`. Der
   Dashboard-Abgleich überträgt den Vermerk in beide Richtungen.

Im Tageslauf nur zählen und melden, keine Entwürfe schreiben.

## Auswertung (`/jobsuche auswertung`)

```
$PY 08_Scripts/after_apply.py stats
```

zeigt den Weg von gefunden über beworben bis Gespräch, Zusage oder Absage, die Antwort- und
Gesprächsquote, die Tage bis zur Antwort und Tabellen nach Bewertung, Herkunft und Land.
Unter „Auffälligkeiten“ stehen nur Häufungen mit mindestens fünf Bewerbungen in der Gruppe.

So damit umgehen:

- Die Zahlen nennen, wie sie sind. Unter acht Bewerbungen gibt es keine Muster; das sagen.
- Aus einer Häufung einen Vorschlag machen, keinen Beschluss: zum Beispiel „Absagen häufen
  sich unter 7,5 – Schwelle für Anschreiben anheben?“. Suchprofil, Schwellen und Gewichte
  ändert nur der Nutzer (Regel 10), mit Eintrag im `changelog`.
- Eine Absage sagt nichts über den Grund. Nichts hineinlesen, was die Mail nicht nennt.

Das Dashboard zeigt dieselben Zahlen im Reiter „Auswertung“.
