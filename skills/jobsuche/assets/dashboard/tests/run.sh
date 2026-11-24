#!/bin/zsh
# Browser test of the dashboard page against an in-memory db (macOS wrapper around run.py).
# Usage: tests/run.sh      prints one FAIL line per failed check, then "N von N OK".
# Python comes from JOBSUCHE_PYTHON (else python3); python-docx there also checks the built .docx.
# Browser: gstack browse if installed, else headless Chrome/Edge, else the default browser.
# Other systems: python tests/run.py   (options: python tests/run.py --help)
cd "$(dirname "$0")" || exit 1
B=~/.claude/skills/gstack/browse/dist/browse
if [ -x "$B" ] && [ -z "$JOBSUCHE_BROWSER" ]; then
  exec "${JOBSUCHE_PYTHON:-python3}" run.py --browse "$B" "$@"
fi
exec "${JOBSUCHE_PYTHON:-python3}" run.py "$@"
