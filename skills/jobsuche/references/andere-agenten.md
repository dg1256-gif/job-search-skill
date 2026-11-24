# Andere Programme als Claude Code

Die Skripte brauchen kein Modell und laufen mit jedem Programm. Unterschiedlich ist nur, was
der Assistent selbst mitbringt. Welches Programm die Läufe auf dem Rechner startet, steht in
`settings.yaml`:

```yaml
agent:
  cli: "claude"        # claude | codex | gemini | grok | custom
  model: ""            # Modellname für das Programm; leer = dessen Voreinstellung
  helper_model: ""     # kleineres Modell für Recherche-Hilfsagenten, wenn das Programm welche kennt
  command: ""          # nur bei custom: ganzer Befehl mit {prompt} und optional {model}
```

Den Modellnamen wählt der Nutzer; er wird nur als Schalter an das Programm übergeben. Welche
Namen gültig sind, sagt das jeweilige Programm.

| `cli` | Programm | Anleitung findet es über | Stand |
|---|---|---|---|
| `claude` | Claude Code | Skill `jobsuche` (`/jobsuche lauf`) | geprüft |
| `codex` | OpenAI Codex CLI (ChatGPT) | `AGENTS.md` im Arbeitsordner | Aufruf ungeprüft |
| `gemini` | Gemini CLI | `GEMINI.md` → `AGENTS.md` | Aufruf ungeprüft |
| `grok` | Grok-Kommandozeile | `AGENTS.md` | Aufruf ungeprüft |
| `custom` | jedes andere | `AGENTS.md` | Befehl kommt vom Nutzer |

„Ungeprüft“ heißt: Der Aufruf ist nach der Dokumentation des Programms gebaut, wurde aber nicht
auf einem Rechner mit diesem Programm getestet. Bei der Einrichtung deshalb immer
`$PY 08_Scripts/run_local.py daily --dry-run` ausführen, dem Nutzer den Befehl zeigen und ihn
einmal von Hand starten lassen. Passt er nicht: `cli: "custom"` und den richtigen Befehl in
`command` eintragen, zum Beispiel `meinprogramm --model {model} {prompt}`.

Der Auftrag, den ein Zeitplan oder der Start-Knopf übergibt, ist immer einer von zwei festen
Sätzen („Lies skills/jobsuche/SKILL.md im Arbeitsordner und führe den täglichen Lauf aus.“
bzw. „… den im Dashboard angefragten Lauf aus.“). Er ist nicht einstellbar.

## Was in deinem Programm anders ist

| Thema | Claude Code | andere Programme |
|---|---|---|
| Aufruf | `/jobsuche …` | in Worten („täglichen Lauf ausführen“), Tabelle in `AGENTS.md` |
| Dashboard | `artifact` oder `local` | `local` (`references/dashboard.md`) |
| Gmail | Connector | eigener Gmail-Zugang des Programms, wenn vorhanden; sonst `imap` mit App-Passwort oder `forward` (`references/mail.md`) |
| Recherche je Region | parallele Hilfsagenten | wenn vorhanden ebenso, sonst nacheinander selbst |
| Websuche, Seiten lesen | eingebaut | eigenes Werkzeug; fehlt eines, mit Feeds und Alert-Mails arbeiten und es melden |
| Formulare im Browser | gstack oder Browser-Erweiterung | eigenes Browser-Werkzeug mit sichtbarem Fenster; sonst Ausfüllhilfe als Tabelle (`references/formular.md`) |
| Lauf in der Cloud | Cloud-Routine | nur, wenn das Programm selbst geplante Läufe anbietet; sonst lokaler Zeitplan |
| Fragen an den Nutzer | Auswahl-Dialog | im Chat fragen |

Fehlt ein Werkzeug, wird der Schritt nicht stillschweigend ausgelassen: in der Meldung eine
Zeile, was fehlte und was deshalb nicht geprüft ist.

## Einrichten in einem anderen Programm

1. `python3 <Skill-Ordner>/scripts/setup.py init --workspace ~/Jobsuche` (Windows: `py`).
   Das legt auch `AGENTS.md`, `GEMINI.md` und `skills/jobsuche/` im Arbeitsordner an.
2. Das Programm **im Arbeitsordner** starten und schreiben: „Jobsuche einrichten“.
3. Weiter nach `references/einrichtung.md`.

Die unverrückbaren Regeln aus `SKILL.md` gelten in jedem Programm gleich.
