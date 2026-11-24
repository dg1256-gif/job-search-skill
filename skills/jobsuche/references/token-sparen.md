# Token sparen – so ist der Skill gebaut, so bleibt er sparsam

## Bauweise

- **Skripte statt Modell:** Abrufen der Arbeitgeber-Feeds, Dubletten-Abgleich, Offen-Prüfung,
  Noten rechnen, Dokumente bauen und prüfen, Berichte, Dashboard-Abgleich und Mail-Abruf
  erledigen Skripte. Sie geben nur knappe Ergebnisse aus. Das Modell liest Anzeigen,
  urteilt und schreibt.
- **Nur Neues:** `fetch`, `mail-candidates` und `dedup` liefern nur neue, wesentlich
  geänderte und noch unbewertete Stellen. Bekannte Stellen werden nie erneut abgerufen
  oder bewertet.
- **Dashboard nur als Differenz:** `dashboard-export` gibt nur geänderte Einträge aus, in
  Paketen zu höchstens 50.
- **Anleitungen in Teilen:** `SKILL.md` ist kurz; je Aufgabe wird nur die passende Datei
  aus `references/` gelesen.
- **Start-Knopf ohne Modell:** Der lokale Abholer und der Zeitplan sind reine Skripte; ein
  Modell läuft erst, wenn wirklich ein Lauf startet.

## Regeln im Betrieb

1. Hilfsagenten für Recherche laufen mit `agent.helper_model` (kleineres Modell, mittlere
   Denktiefe). Zu niedrige Denktiefe liefert bei der Recherche kaum Treffer – mittlere ist
   der erprobte Kompromiss.
2. Dateien gezielt lesen (Suche, Ausschnitte). Große JSON- und CSV-Dateien nie vollständig
   ausgeben; die Skripte liefern Zusammenfassungen.
3. Je Stelle die Anzeige einmal abrufen. Websuchen gezielt, dieselbe Suche nicht wiederholen.
4. Mails: Listen in der kleinsten Ansicht abrufen (nur Betreff, Absender, Kurztext) und roh
   an das Skript geben; eine ganze Mail nur öffnen, wenn Betreff und Kurztext nicht reichen.
   Mails von Portalen enthalten oft nur Tracking-Links und kosten viel für nichts.
5. Werkzeug-Ergebnisse nicht durch den Kontext blättern, um sie zu filtern: in eine Datei
   schreiben lassen und mit einem Skript auswerten.
6. Zwischenstände knapp halten; ausführlich ist nur die Morgen-Nachricht.
7. Formulare ausfüllen und Status setzen brauchen kein großes Modell.
8. Parallele Hilfsagenten nur für getrennte Aufgaben (eine Region je Agent), nie zwei für
   dieselbe.

## Einmalige Einrichtung, die dauerhaft spart

- Arbeitgeber mit offener Stellen-Schnittstelle in `companies.yaml` eintragen – ein
  Feed-Abruf kostet kein Modell, eine Websuche schon.
- Job-Alerts bei den Portalen eng fassen (Titel, Region); jede Alert-Stelle wird bewertet.
- `exclusions.yaml` und die Titel-Filter in `search_profile.yaml` pflegen: Was das Skript
  aussortiert, sieht das Modell nie.
- Rückmeldungen („keine befristeten Stellen“) im `changelog` der `search_profile.yaml`
  festhalten, damit dieselbe Art Stelle nicht jeden Tag neu geprüft wird.
