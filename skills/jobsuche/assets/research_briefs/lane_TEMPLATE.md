# Recherche-Briefing <REGION> ({DATE}), Lane <KÜRZEL>

<!-- Vorlage: je Suchregion aus 01_Config/search_profile.yaml (lanes) eine Kopie als
     lane_<KÜRZEL>.md anlegen und die <…>-Stellen füllen. {DATE} bleibt stehen, der Lauf setzt
     das Datum ein. Die Regeln aus _common.md werden automatisch angehängt. -->

Finde neue, offene Stellen in <LAND ODER REGION>. Vorrang: <ORTE AUS lanes.<name>.locations, wichtigste
zuerst>; darüber hinaus nur bei außergewöhnlicher Passung.

Rollen (in <SPRACHEN> suchen): <ROLLEN AUS roles.high_priority UND roles.also_relevant>.
Höchstens <ZAHL> reine KI-Rollen (Obergrenze `daily_selection.max_ai_share`).

<!-- Optional, wenn es zwei gleichrangige Rollenfamilien gibt:
**Zwei gleichrangige Rollenfamilien** – suche beide in jedem Lauf und liefere aus beiden:
1. <FAMILIE 1>
2. <FAMILIE 2>, belegt im Profil durch <STATION AUS candidate_profile.md>
-->

Unternehmen gezielt prüfen (Karriereseite zuerst), je Lauf mindestens <N> davon, wechselnd:
<ARBEITGEBER AUS companies.yaml (watchlist) FÜR DIESE REGION>. Zusätzlich Websuche über die
Ergebnisseiten der Jobbörsen aus `job_boards`; das Original immer beim Arbeitgeber prüfen.
Abfragewege: `ats` in companies.yaml (Feeds, schon von `fetch` abgedeckt, dann eine andere Firma
wählen) und `ats_lookup`. Die <N> Firmen einzeln mit Ergebnis in `sources_checked`.

Suchanfragen (Beispiele, mit den Rollen und Orten oben kombinieren):
- "<ROLLE>" "<ORT>" Stellenangebot
- "<ROLLE>" <BRANCHE> <ORT> jobs
- site:<KARRIERESEITE> "<ROLLE>"

Gehaltsziel <LAND>: mindestens <BETRAG UND WÄHRUNG AUS salary_rules.yaml> brutto pro Jahr (nie schätzen).
<OPTIONAL: Besonderheiten der Region, z. B. Visum, Sprache, Pendelgrenze>
LANE = <KÜRZEL>
