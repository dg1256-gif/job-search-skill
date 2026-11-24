#!/usr/bin/env python3
"""What an applicant tracking system gets out of the CV PDF, and which posting terms the CV covers.

A portal does not look at the page, it extracts the text. This script does the same and reports:

  text       is there a text layer at all (a scanned or "printed as image" PDF has none)
  contact    are e-mail address, phone number and name in the extracted text, literally
  glyphs     unreadable characters from fonts without a text mapping
  order      does the text come out in the order of the Word file (two-column layouts often do not)
  keywords   each term of the posting: in the CV / proven in the profile but missing in the CV / not proven

It never changes a file and never suggests adding a term the profile does not prove.

  python 08_Scripts/ats_check.py check --pdf <cv.pdf> [--docx <cv.docx>] [--name "<Vor- und Nachname>"]
                                       [--keywords "a, b, c" | --keywords-file <file>] [--posting <file>]
                                       [--profile 01_Config/candidate_profile.md] [--json]
  python 08_Scripts/ats_check.py selftest

Text extraction needs the package pypdf (in requirements.txt) or the program pdftotext.
Exit code 0 = no problem, 3 = at least one check failed.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(os.environ.get("JOBSUCHE_ROOT") or Path(__file__).resolve().parent.parent)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(\+|00)?\d[\d ()/.-]{7,}\d(?!\d)")
STOP = set("""der die das und oder mit für von bei aus auf als auch eine einer eines einem einen ein ist sind wird werden
wir sie ihr ihre ihren du dein deine uns unser unsere im in an am zu zum zur den dem des nicht sowie über unter nach durch
sich dass wie was bist hast haben sein bzw etc the and for with you your our are will have has that this from into about
who can all per not their they its job role team work working years year jahre jahr mehr sehr gute guter gutes neue neuen
erfahrung experience kenntnisse knowledge skills aufgaben profil benefits bieten suchen bringst mitbringen within across
bereich bereichen sowie ideally idealerweise including inkl ability strong""".split())


class NoExtractor(Exception):
    pass


def extract(pdf):
    """(text, pages) of a PDF through pypdf, else pdftotext."""
    try:
        import pypdf
    except ImportError:
        pypdf = None
    if pypdf:
        import logging
        logging.getLogger("pypdf").setLevel(logging.ERROR)     # repaired cross references are not our finding
        reader = pypdf.PdfReader(str(pdf))
        return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)
    tool = shutil.which("pdftotext")
    if tool:
        out = subprocess.run([tool, "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        return out, out.count("\f") or 1
    raise NoExtractor("Kein PDF-Leser: `pip install pypdf` in der Umgebung des Arbeitsordners (steht in requirements.txt).")


def fold(text):
    """Lower case, umlauts and accents folded, hyphens and line breaks as one space."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[-‐‑–—/_]+", " ", text).split())


def digits(text):
    return re.sub(r"\D", "", text or "")


def docx_paragraphs(path):
    """Paragraph texts of a Word file in document order, tables included."""
    import docx
    doc = docx.Document(str(path))
    out = []
    for block in doc.element.body.iter():
        if block.tag.endswith("}p"):
            text = "".join(t.text or "" for t in block.iter() if t.tag.endswith("}t")).strip()
            if text:
                out.append(text)
    return out


def reading_order(paragraphs, pdf_text):
    """How many paragraphs of the Word file are found in the PDF text, and how many of those in order."""
    hay = fold(pdf_text).replace(" ", "")
    pos, last = [], 0
    for p in paragraphs:
        needle = fold(p).replace(" ", "")[:40]
        if len(needle) < 12:
            continue
        i = hay.find(needle, last)               # a repeated line (a date, a place) counts at its next occurrence
        if i < 0:
            i = hay.find(needle)
        else:
            last = i
        pos.append(i)
    found = [p for p in pos if p >= 0]
    best = []                                    # longest increasing run = paragraphs that keep their order
    for p in found:
        import bisect
        i = bisect.bisect_left(best, p)
        best[i:i + 1] = [p]
    return {"checked": len(pos), "found": len(found), "in_order": len(best)}


def keyword_candidates(posting, limit=25):
    """Frequent terms of a posting, as a fallback when the caller passes no keywords."""
    words = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9+#.&-]{2,}", posting or "")
    count, shown = {}, {}
    for w in words:
        w = w.strip(".-&")
        k = fold(w)
        if len(k) < 4 or k in STOP or k.isdigit():
            continue
        count[k] = count.get(k, 0) + 1
        shown.setdefault(k, w)
    ranked = sorted(count, key=lambda k: (-count[k], k))
    return [shown[k] for k in ranked if count[k] >= 2][:limit]


def has_term(term, folded):
    t = fold(term)
    if not t:
        return False
    if t in folded or t.replace(" ", "") in folded.replace(" ", ""):
        return True
    parts = [p for p in t.split() if p not in STOP]
    return len(parts) > 1 and all(re.search(r"\b" + re.escape(p), folded) for p in parts)


def unproven_section(profile):
    """Text of the profile from a heading 'nicht belegt' on: terms that occur only there are not proven."""
    m = re.search(r"(?im)^#+.*nicht belegt.*$", profile or "")
    if not m:
        return profile or "", ""
    rest = profile[m.end():]
    nxt = re.search(r"(?m)^#+ ", rest)
    return profile[:m.start()] + (rest[nxt.start():] if nxt else ""), rest[:nxt.start()] if nxt else rest


def keyword_report(keywords, cv_text, profile):
    proven, unproven = unproven_section(profile)
    cv, pr, un = fold(cv_text), fold(proven), fold(unproven)
    out = {"in_cv": [], "proven_missing": [], "unproven": []}
    for k in keywords:
        if has_term(k, cv):
            out["in_cv"].append(k)
        elif profile and has_term(k, pr) and not has_term(k, un):
            out["proven_missing"].append(k)
        else:
            out["unproven"].append(k)
    return out


def check(pdf, docx_path=None, name="", keywords=None, posting="", profile=""):
    text, pages = extract(pdf)
    plain = " ".join(text.split())
    checks = []

    def add(key, ok, detail, level="fail"):
        checks.append({"check": key, "ok": bool(ok), "level": "ok" if ok else level, "detail": detail})

    add("text", len(plain) >= 300,
        f"{len(plain)} Zeichen auf {pages} Seite(n) lesbar" if len(plain) >= 300 else
        f"nur {len(plain)} Zeichen lesbar – das PDF ist vermutlich ein Bild; aus Word neu als PDF speichern, nicht drucken oder scannen")
    mail = EMAIL.search(plain)
    add("email", mail, "E-Mail-Adresse wird gelesen" if mail else
        "keine E-Mail-Adresse im Text – steht sie in einer Kopfzeile, einem Bild oder einem Textfeld?")
    phone = next((m.group(0) for m in PHONE.finditer(plain) if 9 <= len(digits(m.group(0))) <= 15), None)
    add("phone", phone, "Telefonnummer wird gelesen" if phone else "keine Telefonnummer im Text", "warn")
    if name:
        parts = [p for p in fold(name).split() if len(p) > 1]
        ok = bool(parts) and all(p in fold(plain) for p in parts)
        head = ok and all(p in fold(plain[:400]) for p in parts)
        add("name", ok, "Name steht im Text" + ("" if head else ", aber nicht am Anfang – manche Portale lesen ihn dann falsch")
            if ok else "Name nicht im Text gefunden (Bild, Kopfzeile oder Sonderschrift?)")
        if ok and not head:
            checks[-1].update(ok=False, level="warn")
    bad = sum(1 for c in plain if c == "�" or 0xE000 <= ord(c) <= 0xF8FF) + 5 * plain.count("(cid:")
    share = bad / max(len(plain), 1)
    add("glyphs", share < 0.005, "keine unlesbaren Zeichen" if not bad else
        f"{bad} unlesbare Zeichen ({share:.1%}) – eine Schrift ohne Textzuordnung; Symbol- oder Icon-Schrift durch Text ersetzen",
        "fail" if share >= 0.02 else "warn")
    order = None
    if docx_path:
        order = reading_order(docx_paragraphs(docx_path), text)
        if order["checked"]:
            found, kept = order["found"] / order["checked"], order["in_order"] / max(order["found"], 1)
            add("content", found >= 0.9, f"{order['found']} von {order['checked']} Absätzen der Word-Datei im PDF-Text gefunden", "warn")
            add("order", kept >= 0.9, f"{order['in_order']} von {order['found']} Absätzen in der Reihenfolge der Word-Datei" +
                ("" if kept >= 0.9 else " – Spalten oder Textfelder werden durcheinander gelesen"), "warn")
    if keywords is None and posting:
        keywords = keyword_candidates(posting)
    kw = keyword_report(keywords, text, profile) if keywords else None
    return {"pdf": str(pdf), "pages": pages, "chars": len(plain), "checks": checks, "order": order, "keywords": kw,
            "profile_used": bool(profile), "failed": [c["check"] for c in checks if c["level"] == "fail"],
            "warnings": [c["check"] for c in checks if c["level"] == "warn"]}


def report(r):
    mark = {"ok": "OK     ", "warn": "HINWEIS", "fail": "FEHLER "}
    lines = [f"ATS-Prüfung {Path(r['pdf']).name}"] + [f"  {mark[c['level']]} {c['detail']}" for c in r["checks"]]
    kw = r["keywords"]
    if kw:
        total = sum(len(v) for v in kw.values())
        lines += ["", f"Begriffe der Anzeige: {len(kw['in_cv'])} von {total} stehen im Lebenslauf",
                  "  im Lebenslauf: " + (", ".join(kw["in_cv"]) or "–")]
        if r["profile_used"]:
            lines += ["  im Profil belegt, fehlt im Lebenslauf: " + (", ".join(kw["proven_missing"]) or "–"),
                      "  nicht belegt (nie aufnehmen): " + (", ".join(kw["unproven"]) or "–")]
        else:
            lines += ["  nicht im Lebenslauf: " + (", ".join(kw["unproven"]) or "–") + "  (ohne Profil nicht einstufbar)"]
    return "\n".join(lines)


def selftest():
    assert fold("Prozess-Optimierung\nÜbergabe") == "prozess optimierung uebergabe"
    assert has_term("Change Management", fold("Erfahrung im Change-Management")) and not has_term("SAP", fold("Excel"))
    assert has_term("Projektleitung", fold("Projekt-\nleitung großer Vorhaben"))
    profile = "# Profil\nSAP S/4HANA Einführung, Python\n## Nicht belegt\nKubernetes, Scrum Master\n## Sprachen\nEnglisch"
    k = keyword_report(["Python", "SAP", "Kubernetes", "Englisch", "Rust"], "Lebenslauf: Python, Excel", profile)
    assert k == {"in_cv": ["Python"], "proven_missing": ["SAP", "Englisch"], "unproven": ["Kubernetes", "Rust"]}, k
    o = reading_order(["Erste Station bei der Beispiel AG", "Zweite Station bei Muster GmbH", "Dritte Station Ausbildung"],
                      "Zweite Station bei Muster GmbH\nErste Station bei der Beispiel AG\nDritte Station Ausbildung")
    assert o == {"checked": 3, "found": 3, "in_order": 2}, o
    c = keyword_candidates("Wir suchen Python Python Erfahrung und SAP, SAP sowie Teamgeist.")
    assert c == ["Python"], c                     # SAP is too short for the fallback, "Erfahrung" is a stop word
    assert PHONE.search("Tel. +49 151 2345678") and EMAIL.search("a.b@example.org")
    print("ats_check selftest: OK")


def main():
    ap = argparse.ArgumentParser(description="Prüft, was ein Bewerbungsportal aus dem Lebenslauf-PDF liest.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--pdf", required=True)
    c.add_argument("--docx", help="die Word-Datei, aus der das PDF entstand (für die Lesereihenfolge)")
    c.add_argument("--name", help="Vor- und Nachname; ohne Angabe aus settings.yaml")
    c.add_argument("--keywords", help="Begriffe der Anzeige, durch Komma getrennt")
    c.add_argument("--keywords-file", help="Datei mit einem Begriff je Zeile")
    c.add_argument("--posting", help="Anzeigentext; ohne --keywords werden häufige Begriffe daraus genommen")
    c.add_argument("--profile", default=str(ROOT / "01_Config" / "candidate_profile.md"))
    c.add_argument("--json", action="store_true")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return selftest()
    name = args.name
    if name is None:
        try:
            import settings
            name = (settings.load().get("person") or {}).get("full_name") or ""
        except Exception:
            name = ""
    keywords = None
    if args.keywords_file:
        keywords = [x.strip() for x in Path(args.keywords_file).read_text(encoding="utf-8").splitlines() if x.strip()]
    elif args.keywords:
        keywords = [x.strip() for x in args.keywords.split(",") if x.strip()]
    posting = Path(args.posting).read_text(encoding="utf-8", errors="replace") if args.posting else ""
    profile = Path(args.profile).read_text(encoding="utf-8") if args.profile and Path(args.profile).exists() else ""
    try:
        r = check(args.pdf, args.docx, name, keywords, posting, profile)
    except NoExtractor as e:
        raise SystemExit(str(e))
    print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else report(r))
    sys.exit(3 if r["failed"] else 0)


if __name__ == "__main__":
    main()
