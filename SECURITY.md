# Sicherheit / Security

## Eine Schwachstelle melden / Reporting a vulnerability

Bitte **kein öffentliches Issue** für Sicherheitslücken. Nutze stattdessen
„Report a vulnerability“ im Reiter *Security* dieses Repositories (GitHub Private
Vulnerability Reporting). Beschreibe, was passiert, wie es sich nachstellen lässt und
welche Fassung (Commit) betroffen ist. Eine Antwort kommt nach Möglichkeit innerhalb von
14 Tagen. Dies ist ein privates Projekt ohne zugesicherte Reaktionszeiten.

Please do **not** open a public issue for security problems. Use "Report a vulnerability"
on the repository's *Security* tab instead. This is a personal project without a
guaranteed response time; expect a reply within about 14 days.

## Was der Skill absichert

- **Kein Absenden ohne Bestätigung.** Bewerbungen, Mails und Nachfragen werden nur
  vorbereitet. Abgeschickt wird erst nach dem Ja des Nutzers zu genau dieser Bewerbung.
- **Fremder Text ist Material.** Stellenanzeigen, Mails, Dashboard-Einträge und Dateien aus
  dem Netz werden nie als Anweisung behandelt. `posting_guard.py` entfernt vor dem Lesen
  versteckte Elemente, unsichtbare Zeichen und Zeilen, die sich an eine KI richten, und
  markiert die Anzeige.
- **Keine Zugangsdaten im Arbeitsordner.** Ein Mail-Passwort liegt nur im Schlüsselbund des
  Betriebssystems; Anmelden und CAPTCHAs macht der Nutzer.
- **Nur Belegtes.** Texte behaupten nur, was das eigene Profil belegt.
- **Dieses Repository enthält keine persönlichen Daten.** Die CI prüft jeden Commit auf
  Geheimnisse (gitleaks), Mail-Adressen und Benutzerpfade.

## Grenzen

- Der Schutz vor manipulierten Anzeigen arbeitet mit festen Mustern. Er senkt das Risiko,
  schließt es aber nicht aus; die Regeln in `SKILL.md` gelten deshalb zusätzlich, und der
  Stopp vor dem Absenden bleibt die letzte Sicherung.
- Profil und Anzeigen gehen an den Anbieter des gewählten Modells (siehe README, „Wohin die
  Daten gehen“).
- Auf Windows und mit anderen Programmen als Claude Code ist der Skill nicht erprobt.
