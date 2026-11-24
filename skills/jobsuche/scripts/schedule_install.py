#!/usr/bin/env python3
"""Install, remove or show the local schedule of the job search.

  python 08_Scripts/schedule_install.py install|remove|status daily|mail|poller|all [--dry-run]

  daily   opens the assistant for the daily run at schedule.time
  mail    runs the mail bridge at schedule.mail_bridge_times
  poller  looks every schedule.poll_seconds for the start signal of the dashboard button

macOS: a LaunchAgent per job in ~/Library/LaunchAgents (label com.jobsuche.<job>).
Windows: a task per job in the Task Scheduler (name Jobsuche-<job>), running only while the user
is logged on; no password is stored.
Linux: the crontab lines are printed; this script does not edit the crontab.
--dry-run prints exactly what would be written and executed, and changes nothing.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

ROOT = cfg.ROOT
SCRIPTS = Path(__file__).resolve().parent
JOBS = ("daily", "mail", "poller")
JOB_ARGS = {"daily": ["run_local.py", "daily"], "mail": ["run_local.py", "mail"], "poller": ["trigger_poller.py"]}
TIME_OK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
SUFFIX_OK = re.compile(r"^[A-Za-z0-9-]{0,30}$")


class ScheduleError(Exception):
    """A problem the user can fix; one German line."""


def _time(value):
    m = TIME_OK.match(str(value).strip())
    if not m:
        raise ScheduleError(f"Uhrzeit '{value}' in 01_Config/settings.yaml ist ungültig (Form HH:MM, z. B. 07:30).")
    return int(m.group(1)), int(m.group(2))


def plan(job):
    """What the job runs and when: {"times": [(h, m), ...]} or {"seconds": n}."""
    s = cfg.load()["schedule"]
    if job == "daily":
        return {"times": [_time(s["time"])]}
    if job == "mail":
        times = [_time(t) for t in (s["mail_bridge_times"] or [])]
        if not times:
            raise ScheduleError("schedule.mail_bridge_times ist leer.")
        return {"times": times}
    try:
        seconds = int(s["poll_seconds"])
    except (TypeError, ValueError):
        raise ScheduleError("schedule.poll_seconds muss eine Zahl sein.")
    return {"seconds": max(60, seconds)}


def command(job, python=None):
    return [str(python or cfg.venv_python()), str(SCRIPTS / JOB_ARGS[job][0])] + JOB_ARGS[job][1:]


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, type(e).__name__


# ---------------------------------------------------------------- macOS

def template_dir(arg=None):
    for place in (Path(arg) if arg else None, SCRIPTS / "schedule", SCRIPTS.parent / "assets" / "schedule"):
        if place and (place / "launchd_calendar.plist.tmpl").exists():
            return place
    raise ScheduleError("Die Vorlagen für den Zeitplan fehlen (08_Scripts/schedule). Bitte `setup.py update` ausführen.")


def mac_label(job, suffix=""):
    return f"com.jobsuche.{job}" + (f".{suffix}" if suffix else "")


def mac_plist_path(job, suffix=""):
    return Path.home() / "Library" / "LaunchAgents" / f"{mac_label(job, suffix)}.plist"


def mac_plist(job, suffix="", templates=None):
    p = plan(job)
    name = "launchd_interval.plist.tmpl" if "seconds" in p else "launchd_calendar.plist.tmpl"
    text = (template_dir(templates) / name).read_text(encoding="utf-8")
    path = os.pathsep.join(dict.fromkeys([str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin",
                                          "/usr/bin", "/bin", "/usr/sbin", "/sbin"]))
    values = {
        "LABEL": escape(mac_label(job, suffix)),
        "PROGRAM_ARGS": "\n".join(f"    <string>{escape(a)}</string>" for a in command(job)),
        "WORKDIR": escape(str(ROOT)),
        "CALENDAR": "\n".join(f"    <dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>"
                              for h, m in p.get("times", [])),
        "INTERVAL": str(p.get("seconds", "")),
        "PATH": escape(path),
        "LOG": escape(str(ROOT / "07_Logs" / "runs" / f"schedule_{job}.log")),
    }
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def mac_install(job, suffix, dry, templates):
    path, label, uid = mac_plist_path(job, suffix), mac_label(job, suffix), os.getuid()
    text = mac_plist(job, suffix, templates)
    steps = [["launchctl", "bootout", f"gui/{uid}/{label}"], ["launchctl", "bootstrap", f"gui/{uid}", str(path)]]
    if dry:
        return {"job": job, "probe": True, "datei": str(path), "inhalt": text,
                "befehle": [shlex.join(s) for s in steps] + ["bei Fehler: " + shlex.join(["launchctl", "load", "-w", str(path)])]}
    (ROOT / "07_Logs" / "runs").mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _run(steps[0])                                        # replace an older version; fails harmlessly if none
    code, out = _run(steps[1])
    if code != 0:
        code, out = _run(["launchctl", "load", "-w", str(path)])
    if code != 0:
        raise ScheduleError(f"launchd hat den Zeitplan '{job}' nicht angenommen: {out[-200:]}")
    return {"job": job, "eingerichtet": True, "datei": str(path), "name": label}


def mac_remove(job, suffix, dry):
    path, label, uid = mac_plist_path(job, suffix), mac_label(job, suffix), os.getuid()
    step = ["launchctl", "bootout", f"gui/{uid}/{label}"]
    if dry:
        return {"job": job, "probe": True, "befehle": [shlex.join(step)], "loescht": str(path)}
    code, _ = _run(step)
    if code != 0 and path.exists():
        _run(["launchctl", "unload", str(path)])
    existed = path.exists()
    path.unlink(missing_ok=True)
    return {"job": job, "entfernt": existed or code == 0, "name": label}


def mac_status(job, suffix):
    label = mac_label(job, suffix)
    code, _ = _run(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
    return {"job": job, "name": label, "datei_vorhanden": mac_plist_path(job, suffix).exists(), "geladen": code == 0}


# ---------------------------------------------------------------- Windows

def win_names(job, suffix=""):
    base = f"Jobsuche-{job}" + (f"-{suffix}" if suffix else "")
    p = plan(job)
    count = len(p.get("times", [])) if "times" in p else 1
    return [base] if count <= 1 else [f"{base}-{i + 1}" for i in range(count)]


def win_python():
    """pythonw.exe next to the venv's python.exe, so no console window flashes up every few minutes."""
    exe = Path(cfg.venv_python())
    quiet = exe.with_name("pythonw.exe")
    return quiet if quiet.exists() else exe


def win_commands(job, suffix=""):
    """One `schtasks /Create` per start time. Without /RU the task belongs to the current user and
    runs only while that user is logged on, so no password is asked for or stored."""
    p = plan(job)
    run = subprocess.list2cmdline(command(job, win_python()))
    names = win_names(job, suffix)
    if "seconds" in p:
        minutes = max(1, round(p["seconds"] / 60))
        return [["schtasks", "/Create", "/TN", names[0], "/TR", run, "/SC", "MINUTE", "/MO", str(minutes), "/F"]]
    return [["schtasks", "/Create", "/TN", name, "/TR", run, "/SC", "DAILY", "/ST", f"{h:02d}:{m:02d}", "/F"]
            for name, (h, m) in zip(names, p["times"])]


def win_install(job, suffix, dry):
    cmds = win_commands(job, suffix)
    if dry:
        return {"job": job, "probe": True, "befehle": [subprocess.list2cmdline(c) for c in cmds]}
    if len(cmds[0][5]) > 261:
        raise ScheduleError("Der Pfad des Arbeitsordners ist für die Windows-Aufgabenplanung zu lang "
                            "(höchstens 261 Zeichen für den Befehl). Bitte einen kürzeren Ordner wählen.")
    (ROOT / "07_Logs" / "runs").mkdir(parents=True, exist_ok=True)
    for c in cmds:
        code, out = _run(c)
        if code != 0:
            raise ScheduleError(f"Die Aufgabenplanung hat '{c[3]}' nicht angenommen: {out[-200:]}")
    return {"job": job, "eingerichtet": True, "name": [c[3] for c in cmds]}


def win_remove(job, suffix, dry):
    base = f"Jobsuche-{job}" + (f"-{suffix}" if suffix else "")
    names = [base] + [f"{base}-{i}" for i in range(1, 7)]       # also tasks from an earlier list of times
    cmds = [["schtasks", "/Delete", "/TN", n, "/F"] for n in names]
    if dry:
        return {"job": job, "probe": True, "befehle": [subprocess.list2cmdline(c) for c in cmds]}
    return {"job": job, "entfernt": any(_run(c)[0] == 0 for c in cmds)}


def win_status(job, suffix):
    names = win_names(job, suffix)
    return {"job": job, "name": names, "vorhanden": [_run(["schtasks", "/Query", "/TN", n])[0] == 0 for n in names]}


# ---------------------------------------------------------------- Linux (printed only)

def cron_lines(job):
    p = plan(job)
    run = shlex.join(command(job))
    env = "" if job != "daily" else "DISPLAY=:0 "            # a terminal window needs the desktop session
    if "seconds" in p:
        return [f"*/{max(1, round(p['seconds'] / 60))} * * * * {run}"]
    return [f"{m} {h} * * * {env}{run}" for h, m in p["times"]]


def linux(action, job, dry):
    if action == "status":
        return {"job": job, "hinweis": "Unter Linux bitte mit `crontab -l` nachsehen."}
    lines = cron_lines(job)
    if action == "remove":
        return {"job": job, "hinweis": "Bitte diese Zeile(n) mit `crontab -e` selbst entfernen.", "zeilen": lines}
    return {"job": job, "probe": bool(dry), "hinweis": "Bitte diese Zeile(n) mit `crontab -e` selbst eintragen "
            "(dieses Skript ändert die crontab nicht).", "zeilen": lines}


# ---------------------------------------------------------------- dispatch

def apply(action, job, platform=None, dry_run=False, suffix="", templates=None):
    platform = platform or sys.platform
    if not SUFFIX_OK.match(suffix or ""):
        raise ScheduleError("--label-suffix darf nur Buchstaben, Ziffern und Bindestriche enthalten.")
    if platform != sys.platform and not dry_run:
        raise ScheduleError("Ein fremdes Betriebssystem lässt sich nur mit --dry-run anzeigen.")
    if platform == "darwin":
        return {"install": lambda: mac_install(job, suffix, dry_run, templates),
                "remove": lambda: mac_remove(job, suffix, dry_run),
                "status": lambda: mac_status(job, suffix)}[action]()
    if platform == "win32":
        return {"install": lambda: win_install(job, suffix, dry_run),
                "remove": lambda: win_remove(job, suffix, dry_run),
                "status": lambda: win_status(job, suffix)}[action]()
    return linux(action, job, dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("action", choices=["install", "remove", "status"])
    ap.add_argument("job", choices=list(JOBS) + ["all"])
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    ap.add_argument("--platform", choices=["darwin", "win32", "linux"], help="nur mit --dry-run: anderes System anzeigen")
    ap.add_argument("--label-suffix", default="", help="Zusatz zum Namen (für Tests)")
    ap.add_argument("--templates", help="Ordner mit den Vorlagen (Standard: 08_Scripts/schedule)")
    args = ap.parse_args()
    ok = True
    for job in (JOBS if args.job == "all" else [args.job]):
        try:
            result = apply(args.action, job, args.platform, args.dry_run, args.label_suffix, args.templates)
        except ScheduleError as e:
            result, ok = {"job": job, "fehler": str(e)}, False
        text = result.pop("inhalt", None)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        if text:
            print(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
