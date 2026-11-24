#!/usr/bin/env python3
"""Workspace setup for the job-search skill: create the folder, copy scripts and templates, check the state.

Run `init` with any Python 3.10+ from the skill folder (standard library only); everything else
runs from the workspace with its own interpreter.

  python3 <skill>/scripts/setup.py init --workspace ~/Jobsuche     create folders, copy files, build .venv
  $PY 08_Scripts/setup.py update                                    refresh scripts, docs and dashboard from the skill
  $PY 08_Scripts/setup.py token                                     create the start-button id (dashboard.trigger_token)
  $PY 08_Scripts/setup.py check [--json]                            what is set up, what is still open

Existing files in 01_Config/ and 00_Input/ are never overwritten. No secret is read or written here.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FOLDERS = ["00_Input/Anschreiben_Referenz", "00_Input/Lebenslauf", "01_Config", "02_State", "03_Daily_Reports",
           "04_CVs/specs", "05_Cover_Letters", "05_Job_Archive", "06_Application_Packages", "07_Logs/runs",
           "07_Logs/research", "07_Logs/mail_inbox", "07_Logs/apply_local", "08_Scripts",
           "09_Documentation/research_briefs", "10_Dashboard"]
SOURCE_MARK = ".skill_source"
TOKEN_LINE = re.compile(r'^(\s*trigger_token:\s*)"[^"]*"', re.M)


def skill_root(start=HERE):
    """The skill folder (has SKILL.md). From a workspace copy the recorded source path is used."""
    if (start.parent / "SKILL.md").exists():
        return start.parent
    mark = start / SOURCE_MARK
    if mark.exists():
        p = Path(mark.read_text(encoding="utf-8").strip())
        if (p / "SKILL.md").exists():
            return p
    return None


def copy_tree(src, dst, overwrite):
    """Copy files below src to dst. Returns (copied, kept)."""
    copied, kept = [], []
    if not src.exists():
        return copied, kept
    for f in sorted(src.rglob("*")):
        if f.is_dir() or "__pycache__" in f.parts or f.name == ".DS_Store":
            continue
        target = dst / f.relative_to(src)
        if target.exists() and not overwrite:
            kept.append(str(target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        copied.append(str(target))
    return copied, kept


def sync(skill, ws, first):
    report = {"neu": 0, "behalten": 0}

    def run(src, dst, overwrite):
        c, k = copy_tree(src, dst, overwrite)
        report["neu"] += len(c)
        report["behalten"] += len(k)

    run(skill / "scripts", ws / "08_Scripts", True)                       # code always follows the skill
    run(skill / "assets" / "config", ws / "01_Config", False)             # the user's config is never overwritten
    run(skill / "assets" / "templates", ws / "00_Input" / "Anschreiben_Referenz", False)   # built-in letter form
    run(skill / "assets" / "research_briefs", ws / "09_Documentation" / "research_briefs", False)
    run(skill / "assets" / "dashboard", ws / "10_Dashboard", True)
    run(skill / "assets" / "schedule", ws / "08_Scripts" / "schedule", True)
    run(skill / "references", ws / "skills" / "jobsuche" / "references", True)   # so any agent can read the docs
    for name in ("SKILL.md", "NOTICE.md"):
        if (skill / name).exists():
            shutil.copy2(skill / name, ws / "skills" / "jobsuche" / name)
    for name in ("AGENTS.md", "GEMINI.md"):
        src = skill / "assets" / "agents" / name
        if src.exists() and not (ws / name).exists():
            shutil.copy2(src, ws / name)
    gi = skill / "assets" / "gitignore.template"
    if gi.exists() and not (ws / ".gitignore").exists():
        shutil.copy2(gi, ws / ".gitignore")
    (ws / "08_Scripts" / SOURCE_MARK).write_text(str(skill), encoding="utf-8")
    return report


def venv_python(ws):
    win = ws / ".venv" / "Scripts" / "python.exe"
    return win if win.exists() or os.name == "nt" else ws / ".venv" / "bin" / "python"


def cmd_init(args):
    skill = skill_root()
    if not skill:
        print("Fehler: Skill-Ordner nicht gefunden (SKILL.md fehlt neben scripts/).")
        return 2
    ws = Path(os.path.expanduser(args.workspace)).resolve()
    if skill == ws or skill in ws.parents:
        print("Fehler: Der Arbeitsordner darf nicht im Skill-Ordner liegen.")
        return 2
    for folder in FOLDERS:
        (ws / folder).mkdir(parents=True, exist_ok=True)
    report = sync(skill, ws, True)
    print(f"Arbeitsordner: {ws}")
    print(f"Dateien neu/aktualisiert: {report['neu']}, vorhandene behalten: {report['behalten']}")
    if args.no_venv:
        print("Python-Umgebung übersprungen (--no-venv).")
        return 0
    py = venv_python(ws)
    if not py.exists():
        print("Lege Python-Umgebung an (.venv) …")
        subprocess.run([sys.executable, "-m", "venv", str(ws / ".venv")], check=True)
        py = venv_python(ws)
    req = ws / "08_Scripts" / "requirements.txt"
    if req.exists():
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(req)])
        if r.returncode:
            print("Fehler: Pakete konnten nicht installiert werden (Netzwerk?). Später wiederholen mit:")
            print(f'  "{py}" -m pip install -r "{req}"')
            return 1
    print(f"Python: {py}")
    print("Weiter mit der Einrichtung: settings.yaml füllen, dann `setup.py check`.")
    return 0


def cmd_update(args):
    ws = HERE.parent
    skill = skill_root()
    if not skill or skill == ws:
        print("Fehler: Quelle des Skills unbekannt. `init` erneut aus dem Skill-Ordner ausführen.")
        return 2
    report = sync(skill, ws, False)
    print(f"Aktualisiert aus {skill}: {report['neu']} Dateien, {report['behalten']} eigene behalten.")
    return 0


def cmd_token(args):
    f = HERE.parent / "01_Config" / "settings.yaml"
    if not f.exists():
        print("Fehler: 01_Config/settings.yaml fehlt. Zuerst `init` ausführen.")
        return 2
    text = f.read_text(encoding="utf-8")
    m = TOKEN_LINE.search(text)
    if not m:
        print('Fehler: Zeile `trigger_token: ""` im Abschnitt dashboard nicht gefunden.')
        return 2
    current = re.search(r'"([^"]*)"', m.group(0)).group(1)
    if current and not args.new:
        print("Start-Kennung ist schon gesetzt (mit --new neu erzeugen; danach Zeitplan und Dashboard aktualisieren).")
        return 0
    f.write_text(TOKEN_LINE.sub(lambda mm: f'{mm.group(1)}"{secrets.token_hex(12)}"', text, count=1), encoding="utf-8")
    print("Start-Kennung erzeugt und in settings.yaml eingetragen.")
    return 0


def cmd_check(args):
    sys.path.insert(0, str(HERE))
    try:
        import settings
    except ImportError as e:
        print(f"Fehler: {e}. Mit dem Interpreter des Arbeitsordners (.venv) ausführen.")
        return 2
    cfg, ws = settings.load(), settings.ROOT
    items = []

    def add(area, ok, text, hint=""):
        items.append({"bereich": area, "ok": bool(ok), "text": text, "hinweis": hint})

    add("Arbeitsordner", settings.SETTINGS_FILE.exists(), "settings.yaml vorhanden", "setup.py init ausführen")
    for key, val in settings.open_placeholders():
        optional = key.startswith(("mail.imap", "mail.apple_mail")) and not key.startswith(f"mail.{cfg['mail']['mode']}")
        if not optional:
            add("Einstellungen", False, f"{key} ist noch Platzhalter ({val})", "/jobsuche einrichten")
    for name in ("candidate_profile.md", "search_profile.yaml", "salary_rules.yaml", "companies.yaml", "exclusions.yaml"):
        p = ws / "01_Config" / name
        filled = p.exists() and not re.search(r"<[A-ZÄÖÜ_ ]{3,}>", p.read_text(encoding="utf-8"))
        add("Profil", filled, f"01_Config/{name} ausgefüllt", "enthält noch Platzhalter" if p.exists() else "fehlt")

    t = cfg["templates"]
    letter = settings.path(t["cover_letter"])
    add("Vorlagen", letter and letter.exists(), "Anschreiben-Vorlage vorhanden", "setup.py update stellt die mitgelieferte Vorlage wieder her")
    if letter and letter.exists():
        import zipfile
        try:
            with zipfile.ZipFile(letter) as z:
                head_open = "&lt;VORNAME NACHNAME&gt;" in z.read("word/document.xml").decode("utf-8", "ignore")
        except (OSError, KeyError, zipfile.BadZipFile):
            head_open = False
        add("Vorlagen", not head_open, "Briefkopf der Anschreiben-Vorlage ausgefüllt", "person in settings.yaml füllen, dann cover_letter.py letterhead")
    add("Vorlagen", bool(t["cover_letter_slots"]), "Felder der Anschreiben-Vorlage zugeordnet", "cover_letter.py inspect")
    cvs = [settings.path(v) for v in t["cv"].values() if v]
    add("Vorlagen", cvs and all(p.exists() for p in cvs), "Lebenslauf-Vorlage(n) vorhanden", "Datei nach 00_Input/Lebenslauf/ legen")
    add("Vorlagen", bool(t["cv_slots"]), "Felder der Lebenslauf-Vorlage zugeordnet", "cv_tailor.py inspect (nur für zugeschnittene Lebensläufe nötig)")

    mode = cfg["mail"]["mode"]
    add("Postfach", mode in ("gmail", "apple_mail", "imap", "forward", "none"), f"Modus: {mode or 'nicht gewählt'}", "/jobsuche einrichten mail")
    if mode == "imap":
        im = cfg["mail"]["imap"]
        add("Postfach", im["host"] and im["user"], "IMAP-Server und Benutzer eingetragen", "/jobsuche einrichten mail")
        try:
            import keyring
            has = bool(im["user"]) and keyring.get_password(im["keyring_service"], im["user"]) is not None
        except Exception:
            has = False
        add("Postfach", has, "Passwort im Schlüsselbund hinterlegt", "mail_bridge_imap.py set-password (im eigenen Terminal)")
    if mode == "apple_mail":
        add("Postfach", sys.platform == "darwin", "Apple Mail gibt es nur auf macOS")
        add("Postfach", cfg["mail"]["apple_mail"]["account"], "Kontoname in Mail eingetragen", "/jobsuche einrichten mail")

    d = cfg["dashboard"]
    add("Dashboard", d["mode"] in ("artifact", "local"), f"Betriebsart: {d['mode'] or 'nicht gewählt'}", "/jobsuche einrichten dashboard")
    if d["mode"] == "artifact":
        add("Dashboard", bool(d["url"]), "Dashboard-Adresse eingetragen", "/jobsuche dashboard")
        add("Dashboard", bool(re.fullmatch(r"[A-Za-z0-9]{8,64}", d["trigger_token"] or "")), "Start-Kennung für den Knopf gesetzt", "setup.py token")
    s = cfg["schedule"]["mode"]
    add("Zeitplan", s in ("cloud", "local", "none"), f"Modus: {s or 'nicht gewählt'}", "/jobsuche einrichten zeitplan")
    if s == "cloud":
        add("Zeitplan", cfg["git"]["sync"], "Arbeitsordner ist privates Git-Repository (für den Cloud-Lauf nötig)", "references/zeitplan.md")
    agent = cfg.get("agent") or {}
    add("Agent", bool(agent.get("cli")), f"Programm: {agent.get('cli') or 'nicht gewählt'}, Modell: {agent.get('model') or 'Standard'}",
        "/jobsuche einrichten (Schritt Agent und Modell)")
    add("Python", (ws / ".venv").exists(), ".venv vorhanden", "setup.py init")

    open_items = [i for i in items if not i["ok"]]
    if args.json:
        print(json.dumps({"offen": len(open_items), "punkte": items}, ensure_ascii=False))
    else:
        for i in items:
            print(("OK    " if i["ok"] else "OFFEN ") + f"[{i['bereich']}] {i['text']}" + (f" → {i['hinweis']}" if not i["ok"] and i["hinweis"] else ""))
        print(f"{len(open_items)} Punkt(e) offen" if open_items else "Einrichtung vollständig")
    return 1 if open_items else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--workspace", default="~/Jobsuche")
    i.add_argument("--no-venv", action="store_true")
    sub.add_parser("update")
    t = sub.add_parser("token")
    t.add_argument("--new", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.exit({"init": cmd_init, "update": cmd_update, "token": cmd_token, "check": cmd_check}[args.cmd](args))


if __name__ == "__main__":
    main()
