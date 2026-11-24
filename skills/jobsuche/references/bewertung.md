# Triage, Fact-Check und Bewertung

Maßstab ist immer `01_Config/candidate_profile.md` (belegt / teilweise / nicht belegt) und
`01_Config/search_profile.yaml` (Rollen, Regionen, Gewichte, Schwellen). Die Gesamtnote, die
Gehaltsregeln und die Mengenregeln rechnet `jobsearch.py finalize` – du lieferst Teilnoten und
Begründungen.

## Triage

Aus allen neuen Kandidaten die wählen, die nach Titel, Ort und Seniorität realistisch die
Watchlist-Schwelle erreichen können (Standard 7.0). Keine Obergrenze: Sind es viele, alle
bewerten, bei Bedarf auf Hilfsagenten verteilt.

Alle anderen kommen mit **eigener, kurzer Begründung je Stelle** nach `screened_out` (was am
Titel nicht passt), damit sie nicht wiederkommen. Regeln, die `finalize` durchsetzt:

- Sammelbegründungen sind verboten (ab 10 gleichen Gründen Warnung, ab 15 Fehler). Wer viele
  Stellen pauschal streicht, hat sie nicht geprüft.
- Vermutungen über eine nicht gelesene Anzeige sind kein Grund („vermutlich zu senior“,
  „wahrscheinlich fachfremd“). Dann die Anzeige lesen oder einen Vorab-Score vergeben.
- Rollen, die das Suchprofil ausdrücklich als Kern nennt, und Branchen, die der Nutzer
  ausdrücklich will, sind nie ein Aussortiergrund. Obergrenzen für einen Rollenanteil (z. B.
  KI-Rollen) begrenzen nur die Top-Empfehlungen; bewertet wird die Stelle trotzdem.
- Rückstands-Stellen mit `must_score: true` immer vollständig bewerten.
- Jede neue Stelle aus `mail_candidates.json` landet in `jobs` (bewertet) oder `screened_out`.
- `screened_out` ist nur für Aussortierte. Gewählte Kandidaten gehören bewertet nach `jobs`.

Aussortieren: Berufsjahre weit über dem Profil als Pflicht, Ebenen außerhalb des Suchprofils,
harte Blocker aus `exclusions.yaml`, Orte außerhalb der Regionen, Anzeigen älter als die im
Suchprofil gesetzte Frist ohne besondere Passung.

## Fact-Check

Für jeden Kandidaten die Originalanzeige vollständig lesen:
`$PY 08_Scripts/jobsearch.py detail --keys KEY1,KEY2` (Arbeitgeber-Feeds) oder die
Arbeitgeberseite abrufen. Vor einer Empfehlung prüfen: noch offen? Unternehmen, Ort, Rolle,
Link, Kennung richtig? Gehalt richtig übernommen? Remote/Hybrid richtig gelesen? Visum oder
Umzugshilfe wirklich genannt? Ungeprüfte Stellen bekommen `verified_open: false` und dürfen
nicht APPLY sein.

**Originalanzeige wirklich suchen.** Für jede Alert- oder Portal-Stelle mindestens drei
konkrete Versuche: Stellen-Schnittstelle des Arbeitgebers (Workday, SuccessFactors,
Greenhouse, Lever, Ashby, Personio …), Karriereseite, Websuche „<Firma> <Titel> <Ort>“. Bei
Personalvermittlern zählt deren eigene Anzeige. Erst wenn alle scheitern: Vorab-Score
(`score_basis: "alert"`) mit `verification_note` im Format
`Versuche: <Weg 1>: <Ergebnis>; <Weg 2>: <Ergebnis>; <Weg 3>: <Ergebnis>`.
„Nicht abgefragt“ oder „nur Titel gelesen“ zählt nicht als Versuch. Kernrollen des
Suchprofils mit Vorab-Note ab 6.0 nie als Vorab-Score stehen lassen.

Firmennamen kurz und einheitlich (ohne Rechtsform und Klammerzusätze), Orte ohne Zusätze –
beides fließt in Dublettenschlüssel und Dateinamen ein. Tracking-Parameter (`utm_…`) aus
Links entfernen.

Quellen-Rangfolge bei Widersprüchen: Unternehmensseite > offizieller Stellen-Feed >
verbundener Portal-Connector > etabliertes Portal > Suchmaschine > Sonstiges.

## Teilnoten (0.0–10.0, ohne Inflation)

Die Gewichte stehen in `search_profile.yaml` (`weights`); die Anker unten gelten sinngemäß.

| Kriterium | Anker |
|---|---|
| `fachlich` | 9–10: fast alle Muss-Anforderungen belegt · 7–8: Kern belegt, 1–2 Muss teilweise/nicht belegt · 5–6: die Hälfte fehlt · < 5: anderes Berufsbild |
| `transfer` | 9–10: Aufgaben fast gleich der heutigen Arbeit · 7–8: gleiche Methode, andere Domäne · 5–6: nur allgemein übertragbar |
| `senioritaet` | 9–10: Ebene passt zu den Berufsjahren mit Entwicklungsschritt · 7–8: leicht darüber/darunter · ≤ 6: deutlich mehr Jahre, Führung oder Budget vorausgesetzt |
| `compensation` | setzt das Skript aus dem Gehaltsstatus; ohne Angabe neutral, außer in Ländern mit `salary_required` |
| `standort` | 9–10: Wunschorte aus dem Suchprofil · 7–8: weitere akzeptierte Orte · Ausland mit zugesagter Hilfe 7–9, ohne Angabe 4–6, ausdrücklich ohne Hilfe ≤ 2 |
| `strategie` | 9–10: Zielunternehmen/-branche mit klarem Karriereschritt · 7–8: gute Marke oder Entwicklung · 5–6: neutral |

**Gehaltsstatus** (`salary.status`): `VERIFIED` (steht in der Anzeige; `min`/`max`/`currency`),
`LIKELY` (nur mit belastbarer `evidence`, z. B. Tarifbindung mit Entgeltgruppe), `UNKNOWN`,
`BELOW_TARGET` (nachweislich darunter – nie Top-Treffer). Ziele je Land stehen in
`salary_rules.yaml`. Monats-, Tages- und Stundensätze mit `period` erfassen; das Skript
rechnet um. Schätzungen eines Portals sind nie `VERIFIED`. Nie selbst schätzen.

**Chance:** 3–6 `must_haves` aus der Anzeige – nur echte Muss-Anforderungen (Jahre, Abschluss,
Pflicht-Werkzeug, Sprache, Arbeitserlaubnis), keine Wünsche. Je Eintrag `status`: `met`
(belegt), `partial`, `missing`. `blocker: true` nur für Ausschlusskriterien. Das Skript
rechnet daraus `chance_score`. Ehrlich markieren: Die Chance sagt voraus, ob eine Firma
einlädt – nicht, ob der Nutzer die Stelle will.

**Skill-Gap** je Stelle: `matched`, `partial`, `missing`, `unknown` – in den Worten des
Profils. Gefordertes Werkzeug mit Grundkenntnissen → `partial`, nicht belegtes → `missing`,
nie „vergleichbare Erfahrung“.

**Kategorien und Empfehlung** folgen den Schwellen in `search_profile.yaml` (Standard:
`APPLY` ab 8.5, 8.0–8.4 nur mit `strategic: true` und Begründung, `CONSIDER` für die
Watchlist ab 7.0, sonst `SKIP`). `stretch: true` für höchstens drei Stretch-Stellen.
`hard_blocker` setzen, wenn ein Blocker greift.

Tagesziel sind wenige wirklich gute Stellen. Gibt es nur zwei, werden zwei gezeigt. Keine
Relevanz erfinden, um eine Quote zu füllen.

## Vorab-Score für Alert-Stellen

Alert-Stellen, deren Originalanzeige nicht auffindbar ist: Kurzbewertung nur aus Titel,
Unternehmen und Ort mit denselben Teilnoten, `score_basis: "alert"`, `verified_open: false`,
ein Satz `why_fit`, ein Satz `main_gap`. Sie erscheinen nie unter „Neu“, sondern im
Portal-Reiter als „Vorab-Score“. Lieber niedrig und ehrlich als geraten. Weitere Städte
derselben Ausschreibung nicht einzeln bewerten, sondern in `other_locations` führen.

## Schema `scored.json`

```json
{
  "date": "YYYY-MM-DD",
  "known_skipped": 0,
  "jobs": [{
    "title": "", "company": "", "location": "", "country": "DE", "industry": "",
    "url": "", "apply_url": "", "source": "company_site", "job_id": "", "posted_date": "YYYY-MM-DD",
    "posting_language": "de",
    "salary_text": null, "salary": {"status": "UNKNOWN", "min": null, "max": null, "currency": "EUR", "evidence": null},
    "remote": "hybrid", "remote_text": null, "visa_text": null, "relocation_text": null,
    "experience_required": null,
    "responsibilities": [], "requirements": [], "nice_to_have": [], "contact": null,
    "verified_open": true, "verification_note": "",
    "scores": {"fachlich": 0, "transfer": 0, "senioritaet": 0, "standort": 0, "strategie": 0},
    "score_rationale": "2–3 Sätze zur Begründung der Teilnoten",
    "skills": {"matched": [], "partial": [], "missing": [], "unknown": []},
    "must_haves": [{"req": "", "status": "partial", "blocker": false}],
    "why_fit": "ein Satz", "main_gap": "ein Satz",
    "recommendation": "APPLY", "strategic": false, "stretch": false, "is_ai_role": false, "hard_blocker": null,
    "arguments": [], "weaknesses": [], "screening_risks": [], "application_questions": [], "cv_suggestions": [],
    "origin": "", "score_basis": "posting", "portal_url": "", "alert_name": "", "other_locations": [],
    "cover_letter": {"language": "de", "subject": "", "salutation": "", "paragraphs": ["", "", "", ""]}
  }],
  "screened_out": [{"title": "", "company": "", "location": "", "url": "", "job_id": "", "source": "", "reason": ""}]
}
```

`cover_letter` nur bei `APPLY` – oder mit `"letter_requested": true`, wenn der Nutzer
ausdrücklich eine Bewerbung auf genau diese Stelle verlangt hat (nie von selbst setzen).
`origin`, `portal_url`, `alert_name` nur bei Stellen aus Alert-Mails. Optional `segment`,
wenn die automatische Zuordnung nach Titel danebenliegt; Stellen einer Suchspur mit eigenem
Reiter behalten deren `segment`.

## Einzelne Stelle bewerten (`/jobsuche bewerte <URL>`)

Originalanzeige auf der Arbeitgeberseite prüfen (Portal-Kopien können veraltet sein; ist die
Stelle dort geschlossen, `closed: true`), mit `jobsearch.py dedup --in <datei>` gegen den
Bestand abgleichen, bewerten und mit `origin: "manual"` in eine eigene Datei schreiben. Dann
`jobsearch.py finalize --in <datei> --date DATE` – ein weiterer `finalize` am selben Tag
ergänzt den Tageslauf (nur `--replace` würde ihn verwerfen). Vom Nutzer eingereichte Stellen
bleiben immer sichtbar.
