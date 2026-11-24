#!/usr/bin/env python3
"""Start the local parts of the job search on this computer.

  python 08_Scripts/run_local.py mail              run the configured mail bridge (quiet, for the scheduler)
  python 08_Scripts/run_local.py daily             open the assistant in a new terminal window for the daily run
  python 08_Scripts/run_local.py start-requested   the same, for a run requested with the dashboard button
  ... daily|start-requested --dry-run              only print what would be started

Why a terminal window: the dashboard can only be read and written from an interactive session of
the assistant, not from a background call.

The text handed to the assistant is one of the constants below. Nothing from files, mails, the
dashboard or the start signal is ever put into it; the only configurable parts are the program
(agent.cli / agent.command) and a model name that is checked against a strict pattern.
A lock in 07_Logs/runs/ keeps two runs from starting within 30 minutes.
"""
import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

ROOT = cfg.ROOT
SCRIPTS = Path(__file__).resolve().parent
RUNS = ROOT / "07_Logs" / "runs"
LOCK = RUNS / "run.lock"
LOCK_SECONDS = 30 * 60
MODEL_OK = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")

# How each assistant is started interactively with a first message.
# claude: checked against `claude --help` ("claude [options] [command] [prompt]", "--model <model>").
# codex, gemini, grok: NOT verified - these programs were not installed when this was written. The
# entries follow their published usage; if one does not fit, set agent.cli: custom and agent.command.
AGENT_PRESETS = {
    "claude": {"bin": "claude", "args": ["{prompt}"], "model_flag": "--model"},
    "codex": {"bin": "codex", "args": ["{prompt}"], "model_flag": "-m"},            # unverified
    "gemini": {"bin": "gemini", "args": ["-i", "{prompt}"], "model_flag": "-m"},    # unverified
    "grok": {"bin": "grok", "args": ["{prompt}"], "model_flag": "-m"},              # unverified
}
VERIFIED_PRESETS = ("claude",)
# The only texts ever handed to an assistant.
PROMPTS = {
    "claude": {"daily": "/jobsuche lauf", "requested": "/jobsuche lauf --angefragt"},
    "other": {"daily": "Lies skills/jobsuche/SKILL.md im Arbeitsordner und führe den täglichen Lauf aus.",
              "requested": "Lies skills/jobsuche/SKILL.md im Arbeitsordner und führe den im Dashboard "
                           "angefragten Lauf aus."},
}


class StartError(Exception):
    """A problem the user can fix; one German line."""


def log(text, name="run_local.log"):
    RUNS.mkdir(parents=True, exist_ok=True)
    with (RUNS / name).open("a", encoding="utf-8") as handle:
        handle.write(f"{dt.datetime.now().astimezone().isoformat(timespec='seconds')} {text}\n")


# ---------------------------------------------------------------- the assistant command

def _extra_dirs():
    home = Path.home()
    dirs = [home / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / "bin",
            home / ".npm-global" / "bin", home / ".bun" / "bin"]
    if os.name == "nt":
        dirs = [Path(p) for p in (os.path.join(os.environ.get("APPDATA", ""), "npm"),
                                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "claude"),
                                  os.path.join(str(home), ".local", "bin")) if p]
    return [d for d in dirs if d.is_dir()]


def find_binary(name):
    """Full path of a program from PATH or the usual per-user install folders (a scheduler starts
    with a short PATH), else None."""
    hit = shutil.which(name)
    if hit:
        return hit
    path = os.pathsep.join(str(d) for d in _extra_dirs())
    return shutil.which(name, path=path) if path else None


def agent_command(kind, conf=None):
    """argv for an interactive session whose first message is the constant prompt for `kind`."""
    conf = conf if conf is not None else (cfg.load().get("agent") or {})
    cli = str(conf.get("cli") or "claude").strip().lower()
    model = str(conf.get("model") or "").strip()
    custom = str(conf.get("command") or "").strip()
    if model and not MODEL_OK.match(model):
        raise StartError("agent.model in 01_Config/settings.yaml enthält unzulässige Zeichen "
                         "(erlaubt: Buchstaben, Ziffern und . _ : / -, höchstens 80 Zeichen).")
    prompt = PROMPTS["claude" if cli == "claude" else "other"][kind]
    if custom:                                    # overrides every preset
        argv = shlex.split(custom, posix=os.name != "nt")
        if os.name == "nt":
            argv = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in argv]
        if not any("{prompt}" in a for a in argv):
            raise StartError("agent.command in 01_Config/settings.yaml braucht den Platzhalter {prompt}.")
        if any("{model}" in a for a in argv) and not model:
            raise StartError("agent.command nutzt {model}, aber agent.model ist leer.")
        argv = [a.replace("{prompt}", prompt).replace("{model}", model) for a in argv]
        key = "agent.command"
    elif cli in AGENT_PRESETS:
        preset = AGENT_PRESETS[cli]
        argv = [preset["bin"]] + ([preset["model_flag"], model] if model else [])
        argv += [a.replace("{prompt}", prompt) for a in preset["args"]]
        key = "agent.cli"
    else:
        raise StartError(f"agent.cli '{cli}' ist unbekannt (claude | codex | gemini | grok | custom). "
                         "Bei custom muss agent.command gesetzt sein.")
    binary = find_binary(argv[0])
    if not binary:
        raise StartError(f"Das Programm '{argv[0]}' wurde auf diesem Rechner nicht gefunden. Bitte installieren "
                         f"oder {key} in 01_Config/settings.yaml anpassen.")
    return [binary] + argv[1:]


# ---------------------------------------------------------------- terminal window

def _launcher(argv):
    """Write the small start file for this system and return (file, command that opens it)."""
    RUNS.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = RUNS / "start_session.cmd"
        script.write_text("@echo off\r\nchcp 65001 >nul\r\n"
                          f'cd /d "{ROOT}"\r\n{subprocess.list2cmdline(argv)}\r\n', encoding="utf-8", newline="")
        return script, None                        # opened with os.startfile
    path = os.pathsep.join(dict.fromkeys([str(Path(argv[0]).parent)] + [str(d) for d in _extra_dirs()]
                                         + os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)))
    script = RUNS / ("start_session.command" if sys.platform == "darwin" else "start_session.sh")
    script.write_text("#!/bin/sh\n"
                      f"export PATH={shlex.quote(path)}\n"
                      f"cd {shlex.quote(str(ROOT))} || exit 1\n"
                      f"exec {' '.join(shlex.quote(a) for a in argv)}\n", encoding="utf-8")
    script.chmod(0o700)
    if sys.platform == "darwin":
        return script, ["open", "-a", "Terminal", str(script)]
    for term, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"),
                       ("xfce4-terminal", "-x"), ("kitty", None), ("alacritty", "-e"), ("xterm", "-e")):
        hit = shutil.which(term)
        if hit:
            return script, [hit] + ([flag] if flag else []) + [str(script)]
    raise StartError("Kein Terminal-Programm gefunden. Bitte den Assistenten im Arbeitsordner von Hand starten.")


def open_terminal(argv):
    script, opener = _launcher(argv)
    if opener is None:
        os.startfile(str(script))                  # noqa: S606  (Windows: opens a console window)
    else:
        subprocess.Popen(opener, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return script


# ---------------------------------------------------------------- lock

def lock_age():
    """Seconds since the last start, or None if there is no valid lock."""
    try:
        age = time.time() - LOCK.stat().st_mtime
    except OSError:
        return None
    return age if 0 <= age < LOCK_SECONDS else None


def acquire_lock():
    """True if this call may start a run. A lock older than 30 minutes no longer counts."""
    RUNS.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        if lock_age() is not None:
            return False
        try:
            LOCK.unlink()
        except OSError:
            pass
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue                               # another start was faster
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dt.datetime.now().astimezone().isoformat(timespec="seconds"))
        return True
    return False


def _start(kind, dry_run=False):
    try:
        argv = agent_command(kind)
        if dry_run:
            return {"gestartet": False, "probe": True, "befehl": argv, "ordner": str(ROOT)}
        if not acquire_lock():
            log(f"{kind}: nicht gestartet, letzter Start vor weniger als 30 Minuten")
            return {"gestartet": False, "grund": "In den letzten 30 Minuten wurde bereits ein Lauf gestartet."}
        try:
            open_terminal(argv)
        except Exception:
            LOCK.unlink(missing_ok=True)           # nothing started: do not block the next try
            raise
    except StartError as e:
        log(f"{kind}: {e}")
        return {"gestartet": False, "grund": str(e)}
    except Exception as e:                         # broken settings file, no terminal, no rights
        log(f"{kind}: nicht gestartet ({type(e).__name__})")
        return {"gestartet": False, "grund": "Das Terminal-Fenster ließ sich nicht öffnen "
                                             f"({type(e).__name__}); Einzelheiten in 07_Logs/runs/run_local.log."}
    log(f"{kind}: Sitzung gestartet ({Path(argv[0]).name})")
    return {"gestartet": True, "programm": Path(argv[0]).name}


def _answer(result):
    if result.get("gestartet"):
        return True, f"Der Lauf wurde in einem neuen Terminal-Fenster gestartet ({result['programm']})."
    return False, result.get("grund") or "Der Lauf wurde nicht gestartet."


def start_daily():
    """Open the assistant for the daily run. Returns (ok, German message); never raises."""
    return _answer(_start("daily"))


def start_requested():
    """Open the assistant for a run requested in the dashboard. Returns (ok, German message); never raises."""
    return _answer(_start("requested"))


# ---------------------------------------------------------------- mail bridge + optional git sync

def _run(cmd, timeout=900):
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "Zeitüberschreitung"
    except OSError as e:
        return 127, "", type(e).__name__


def _git_ready(conf):
    return bool(conf["git"]["sync"]) and (ROOT / ".git").exists() and shutil.which("git")


def _wait_for(host, port, tries=20, pause=30):
    """After waking up, the network can take a while. Give up quietly after ten minutes."""
    for i in range(tries):
        try:
            socket.create_connection((host, port), timeout=10).close()
            return True
        except OSError:
            if i + 1 < tries:
                time.sleep(pause)
    return False


def _git_host():
    code, out, _ = _run(["git", "remote", "get-url", "origin"], 30)
    m = re.search(r"(?:@|//)([A-Za-z0-9.-]+)", out) if code == 0 else None
    return m.group(1) if m else None


def mail(wait=True):
    """Run the bridge for mail.mode; with git.sync also pull before and commit + push the inbox after."""
    mlog = lambda text: log(text, "mail_bridge.log")
    conf = cfg.load()
    mode = conf["mail"]["mode"]
    bridges = {"apple_mail": ["mail_bridge_apple.py", "--refresh"], "imap": ["mail_bridge_imap.py", "fetch"]}
    if mode not in bridges:
        mlog(f"nichts zu tun: mail.mode ist '{mode or 'none'}' (lokale Brücke nur bei apple_mail oder imap)")
        return 0
    git = _git_ready(conf)
    if wait:
        target = (conf["mail"]["imap"]["host"], 993) if mode == "imap" else ((_git_host(), 443) if git else (None, 0))
        if target[0] and not _wait_for(*target):
            mlog("kein Netz, Abbruch")
            return 0
    branch = None
    if git:
        code, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], 30)
        branch = branch if code == 0 and branch and branch != "HEAD" else None
        if branch:
            code, _, err = _run(["git", "pull", "--rebase", "--autostash", "origin", branch], 300)
            if code != 0:
                mlog(f"git pull fehlgeschlagen: {err[-200:]}")
    code, out, err = _run([str(cfg.venv_python()), str(SCRIPTS / bridges[mode][0])] + bridges[mode][1:])
    mlog(f"{mode}: {' '.join(out.split())[:500] if code == 0 else 'Fehler: ' + (err or out)[-300:]}")
    if git and branch:
        _run(["git", "add", "07_Logs/mail_inbox"], 60)
        if _run(["git", "diff", "--cached", "--quiet"], 60)[0] != 0:
            _run(["git", "commit", "-q", "-m", f"Mail bridge {dt.datetime.now():%Y-%m-%d %H:%M}"], 60)
            for attempt in range(3):
                if _run(["git", "push", "-q", "origin", branch], 300)[0] == 0:
                    break
                time.sleep(5 * (attempt + 1))
                _run(["git", "pull", "--rebase", "--autostash", "origin", branch], 300)
            else:
                mlog("git push fehlgeschlagen (3 Versuche)")
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mail")
    m.add_argument("--no-wait", action="store_true", help="nicht auf das Netz warten")
    for name in ("daily", "start-requested"):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true", help="nur anzeigen, was gestartet würde")
    args = ap.parse_args()
    if args.cmd == "mail":
        sys.exit(1 if mail(wait=not args.no_wait) else 0)
    result = _start("daily" if args.cmd == "daily" else "requested", dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("gestartet") or result.get("probe") else 1)


if __name__ == "__main__":
    main()
