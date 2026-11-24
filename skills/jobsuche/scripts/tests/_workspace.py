"""Scratch workspace for the tests: neutral settings, two letter templates in different layouts and
a CV, all generated with python-docx. Nothing here touches a real workspace.

Importing this module creates the workspace once and points JOBSUCHE_ROOT at it, so it must be
imported before `settings`. As a script it builds a workspace at a given path:

  python tests/_workspace.py /path/to/empty/folder [table|plain]
"""
import os
import sys
import tempfile
from pathlib import Path

import docx
import yaml
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

SCRIPTS = Path(__file__).resolve().parent.parent

BODY = [
    "in Ihrer Ausschreibung suchen Sie eine Person, die Abläufe im Kundendienst ordnet und messbar macht. "
    "Genau das habe ich in den letzten vier Jahren bei der Beispiel AG getan, zuerst als Sachbearbeiterin und "
    "seit zwei Jahren als Teamleiterin für zwölf Kolleginnen und Kollegen.",
    "Dort habe ich die Bearbeitungszeit für Reklamationen von neun auf vier Tage gesenkt, indem ich die Übergabe "
    "zwischen Lager und Kundendienst neu geregelt und ein gemeinsames Formular eingeführt habe. Die Zahl der "
    "Rückfragen ist seitdem um ein Drittel gefallen, und die Auswertung dazu erstelle ich jeden Monat selbst.",
    "Außerdem habe ich drei neue Mitarbeitende eingearbeitet und die Schulungsunterlagen des Teams überarbeitet. "
    "Diese Erfahrung möchte ich bei Ihnen einbringen, weil Ihr Kundendienst gerade wächst und feste Abläufe "
    "braucht. Über ein Gespräch freue ich mich.",
]
SLOTS = {
    "table": {"date": "tbl:0:0:1", "subject": "p:0", "salutation": "p:2", "body_first": "p:3", "body_last": "p:5",
              "closing": "p:6", "signature": "p:8", "recipient": None},
    "plain": {"recipient": "p:1..p:3", "date": "p:4", "subject": "p:5", "salutation": "p:6", "body_first": "p:7",
              "body_last": "p:9", "closing": "p:10", "signature": "p:11",
              "date_format": {"de": "{city}, {dd}.{mm}.{yyyy}", "en": "{city}, {d} {month} {yyyy}"}},
}
CV_SLOTS = {"headline": "p:1", "summary_heading": "PROFIL", "focus_heading": "SCHWERPUNKTE",
            "reorder_groups": [{"name": "station", "heading": "Beispiel AG"}]}
CV_BULLETS = ["Bearbeitungszeit für Reklamationen von neun auf vier Tage gesenkt",
              "Team von zwölf Personen geführt",
              "Monatliche Auswertung der Rückfragen erstellt",
              "Drei neue Mitarbeitende eingearbeitet"]
CV_FOCUS = ["Kundendienst", "Prozessverbesserung", "Teamführung"]


def _para(document, text, bold=False, size=11, align=None, style=None):
    p = document.add_paragraph(style=style)
    if text:
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
    if align is not None:
        p.alignment = align
    return p


def letter_table(path):
    """Layout 1: sender and date in a two-column table, no recipient block, spacer paragraphs."""
    d = docx.Document()
    table = d.add_table(rows=1, cols=2)
    left, right = table.rows[0].cells
    left.paragraphs[0].add_run("Erika Mustermann").bold = True
    left.add_paragraph("Musterstraße 1, 12345 Musterstadt")
    right.paragraphs[0].add_run("Musterstadt, 1. Januar 2025")
    right.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _para(d, "Bewerbung als Sachbearbeiterin Kundendienst", bold=True, size=12)
    _para(d, "")
    _para(d, "Sehr geehrte Frau Beispiel,")
    for text in BODY:
        _para(d, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    _para(d, "Mit freundlichen Grüßen")
    _para(d, "")
    _para(d, "Erika Mustermann")
    d.save(str(path))


def letter_plain(path):
    """Layout 2: everything as plain paragraphs, recipient block of three lines, date right-aligned."""
    d = docx.Document()
    _para(d, "Erika Mustermann · Musterstraße 1 · 12345 Musterstadt", size=9)
    for line in ("Vorlage KG", "Frau Beispiel", "Beispielweg 2, 12345 Musterstadt"):
        _para(d, line)
    _para(d, "Musterstadt, 01.01.2025", align=WD_ALIGN_PARAGRAPH.RIGHT)
    _para(d, "Bewerbung als Sachbearbeiterin Kundendienst", bold=True, size=12)
    _para(d, "Sehr geehrte Frau Beispiel,")
    for text in BODY:
        _para(d, text)
    _para(d, "Mit freundlichen Grüßen")
    _para(d, "Erika Mustermann")
    d.save(str(path))


def cv(path):
    d = docx.Document()
    _para(d, "Erika Mustermann", bold=True, size=16)
    _para(d, "TEAMLEITERIN KUNDENDIENST", size=11)
    _para(d, "PROFIL", bold=True)
    _para(d, "Teamleiterin im Kundendienst mit vier Jahren Erfahrung in der Bearbeitung von Reklamationen.")
    _para(d, "SCHWERPUNKTE", bold=True)
    for text in CV_FOCUS:
        _para(d, text, style="List Bullet")
    _para(d, "BERUFSERFAHRUNG", bold=True)
    _para(d, "Beispiel AG", bold=True)
    _para(d, "Teamleiterin Kundendienst, 2021 bis heute")
    for text in CV_BULLETS:
        _para(d, text, style="List Bullet")
    _para(d, "AUSBILDUNG", bold=True)
    _para(d, "Kauffrau für Büromanagement, Musterschule Musterstadt")
    d.save(str(path))


def settings(layout="table", **over):
    data = {
        "person": {"full_name": "Erika Mustermann", "city": "Musterstadt", "timezone": "Europe/Berlin", "fixed_title": ""},
        "language": {"default": "de"},
        "mail": {"mode": "imap", "address": "erika@example.com", "days_back": 2,
                 "alert_senders": ["jobalerts-noreply@linkedin.com", "mailrobot@mail.xing.com", "alert@indeed.com"],
                 "imap": {"host": "imap.example.com", "port": 993, "user": "erika@example.com",
                          "keyring_service": "jobsuche-imap-test", "drafts_folder": "Entwürfe", "folders": ["INBOX"]},
                 "apple_mail": {"account": "Beispielkonto"}},
        "templates": {"cover_letter": f"00_Input/Anschreiben_Referenz/vorlage_{layout}.docx",
                      "cover_letter_slots": SLOTS[layout],
                      "cv": {"de": "00_Input/Lebenslauf/lebenslauf_de.docx", "en": ""}, "cv_pdf": "",
                      "cv_slots": CV_SLOTS},
        "documents": {"pdf_engine": "auto", "letter_filename": "Anschreiben_{role}.docx",
                      "letter_words": [100, 400], "max_pages": 1, "cv_summary_words": [10, 60]},
        "dashboard": {"url": "", "trigger_token": "Abc123Def456", "portals": [], "segment_tabs": []},
        "schedule": {"mode": "local", "time": "07:30", "mail_bridge_times": ["08:30", "18:30"], "poll_seconds": 120},
        "agent": {"cli": "claude", "model": "", "helper_model": "", "command": ""},
        "git": {"sync": False},
    }
    for key, value in over.items():
        section, _, name = key.partition("__")
        if name:
            data[section][name] = value
        else:
            data[section] = value
    return data


def write_settings(root, layout="table", **over):
    path = Path(root) / "01_Config" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(settings(layout, **over), allow_unicode=True, sort_keys=False), encoding="utf-8")


def make(root, layout="table"):
    root = Path(root)
    for sub in ("00_Input/Anschreiben_Referenz", "00_Input/Lebenslauf", "01_Config", "02_State", "03_Applications",
                "04_CVs", "07_Logs/runs", "07_Logs/mail_inbox"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    letter_table(root / "00_Input/Anschreiben_Referenz/vorlage_table.docx")
    letter_plain(root / "00_Input/Anschreiben_Referenz/vorlage_plain.docx")
    cv(root / "00_Input/Lebenslauf/lebenslauf_de.docx")
    write_settings(root, layout)
    return root


if __name__ == "__main__":
    target = make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "table")
    print(target)
else:
    ROOT = Path(os.environ.get("JOBSUCHE_TEST_ROOT") or tempfile.mkdtemp(prefix="jobsuche_test_"))
    os.environ["JOBSUCHE_ROOT"] = str(ROOT)
    make(ROOT)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
