# Postfach einrichten

Das Postfach liefert zweierlei: die **Job-Alerts** der Portale (LinkedIn, XING, Indeed …) und
die **Antworten der Unternehmen** auf Bewerbungen. Gelesen werden nur diese Mails. Gesendet
wird nie etwas; eine Bewerbungs-Mail entsteht höchstens als Entwurf, den der Nutzer selbst
abschickt.

Zuerst fragen, bei welchem Anbieter das Postfach liegt, in dem die Alerts ankommen, und den
Weg aus der Tabelle wählen. Trag `mail.address` und `mail.mode` ein.

| Lage | `mail.mode` | Aufwand |
|---|---|---|
| Gmail, und ein Gmail-Connector ist in deinem Programm verbunden | `gmail` | keiner |
| Mac, das Konto ist in der Mail-App eingerichtet | `apple_mail` | 2 Minuten, kein Passwort |
| jeder andere Anbieter (Telekom/T-Online, GMX, WEB.DE, Outlook.com, iCloud, Posteo …), Windows oder Mac | `imap` | 10 Minuten |
| IMAP nicht gewünscht oder nicht möglich | `forward` | Weiterleitung an ein Gmail-Postfach mit Connector |
| ohne Mail | `none` | keine Alerts, keine automatischen Statusänderungen |

Bei einem Cloud-Lauf gilt: `gmail` und `forward` liest der Lauf selbst. `apple_mail` und
`imap` liest eine kleine Brücke auf dem Rechner des Nutzers und legt das Ergebnis im
Arbeitsordner ab; der Rechner muss dafür zu den Brücken-Zeiten an sein
(`references/zeitplan.md`).

## Alerts abonnieren (bei jedem Weg)

Der Nutzer legt in den Portalen selbst gespeicherte Suchen mit täglicher Mail an. Du
schlägst ihm je Portal drei bis sechs Suchen aus `search_profile.yaml` vor (Titel + Ort) und
trägst die Absender in `mail.alert_senders` ein. Die Portale selbst rufst du nie ab.

## `gmail`

1. Prüfen, ob ein Gmail-Werkzeug vorhanden ist (Suche nach Threads). Fehlt es: Der Nutzer
   verbindet Gmail in den Einstellungen seines Programms (Connectors); das ist sein Klick
   und seine Anmeldung.
2. Probe: nach einem Alert-Absender der letzten 7 Tage suchen, kleinste Ansicht. Nennen,
   wie viele Mails gefunden wurden – keine Inhalte ausbreiten.
3. Bewerbungs-Mails entstehen als Entwurf über den Connector, nie als gesendete Mail.

## `apple_mail` (nur macOS)

1. Kontoname erfragen, so wie er in Mail unter Einstellungen → Accounts steht →
   `mail.apple_mail.account`; Postfächer → `mailboxes` (meist `INBOX`).
2. Probe: `$PY 08_Scripts/mail_bridge_apple.py --days 7`. macOS fragt beim ersten Mal, ob
   das Terminal Mail steuern darf: der Nutzer erlaubt es. (Später ändern unter
   Systemeinstellungen → Datenschutz & Sicherheit → Automation.)
3. Das Skript nennt die Zahl der gefundenen Mails und schreibt `07_Logs/mail_inbox/`.

## `imap` – Schritt für Schritt (Beispiel Telekom / T-Online)

Jeder Schritt ist eine Sache; erst weiter, wenn sie erledigt ist.

1. **Server:** `$PY 08_Scripts/mail_bridge_imap.py hosts` zeigt die Server gängiger
   Anbieter. Telekom: `secureimap.t-online.de`, Port 993. Bei anderen Anbietern steht der
   „Posteingangsserver (IMAP)“ auf deren Hilfeseite. Eintragen: `mail.imap.host`,
   `mail.imap.user` (in der Regel die vollständige Mailadresse).
2. **Zugang für Mail-Programme beim Anbieter freischalten.** Das macht der Nutzer in seinem
   Kundenkonto, du erklärst nur wo:
   - *Telekom:* Für Mail-Programme gilt nicht das Login-Passwort, sondern ein eigenes
     „Passwort für E-Mail-Programme“. Es wird im Kundencenter bzw. in den Einstellungen des
     E-Mail-Centers festgelegt (Menüpunkt mit den Passwörtern). Den genauen Klickweg ändert
     der Anbieter gelegentlich; findet der Nutzer ihn nicht, in der Telekom-Hilfe nach
     „Passwort für E-Mail-Programme“ suchen.
   - *GMX, WEB.DE:* in den Einstellungen des Postfachs „POP3/IMAP-Abruf“ erlauben.
   - *Gmail, iCloud, Outlook.com, Yahoo:* Zwei-Faktor-Anmeldung einschalten und ein
     „App-Passwort“ erzeugen; das normale Passwort funktioniert dort nicht.
   Der Nutzer legt das Passwort selbst fest und nennt es dir nicht.
3. **Passwort hinterlegen – im eigenen Terminal des Nutzers, nicht über dich.** Er öffnet
   ein Terminal (Windows: PowerShell), wechselt in den Arbeitsordner und tippt:
   - macOS/Linux: `.venv/bin/python 08_Scripts/mail_bridge_imap.py set-password`
   - Windows: `.venv\Scripts\python.exe 08_Scripts\mail_bridge_imap.py set-password`

   Die Eingabe bleibt unsichtbar und landet nur im Schlüsselbund des Systems (macOS
   Schlüsselbund, Windows Anmeldeinformationsverwaltung). Das Skript verweigert die Eingabe,
   wenn es nicht in einem echten Terminal läuft – starte es deshalb nie selbst.
4. **Prüfen:** `$PY 08_Scripts/mail_bridge_imap.py check`. Meldet Anmeldung, Ordner und Zahl
   der Alert-Mails. Typische Fehler:
   - „Anmeldung abgelehnt“: Schritt 2 fehlt, falsches Passwort (das Login-Passwort statt des
     Programm-Passworts) oder falscher Benutzername. Zurück zu Schritt 2 bzw. 3.
   - „Server nicht erreichbar“: Tippfehler im Server, Firmen-Netz oder VPN blockt Port 993.
   - 0 Alert-Mails: Absender in `mail.alert_senders` stimmen nicht, oder die Alerts liegen
     in einem anderen Ordner.
5. **Ordner:** `$PY 08_Scripts/mail_bridge_imap.py folders` listet die Ordnernamen. Den
   Ordner für Entwürfe in `mail.imap.drafts_folder` eintragen (Telekom-Postfächer nennen ihn
   oft anders als „Drafts“), weitere Ordner mit Alerts in `mail.imap.folders`.
6. **Probeabruf:** `$PY 08_Scripts/mail_bridge_imap.py fetch --days 7`.

Was die Brücke technisch tut und nicht tut: nur verschlüsselte Verbindung mit geprüftem
Zertifikat; das Postfach wird nur lesend geöffnet, nichts wird als gelesen markiert,
verschoben oder gelöscht; der einzige Schreibvorgang ist das Ablegen eines Entwurfs
(`put-draft`); es gibt keinen Code zum Senden. Passwort entfernen:
`mail_bridge_imap.py delete-password`.

## `forward`

Der Nutzer richtet bei seinem Anbieter eine Weiterleitung nur für die Alert-Absender an ein
Gmail-Postfach ein, das mit dem Connector verbunden ist (Filterregel beim Anbieter; Gmail
bestätigt die Weiterleitung mit einer Mail). Danach wie `gmail`. Antworten der Unternehmen
kommen so nur an, wenn er auch sie weiterleitet – darauf hinweisen.

## Bewerbung per Mail

`$PY 08_Scripts/jobsearch.py mail-draft --key <KEY>` (mit `--dry-run` zum Ansehen) bereitet
Text und Anhänge vor; der Text durchläuft den Humanizer.

- `gmail`: das Skript schreibt `07_Logs/apply_local/<key>/gmail_draft.json`; mit genau
  diesen Angaben den Entwurf über den Connector anlegen.
- `imap`: `$PY 08_Scripts/mail_bridge_imap.py put-draft --eml 07_Logs/apply_local/<key>/Bewerbung_<key>.eml`
  legt den Entwurf im Entwürfe-Ordner ab.
- `apple_mail`, `forward`, `none`: Der Nutzer öffnet die `.eml`-Datei mit einem Doppelklick
  in seinem Mail-Programm.

In jedem Fall liest der Nutzer den Entwurf und sendet selbst.

## Wechsel des Anbieters

`/jobsuche einrichten mail` erneut durchlaufen. Bei einem Wechsel weg von `imap`:
`mail_bridge_imap.py delete-password` und den lokalen Zeitplan der Brücke entfernen
(`schedule_install.py remove mail`).
