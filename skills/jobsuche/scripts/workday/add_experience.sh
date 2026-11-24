#!/usr/bin/env bash
# Optional helper for German Workday application forms (macOS/Linux, needs the gstack browse tool).
# Adds one work-experience block on the open "Berufserfahrung" page and fills it.
# usage: add_experience.sh TITLE COMPANY LOCATION FROM_MONTH FROM_YEAR TO_MONTH TO_YEAR DESCRIPTION
# The browse binary is taken from $BROWSE_BIN, else from the usual gstack install folder.
B="${BROWSE_BIN:-$HOME/.claude/skills/gstack/browse/dist/browse}"
[ -x "$B" ] || { echo "Browser-Werkzeug nicht gefunden: $B (BROWSE_BIN setzen)"; exit 1; }
[ $# -eq 8 ] || { echo "Aufruf: add_experience.sh TITEL FIRMA ORT VON_MONAT VON_JAHR BIS_MONAT BIS_JAHR BESCHREIBUNG"; exit 1; }
S=$("$B" --headed snapshot -i 2>&1)
ADD=$(echo "$S" | grep '"Weitere hinzufügen"' | grep -o '@e[0-9]*' | head -1)
"$B" --headed click "$ADD" >/dev/null 2>&1; sleep 1.5
S=$("$B" --headed snapshot -i 2>&1)
field() { echo "$S" | grep "\"$1\"" | grep -v ': ' | grep -o '@e[0-9]*' | head -1; }   # first empty field with this label
T=$(field "Tätigkeitsbezeichnung"); C=$(field "Unternehmen"); L=$(field "Standort"); D=$(field "Rollenbeschreibung")
SP=()
while IFS= read -r ref; do SP+=("$ref"); done < <(echo "$S" | grep 'spinbutton' | grep -v ': "' | grep -o '@e[0-9]*')
echo "refs T=$T C=$C L=$L D=$D spins=${SP[*]}"
[ -n "$T" ] && [ -n "$C" ] && [ "${#SP[@]}" -ge 4 ] || { echo "Felder nicht gefunden - Seite prüfen"; exit 1; }
"$B" --headed fill "$T" "$1" >/dev/null; "$B" --headed fill "$C" "$2" >/dev/null; "$B" --headed fill "$L" "$3" >/dev/null
"$B" --headed fill "${SP[0]}" "$4" >/dev/null; "$B" --headed fill "${SP[1]}" "$5" >/dev/null
"$B" --headed fill "${SP[2]}" "$6" >/dev/null; "$B" --headed fill "${SP[3]}" "$7" >/dev/null
"$B" --headed fill "$D" "$8" >/dev/null
