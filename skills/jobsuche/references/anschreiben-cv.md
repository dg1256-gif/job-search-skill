# Anschreiben und Lebenslauf aus Vorlagen

Beide Dokumente entstehen als **Kopie einer Vorlage**: das Anschreiben aus der mitgelieferten
Form (oder einer eigenen des Nutzers), der Lebenslauf aus der Datei des Nutzers. Ersetzt wird nur der Text in
festgelegten Feldern; Schrift, Abstände, Ränder, Kopf- und Kontaktblock bleiben, wie sie
sind. Das erledigen `cover_letter.py` und `cv_tailor.py` und sie prüfen es auch. Nie ein
Dokument selbst mit einer Bibliothek aufbauen oder die Vorlage bearbeiten.

## Vorlage einrichten (einmalig)

### Anschreiben

Die mitgelieferte Vorlage ist fertig zugeordnet. Einmalig `$PY 08_Scripts/cover_letter.py
letterhead` (füllt Name und Kontaktzeile aus `person`; leere Angaben fallen weg). Solange der
Briefkopf Platzhalter enthält, verweigert `build`.

**Eigene Vorlage** (nur auf Wunsch des Nutzers):

1. `$PY 08_Scripts/cover_letter.py inspect` nummeriert alle Absätze der Vorlage mit ihrem
   Ort (`p:4`, `tbl:0:0:1` …).
2. `$PY 08_Scripts/cover_letter.py suggest-slots` schlägt die Zuordnung vor: Datum,
   Empfänger, Betreff, Anrede, erster und letzter Textabsatz, Grußformel, Unterschrift.
3. Den Vorschlag gegen die Ausgabe von `inspect` prüfen, dem Nutzer in Worten zeigen („Der
   Betreff ist die Zeile ‚Bewerbung als …‘, der Text reicht von ‚…‘ bis ‚…‘“) und nach
   seinem Ja in `templates.cover_letter_slots` eintragen. Teile, die seine Vorlage nicht
   hat, bleiben `null`.
4. Wörter aus dem alten Brief, die in keinem neuen stehen dürfen (Firmenname, Rolle des
   alten Briefs), nach `templates.cover_letter_leftovers`.

### Lebenslauf

1. `$PY 08_Scripts/cv_tailor.py inspect --lang de` (und `en`, falls vorhanden).
2. In `templates.cv_slots` eintragen: die Zeile unter dem Namen (`headline`), die
   Zusammenfassung (`summary` oder die Überschrift davor als `summary_heading`) und die
   Aufzählungen, deren Reihenfolge sich ändern darf (`focus_heading`, `reorder_groups`).
   Jeder Eintrag ist freiwillig. Ohne Einträge wird der Lebenslauf unverändert beigelegt.
3. Hat der Lebenslauf keine Zusammenfassung, wird keine eingefügt. Das wäre eine Änderung
   am Format; nur der Nutzer ergänzt seine Vorlage.

### Probe

Ein Test-Anschreiben für eine erfundene Musterfirma bauen (`build`, siehe unten, Ausgabe
nach `07_Logs/`) und prüfen, dass der Bau ohne Fehler durchläuft. Bei einer eigenen Vorlage
den Nutzer die Datei daneben öffnen lassen: Erst wenn er keinen Unterschied im Aussehen
findet, gilt sie als eingerichtet.

## Anschreiben schreiben

1. Lesen: die Anzeige (Aufgaben, Anforderungen), `01_Config/candidate_profile.md`,
   `01_Config/writing_style.md`.
2. Aufbau, wenn `writing_style.md` nichts anderes sagt: Einstieg bei der eigenen letzten
   Tätigkeit und dem Anknüpfungspunkt; zwei Absätze, die die Kernaufgaben der Anzeige mit
   belegter Erfahrung beantworten; ein Absatz zu Lücke und Motivation, wenn es eine
   wesentliche Lücke gibt; schlichter Schluss. Sprache = Sprache der Anzeige.
3. Fakten nur aus dem Profil, jede bei ihrer Station. Was unter „nicht belegt“ steht, wird
   nicht behauptet, auch nicht abgeschwächt.
4. Anrede nur mit Nachnamen, wenn die Anzeige eine Ansprechperson nennt; sonst die neutrale
   Form. Betreff = Titel der Anzeige, gegebenenfalls mit Kennziffer.
5. **Humanizer** (`references/humanizer.md`): vier Durchgänge, dann prüfen.
6. Im Tageslauf steht der Text als `cover_letter` in `scored.json`; `finalize` baut und
   prüft die Datei. Einzeln:

   ```
   $PY 08_Scripts/cover_letter.py build --spec <letter.json>
   ```

   ```json
   {"company": "", "role": "", "language": "de", "subject": "", "salutation": "",
    "paragraphs": ["", "", "", ""], "output": "05_Cover_Letters/<Jahr>/<Datum>/<Firma>/Anschreiben_<Rolle>.docx"}
   ```

   Der Bau bricht ab bei: Befund des Humanizers auf Stufe FEHLER, Begriff aus
   `unproven_terms.txt`, Rest aus dem alten Brief, falscher Anrede, Wortzahl außerhalb
   `documents.letter_words`, mehr Seiten als `documents.max_pages`, oder wenn sich an der
   Vorlage etwas anderes als die Felder geändert hätte. Dann den Text ändern, nicht die
   Prüfung umgehen. Passt der Text nicht auf die Seite: kürzen, nie Schrift oder Ränder
   verkleinern.
7. Einmal gegen das Profil gegenlesen. Ab `documents.review_min_score` (Standard 8.5)
   liest zusätzlich ein Zweitleser gegen, der den Text nicht geschrieben hat
   (`references/zweitleser.md`). Dem Nutzer Pfad und Text nennen.

Ein Anschreiben, das der Nutzer im Dashboard-Editor bearbeitet hat, gehört ihm: Es wird
neu gebaut und geprüft, aber nie umformuliert (`references/tageslauf.md`, Schritt 1).

## Lebenslauf zuschneiden

Geändert werden höchstens drei Dinge: die Zeile unter dem Namen, die Zusammenfassung (der
einzige neu geschriebene Text) und die Reihenfolge von Aufzählungspunkten innerhalb der
freigegebenen Gruppen. Kein Punkt wird umformuliert, gestrichen oder ergänzt; das Skript
bricht ab, wenn sich irgendein anderer Absatz ändert.

1. Zusammenfassung schreiben (Länge `documents.cv_summary_words`): wer der Nutzer
   beruflich ist und was davon zu dieser Stelle gehört, nur Belegtes. Humanizer wie beim
   Anschreiben.
2. Reihenfolge: je Gruppe die Anfänge der Punkte nennen, die für diese Stelle nach vorn
   gehören. Nicht genannte behalten ihre Reihenfolge.
3. Spec nach `04_CVs/specs/<job_key>.json`:

   ```json
   {"job_key": "", "company": "", "role": "", "language": "de", "headline": "",
    "summary": "", "order": {"focus": ["Anfang des Eintrags"], "station": ["Anfang des Punkts"]}}
   ```

4. `$PY 08_Scripts/cv_tailor.py build --spec 04_CVs/specs/<job_key>.json` schreibt Word und
   PDF nach `04_CVs/<Jahr>/<Datum>/<Firma>/<Rolle>/`. Ohne PDF-Programm: `--no-pdf` und es
   dem Nutzer sagen.
5. Ohne Zuschnitt: `$PY 08_Scripts/cv_tailor.py base --lang de` nennt das unveränderte PDF.

Soll etwas am Lebenslauf geändert werden, das darüber hinausgeht (ein Punkt gekürzt, eine
Station anders gewichtet), schlägst du es dem Nutzer vor und er ändert seine Vorlage. Du
streichst nie einen vorhandenen Punkt, um Platz zu schaffen.

## ATS-Prüfung des Lebenslaufs (`/jobsuche ats`)

Bewerbungssysteme lesen aus dem PDF nur den Text. Die Prüfung liest das PDF genauso und
meldet, was dabei verloren geht:

```
$PY 08_Scripts/ats_check.py check --pdf <Lebenslauf.pdf> [--docx <Lebenslauf.docx>] \
    [--keywords "Begriff 1, Begriff 2, …" --profile 01_Config/candidate_profile.md]
```

- Geprüft wird: Text vorhanden (kein Bild-PDF), E-Mail und Telefon lesbar, Name am Anfang,
  keine zerstörten Zeichen, mit `--docx` auch Vollständigkeit und Lesereihenfolge gegenüber
  der Word-Datei. Rückgabewert 3 = mindestens ein FEHLER.
- Für eine Stelle: 15–25 Begriffe aus den Anforderungen der Anzeige als `--keywords`
  mitgeben (Fachbegriffe, Werkzeuge, Methoden, Abschlüsse – in der Schreibweise der Anzeige).
  Das Ergebnis hat drei Gruppen:
  - **im Lebenslauf** – nichts zu tun.
  - **belegt, fehlt im Lebenslauf** – steht im Profil, aber nicht im PDF. Dem Nutzer als
    Vorschlag nennen (Zusammenfassung des zugeschnittenen Lebenslaufs oder seine Vorlage).
  - **nicht belegt** – wird nie in Lebenslauf oder Anschreiben geschrieben (Regel 3). Es
    gehört als Lücke in die Bewertung.
- Ein Hinweis zur Lesereihenfolge (Spalten, Tabellen, Textfelder) ist ein Vorschlag an den
  Nutzer für seine Vorlage. Du baust den Lebenslauf nicht um (Regel 4).
- Die Prüfung sagt nicht voraus, wie ein bestimmtes System bewertet; sie zeigt nur, was
  lesbar ankommt. Keine „ATS-Punktzahl“ nennen.

Im Ablauf: nach `cv_tailor.py build` und vor jedem Hochladen (`references/formular.md`).

## Bewerbungspaket

`$PY 08_Scripts/jobsearch.py apply-package --key <KEY> [--cv <pfad>] [--cover-letter <pfad>]`
legt Kopien der freigegebenen Dateien und die Angaben für das Formular in
`07_Logs/apply_local/<key>/` ab. Weiter mit `references/formular.md` oder, bei Bewerbung
per Mail, `references/mail.md`.
