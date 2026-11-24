#!/usr/bin/env python3
"""One cheap look into the Downloads folder for the start signal of the dashboard button.

The button "Job suche starten" lets the browser save an empty file named
`jobsuche-start-<dashboard.trigger_token>.trigger`. This script (run every few minutes by the
scheduler) deletes such files and then opens the assistant through run_local.start_requested().

Rules:
  - the token must be set and consist of 8-64 letters or digits, otherwise nothing happens
  - only regular files (no folders, no links) younger than 24 hours and smaller than 1 KB count
  - the file name decides. The content is untrusted: at most 64 bytes are read, and only a request
    id of the form run_<letters, digits, _ or -> is kept (in 07_Logs/runs/requested_run.json, for the
    dashboard bookkeeping). It never becomes part of a prompt or a command
  - nothing found = no assistant is started, so no model tokens are used

  python 08_Scripts/trigger_poller.py [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

ROOT = cfg.ROOT
RUNS = ROOT / "07_Logs" / "runs"
MARKER = RUNS / "poller_permission_needed.txt"
HEARTBEAT = RUNS / "poller_last_ok.txt"
TOKEN_OK = re.compile(r"^[A-Za-z0-9]{8,64}$")
MAX_AGE = 24 * 3600
MAX_BYTES = 1024
REQUEST_OK = re.compile(r"^run_[A-Za-z0-9_-]{1,40}$")
REQUEST_FILE = RUNS / "requested_run.json"


def token():
    value = str(cfg.load()["dashboard"]["trigger_token"] or "")
    return value if TOKEN_OK.match(value) else None


def name_pattern(tok):
    """Exact name, or the copy a browser makes when the name exists: "name (1).trigger", "name-1.trigger"."""
    return re.compile(rf"^jobsuche-start-{re.escape(tok)}(?: ?\(\d{{1,3}}\)|-\d{{1,3}})?\.trigger$")


def _windows_downloads():
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        folder_id = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(out)) == 0:
            value = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            if value:
                return Path(value)
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
        return Path(os.path.expandvars(value))
    except Exception:
        return None


def downloads_dir():
    custom = str(cfg.load()["schedule"].get("downloads_dir") or "").strip()
    if custom:
        return Path(os.path.expandvars(custom)).expanduser()
    if sys.platform == "win32":
        return _windows_downloads() or Path.home() / "Downloads"
    return Path.home() / "Downloads"


def find_triggers(folder, tok, now=None):
    """Matching signal files in `folder`. Raises PermissionError if the folder may not be listed."""
    now = now or time.time()
    pattern, hits = name_pattern(tok), []
    with os.scandir(folder) as entries:
        for entry in entries:
            if not pattern.match(entry.name):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):                    # folders and links never count
                continue
            if info.st_size >= MAX_BYTES or not -300 <= now - info.st_mtime < MAX_AGE:
                continue
            hits.append(Path(entry.path))
    return hits


def request_id(path):
    """The request id in a signal file, or None. Anything else in the file is ignored."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            raw = os.read(fd, 64)
        finally:
            os.close(fd)
        text = raw.decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if REQUEST_OK.match(text) else None


def _note(text):
    RUNS.mkdir(parents=True, exist_ok=True)
    with (RUNS / "poller.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{dt.datetime.now().astimezone().isoformat(timespec='seconds')} {text}\n")


def poll(dry_run=False, start=None):
    """One pass. Returns a small report; starts a run only after a signal file was deleted."""
    tok = token()
    if not tok:
        return {"status": "kein_token"}                           # not set up: do nothing at all
    folder = downloads_dir()
    try:
        hits = find_triggers(folder, tok)
    except PermissionError:
        RUNS.mkdir(parents=True, exist_ok=True)
        if not MARKER.exists():
            _note(f"Kein Zugriff auf den Download-Ordner ({folder}). Bitte dem Hintergrunddienst den Zugriff "
                  "erlauben oder schedule.downloads_dir auf einen anderen Ordner setzen.")
            MARKER.write_text("Der Abholer für den Start-Knopf darf den Download-Ordner nicht lesen.\n"
                              "Bis das erlaubt ist, startet der Knopf im Dashboard keinen Lauf.\n", encoding="utf-8")
        return {"status": "kein_zugriff", "ordner": str(folder)}
    except OSError:
        return {"status": "ordner_fehlt", "ordner": str(folder)}
    RUNS.mkdir(parents=True, exist_ok=True)
    MARKER.unlink(missing_ok=True)
    HEARTBEAT.write_text(dt.datetime.now().astimezone().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    if not hits:
        return {"status": "nichts"}
    if dry_run:
        return {"status": "gefunden", "dateien": len(hits), "probe": True}
    deleted, ids = 0, []
    for path in hits:
        rid = request_id(path)
        try:
            path.unlink()
            deleted += 1
        except OSError:
            continue
        if rid and rid not in ids:
            ids.append(rid)
    if not deleted:                                               # a file that cannot be removed would start a run every pass
        _note("Startsignal gefunden, ließ sich aber nicht löschen - kein Lauf gestartet.")
        return {"status": "nicht_loeschbar", "dateien": len(hits)}
    if start is None:
        import run_local
        start = run_local.start_requested
    REQUEST_FILE.write_text(json.dumps({"request_ids": ids, "picked_up":
                                        dt.datetime.now().astimezone().isoformat(timespec="seconds")}), encoding="utf-8")
    result = start()                                              # takes no arguments: nothing from the file goes along
    ok = bool(result[0]) if isinstance(result, tuple) else bool(result)
    _note(f"Startsignal abgeholt ({deleted} Datei(en)); gestartet: {ok}")
    return {"status": "gestartet" if ok else "nicht_gestartet", "dateien": deleted}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="nur nachsehen, nichts löschen und nichts starten")
    args = ap.parse_args()
    report = poll(dry_run=args.dry_run)
    if args.dry_run or report["status"] not in ("nichts", "kein_token"):
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
