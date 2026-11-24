#!/usr/bin/env bash
# Optional helper for German Workday application forms (macOS/Linux, needs the gstack browse tool).
# Adds one language entry on the open page and fills it.
# usage: add_language.sh LANGUAGE LEVEL FLUENT(0|1)   LANGUAGE and LEVEL exactly as the form's lists show them
# The browse binary is taken from $BROWSE_BIN, else from the usual gstack install folder.
B="${BROWSE_BIN:-$HOME/.claude/skills/gstack/browse/dist/browse}"
[ -x "$B" ] || { echo "Browser-Werkzeug nicht gefunden: $B (BROWSE_BIN setzen)"; exit 1; }
[ $# -eq 3 ] || { echo "Aufruf: add_language.sh SPRACHE NIVEAU FLIESSEND(0|1)"; exit 1; }
# The two values are put into page script text: allow only letters, digits, spaces and . , ( ) / + -
for v in "$1" "$2"; do
  case "$v" in *[!A-Za-z0-9ÄÖÜäöüß\ .,\(\)/+-]*) echo "Unzulässiges Zeichen in: $v"; exit 1;; esac
done
"$B" --headed js "const b=[...document.querySelectorAll('button')].filter(x=>['Weitere hinzufügen','Hinzufügen'].includes(x.innerText.trim())); const s=b.find(x=>x.closest('[aria-labelledby=Sprachen-section]'))||b[2]; s.click(); 'add'" >/dev/null
sleep 1.5
pick() {
  local btn
  btn=$("$B" --headed snapshot -i 2>&1 | grep "\[button\] \"$1 Wert auswählen" | grep -o '@e[0-9]*' | tail -1)
  [ -z "$btn" ] && { echo "kein leeres Feld $1"; return; }
  "$B" --headed click "$btn" >/dev/null 2>&1; sleep 1
  "$B" --headed js "const o=[...document.querySelectorAll('[role=option]')].filter(x=>x.innerText.trim()==='$2' && x.offsetParent); o.length ? (o[0].scrollIntoView({block:'center'}), o[0].click(), 'ok') : 'missing $2'" | grep missing
  sleep 0.8
}
pick "Sprache" "$1"
if [ "$3" = "1" ]; then
  c=$("$B" --headed snapshot -i 2>&1 | grep 'fließend' | grep -v checked | grep -o '@e[0-9]*' | tail -1)
  [ -n "$c" ] && "$B" --headed click "$c" >/dev/null 2>&1
fi
pick "Lesen" "$2"; pick "Lesen - Sprechen - Schreiben" "$2"; pick "Schreiben" "$2"; pick "Sprechen" "$2"
