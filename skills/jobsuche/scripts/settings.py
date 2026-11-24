#!/usr/bin/env python3
"""Shared settings loader: every script reads the workspace and 01_Config/settings.yaml through this.

The workspace root is the parent of the folder this file lives in (scripts are copied to
<workspace>/08_Scripts/). JOBSUCHE_ROOT overrides it, which the tests use.

  python 08_Scripts/settings.py            -> prints the settings that are still placeholders
"""
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("JOBSUCHE_ROOT") or Path(__file__).resolve().parent.parent)
SETTINGS_FILE = ROOT / "01_Config" / "settings.yaml"
PLACEHOLDER = re.compile(r"^<[^<>]+>$|<[A-ZÄÖÜ_ ]{3,}>")

DEFAULTS = {
    "person": {"full_name": "", "city": "", "timezone": "Europe/Berlin", "fixed_title": ""},
    "language": {"default": "de"},
    "mail": {"mode": "none", "address": "", "alert_senders": [], "days_back": 2, "signature_lines": [],
             "imap": {"host": "", "port": 993, "user": "", "keyring_service": "jobsuche-imap",
                      "drafts_folder": "Drafts", "folders": ["INBOX"]},
             "apple_mail": {"account": "", "mailboxes": ["INBOX"]}},
    "templates": {"cover_letter": "", "cover_letter_slots": {}, "cover_letter_leftovers": [],
                  "cv": {"de": "", "en": ""}, "cv_pdf": "", "cv_slots": {}},
    "documents": {"pdf_engine": "auto", "letter_filename": "Anschreiben_{role}.docx",
                  "letter_words": [250, 400], "max_pages": 1, "cv_summary_words": [50, 140]},
    "browser": {"engine": "auto"},
    "form_defaults": {},
    "dashboard": {"mode": "artifact", "local_port": 8765, "url": "", "trigger_token": "", "portals": [],
                  "segment_tabs": []},
    "schedule": {"mode": "none", "time": "07:30", "mail_bridge_times": ["07:00", "18:30"],
                 "poll_seconds": 120, "downloads_dir": ""},
    "agent": {"cli": "claude", "model": "", "helper_model": "", "command": ""},
    "git": {"sync": False},
}


def is_placeholder(value):
    return isinstance(value, str) and bool(PLACEHOLDER.search(value))


def _merge(base, over):
    out = dict(base)
    for key, val in (over or {}).items():
        out[key] = _merge(base[key], val) if isinstance(val, dict) and isinstance(base.get(key), dict) else val
    return out


def _blank(node):
    """Placeholders read as empty, so a script never works with '<WOHNORT>' as if it were a value."""
    if isinstance(node, dict):
        return {k: _blank(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_blank(v) for v in node if not is_placeholder(v)]
    return "" if is_placeholder(node) else node


def load(raw=False):
    """Settings merged over the defaults. raw=True keeps placeholder strings (for the setup check)."""
    data = {}
    if SETTINGS_FILE.exists():
        data = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    merged = _merge(DEFAULTS, data)
    return merged if raw else _blank(merged)


def path(value):
    """A settings path: relative to the workspace, '~' allowed, empty -> None."""
    if not value:
        return None
    p = Path(os.path.expanduser(str(value)))
    return p if p.is_absolute() else ROOT / p


def open_placeholders(node=None, prefix=""):
    node = load(raw=True) if node is None else node
    found = []
    if isinstance(node, dict):
        for key, val in node.items():
            found += open_placeholders(val, f"{prefix}{key}.")
    elif isinstance(node, list):
        for i, val in enumerate(node):
            found += open_placeholders(val, f"{prefix}{i}.")
    elif is_placeholder(node):
        found.append((prefix.rstrip("."), node))
    return found


def venv_python():
    """The workspace interpreter on macOS/Linux and Windows."""
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    return win if win.exists() else ROOT / ".venv" / "bin" / "python"


if __name__ == "__main__":
    missing = open_placeholders()
    for key, val in missing:
        print(f"offen: {key} = {val}")
    print(f"{len(missing)} Platzhalter offen" if missing else "settings.yaml vollständig")
    sys.exit(1 if missing else 0)
