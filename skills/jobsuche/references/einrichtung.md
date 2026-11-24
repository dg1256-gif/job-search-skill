# Einrichtung

Du führst den Nutzer Schritt für Schritt durch die Einrichtung, bis ein täglicher Lauf ohne
offene Punkte möglich ist. Immer nur ein Schritt, in einfachen Worten, mit einer konkreten
Frage oder einer Sache, die er tun soll. Nach jedem Schritt prüfen, ob er geklappt hat, bevor
der nächste kommt. Die Einrichtung ist unterbrechbar: `setup.py check` zeigt jederzeit, wo es
weitergeht.

Du trägst die Antworten selbst in `01_Config/settings.yaml` ein (nur die betroffene Zeile
ändern, Kommentare erhalten). **Passwörter, Tokens und Schlüssel fragst du nie ab und
schreibst sie nie in eine Datei.** Nennt der Nutzer versehentlich eines im Chat: nicht
verwenden, nicht wiederholen, und ihm raten, es beim Anbieter zu ändern.

`/jobsuche einrichten <teil>` (mail, vorlagen, profil, zeitplan, dashboard, agent) wiederholt
nur diesen Teil.

## 0. Arbeitsordner

1. Fragen, wo der Ordner liegen soll (Vorschlag `~/Jobsuche`; nicht in einem Cloud-Ordner,
   der Dateien auslagert).
2. `python3 <Skill-Ordner>/scripts/setup.py init --workspace <Ordner>` (Windows: `py -3 …`).
   Braucht Python 3.10 oder neuer; fehlt es, den Nutzer zur Installation von python.org
   führen. Das Skript legt die Ordner an, kopiert Skripte und Vorlagen und baut `.venv`.
3. Ab jetzt im Arbeitsordner arbeiten. `$PY 08_Scripts/setup.py check` zeigt die offenen Punkte.

## 1. Person

Name, Wohnort (für die Datumszeile im Anschreiben), Zeitzone → Abschnitt `person`.
Sprache der Berichte → `language.default`.

## 2. Programm und Modell

Fragen, mit welchem Programm die Läufe auf diesem Rechner starten sollen (Claude Code,
Codex/ChatGPT, Gemini, Grok, anderes) und ob ein bestimmtes Modell verwendet werden soll →
Abschnitt `agent`. Leeres `model` heißt: Voreinstellung des Programms. Ein kleineres
`helper_model` für die Recherche spart am meisten. Details und der Probelauf des Aufrufs:
`references/andere-agenten.md`.

## 3. Unterlagen und Vorlagen

1. Der Nutzer legt seinen Lebenslauf (Word, dazu wenn vorhanden als PDF) nach
   `00_Input/Lebenslauf/` und ein eigenes, fertiges Anschreiben als Word-Datei nach
   `00_Input/Anschreiben_Referenz/`. Dieses Anschreiben ist die Vorlage: neue Anschreiben
   sehen genauso aus. Pfade in `templates` eintragen.
2. Felder zuordnen: `references/anschreiben-cv.md`, Abschnitt „Vorlage einrichten“. Dem
   Nutzer den Vorschlag zeigen und bestätigen lassen.
3. PDF: `$PY 08_Scripts/docs_pdf.py check`. Ohne Word und ohne LibreOffice entstehen nur
   Word-Dateien; dann LibreOffice empfehlen oder `documents.pdf_engine: "none"` setzen.
4. Probe: ein Test-Anschreiben bauen (Abschnitt „Probe“ dort) und den Nutzer die Datei
   öffnen lassen: Sieht sie aus wie seine Vorlage? Erst dann weiter.

## 4. Profil

`01_Config/candidate_profile.md` ist die einzige Faktenquelle für alle späteren Texte.

1. Lebenslauf lesen und das Profil nach der Gliederung der Vorlage füllen: Stationen mit
   Zeitraum, belegte Ergebnisse, Skill-Matrix in drei Spalten (belegt / teilweise / nicht
   belegt). Jede Angabe bleibt bei der Station, aus der sie stammt.
2. Nichts ergänzen, was der Lebenslauf nicht hergibt. Unklares fragen (Führungsspanne,
   Sprachen mit Niveau, Arbeitserlaubnis, Zahlen zu Ergebnissen).
3. Dem Nutzer das Profil zum Gegenlesen geben. Was er streicht oder korrigiert, gilt.
4. `01_Config/unproven_terms.txt`: Begriffe, die in keinem Text behauptet werden dürfen
   (aus der Spalte „nicht belegt“).

## 5. Suche

Im Gespräch klären und eintragen:

- `search_profile.yaml`: gesuchte Rollen und Titel, Regionen und Orte, Homeoffice, was
  ausgeschlossen ist (Befristung, Zeitarbeit, Branchen), Gewichte und Schwellen (Vorgaben
  stehen lassen, wenn er keine Meinung hat), optionale Suchspuren (`segments`).
- `salary_rules.yaml`: Zielgehalt und Untergrenze je Region. Keine Zahl vorschlagen, die er
  nicht genannt hat.
- `companies.yaml`: Wunsch-Arbeitgeber. Für jeden die Karriereseite öffnen und das
  Bewerbungssystem bestimmen (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Personio …);
  nur eintragen, was `$PY 08_Scripts/jobsearch.py fetch` danach ohne Fehler abruft.
- `exclusions.yaml`: Arbeitgeber, die nie erscheinen sollen.
- `09_Documentation/research_briefs/`: je Region `lane_TEMPLATE.md` nach `lane_<NAME>.md`
  kopieren und füllen.

## 6. Postfach

`references/mail.md`. Ergebnis: `mail.mode` steht und ein Probeabruf liefert Mails (oder der
Nutzer hat sich bewusst für `none` entschieden).

## 7. Formulare

- Browser: `browser.engine` bleibt `auto`, wenn ein Browser-Werkzeug vorhanden ist; sonst
  erklären, dass die Ausfüllhilfe dann eine Tabelle zum Abtippen liefert.
- `form_defaults` gemeinsam füllen (`references/formular.md`): Kündigungsfrist, frühester
  Start, Gehaltswunsch (leer = jedes Mal fragen). Persönliche Merkmale nur, wenn er sie
  ausdrücklich hinterlegen will.

## 8. Dashboard

`references/dashboard.md`: Betriebsart wählen, einrichten, ersten Export schreiben.

## 9. Zeitplan und Start-Knopf

`references/zeitplan.md`: Cloud oder lokal, Uhrzeit, Abholer für den Knopf.

## 10. Sichern (optional, für den Cloud-Lauf Pflicht)

Den Arbeitsordner als **privates** Git-Repository anlegen. `.gitignore` ist schon da und
hält `07_Logs/`, `.venv/` und lokale Bewerbungsdaten heraus. Vor dem ersten Commit
`git status` lesen und mit dem Nutzer durchgehen, was hineinkommt: Lebenslauf, Profil und
Anschreiben liegen dann beim Git-Anbieter. `git.sync: true` erst nach seinem Ja.

## Prüfen

`$PY 08_Scripts/setup.py check` (mit `--json` für die Auswertung). Jeden offenen Punkt mit
dem zugehörigen Schritt oben schließen. Danach die Selbsttests:

```
$PY 08_Scripts/jobsearch.py selftest
$PY 08_Scripts/humanizer.py selftest
```

Zum Schluss ein erster Lauf (`references/tageslauf.md`) im Beisein des Nutzers und eine
Zusammenfassung in fünf Zeilen: was eingerichtet ist, wann der Lauf startet, wo das
Dashboard liegt, was er selbst tun muss (Alerts abonnieren, Rechner an), was noch offen ist.

## Aktualisieren

Neue Fassung des Skills: `$PY 08_Scripts/setup.py update` erneuert Skripte, Anleitungen und
Dashboard-Seite; `01_Config/` und `00_Input/` bleiben unberührt. Danach das Dashboard neu
veröffentlichen bzw. den lokalen Server neu starten und den Zeitplan mit
`schedule_install.py install all` erneuern.
