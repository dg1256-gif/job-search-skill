# Schreibstil für Anschreiben

Vor jedem Anschreiben lesen und befolgen. Die Regeln unten sind ein allgemeiner Startpunkt.
Eigene Regeln entstehen aus deinen Überarbeitungen im Dashboard-Editor
(`02_State/letter_edits_log.jsonl`): eine neue Regel wird nur mit Beleg aus einer echten
Überarbeitung ergänzt (Datum, Stelle, Vorher → Nachher), nie aus einer Vermutung.

Fakten kommen ausschließlich aus `01_Config/candidate_profile.md`. Der Stil regelt nur, WIE etwas
gesagt wird, nie WAS behauptet werden darf.

## Regeln

1. **Teamleistung als Teamleistung.** Was im Team entstanden ist, so schreiben: "Dort haben das
   Team und ich … konzipiert und eingeführt." Kein reines "Ich habe …" für gemeinsame Ergebnisse.
2. **Abstimmung und Freigabe richtig benennen.** Mit wem etwas abgestimmt wurde und wer es
   freigegeben hat, ist oft aussagekräftiger als ein Werkzeugname.
3. **Interne Begriffe kurz erklären.** Ein Begriff, den nur der bisherige Arbeitgeber kennt,
   bekommt beim ersten Auftreten eine Erklärung in drei, vier Wörtern.
4. **Weniger ist mehr.** Keine Aufzählung von Zertifikaten oder Zusatzerfolgen im Fließtext, wenn
   sie nicht direkt zur Stelle gehören. Ein Absatz darf zwei Sätze haben.
5. **Keine defensiven Einschübe.** Nichts wie "ohne selbst … zu sein" oder "auch wenn ich bisher
   nicht …".
6. **Lücken schlicht benennen.** Ein Satz, ohne Rechtfertigung: "Neu wäre für mich <Feld>, da mein
   Hintergrund <Feld> ist."
7. **Lücke als Übergang zur Motivation.** Nach der Lücke folgt, was an der Aufgabe konkret
   interessiert, und die Bereitschaft zur gezielten Einarbeitung.
8. **Schluss schlicht.** "Ich freue mich auf Ihre Rückmeldung." / "I look forward to hearing from
   you." Keine werbende Gesprächsformel.
9. **Keine Semikolons, höchstens ein Gedankenstrich.** Lieber zwei Sätze. Verknüpfungen wie
   "Zudem", "Außerdem", "da".
10. **Natürlicher Einstieg.** Mit dir selbst beginnen: was du zuletzt gemacht hast und woran du bei
    diesem Arbeitgeber anknüpfen willst. Kein Satz, der die Ausschreibung nacherzählt ("Ihre
    Ausschreibung verbindet …", "<Firma> is looking for …"), kein Infinitiv-Block als erster Satz.
11. **Eher kurz.** Zielbereich 250 bis 300 Wörter; die harte Grenze steht in
    `settings.yaml` → `documents.letter_words`.
12. **Konkret statt allgemein.** Themenfelder beim Namen nennen und Verbesserungen als
    Vorher → Nachher mit Zweck beschreiben.
13. **Auf die Stelle mappen.** Jede Kernaufgabe und Kernqualifikation der Anzeige mit belegter
    Erfahrung beantworten, Absatz für Absatz. Was die Anzeige nicht verlangt, weglassen.
14. **Tiefe statt Tätigkeitsliste.** Nicht aufzählen, was du gemacht hast, sondern zeigen, wie du an
    den Kern der Stelle anknüpfst: wie du Lösungen beurteilt und welche Entscheidungen du getroffen
    hast. Werkzeuge nur nennen, wenn sie die Stelle wirklich tragen.
15. **Stationen nicht vermischen.** Jede Aussage gehört zu der Station, aus der sie stammt
    (Studium, Praktikum, aktuelle Stelle); nie eine Erfahrung einer anderen Station zuschreiben.
16. **Fester Titel.** Steht in `settings.yaml` → `person.fixed_title` ein Titel, erscheint er
    wörtlich im ersten Absatz. `cover_letter.py` prüft das.
17. **Eine Seite.** Länger nur, wenn du es für eine Stelle ausdrücklich freigibst.
18. **Sprache folgt der Anzeige.** Englische Anzeige, englisches Anschreiben.
19. **Anrede.** "Sehr geehrte Frau <Nachname>," / "Sehr geehrter Herr <Nachname>," wenn die Anzeige
    eine Ansprechperson nennt, sonst "Sehr geehrte Damen und Herren,". Nie einen Namen raten.

## Musteraufbau

1. **Einstieg (2 Sätze):** letzte Station und Rolle, dann woran du bei <Firma> anknüpfen willst.
2. **Kernabsatz:** die Erfahrung, die die wichtigste Aufgabe der Stelle beantwortet, mit einem
   konkreten Ergebnis.
3. **Zweiter Absatz:** weitere Muss-Anforderungen der Anzeige, je mit Beleg.
4. **Lücke → Motivation:** eine Lücke schlicht benennen, dann das konkrete Interesse.
5. **Schluss:** ein Satz.

## Geklärt

Entscheidungen zu Einzelfällen, mit Datum.

- <JJJJ-MM-TT>: <Entscheidung>

## Belege

Je Regel die Überarbeitung, aus der sie stammt.

- <JJJJ-MM-TT>, <Firma> <Stelle> (`<job_key>`): Regel <Nr.> – <Vorher → Nachher in einem Satz>
