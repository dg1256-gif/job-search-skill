# Jobsuche – Skill für die tägliche Stellensuche

Ein Skill für Claude Code (und andere Programme wie Codex/ChatGPT, Gemini oder Grok), der
eine persönliche Jobsuche einrichtet und betreibt:

- sucht täglich neue Stellen (Karriereseiten, Job-Alerts aus dem eigenen Postfach, Websuche)
- bewertet sie gegen das eigene Profil und zeigt nur, was offen ist und passt
- schreibt Anschreiben und Lebenslauf **in den eigenen Word-Vorlagen**, ohne deren Format zu ändern
- prüft jeden Text automatisch mit einem eingebauten Humanizer
- füllt Bewerbungsformulare im Browser aus und hält vor dem Absenden an
- zeigt alles in einem Dashboard mit dem Knopf **„Job suche starten“**
- läuft nach Zeitplan in der Cloud oder auf dem eigenen Rechner (macOS und Windows)

Der Skill enthält keine persönlichen Daten und keine Zugangsdaten. Alles Persönliche entsteht
bei der Einrichtung im eigenen Arbeitsordner; ein Mail-Passwort liegt nur im Schlüsselbund
des Betriebssystems.

## Installieren

Voraussetzung: Python 3.10 oder neuer. Für PDF zusätzlich Microsoft Word oder LibreOffice.

**Claude Code**

```
git clone https://github.com/dg1256-gif/job-search-skill.git
cp -R job-search-skill/skills/jobsuche ~/.claude/skills/jobsuche
```

(Windows: den Ordner `skills\jobsuche` nach `%USERPROFILE%\.claude\skills\jobsuche` kopieren.)
Dann in Claude Code: `/jobsuche einrichten`. Der Assistent führt Schritt für Schritt durch
Arbeitsordner, Profil, Vorlagen, Postfach, Dashboard und Zeitplan.

**Anderes Programm (Codex, Gemini, Grok …)**

```
python3 job-search-skill/skills/jobsuche/scripts/setup.py init --workspace ~/Jobsuche
```

Das Programm im Ordner `~/Jobsuche` starten und schreiben: „Jobsuche einrichten“. Die
Anleitung findet es über `AGENTS.md`. Einzelheiten: `skills/jobsuche/references/andere-agenten.md`.

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

## Wohin die Daten gehen

Arbeitsordner, Lebenslauf, Profil und Anschreiben liegen auf dem eigenen Rechner. Das gewählte
Programm (Claude Code, Codex, Gemini, Grok) liest Profil und Stellenanzeigen aber, um zu bewerten
und zu schreiben; diese Inhalte gehen dabei an den Anbieter des Modells. Ein Container ändert
daran nichts. Wer das nicht will, trägt in `agent.command` ein lokal laufendes Modell ein
(ungetestet) oder nutzt nur die Skripte. Mit dem Dashboard als claude.ai-Artifact und mit dem
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
../../../.venv/bin/python humanizer.py selftest
```

## Lizenz und Herkunft

MIT, siehe `LICENSE`. 
Die Humanizer-Methode ist aus „linkedin-humanizer“ von Sergey Bulaev (MIT) abgeleitet, siehe
`skills/jobsuche/NOTICE.md`.
