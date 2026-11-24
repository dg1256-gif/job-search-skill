# Zeitplan und Start-Knopf

Zwei Wege für den täglichen Lauf (`schedule.mode`). Frag den Nutzer und empfiehl nach der
Tabelle.

| | `cloud` | `local` |
|---|---|---|
| läuft | in der Cloud des Anbieters, auch bei ausgeschaltetem Rechner | auf dem eigenen Rechner; er muss an und der Nutzer angemeldet sein |
| braucht | Claude Code mit Cloud-Routinen, privates Git-Repository, Dashboard `artifact` | nur das gewählte Programm |
| Postfach | `gmail`/`forward` direkt; `apple_mail`/`imap` über die Brücke auf dem Rechner | jeder Modus direkt |
| Lebenslauf zuschneiden, Formulare | nein (nur am Rechner) | ja |
| geeignet für | Claude Code mit Gmail | andere Programme, Telekom & Co. ohne Umweg, wer nichts bei einem Git-Anbieter ablegen will |

`none`: kein Zeitplan; der Nutzer startet Läufe selbst oder über den Knopf.

Uhrzeit → `schedule.time` (Ortszeit). Kosten nennen: Jeder Lauf verbraucht Modell-Kontingent
des Nutzers; ein Lauf am Tag ist die Vorgabe.

## `local`

```
$PY 08_Scripts/schedule_install.py install daily --dry-run     # zeigen, was eingerichtet würde
$PY 08_Scripts/schedule_install.py install daily
$PY 08_Scripts/schedule_install.py status all
```

Den Probelauf (`--dry-run`) dem Nutzer zeigen, dann erst einrichten.

- macOS: ein Eintrag je Aufgabe in `~/Library/LaunchAgents` (`com.jobsuche.<aufgabe>`).
- Windows: eine Aufgabe je Eintrag in der Aufgabenplanung (`Jobsuche-<aufgabe>`); läuft nur,
  während der Nutzer angemeldet ist, es wird kein Passwort gespeichert.
- Linux: Das Skript gibt die Zeilen für die crontab aus; eintragen muss sie der Nutzer.

Zur Laufzeit öffnet sich ein Terminal-Fenster mit dem Assistenten und einem festen Auftrag.
Das Fenster ist nötig, weil der Assistent nur in einer sichtbaren Sitzung auf Dashboard und
Postfach-Werkzeuge zugreifen kann. War der Rechner zur Uhrzeit aus, holt macOS den Lauf nach
dem Aufwachen nach; unter Windows hängt das von der Aufgabenplanung ab – dann den Knopf
benutzen.

Entfernen: `schedule_install.py remove all`.

## `cloud` (Claude Code)

Voraussetzungen: Arbeitsordner als privates Git-Repository mit Gegenstelle (`git.sync: true`,
`references/einrichtung.md` Schritt 10), Dashboard in der Betriebsart `artifact`.

1. Routine anlegen: unter `claude.ai/code/routines` oder mit dem Werkzeug für geplante
   Läufe, falls deine Sitzung eines hat. Repository = das private Repository des Nutzers;
   Auftrag = `/jobsuche lauf`. Liegt der Skill nicht im Repository, stattdessen: „Lies
   skills/jobsuche/SKILL.md und führe den täglichen Lauf aus.“
   (Den Klickweg auf der Seite zeigt dir der Nutzer; beschreibe nur, was einzutragen ist.)
2. Uhrzeit: Der Zeitplan der Routine rechnet in **UTC und kennt keine Sommerzeit**. Die
   Ortszeit umrechnen und dem Nutzer sagen, dass sich der Lauf mit der Zeitumstellung um
   eine Stunde verschiebt.
3. Netzwerk: In der Cloud-Umgebung der Routine den Netzwerkzugriff auf **vollen Zugriff**
   stellen oder die Karriereseiten der Arbeitgeber aus `companies.yaml` einzeln erlauben.
   Mit der Voreinstellung erreicht `fetch` die Feeds nicht; der Lauf arbeitet dann nur mit
   Websuche und Alerts und meldet das.
4. Connectors (Gmail, gegebenenfalls ein Stellenportal) müssen für die Routine freigegeben
   sein.
5. Postfach `apple_mail` oder `imap`: Die Brücke auf dem Rechner holt die Mails und schiebt
   sie ins Repository, bevor der Cloud-Lauf startet:

   ```
   $PY 08_Scripts/schedule_install.py install mail
   ```

   `schedule.mail_bridge_times` so wählen, dass die erste Zeit vor `schedule.time` liegt.
   Das Skript wartet auf das Netz und überträgt nur `07_Logs/mail_inbox/`.
6. Probe: die Routine einmal von Hand starten und das Ergebnis mit dem Nutzer ansehen.

Was im Repository liegt, liegt beim Git-Anbieter: Profil, Lebenslauf, Anschreiben. Das
Repository bleibt privat; Zugangsdaten stehen dort nie.

## Abholer für „Job suche starten“ (Dashboard `artifact`)

Der Knopf speichert eine leere Datei `jobsuche-start-<Kennung>.trigger` im Download-Ordner.
Der Abholer schaut alle `schedule.poll_seconds` Sekunden nach, löscht sie und öffnet den
Assistenten. Er ist ein reines Skript und verbraucht kein Modell-Kontingent, solange nichts
gefunden wird.

```
$PY 08_Scripts/setup.py token
$PY 08_Scripts/schedule_install.py install poller
$PY 08_Scripts/trigger_poller.py --dry-run
```

- Speichert der Browser nicht im normalen Download-Ordner: `schedule.downloads_dir` setzen.
- macOS kann beim ersten Zugriff auf den Download-Ordner um Erlaubnis fragen oder den
  Zugriff still verweigern. Meldet `07_Logs/runs/` einen Zugriffsfehler: dem Python des
  Arbeitsordners unter Systemeinstellungen → Datenschutz & Sicherheit → Dateien und Ordner
  den Download-Ordner erlauben, oder `downloads_dir` auf einen Ordner außerhalb der
  geschützten Bereiche legen und den Browser dorthin speichern lassen.
- Der Browser fragt beim ersten Klick, ob die Seite Dateien speichern darf.
- Probe mit dem Nutzer: Knopf drücken, innerhalb von zwei bis drei Minuten öffnet sich das
  Terminal-Fenster.

Beim Dashboard `local` braucht es keinen Abholer; der Server startet den Lauf selbst.

## Lokales Dashboard dauerhaft

`dashboard_local.py serve` läuft, solange sein Terminal-Fenster offen ist. Einen eigenen
Autostart richtet der Skill nicht ein; wer ihn möchte, legt den Befehl in die
Anmeldeobjekte (macOS) bzw. den Autostart-Ordner (Windows).

## Störungen

| Zeichen | Ursache | Abhilfe |
|---|---|---|
| kein Fenster zur Laufzeit | Rechner aus, Nutzer nicht angemeldet, Programm nicht gefunden | `schedule_install.py status all`; `run_local.py daily --dry-run`; `07_Logs/runs/run_local.log` |
| „läuft bereits“ | Sperre: zwei Starts innerhalb von 30 Minuten | warten |
| Knopf ohne Wirkung | Abholer nicht eingerichtet, anderer Download-Ordner, Kennung geändert | Abschnitt Abholer |
| Cloud-Lauf ohne Feeds | Netzwerkzugriff der Umgebung | Schritt 3 |
| Cloud-Lauf ohne Alerts | Brücke lief nicht (Rechner aus) | nächster Lauf holt sie nach (`mail.days_back`) |
