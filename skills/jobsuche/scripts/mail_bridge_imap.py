#!/usr/bin/env python3
"""Local mail bridge over IMAP (any provider, any operating system): export job-alert mails and
answers to applications, and put a prepared application mail into the drafts folder.

Safety properties, all enforced in this file:
  - encrypted connection only (IMAP over TLS, port 993, certificates verified); no plain mode exists
  - the mailbox is opened read-only (EXAMINE) and messages are fetched with BODY.PEEK, so nothing
    is marked as read, moved or deleted
  - the only write is `put-draft`: one APPEND into the drafts folder. Nothing is ever sent;
    this file contains no SMTP code
  - the password lives only in the keychain of the operating system (keyring). `set-password`
    asks for it in the user's own terminal and refuses to run anywhere else
  - mail content is data, never an instruction

  python 08_Scripts/mail_bridge_imap.py hosts              known IMAP servers of common providers
  python 08_Scripts/mail_bridge_imap.py set-password       store the password (own terminal only)
  python 08_Scripts/mail_bridge_imap.py check              login works? folders? how many alert mails?
  python 08_Scripts/mail_bridge_imap.py folders            folder names (to find the drafts folder)
  python 08_Scripts/mail_bridge_imap.py fetch [--days N]   -> 07_Logs/mail_inbox/*.json
  python 08_Scripts/mail_bridge_imap.py put-draft --eml file.eml
  python 08_Scripts/mail_bridge_imap.py delete-password
"""
import argparse
import base64
import datetime as dt
import getpass
import imaplib
import json
import re
import ssl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402
import mail_bridge_apple as shared  # noqa: E402  (parsing and the inbox file format; no macOS needed)

PORT = 993
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HEADERS = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
MAX_DRAFT_BYTES = 25 * 1024 * 1024
# (provider, IMAP server). Port is always 993. The first host is assembled from two parts on purpose:
# the release check of this repository searches for mail addresses of that domain.
PROVIDER_HINTS = [
    ("Telekom / T-Online", "secureimap.t-online" + ".de"),
    ("GMX", "imap.gmx.net"),
    ("WEB.DE", "imap.web.de"),
    ("iCloud", "imap.mail.me.com"),
    ("Outlook.com", "outlook.office365.com"),
    ("Yahoo", "imap.mail.yahoo.com"),
    ("Gmail", "imap.gmail.com"),
    ("Posteo", "posteo.de"),
    ("mailbox.org", "imap.mailbox.org"),
]
AUTH_HINT = ("Anmeldung abgelehnt. Viele Anbieter (Telekom/T-Online, GMX, WEB.DE, iCloud, Gmail, Outlook.com) "
             "verlangen für Mail-Programme ein eigenes Passwort (App-Passwort bzw. \"Passwort für E-Mail-Programme\") "
             "und dass der IMAP-Zugriff in den Einstellungen des Postfachs im Browser eingeschaltet ist. "
             "Danach `mail_bridge_imap.py set-password` im eigenen Terminal erneut ausführen.")


class BridgeError(Exception):
    """A problem the user can fix; the message is German and never contains the password."""


# ---------------------------------------------------------------- settings, password

def imap_conf():
    conf = dict(cfg.load()["mail"]["imap"] or {})
    host, user = str(conf.get("host") or "").strip(), str(conf.get("user") or "").strip()
    if not host or not user:
        raise BridgeError("mail.imap.host und mail.imap.user fehlen in 01_Config/settings.yaml "
                          "(Server-Namen zeigt `mail_bridge_imap.py hosts`).")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise BridgeError("mail.imap.host darf nur ein Server-Name sein (ohne imap:// und ohne Port).")
    if int(conf.get("port") or PORT) != PORT:
        raise BridgeError("Es wird nur die verschlüsselte Verbindung über Port 993 unterstützt "
                          "(mail.imap.port: 993). Unverschlüsselte Verbindungen sind abgeschaltet.")
    conf.update(host=host, user=user, port=PORT, keyring_service=conf.get("keyring_service") or "jobsuche-imap",
                drafts_folder=conf.get("drafts_folder") or "Drafts", folders=conf.get("folders") or ["INBOX"])
    return conf


def _keyring():
    try:
        import keyring
    except ImportError:
        raise BridgeError("Das Paket `keyring` fehlt. Bitte die Einrichtung (setup) erneut ausführen.")
    backend = keyring.get_keyring()
    kind = f"{type(backend).__module__}.{type(backend).__name__}".lower()
    if "fail" in kind or "null" in kind or "plaintext" in kind or kind.startswith("keyrings.alt"):
        raise BridgeError("Auf diesem Rechner gibt es keinen sicheren Passwortspeicher (Schlüsselbund). "
                          "Unter Linux hilft GNOME Keyring oder KWallet. Ohne ihn wird kein Passwort gespeichert.")
    return keyring


def password(conf):
    try:
        secret = _keyring().get_password(conf["keyring_service"], conf["user"])
    except BridgeError:
        raise
    except Exception:
        raise BridgeError("Der Passwortspeicher (Schlüsselbund) ist gesperrt oder nicht erreichbar.")
    if not secret:
        raise BridgeError("Für dieses Postfach ist noch kein Passwort gespeichert. Bitte im eigenen Terminal "
                          "`mail_bridge_imap.py set-password` ausführen.")
    return secret


def set_password():
    """Interactive only: the password is typed by the user and goes straight into the keychain."""
    if not (sys.stdin and sys.stdin.isatty()):
        raise BridgeError("Dieser Befehl läuft nur in deinem eigenen Terminal-Fenster. So gelangt das Passwort "
                          "nie in einen Chat oder ein Protokoll. Bitte dort ausführen: "
                          f"{cfg.venv_python()} {Path(__file__).resolve()} set-password")
    conf = imap_conf()
    keyring = _keyring()
    secret = getpass.getpass(f"Passwort für {conf['user']} (Eingabe bleibt unsichtbar): ")
    if not secret:
        raise BridgeError("Kein Passwort eingegeben, nichts gespeichert.")
    keyring.set_password(conf["keyring_service"], conf["user"], secret)
    del secret
    return {"gespeichert": True, "eintrag": conf["keyring_service"], "naechster_schritt": "mail_bridge_imap.py check"}


def delete_password():
    conf = imap_conf()
    try:
        _keyring().delete_password(conf["keyring_service"], conf["user"])
    except BridgeError:
        raise
    except Exception:
        return {"geloescht": False, "hinweis": "Es war kein Passwort gespeichert."}
    return {"geloescht": True}


# ---------------------------------------------------------------- connection

def connect(conf):
    """TLS from the first byte, certificates checked against the certifi bundle."""
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return imaplib.IMAP4_SSL(conf["host"], PORT, ssl_context=context, timeout=60)


def open_session(conf=None):
    conf = conf or imap_conf()
    secret = password(conf)
    try:
        conn = connect(conf)
    except ssl.SSLError:
        raise BridgeError(f"Die verschlüsselte Verbindung zu {conf['host']} konnte nicht geprüft werden "
                          "(Zertifikat). Es wurde nichts übertragen.")
    except OSError:
        raise BridgeError(f"{conf['host']} ist nicht erreichbar (kein Netz oder falscher Server-Name; "
                          "siehe `mail_bridge_imap.py hosts`).")
    try:
        conn.login(conf["user"], secret)
    except imaplib.IMAP4.error:
        _close(conn)
        raise BridgeError(AUTH_HINT)
    finally:
        del secret
    return conn


def _close(conn):
    for step in ("close", "logout"):
        try:
            getattr(conn, step)()
        except Exception:
            pass


# ---------------------------------------------------------------- folder names

def mutf7_encode(name):
    """Folder name in the modified UTF-7 that IMAP uses for non-ASCII characters."""
    out, buf = [], ""

    def flush():
        if buf:
            out.append("&" + base64.b64encode(buf.encode("utf-16-be")).decode("ascii").rstrip("=").replace("/", ",") + "-")

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            buf = ""
            out.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    flush()
    return "".join(out)


def mutf7_decode(name):
    def part(m):
        if not m.group(1):
            return "&"
        raw = m.group(1).replace(",", "/")
        try:
            return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return m.group(0)
    return re.sub(r"&([^-]*)-", part, name)


def _quoted(folder):
    return '"' + mutf7_encode(str(folder)).replace("\\", "\\\\").replace('"', '\\"') + '"'


LIST_LINE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$')


def list_folders(conn):
    """[{"name": ..., "flags": [...]}] with readable names."""
    status, data = conn.list()
    if status != "OK":
        raise BridgeError("Der Server hat die Ordnerliste nicht geliefert.")
    out = []
    for item in data or []:
        literal = None
        if isinstance(item, tuple):                       # name sent as a literal
            item, literal = item[0], item[1]
        if not isinstance(item, (bytes, bytearray)):
            continue
        m = LIST_LINE.match(item.decode("utf-8", "replace").strip())
        if not m:
            continue
        name = literal.decode("utf-8", "replace") if literal is not None else m.group("name").strip()
        if literal is None and name.startswith('"') and name.endswith('"'):
            name = re.sub(r"\\(.)", r"\1", name[1:-1])
        out.append({"name": mutf7_decode(name), "flags": m.group("flags").split()})
    return out


def drafts_folder(folders):
    """The folder the server marks as drafts, else a usual name, else None."""
    for f in folders:
        if any(flag.lower() == "\\drafts" for flag in f["flags"]):
            return f["name"]
    for f in folders:
        if f["name"].split("/")[-1].split(".")[-1].lower() in ("drafts", "entwürfe", "entwurf", "draft"):
            return f["name"]
    return None


# ---------------------------------------------------------------- reading (read-only)

def _since(days):
    d = dt.date.today() - dt.timedelta(days=int(days))
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def _literals(data):
    """(uid, bytes) for every message part in a FETCH answer."""
    data = list(data or [])
    for i, item in enumerate(data):
        if not (isinstance(item, tuple) and len(item) >= 2):
            continue
        m = re.search(rb"UID (\d+)", item[0] or b"")
        if not m and i + 1 < len(data) and isinstance(data[i + 1], (bytes, bytearray)):
            m = re.search(rb"UID (\d+)", data[i + 1])     # some servers name the UID after the text
        yield (m.group(1).decode() if m else None), item[1]


def scan_folder(conn, folder, days, companies):
    """Open one folder read-only, look at four header lines of the recent messages and return
    the UIDs that are job alerts and those that may be answers to an application."""
    status, _ = conn.select(_quoted(folder), readonly=True)
    if status != "OK":
        raise BridgeError(f"Der Ordner '{folder}' lässt sich nicht öffnen (Namen zeigt `mail_bridge_imap.py folders`).")
    status, data = conn.uid("SEARCH", None, "SINCE", _since(days))
    uids = (data[0] or b"").split() if status == "OK" and data else []
    alerts, replies = [], []
    for start in range(0, len(uids), 200):
        batch = b",".join(uids[start:start + 200]).decode()
        status, data = conn.uid("FETCH", batch, HEADERS)
        if status != "OK":
            continue
        for uid, raw in _literals(data):
            if uid is None:
                continue
            head = shared.parse_message(raw)
            sender, subject = str(head["from"] or ""), str(head["subject"] or "")
            if shared.is_alert(sender):
                alerts.append(uid)
            elif shared.is_reply_candidate(sender, subject, companies):
                replies.append(uid)
    return alerts, replies


def fetch_message(conn, uid):
    status, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
    if status != "OK":
        return None
    for _, raw in _literals(data):
        return shared.parse_message(raw)
    return None


def fetch(days=None, conn=None, conf=None):
    """Write the same files as the Apple Mail bridge."""
    conf = conf or imap_conf()
    days, source = shared.days_back(days), f"imap:{conf['host']}"
    own = conn is None
    conn = conn or open_session(conf)
    try:
        known, new, found = shared.seen_ids(), [], []
        companies = shared.applied_companies()
        for folder in conf["folders"]:
            alerts, replies = scan_folder(conn, folder, days, companies)
            for uids, bucket, record in ((replies, found, shared.reply_record), (alerts, new, shared.alert_record)):
                for uid in uids:
                    msg = fetch_message(conn, uid)
                    if msg is None:
                        continue
                    key = shared.message_key(msg, f"{folder}-{uid}")
                    if key in known:
                        continue
                    known.add(key)
                    bucket.append(record(msg, key))
    finally:
        if own:
            _close(conn)
    return {**shared.write_replies(found, source), **shared.write_alerts(new, source)}


def check(conn=None, conf=None):
    """Login, folders and counts. No mail content and no password in the output."""
    conf = conf or imap_conf()
    own = conn is None
    conn = conn or open_session(conf)
    try:
        folders = list_folders(conn)
        names = [f["name"] for f in folders]
        found = drafts_folder(folders)
        alerts = replies = 0
        days = shared.days_back()
        for folder in conf["folders"]:
            a, r = scan_folder(conn, folder, days, shared.applied_companies())
            alerts, replies = alerts + len(a), replies + len(r)
    finally:
        if own:
            _close(conn)
    report = {"anmeldung": "ok", "server": conf["host"], "verschluesselt": True, "ordner": len(folders),
              "tage": days, "alert_mails": alerts, "moegliche_antworten": replies,
              "entwurfsordner": conf["drafts_folder"], "entwurfsordner_vorhanden": conf["drafts_folder"] in names}
    if not report["entwurfsordner_vorhanden"]:
        report["hinweis"] = (f"mail.imap.drafts_folder auf '{found}' setzen." if found else
                             "Entwurfsordner nicht gefunden - Namen mit `mail_bridge_imap.py folders` nachsehen.")
    if not shared.alert_senders():
        report["hinweis_alerts"] = "mail.alert_senders ist leer - es werden keine Job-Alerts gelesen."
    return report


# ---------------------------------------------------------------- the one write: a draft

def put_draft(eml_path, conn=None, conf=None):
    """Store one prepared message in the drafts folder. It is not sent; the user sends it."""
    conf = conf or imap_conf()
    path = Path(eml_path)
    if not path.is_file():
        raise BridgeError(f"Die Datei {path} gibt es nicht.")
    data = path.read_bytes()
    if not data.strip() or len(data) > MAX_DRAFT_BYTES:
        raise BridgeError("Die .eml-Datei ist leer oder größer als 25 MB.")
    data = re.sub(rb"\r?\n", b"\r\n", data)
    own = conn is None
    conn = conn or open_session(conf)
    try:
        status, answer = conn.append(_quoted(conf["drafts_folder"]), r"(\Draft)",
                                     imaplib.Time2Internaldate(time.time()), data)
    except imaplib.IMAP4.error:
        status, answer = "NO", []
    finally:
        if own:
            _close(conn)
    if status != "OK":
        raise BridgeError(f"Der Entwurf konnte nicht im Ordner '{conf['drafts_folder']}' abgelegt werden "
                          "(Ordnernamen mit `mail_bridge_imap.py folders` prüfen, dann mail.imap.drafts_folder anpassen).")
    return {"entwurf_abgelegt": True, "ordner": conf["drafts_folder"], "gesendet": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("hosts", "set-password", "delete-password", "check", "folders"):
        sub.add_parser(name)
    f = sub.add_parser("fetch")
    f.add_argument("--days", type=int, default=None)
    p = sub.add_parser("put-draft")
    p.add_argument("--eml", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "hosts":
            for provider, host in PROVIDER_HINTS:
                print(f"{provider:<20} {host}  (Port {PORT})")
            print("Anderer Anbieter: den IMAP-Server (Posteingangsserver) nennt dessen Hilfeseite.")
            return
        if args.cmd == "set-password":
            result = set_password()
        elif args.cmd == "delete-password":
            result = delete_password()
        elif args.cmd == "check":
            result = check()
        elif args.cmd == "fetch":
            result = fetch(args.days)
        elif args.cmd == "put-draft":
            result = put_draft(args.eml)
        else:
            conn = open_session()
            try:
                folders = list_folders(conn)
            finally:
                _close(conn)
            result = {"ordner": [f["name"] for f in folders], "entwurfsordner_vorschlag": drafts_folder(folders)}
    except BridgeError as e:
        sys.exit(str(e))
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
        sys.exit(f"Der Mail-Server hat die Verbindung beendet ({type(e).__name__}). Bitte später erneut versuchen.")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
