#!/usr/bin/env python3
"""Tailored CV per job from the user's own Word CV.

The CV keeps its layout. Only three things change, so nothing can be invented:
  1. the headline under the name,
  2. the profile summary (the only newly written text, checked like a cover letter),
  3. the order of bullets inside the configured groups (moved, never rewritten, never dropped
     or added - the validator stops if any other paragraph changes).

Which paragraph is what is stored in 01_Config/settings.yaml (templates.cv_slots), either once or
per language ({de: {...}, en: {...}}). Every entry is optional; without any, only `base` works.

  headline: "tbl:0:0:1:1"            locator of the headline paragraph (see `inspect`)
  summary: "tbl:0:0:1:4"             locator of the summary paragraph, or instead
  summary_heading: "PROFIL"          the heading the summary follows
  focus_heading: "SCHWERPUNKTE"      heading of a bullet list that may be reordered (group "focus")
  reorder_groups:                    further bullet groups that may be reordered
    - {name: "station", heading: "Muster GmbH", until: "Erfolge"}   bullets after this line (until optional)
    - {name: "projekte", first: "p:12", last: "p:17"}                or a locator range

Spec (JSON):
  {"job_key": "...", "company": "...", "role": "...", "language": "de"|"en",
   "headline": "...", "summary": "...",
   "order": {"station": ["start of bullet", ...], "focus": ["start of entry", ...]}}
  Listed bullets come first, in this order; the rest keep their order.
  ("bullet_order" = order of the first reorder group, "focus_order" = order of "focus".)

  cv_tailor.py inspect [--lang de|en] [--template file.docx]   numbered paragraphs with locators
  cv_tailor.py build --spec spec.json [--no-pdf]   -> 04_CVs/<year>/<date>/<Company>/<Role>/<base name>.docx + .pdf
  cv_tailor.py base --lang de|en                   -> path of the untailored PDF
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402
import cover_letter as cl  # noqa: E402  (shared: locators, text replacement, style and fact checks)
import docs_pdf  # noqa: E402

ROOT = cfg.ROOT
OUT_DIR = ROOT / "04_CVs"                       # git-ignored: CVs stay local (data minimisation)
INDEX = OUT_DIR / "index.json"                  # job_key -> tailored .docx (relative to ROOT)
BULLET_STYLE = re.compile(r"list|aufz|bullet", re.I)
BULLET_GLYPH = re.compile(r"^\s*[•▪■●◦·–-]\s")
NO_SLOTS = ("Für den Lebenslauf ist kein Zuschnitt eingerichtet (templates.cv_slots ist leer). "
            "Möglich ist nur `cv_tailor.py base` (unveränderter Lebenslauf als PDF). "
            "Zum Einrichten: `cv_tailor.py inspect` ausführen und die Zuordnung eintragen.")


def _settings():
    return cfg.load()


def base_docx(lang):
    """The user's CV for this language; the other language stands in if there is only one."""
    cv = _settings()["templates"]["cv"] or {}
    for key in (lang, "de", "en"):
        path = cfg.path(cv.get(key))
        if path and path.exists():
            return path
    return None


def _need_base(lang):
    src = base_docx(lang)
    if src is None:
        raise SystemExit("Lebenslauf fehlt: templates.cv.de (oder .en) in 01_Config/settings.yaml auf deine "
                         ".docx-Datei setzen.")
    return src


def slots(lang):
    s = _settings()["templates"]["cv_slots"] or {}
    if s and set(s) <= {"de", "en"}:
        s = s.get(lang) or {}
    return {k: v for k, v in s.items() if v}


def summary_words():
    span = list(_settings()["documents"].get("cv_summary_words") or [])
    lo, hi = span if len(span) == 2 else (50, 140)
    return int(lo), int(hi)


# ---------------------------------------------------------------- locating

def _find_heading(body, heading):
    """First paragraph whose text is the heading (else: starts with it), case-insensitive."""
    want = str(heading).strip().casefold()
    flat = [el for _, el in cl.walk(body)]
    for test in (lambda t: t == want, lambda t: t.startswith(want)):
        for el in flat:
            if test(cl.el_text(el).strip().casefold()):
                return el
    raise SystemExit(f"Die Überschrift '{heading}' steht nicht im Lebenslauf. Bitte `cv_tailor.py inspect` "
                     "ausführen und templates.cv_slots korrigieren.")


def is_bullet(el, document=None):
    """List paragraph: has numbering, a list style, or starts with a bullet character."""
    ppr = el.find(qn("w:pPr"))
    if ppr is not None:
        if ppr.find(qn("w:numPr")) is not None:
            return True
        style = ppr.find(qn("w:pStyle"))
        if style is not None:
            name = style.get(qn("w:val")) or ""
            if document is not None:
                try:
                    name += " " + (Paragraph(el, document._body).style.name or "")
                except Exception:
                    pass
            if BULLET_STYLE.search(name):
                return True
    return bool(BULLET_GLYPH.match(cl.el_text(el)))


def headline_el(document, s):
    return cl.resolve(document.element.body, s["headline"]) if s.get("headline") else None


def summary_el(document, s):
    body = document.element.body
    if s.get("summary"):
        return cl.resolve(body, s["summary"])
    if s.get("summary_heading"):
        el = _find_heading(body, s["summary_heading"]).getnext()
        while el is not None:
            if el.tag == cl.W_P and cl.el_text(el).strip():
                return el
            el = el.getnext()
        raise SystemExit(f"Nach der Überschrift '{s['summary_heading']}' folgt kein Text. Bitte `inspect` ausführen.")
    return None


def group_defs(s):
    groups = [dict(g) for g in (s.get("reorder_groups") or []) if isinstance(g, dict) and g.get("name")]
    if s.get("focus_heading"):
        groups.append({"name": "focus", "heading": s["focus_heading"]})
    return groups


def group_members(document, g):
    """The bullet paragraphs of one reorder group, in document order."""
    body = document.element.body
    if g.get("first") and g.get("last"):
        return [e for e in cl.span(body, g["first"], g["last"]) if cl.el_text(e).strip()]
    if not g.get("heading"):
        raise SystemExit(f"Gruppe '{g.get('name')}' in templates.cv_slots braucht `heading` oder `first`/`last`.")
    until = str(g.get("until") or "").strip().casefold()
    out, lead = [], 0
    el = _find_heading(body, g["heading"]).getnext()
    while el is not None:
        text = cl.el_text(el).strip() if el.tag == cl.W_P else None
        if text is not None and until and text.casefold().startswith(until):
            break
        if text is None or not text:
            if el.tag != cl.W_P and out and not until:
                break                                   # a table ends an open list
        elif is_bullet(el, document):
            out.append(el)
        elif not until:
            if out:
                break                                   # first normal line after the list ends it
            lead += 1                                   # date and role lines between heading and list
            if lead > 6:
                break
        el = el.getnext()
    return out


def orders(spec, s):
    """Group name -> requested order, from "order" or the two short forms."""
    out = dict(spec.get("order") or {})
    named = [g["name"] for g in group_defs(s) if g["name"] != "focus"]
    if spec.get("bullet_order") and named:
        out.setdefault(named[0], spec["bullet_order"])
    if spec.get("focus_order"):
        out.setdefault("focus", spec["focus_order"])
    return out


def _reorder(elems, order, what):
    """Put the paragraphs named in `order` (by their start) first; every paragraph keeps one of the
    group's original positions, so nothing around the list moves and nothing is lost."""
    if not order:
        return
    if not elems:
        raise SystemExit(f"Gruppe '{what}': im Lebenslauf wurden keine Aufzählungspunkte gefunden.")
    picked = []
    for start in order:
        hits = [e for e in elems if cl.el_text(e).strip().lower().startswith(str(start).strip().lower())]
        if len(hits) != 1:
            raise SystemExit(f"{what}: '{start}' passt auf {len(hits)} Einträge (muss genau einer sein)")
        if not any(hits[0] is p for p in picked):
            picked.append(hits[0])
    new_order = picked + [e for e in elems if not any(e is p for p in picked)]
    markers = []
    for e in elems:
        marker = e.makeelement(cl.W_P, {})
        e.addprevious(marker)
        e.getparent().remove(e)
        markers.append(marker)
    for marker, e in zip(markers, new_order):
        marker.addprevious(e)
        marker.getparent().remove(marker)


# ---------------------------------------------------------------- build / validate

def default_output(spec, date=None):
    d = dt.date.fromisoformat(date or cl.letter_date())
    # one folder per role: two roles at the same company on the same day must not overwrite each other
    folder = OUT_DIR / str(d.year) / d.isoformat() / cl.short_name(spec["company"])
    if spec.get("role"):
        folder = folder / cl.short_name(spec["role"])
    return folder / _need_base(spec["language"]).name


def build(spec):
    lang = spec["language"]
    src, s = _need_base(lang), slots(lang)
    if not s:
        raise SystemExit(NO_SLOTS)
    out = Path(spec.get("output") or default_output(spec, spec.get("date")))
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out)
    d = docx.Document(str(out))
    head, summary = headline_el(d, s), summary_el(d, s)
    groups = [(g["name"], group_members(d, g)) for g in group_defs(s)]
    wanted = orders(spec, s)
    unknown = sorted(set(wanted) - {name for name, _ in groups})
    if unknown:
        raise SystemExit("Unbekannte Gruppe in der Spec: " + ", ".join(unknown) + " (siehe templates.cv_slots)")
    for key, el in (("headline", head), ("summary", summary)):
        if spec.get(key) and el is None:
            raise SystemExit(f"Die Spec enthält '{key}', aber templates.cv_slots nennt dafür keinen Absatz.")
    if spec.get("headline"):
        text = spec["headline"].strip()
        old = cl.el_text(head)
        cl.set_text(head, text.upper() if old.strip() and old == old.upper() else text)   # capitals as in the CV
    if spec.get("summary"):
        cl.set_text(summary, spec["summary"].strip())
    for name, members in groups:
        _reorder(members, wanted.get(name), name)
    d.save(str(out))
    return out


def validate(out, spec):
    lang = spec["language"]
    s = slots(lang)
    base, new = docx.Document(str(_need_base(lang))), docx.Document(str(out))
    errors, warnings = [], []
    base_flat, new_flat = list(cl.walk(base.element.body)), list(cl.walk(new.element.body))
    index = {id(el): i for i, (_, el) in enumerate(base_flat)}
    head, summary = headline_el(base, s), summary_el(base, s)
    written = {index[id(el)] for el in (head, summary) if el is not None}
    groups = {g["name"]: [index[id(e)] for e in group_members(base, g)] for g in group_defs(s)}
    grouped = {i for members in groups.values() for i in members}
    text = lambda flat, i: cl.el_text(flat[i][1])

    if len(base_flat) != len(new_flat):
        errors.append(f"paragraph count changed ({len(base_flat)} -> {len(new_flat)}) - nothing may be added or dropped")
    else:
        for i, (loc, el) in enumerate(base_flat):
            if i not in written and i not in grouped and text(new_flat, i) != cl.el_text(el):
                errors.append(f"paragraph {loc} changed - only headline, summary and bullet order may change")
            sig = lambda flat, d: cl.para_signature(Paragraph(flat[i][1], d._body))
            if i not in grouped and sig(new_flat, new) != sig(base_flat, base):
                errors.append(f"formatting of paragraph {loc} differs from the base CV")
        for name, members in groups.items():
            if sorted(text(base_flat, i) for i in members) != sorted(text(new_flat, i) for i in members):
                errors.append(f"bullets of group '{name}' changed - only their order may change")

    new_text = lambda el: text(new_flat, index[id(el)]) if el is not None and len(base_flat) == len(new_flat) else ""
    summary_text, headline_text = new_text(summary), new_text(head)
    words = len(summary_text.split())
    if spec.get("summary"):
        lo, hi = summary_words()
        if not lo <= words <= hi:
            errors.append(f"summary has {words} words (target {lo}-{hi})")
        # the summary is the only newly written text: same style and fact rules as a cover letter
        h_err, h_warn = cl.style_findings([summary_text], lang, ["Zusammenfassung"])
        errors += h_err
        warnings += h_warn
        for term in cl.review_terms():
            if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", summary_text, re.I):
                warnings.append(f"summary mentions '{term}' (not evidenced as practice) - check the wording")
    if cl.PLACEHOLDER.search(" ".join(t for t, key in ((summary_text, "summary"), (headline_text, "headline"))
                                      if spec.get(key))):
        errors.append("placeholder in headline or summary")
    if spec.get("headline") and len(headline_text) > 90:
        warnings.append("headline longer than 90 characters may wrap to another line")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary_words": words}


def pdf_pages(pdf):
    return docs_pdf.pdf_pages(pdf) or 0


def register(key, docx_path):
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    index[key] = Path(docx_path).resolve().relative_to(ROOT.resolve()).as_posix()
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def tailored_for(key):
    """The tailored .docx for a job, or None."""
    if not INDEX.exists():
        return None
    rel = json.loads(INDEX.read_text(encoding="utf-8")).get(key)
    return ROOT / rel if rel and (ROOT / rel).exists() else None


def base_pdf(lang, convert=True):
    """The untailored CV as PDF: the PDF next to the .docx if it is current, else the configured
    templates.cv_pdf, else a conversion kept in 04_CVs/_base/. None if nothing can produce one."""
    src = base_docx(lang)
    if src is not None:
        side = src.with_suffix(".pdf")
        if side.exists() and side.stat().st_mtime >= src.stat().st_mtime:
            return side
        cached = OUT_DIR / "_base" / side.name
        if cached.exists() and cached.stat().st_mtime >= src.stat().st_mtime:
            return cached
    fixed = cfg.path(_settings()["templates"]["cv_pdf"])
    cv = _settings()["templates"]["cv"] or {}
    only_one = sum(1 for k in ("de", "en") if cv.get(k)) <= 1
    if fixed and fixed.exists() and (only_one or src is None):
        return fixed
    if src is not None and convert:
        cached = OUT_DIR / "_base" / src.with_suffix(".pdf").name
        cached.parent.mkdir(parents=True, exist_ok=True)
        made = docs_pdf.to_pdf(src, out=cached)
        if made:
            return made
    return fixed if fixed and fixed.exists() else None


def inspect(lang="de", template=None):
    path = Path(template) if template else _need_base(lang)
    document = docx.Document(str(path))
    return cl.inspect(path, extra=lambda el, p: {"bullet": True} if is_bullet(el, document) else {})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--spec", required=True)
    b.add_argument("--no-pdf", action="store_true")
    s = sub.add_parser("base")
    s.add_argument("--lang", default=_settings()["language"]["default"] or "de")
    i = sub.add_parser("inspect")
    i.add_argument("--lang", default=_settings()["language"]["default"] or "de")
    i.add_argument("--template")
    args = ap.parse_args()
    if args.cmd == "inspect":
        result = inspect(args.lang, args.template)
        rows = ",\n  ".join(json.dumps(r, ensure_ascii=False) for r in result.pop("paragraphs"))
        print(f'{json.dumps(result, ensure_ascii=False)[:-1]}, "paragraphs": [\n  {rows}\n]}}')
        return
    if args.cmd == "base":
        pdf = base_pdf(args.lang)
        print(pdf if pdf else "Kein Lebenslauf-PDF vorhanden. " + docs_pdf.HINT)
        sys.exit(0 if pdf else 1)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out = build(spec)
    report = {"file": str(out), **validate(out, spec)}
    if report["ok"] and not args.no_pdf:
        pdf = docs_pdf.to_pdf(out)
        report["pdf"] = str(pdf) if pdf else None
        if pdf is None:
            report["warnings"].append("Kein PDF erzeugt. " + docs_pdf.HINT)
        else:
            report["pages"] = pdf_pages(pdf)
            base = base_pdf(spec["language"])
            base_pages = pdf_pages(base) if base else None
            if base_pages and report["pages"] > base_pages:    # the layout is untouched only if the length is
                report["errors"].append(f"{report['pages']} pages, base CV has {base_pages} - shorten the summary")
                report["ok"] = False
    if report["ok"] and spec.get("job_key"):
        register(spec["job_key"], out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
