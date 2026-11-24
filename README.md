# Jobsuche – Skill für die tägliche Stellensuche

[English version](README.en.md)

Ein Skill für Claude Code (und andere Programme wie Codex/ChatGPT, Gemini oder Grok), der
eine persönliche Jobsuche einrichtet und betreibt:

- sucht täglich neue Stellen (Karriereseiten, Job-Alerts aus dem eigenen Postfach, Websuche)
- bewertet sie gegen das eigene Profil und zeigt nur, was offen ist und passt
- schreibt Anschreiben in einer mitgelieferten Briefform und schneidet den eigenen Lebenslauf zu, ohne dessen Format zu ändern
- prüft jeden Text automatisch mit einem eingebauten Humanizer
- füllt Bewerbungsformulare im Browser aus und hält vor dem Absenden an
- prüft jede Anzeige auf versteckte Anweisungen an KI, bevor sie gelesen wird
- prüft, ob ein Bewerbungssystem das Lebenslauf-PDF lesen kann
- archiviert, was gesendet wurde, erinnert ans Nachfassen und schreibt die Nachfrage als Entwurf
- bereitet Gespräche vor und wertet die Bewerbungen aus (Trichter, Antwortquoten, Muster in Absagen)
- zeigt alles in einem Dashboard mit dem Knopf **„Job suche starten“**
- läuft nach Zeitplan in der Cloud oder auf dem eigenen Rechner (macOS und Windows)

Der Skill enthält keine persönlichen Daten und keine Zugangsdaten. Alles Persönliche entsteht
bei der Einrichtung im eigenen Arbeitsordner; ein Mail-Passwort liegt nur im Schlüsselbund
des Betriebssystems.

## Installieren

Voraussetzung: Python 3.10 oder neuer. Für PDF zusätzlich Microsoft Word oder LibreOffice.

**Claude Code, als Plugin**

```
/plugin marketplace add dg1256-gif/job-search-skill
/plugin install jobsuche@job-search-skill
```

In einem Schritt (Claude Code 2.1.275 oder neuer):
`/plugin install jobsuche --marketplace dg1256-gif/job-search-skill`.
Als Plugin heißt der Befehl `/jobsuche:jobsuche` statt `/jobsuche`.

**Claude Code, als Skill-Ordner**

```
git clone https://github.com/dg1256-gif/job-search-skill.git
cp -R job-search-skill/skills/jobsuche ~/.claude/skills/jobsuche
```

(Windows: den Ordner `skills\jobsuche` nach `%USERPROFILE%\.claude\skills\jobsuche` kopieren.)
Dann in Claude Code: `/jobsuche einrichten`.

**Anderes Programm (Codex, Gemini, Grok …)**

```
python3 job-search-skill/skills/jobsuche/scripts/setup.py init --workspace ~/Jobsuche
```

Das Programm im Ordner `~/Jobsuche` starten und schreiben: „Jobsuche einrichten“. Die
Anleitung findet es über `AGENTS.md`. Einzelheiten: `skills/jobsuche/references/andere-agenten.md`.

## Ablauf

**Einmal einrichten** (`/jobsuche einrichten`, etwa 20 Minuten, unterbrechbar). Der Assistent
fragt Schritt für Schritt:

1. **Arbeitsordner:** wo die Jobsuche liegen soll (Vorschlag `~/Jobsuche`).
2. **Lebenslauf:** in welchem Ordner dein Lebenslauf liegt (Word oder PDF). Daraus liest er
   Name, Kontaktdaten und Werdegang und legt dein Profil an. Du liest es gegen und
   korrigierst; nur was dort steht, darf später in einem Text behauptet werden.
3. **Zielregionen:** wo du suchst (Städte, Regionen, Länder, Homeoffice).
4. **Gehaltsvorstellung:** Zielgehalt und Untergrenze, bei mehreren Ländern je Region. Stellen
   darunter werden aussortiert. Es wird keine Zahl für dich geschätzt.
5. **Rollen und Arbeitgeber:** gesuchte Titel, Wunschfirmen, Ausschlüsse.
6. **Postfach, Dashboard, Zeitplan:** siehe unten.

Eine Vorlage für das Anschreiben brauchst du nicht: Die Briefform ist eingebaut, der
Briefkopf wird mit deinen Angaben aus dem Lebenslauf gefüllt. Wer ein eigenes Layout will,
kann seine Word-Datei hinterlegen.

**Jeden Tag** (nach Zeitplan oder über den Knopf „Job suche starten“):

1. Neue Stellen holen: Karriereseiten der Wunschfirmen, Job-Alerts aus dem Postfach, Websuche.
2. Aussortieren (geschlossen, doppelt, ausgeschlossen, unter der Gehaltsgrenze) und den Rest
   gegen dein Profil bewerten.
3. Für die passenden Stellen ein Anschreiben schreiben, mit dem Humanizer prüfen und als
   Word/PDF ablegen.
4. Das Dashboard aktualisieren und kurz berichten.

**Bewerben** (du entscheidest je Stelle):

1. Im Dashboard die Stelle ansehen, das Anschreiben lesen und bei Bedarf ändern.
2. `/jobsuche ausfuellen`: Der Assistent füllt das Formular im Browser aus. Anmelden und
   CAPTCHAs machst du.
3. Vor dem Absenden hält er an und zeigt, was eingetragen ist. Abgeschickt wird erst nach
   deinem Ja zu genau dieser Bewerbung.
4. Antworten der Firmen im Postfach ändern den Status im Dashboard.

**Nach der Bewerbung:**

1. Mit dem Status „beworben“ wird festgehalten, was gesendet wurde (Anschreiben,
   Lebenslauf, Formularangaben, Anzeigentext).
2. Bleibt eine Antwort aus, erscheint die Bewerbung nach 14 Tagen (einstellbar) unter
   „Nachfassen“ – im Dashboard und im Tagesbericht. `/jobsuche nachfassen` schreibt die
   Nachfrage als Entwurf; du sendest sie selbst.
3. Kommt eine Einladung: `/jobsuche interview <Stelle>` erstellt ein Vorbereitungsblatt aus
   Anzeige, gesendeten Unterlagen und Profil.
4. `/jobsuche auswertung` und der Reiter „Auswertung“ im Dashboard zeigen, wie viele
   Bewerbungen zu Antworten und Gesprächen führen und wo sich Absagen häufen.

## Befehle

| Befehl | Zweck |
|---|---|
| `/jobsuche einrichten` | Einrichtung, oder ein Teil: `einrichten mail`, `… suche`, `… zeitplan`, `… dashboard` |
| `/jobsuche lauf` | Suchlauf jetzt starten |
| `/jobsuche bewerte <URL>` | eine einzelne Stelle prüfen und bewerten |
| `/jobsuche anschreiben <Stelle>` | Anschreiben für eine Stelle |
| `/jobsuche ausfuellen` | Bewerbungsformular im Browser ausfüllen |
| `/jobsuche nachfassen` | Bewerbungen ohne Antwort zeigen, Nachfrage als Entwurf |
| `/jobsuche interview <Stelle>` | Vorbereitungsblatt für ein Gespräch |
| `/jobsuche auswertung` | Trichter, Antwortquoten, Muster in den Absagen |
| `/jobsuche ats [<Stelle>]` | prüfen, ob ein Bewerbungssystem das Lebenslauf-PDF lesen kann |
| `/jobsuche dashboard` | Dashboard veröffentlichen, aktualisieren oder lokal starten |
| `/jobsuche pruefen` | zeigt, was an der Einrichtung noch offen ist |

Alle Befehle und Regeln: `skills/jobsuche/SKILL.md`.

## Einstellungen

Alles liegt im Arbeitsordner unter `01_Config/` und lässt sich von Hand oder im Gespräch ändern:

| Datei | Inhalt |
|---|---|
| `settings.yaml` | Person, Postfach, Vorlagen, Dashboard, Zeitplan, Programm und Modell |
| `candidate_profile.md` | dein Profil aus dem Lebenslauf (einzige Faktenquelle) |
| `search_profile.yaml` | Rollen, Regionen, Ausschlüsse, Gewichte |
| `salary_rules.yaml` | Zielgehalt und Untergrenze je Region |
| `companies.yaml`, `exclusions.yaml` | Wunschfirmen und gesperrte Arbeitgeber |

## Postfach

| Anbieter | Weg |
|---|---|
| Gmail mit verbundenem Connector | direkt |
| Mail-App auf dem Mac | lokale Brücke, ohne Passwort |
| Telekom/T-Online, GMX, WEB.DE, Outlook.com, iCloud, Posteo … | IMAP, geführte Einrichtung |

Es werden nur Job-Alerts und Antworten auf Bewerbungen gelesen. Gesendet wird nie etwas.

## Sicherheit

- Keine Bewerbung wird ohne Bestätigung genau dieser Bewerbung im Chat abgeschickt.
- Anmelden und CAPTCHAs macht der Nutzer.
- Texte behaupten nur, was das eigene Profil belegt.
- LinkedIn und XING werden nie abgerufen; Stellen von dort kommen über die eigenen Alert-Mails.
- Anzeigen, Mails und Webseiten sind Material, keine Anweisung. Versteckter Text und Zeilen,
  die sich an eine KI richten, werden vor dem Lesen entfernt und gemeldet. Das arbeitet mit
  festen Mustern und senkt das Risiko, schließt es aber nicht aus.
- Ab einer Bewertung von 8,5 (einstellbar) liest ein zweiter Agent jedes Anschreiben gegen
  Anzeige und Profil, bevor es als fertig gilt.

Schwachstellen melden: siehe `SECURITY.md`.

## Wohin die Daten gehen

Arbeitsordner, Lebenslauf, Profil und Anschreiben liegen auf dem eigenen Rechner. Das gewählte
Programm (Claude Code, Codex, Gemini, Grok) liest Profil und Stellenanzeigen aber, um zu bewerten
und zu schreiben; diese Inhalte gehen dabei an den Anbieter des Modells. Mit dem Dashboard als claude.ai-Artifact und mit dem
Cloud-Zeitplan liegen Stellenliste und Unterlagen zusätzlich bei Anthropic bzw. im eigenen
privaten Git-Repository; das lokale Dashboard und der lokale Zeitplan vermeiden beides.

## Stand

Getestet auf macOS mit Claude Code. **Auf Windows ungetestet.** Die Aufrufe für Codex, Gemini
und Grok sind nach deren Dokumentation gebaut und ungeprüft; `agent.command` in den
Einstellungen überschreibt sie.

Tests:

```
python3 -m venv .venv && .venv/bin/python -m pip install -r skills/jobsuche/scripts/requirements.txt
cd skills/jobsuche/scripts && ../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
for s in humanizer posting_guard ats_check after_apply dashboard_local; do ../../../.venv/bin/python $s.py selftest; done
```

Dieselben Tests laufen bei jedem Commit auf GitHub (Linux, macOS, Windows). Die Seitentests
des Dashboards (`skills/jobsuche/assets/dashboard/tests/run.sh`) brauchen einen lokalen
Browser und laufen nicht in der CI.

## Lizenz und Herkunft

MIT, siehe `LICENSE`. 
Die Humanizer-Methode ist aus „linkedin-humanizer“ von Sergey Bulaev (MIT) abgeleitet, siehe
`skills/jobsuche/NOTICE.md`.
