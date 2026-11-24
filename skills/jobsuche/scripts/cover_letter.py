#!/usr/bin/env python3
"""Build and validate a cover letter .docx from a template letter (the shipped one or the user's own).

The template is copied and only the text of its content slots is replaced, so styles, section
settings, fonts, spacing and the name/contact block stay exactly as in the template. Which
paragraph is which slot is stored in 01_Config/settings.yaml (templates.cover_letter_slots).

  python 08_Scripts/cover_letter.py inspect [--template file.docx]      numbered paragraphs with locators
  python 08_Scripts/cover_letter.py suggest-slots [--template file.docx] proposed slot map (to confirm)
  python 08_Scripts/cover_letter.py letterhead                           name and contact line from `person`
  python 08_Scripts/cover_letter.py build --spec letter.json
  python 08_Scripts/cover_letter.py validate --docx out.docx --spec letter.json

Locators (0-based, negative numbers count from the end):
  p:N              N-th paragraph directly in the document body
  tbl:T:R:C        first paragraph of table T, row R, cell C
  tbl:T:R:C:P      paragraph P of that cell
  tbl:T:R:C/tbl:T:R:C:P   paragraph in a table nested in a cell
  A..B             range of paragraphs with the same parent (recipient block)

Slots (templates.cover_letter_slots):
  salutation, body_first, body_last   required
  subject, closing, signature, date, recipient   optional (null = the template has no such part)
  date_format   "{city}, {d}. {month} {yyyy}" or {de: "...", en: "..."}; fields {city} {d} {dd} {m} {mm}
                {month} {yyyy} {yy}

Spec (JSON):
  {"company": "...", "role": "...", "language": "en"|"de", "subject": "...", "salutation": "...",
   "paragraphs": ["...", ...], "closing": "..." (optional), "recipient": ["line", ...] (optional),
   "max_pages": 2 (optional), "output": "path/to/file.docx" (optional)}
"""
import argparse
import copy
import datetime as dt
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

ROOT = cfg.ROOT
TEMPLATE = cfg.path(cfg.load()["templates"]["cover_letter"])   # None until the setup has set it

MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
             "September", "Oktober", "November", "Dezember"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
CLOSING = {"en": "Yours sincerely,", "de": "Mit freundlichen Grüßen"}
LANG_TAG = {"en": "en-GB", "de": "de-DE"}
DATE_FORMAT = {"de": "{city}, {d}. {month} {yyyy}", "en": "{city}, {d} {month} {yyyy}"}
REQUIRED_SLOTS = ("salutation", "body_first", "body_last")
SINGLE_SLOTS = ("date", "subject", "salutation", "closing", "signature")
WORDS_MIN, WORDS_MAX = (list(cfg.load()["documents"]["letter_words"]) + [250, 400])[:2]

PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]|\{\{|\}\}|<[A-Z_ ]{3,}>|\bTBD\b|\bXXX\b|lorem ipsum", re.I)

W_P, W_TBL, W_TR, W_TC, W_R, W_T = (qn(x) for x in ("w:p", "w:tbl", "w:tr", "w:tc", "w:r", "w:t"))
W_SDT, W_SDT_CONTENT = qn("w:sdt"), qn("w:sdtContent")


# ---------------------------------------------------------------- settings

def _settings():
    return cfg.load()


def template_path(template=None):
    path = Path(template) if template else cfg.path(_settings()["templates"]["cover_letter"])
    if path is None or not path.exists():
        raise SystemExit("Anschreiben-Vorlage fehlt: templates.cover_letter in 01_Config/settings.yaml "
                         "auf deine .docx-Vorlage setzen.")
    return path


def slot_map(slots=None):
    """The configured slots; stops with one German line if the setup has not filled them."""
    slots = dict(slots if slots is not None else _settings()["templates"]["cover_letter_slots"] or {})
    missing = [k for k in REQUIRED_SLOTS if not slots.get(k)]
    if missing:
        raise SystemExit("Anschreiben-Vorlage ist noch nicht eingerichtet (es fehlt: " + ", ".join(missing)
                         + "). Bitte `cover_letter.py inspect` ausführen und templates.cover_letter_slots füllen.")
    return slots


def review_terms():
    """Skills and tools the CV does not evidence: a mention must be a stated gap, never a claim.
    Source: key `unbelegt:` in 01_Config/exclusions.yaml and/or 01_Config/unproven_terms.txt."""
    terms = []
    excl = ROOT / "01_Config" / "exclusions.yaml"
    if excl.exists():
        try:
            import yaml
            data = yaml.safe_load(excl.read_text(encoding="utf-8")) or {}
            terms += [str(t) for t in (data.get("unbelegt") or []) if str(t).strip()]
        except Exception:      # a broken config file must not stop a letter
            pass
    txt = ROOT / "01_Config" / "unproven_terms.txt"
    if txt.exists():
        terms += [ln.strip() for ln in txt.read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    return list(dict.fromkeys(terms))


# ---------------------------------------------------------------- dates and names

def letter_date():
    """The date printed in every letter: the day it is built, in the user's time zone."""
    tz = _settings()["person"]["timezone"] or "Europe/Berlin"
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz)).date().isoformat()
    except Exception:          # no tz database (Windows without the tzdata package): local date
        return dt.date.today().isoformat()


def format_date(iso, lang, slots=None):
    d = dt.date.fromisoformat(iso)
    slots = slots if slots is not None else (_settings()["templates"]["cover_letter_slots"] or {})
    fmt = slots.get("date_format")
    if isinstance(fmt, dict):
        fmt = fmt.get(lang)
    fmt = fmt or DATE_FORMAT.get(lang, DATE_FORMAT["en"])
    city = _settings()["person"]["city"] or ""
    fields = {"city": city, "d": d.day, "dd": f"{d.day:02d}", "m": d.month, "mm": f"{d.month:02d}",
              "month": (MONTHS_DE if lang == "de" else MONTHS_EN)[d.month - 1],
              "yyyy": d.year, "yy": f"{d.year % 100:02d}"}
    out = re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), m.group(0))), fmt)
    return out if city else re.sub(r"^\s*,\s*", "", out)


def safe_name(text):
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss"))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:60].strip("_")


def short_name(text):
    """Company or role without legal forms, gender tags and bracketed additions (for file names)."""
    text = re.sub(r"\([^)]*\)", " ", text or "")
    text = re.sub(r"(?i)\b(gmbh|ag|se|kg|co\.?|b\.v\.|ltd\.?|inc\.?|llc|plc|international)(?=\W|$)", " ", text)
    text = re.sub(r"\d+\s*-\s*\d+\s*%", " ", text)
    return safe_name(text) or "x"


def _filename_fields(spec):
    return {"role": short_name(spec.get("role")), "company": short_name(spec.get("company")),
            "name": safe_name(_settings()["person"]["full_name"] or "") or "x",
            "date": spec.get("date") or letter_date()}


def letter_filename(spec):
    """File name from documents.letter_filename. By default the employer sees only
    "Anschreiben_<Stellenbezeichnung>.docx"; date and company only name the folders."""
    pattern = _settings()["documents"]["letter_filename"] or "Anschreiben_{role}.docx"
    fields = _filename_fields(spec)
    name = re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), "x")), pattern)
    return name if name.lower().endswith(".docx") else name + ".docx"


def filename_rule():
    """Regex every letter file name must match (the pattern with its fields left open)."""
    pattern = _settings()["documents"]["letter_filename"] or "Anschreiben_{role}.docx"
    if not pattern.lower().endswith(".docx"):
        pattern += ".docx"
    parts = re.split(r"\{\w+\}", pattern)
    return re.compile(r"[A-Za-z0-9_-]+".join(re.escape(p) for p in parts))


def default_output(spec):
    d = dt.date.fromisoformat(spec.get("date") or letter_date())
    return (ROOT / "04_Cover_Letters" / str(d.year) / d.isoformat() / short_name(spec["company"])
            / letter_filename(spec))


# ---------------------------------------------------------------- locators

def _blocks(container):
    """Paragraphs and tables of a body or cell in document order; content controls are transparent."""
    for el in container:
        if el.tag in (W_P, W_TBL):
            yield el
        elif el.tag == W_SDT:
            content = el.find(W_SDT_CONTENT)
            if content is not None:
                yield from _blocks(content)


def _rows(tbl):
    return [[tc for tc in tr if tc.tag == W_TC] for tr in tbl if tr.tag == W_TR]


def walk(container, outer="", cell=None):
    """(locator, paragraph element) for every paragraph in document order, table cells included."""
    pi = ti = 0
    for el in _blocks(container):
        if el.tag == W_P:
            yield (f"{outer}{cell}:{pi}" if cell else f"p:{pi}"), el
            pi += 1
        else:
            for r, row in enumerate(_rows(el)):
                for c, tc in enumerate(row):
                    yield from walk(tc, f"{outer}{cell}/" if cell else "", f"tbl:{ti}:{r}:{c}")
            ti += 1


def resolve(body, loc):
    """The paragraph element a locator names."""
    container, segs = body, str(loc).strip().split("/")
    try:
        for i, seg in enumerate(segs):
            parts, last = seg.split(":"), i == len(segs) - 1
            if parts[0] == "p" and last and len(parts) == 2:
                return [e for e in _blocks(container) if e.tag == W_P][int(parts[1])]
            if parts[0] == "tbl" and (len(parts) == 4 or (last and len(parts) == 5)):
                tbl = [e for e in _blocks(container) if e.tag == W_TBL][int(parts[1])]
                container = _rows(tbl)[int(parts[2])][int(parts[3])]
                if last:
                    return [e for e in _blocks(container) if e.tag == W_P][int(parts[4]) if len(parts) == 5 else 0]
                continue
            break
    except (ValueError, IndexError):
        pass
    raise SystemExit(f"Die Angabe '{loc}' passt nicht zur Vorlage. Bitte `inspect` ausführen und die "
                     "Zuordnung in 01_Config/settings.yaml korrigieren.")


def span(body, first, last):
    """All paragraphs from locator `first` to locator `last` (same parent, inclusive)."""
    a, b = resolve(body, first), resolve(body, last)
    out, el = [], a
    while el is not None:
        if el.tag == W_P:
            out.append(el)
        if el is b or el == b:
            return out
        el = el.getnext()
    raise SystemExit(f"Der Bereich '{first}..{last}' ist in der Vorlage nicht zusammenhängend. "
                     "Bitte `inspect` ausführen und die Zuordnung korrigieren.")


def el_text(p_el):
    """Visible text of a paragraph element (line breaks as newlines)."""
    out = []
    for node in p_el.iter(W_T, qn("w:br"), qn("w:tab")):
        out.append(node.text or "" if node.tag == W_T else "\n" if node.tag == qn("w:br") else "\t")
    return "".join(out)


def _has_text(p_el):
    return bool(el_text(p_el).strip())


def resize(elems, n):
    """Grow or shrink a paragraph range to n text paragraphs and return them. Empty spacer
    paragraphs between them are kept: a new paragraph is a clone of the last one together with the
    spacer in front of it, a removed paragraph takes its spacer with it."""
    content = [e for e in elems if _has_text(e)]
    if not content:
        raise SystemExit("Der zugeordnete Bereich der Vorlage enthält keinen Text. Bitte `inspect` ausführen.")
    while len(content) > max(n, 1):
        victim = content.pop()
        prev = victim.getprevious()
        while prev is not None and prev.tag == W_P and prev != content[-1] and not _has_text(prev):
            before = prev.getprevious()
            prev.getparent().remove(prev)
            prev = before
        victim.getparent().remove(victim)
    while len(content) < n:
        last, spacers = content[-1], []
        prev = last.getprevious()
        while len(content) > 1 and prev is not None and prev.tag == W_P and prev != content[-2] and not _has_text(prev):
            spacers.insert(0, prev)
            prev = prev.getprevious()
        anchor = last
        for s in spacers:
            clone = copy.deepcopy(s)
            anchor.addnext(clone)
            anchor = clone
        clone = copy.deepcopy(last)
        anchor.addnext(clone)
        content.append(clone)
    return content


def locate(document, slots):
    """Slot name -> paragraph element(s) of this document, resolved before anything changes size."""
    body = document.element.body
    found = {k: resolve(body, slots[k]) if slots.get(k) else None for k in SINGLE_SLOTS}
    found["body"] = [e for e in span(body, slots["body_first"], slots["body_last"]) if _has_text(e)]
    found["_body_span"] = span(body, slots["body_first"], slots["body_last"])
    rec = slots.get("recipient")
    found["recipient"], found["_recipient_span"] = [], None
    if rec and ".." in str(rec):
        a, b = (x.strip() for x in str(rec).split("..", 1))
        found["_recipient_span"] = span(body, a, b)
        found["recipient"] = [e for e in found["_recipient_span"] if _has_text(e)]
    elif rec:
        found["recipient"] = [resolve(body, rec)]
    taken = [found[k] for k in SINGLE_SLOTS if found[k] is not None] + found["recipient"]
    if any(any(t == b for b in found["_body_span"]) for t in taken) or len({id(t) for t in taken}) != len(taken):
        raise SystemExit("Zwei Zuordnungen der Anschreiben-Vorlage zeigen auf denselben Absatz. "
                         "Bitte `inspect` ausführen und templates.cover_letter_slots korrigieren.")
    return found


def recipient_lines(spec):
    """Lines of the recipient block; without one in the spec the company name stands alone."""
    rec = spec.get("recipient")
    if isinstance(rec, str):
        rec = rec.split("\n")
    lines = [str(x).strip() for x in (rec or []) if str(x).strip()]
    return lines or [str(spec.get("company") or "").strip()]


def fit(found, spec):
    """Bring body and recipient range to the size the spec needs (structure only, no text)."""
    found["body"] = resize(found["_body_span"], len(spec["paragraphs"]))
    if found["_recipient_span"]:
        found["recipient"] = resize(found["_recipient_span"], len(recipient_lines(spec)))
    return found


# ---------------------------------------------------------------- build

def set_text(p_el, text, lang=None):
    """Replace a paragraph's text, keeping the formatting of its first run."""
    runs = p_el.findall(W_R)
    if runs:
        keep = runs[0]
    else:                                         # text sits in a hyperlink or field wrapper, or there is none
        inner = next(p_el.iter(W_R), None)
        keep = copy.deepcopy(inner) if inner is not None else p_el.makeelement(W_R, {})
    for child in list(p_el):
        if child.tag == qn("w:pPr") or child is keep:
            continue
        p_el.remove(child)  # extra runs, proofErr, bookmarks
    if keep.getparent() is None:
        p_el.append(keep)
    for child in list(keep):
        if child.tag != qn("w:rPr"):
            keep.remove(child)
    for i, line in enumerate(text.split("\n")):   # a line break the user typed stays a line break (Shift+Enter)
        if i:
            keep.append(keep.makeelement(qn("w:br"), {}))
        t = keep.makeelement(W_T, {})
        t.text = line
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        keep.append(t)
    if lang:
        rpr = keep.find(qn("w:rPr"))
        if rpr is None:
            rpr = keep.makeelement(qn("w:rPr"), {})
            keep.insert(0, rpr)
        for old in rpr.findall(qn("w:lang")):
            rpr.remove(old)
        lang_el = rpr.makeelement(qn("w:lang"), {qn("w:val"): LANG_TAG.get(lang, LANG_TAG["en"])})
        rpr.append(lang_el)


def clean_package(path, spec, body_text):
    """Make the .docx look like a letter saved in Word: no generator note, no inherited title,
    no sensitivity label or custom properties from the template, current times and real counts."""
    import random
    from xml.sax.saxutils import escape
    path = Path(path)
    author = escape(_settings()["person"]["full_name"] or "")
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    minutes = random.randint(18, 47)
    modified = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    created = modified - dt.timedelta(minutes=minutes)
    stamp = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    title = escape(path.stem)                               # document title = file name
    words = len(body_text.split())
    chars_nospace = len(re.sub(r"\s", "", body_text))
    out = []
    for info, data in items:
        name = info.filename
        if name == "docProps/custom.xml":
            continue                                   # template sensitivity label and other custom fields
        if name.endswith(".xml") or name.endswith(".rels"):
            text = data.decode("utf-8")
            text = re.sub(r"^<\?xml version='1.0' encoding='UTF-8' standalone='yes'\?>",
                          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', text)
            if name == "[Content_Types].xml":
                text = re.sub(r'<Override PartName="/docProps/custom.xml"[^>]*/>', "", text)
            elif name == "_rels/.rels":
                text = re.sub(r'<Relationship [^>]*Target="docProps/custom.xml"[^>]*/>', "", text)
            elif name == "docProps/core.xml":
                text = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", f"<dc:title>{title}</dc:title>", text, flags=re.S)
                text = re.sub(r"<dc:subject>.*?</dc:subject>", "<dc:subject></dc:subject>", text, flags=re.S)
                text = re.sub(r"<dc:description>.*?</dc:description>|<dc:description/>", "<dc:description></dc:description>", text, flags=re.S)
                text = re.sub(r"<dc:creator>.*?</dc:creator>|<dc:creator/>", lambda m: f"<dc:creator>{author}</dc:creator>", text, flags=re.S)
                text = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>|<cp:lastModifiedBy/>",
                              lambda m: f"<cp:lastModifiedBy>{author}</cp:lastModifiedBy>", text, flags=re.S)
                text = re.sub(r"<cp:revision>.*?</cp:revision>", f"<cp:revision>{random.randint(3, 9)}</cp:revision>", text)
                text = re.sub(r"<cp:lastPrinted>.*?</cp:lastPrinted>", "", text)
                text = re.sub(r"(<dcterms:created[^>]*>).*?(</dcterms:created>)", lambda m: m.group(1) + stamp(created) + m.group(2), text)
                text = re.sub(r"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)", lambda m: m.group(1) + stamp(modified) + m.group(2), text)
            elif name == "docProps/app.xml":
                for tag, val in (("TotalTime", minutes), ("Words", words), ("Characters", chars_nospace),
                                 ("CharactersWithSpaces", len(body_text)), ("Lines", max(1, len(body_text) // 95)),
                                 ("Paragraphs", len(spec["paragraphs"]) + 2), ("Pages", 1)):
                    text = re.sub(rf"<{tag}>\d+</{tag}>", f"<{tag}>{val}</{tag}>", text)
                text = re.sub(r"(<TitlesOfParts><vt:vector[^>]*><vt:lpstr>).*?(</vt:lpstr>)", lambda m: m.group(1) + title + m.group(2), text, flags=re.S)
                text = re.sub(r"<Company>.*?</Company>", "<Company></Company>", text)
            data = text.encode("utf-8")
        out.append((info, data))
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in out:
            info.date_time = created.astimezone().timetuple()[:6]
            z.writestr(info, data)
    tmp.replace(path)


LETTERHEAD = {"<VORNAME NACHNAME>": "full_name", "<STRASSE HAUSNUMMER>": "street", "<PLZ ORT>": "postal_city",
              "<TELEFON>": "phone", "<E-MAIL>": "email"}


def letterhead_open(path):
    """Locators of paragraphs in which the built-in template still holds a letterhead placeholder."""
    document = docx.Document(str(path))
    return [loc for loc, el in walk(document.element.body) if any(k in el_text(el) for k in LETTERHEAD)]


def letterhead(template=None):
    """Fill name and contact line of the built-in template from `person` in the settings. Only
    paragraphs that hold a placeholder change; a contact part without a value is left out."""
    path = template_path(template)
    person = _settings()["person"]
    if not person.get("full_name"):
        raise SystemExit("person.full_name in 01_Config/settings.yaml fehlt; ohne Namen kein Briefkopf.")
    document = docx.Document(str(path))
    changed = []
    for loc, el in walk(document.element.body):
        text = el_text(el)
        if not any(k in text for k in LETTERHEAD):
            continue
        parts = []
        for part in text.split(" · "):
            for token, key in LETTERHEAD.items():
                part = part.replace(token, str(person.get(key) or "").strip())
            if part.strip():
                parts.append(part.strip())
        set_text(el, " · ".join(parts))
        changed.append(loc)
    if changed:
        document.save(str(path))
    return {"template": str(path), "geaendert": changed,
            "fehlt": [k for k in ("street", "postal_city", "phone", "email") if not person.get(k)]}


def build(spec, template=None, slots=None):
    missing = [k for k in ("company", "role", "language", "salutation", "paragraphs") if not spec.get(k)]
    if missing:
        raise SystemExit("Im Auftrag fehlen Angaben: " + ", ".join(missing))
    lang = spec["language"]
    slots, template = slot_map(slots), template_path(template)
    if letterhead_open(template):
        raise SystemExit("Der Briefkopf der Vorlage ist noch nicht ausgefüllt: person in 01_Config/settings.yaml "
                         "füllen, dann `cover_letter.py letterhead` ausführen.")
    out = Path(spec.get("output") or default_output(spec))
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, out)
    document = docx.Document(str(out))
    found = fit(locate(document, slots), spec)

    if found["date"] is not None:
        set_text(found["date"], format_date(letter_date(), lang, slots))
    if found["subject"] is not None:
        set_text(found["subject"], spec["subject"], lang)
    set_text(found["salutation"], spec["salutation"], lang)
    texts = spec["paragraphs"]
    for p_el, text in zip(found["body"], texts):
        set_text(p_el, text, lang)
    if found["closing"] is not None:
        set_text(found["closing"], spec.get("closing") or CLOSING[lang], lang)
    if found["_recipient_span"]:
        for p_el, line in zip(found["recipient"], recipient_lines(spec)):
            set_text(p_el, line, lang)
    elif found["recipient"]:
        set_text(found["recipient"][0], "\n".join(recipient_lines(spec)), lang)
    # the signature paragraph (name) and everything that is no slot stay as in the template
    document.core_properties.title = out.stem
    document.save(str(out))
    clean_package(out, spec, " ".join(texts))
    return out


# ---------------------------------------------------------------- validate

def para_signature(p):
    """Formatting fingerprint used to compare a generated letter with the template."""
    pf = p.paragraph_format
    run = p.runs[0] if p.runs else None
    return (
        p.style.name if p.style is not None else None, p.alignment,
        pf.space_before.pt if pf.space_before is not None else None,
        pf.space_after.pt if pf.space_after is not None else None,
        run.font.name if run else None,
        run.font.size.pt if run and run.font.size else None,
        bool(run.bold) if run else None,
        str(run.font.color.rgb) if run and run.font.color and run.font.color.type else None,
    )


def fingerprint(docx_path):
    """Formatting fingerprint of every paragraph (document order), for comparing letter and template."""
    document = docx.Document(str(docx_path))
    return [para_signature(Paragraph(el, document._body)) for _, el in walk(document.element.body)]


def page_count(docx_path):
    """Real page count if LibreOffice is installed, else None (Word is not started for a check)."""
    try:
        import docs_pdf
        return docs_pdf.page_count(docx_path)
    except Exception:
        return None


# A named contact is addressed by title and last name only ("Sehr geehrte Frau Mustermann,"),
# never by first and last name; without a name the neutral form is used.
SALUTATION_OK = {
    "de": re.compile(r"^(Sehr geehrte Frau|Sehr geehrter Herr) (Dr\. |Prof\. (Dr\. )?)?((von|van|de|zu|vom|von der|van der|de la) )?"
                     r"[A-ZÄÖÜ][\w'-]+,$"
                     r"|^Sehr geehrte Damen und Herren,$"),
    "en": re.compile(r"^Dear (Ms|Mr|Mrs|Dr|Prof)\.? [A-Z][\w'-]+,$|^Dear (Sir or Madam|Hiring Manager|[A-Z][\w&.' -]* (Hiring |Recruiting )?Team),$"),
}
NEUTRAL_SALUTATION = re.compile(r"^(Sehr geehrte Damen und Herren|Dear Sir or Madam|Dear Hiring Manager),$")


def salutation_problem(text, lang):
    """None if the salutation follows the rule, otherwise a short explanation."""
    text = (text or "").strip()
    if SALUTATION_OK.get(lang, SALUTATION_OK["en"]).match(text):
        return None
    if lang == "de":
        return ("Anrede muss 'Sehr geehrte Frau <Nachname>,' / 'Sehr geehrter Herr <Nachname>,' "
                "oder 'Sehr geehrte Damen und Herren,' sein – nie Vor- und Nachname")
    return "salutation must be 'Dear Ms/Mr <Last name>,' or 'Dear <Company> Hiring Team,' – never first and last name"


def style_findings(paragraphs, lang, labels=None):
    """Mandatory humanizer pass: (errors, warnings). `block` findings stop the document."""
    try:
        import humanizer
    except ImportError:
        return ["humanizer.py fehlt in 08_Scripts - die Stilprüfung ist Pflicht und konnte nicht laufen"], []
    errors, warnings = [], []
    for f in humanizer.audit_paragraphs(list(paragraphs), lang):
        i = f.get("paragraph")
        where = ""
        if isinstance(i, int):
            where = (labels[i] if labels and i < len(labels) else f"Absatz {i + 1}") + ": "
        msg = f"{where}{f.get('rule')}: {f.get('hit')!r}" + (f" – {f['hint']}" if f.get("hint") else "")
        (errors if f.get("level") == "block" else warnings).append(msg)
    return errors, warnings


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) >= 30]


def title_problems(body_text):
    """The fixed job title (person.fixed_title) must stand in the body word for word."""
    title = (_settings()["person"]["fixed_title"] or "").strip()
    if not title:
        return []
    if title not in body_text:
        return [f"title '{title}' missing from the letter body"]
    words = title.split()
    if len(words) > 1:                          # the title without its first word is a shortened title
        tail = " ".join(words[1:])
        if re.search(r"(?<!" + re.escape(words[0] + " ") + r")" + re.escape(tail), body_text):
            return [f"wrong title: write '{title}'"]
    return []


def validate(docx_path, spec, template=None, slots=None):
    errors, warnings = [], []
    slots, template = slot_map(slots), template_path(template)
    lang = spec.get("language", "en")
    cfg_doc = _settings()["documents"]
    words_min, words_max = (list(cfg_doc["letter_words"]) + [250, 400])[:2]
    if not zipfile.is_zipfile(docx_path) or Path(docx_path).suffix != ".docx":
        return {"file": str(docx_path), "ok": False, "errors": ["not a real .docx file"], "warnings": [],
                "body_words": 0, "body_paragraphs": 0, "pages": None}
    document = docx.Document(str(docx_path))
    pristine = locate(docx.Document(str(template)), slots)          # the template's own slot texts
    ref = docx.Document(str(template))
    ref_found = fit(locate(ref, slots), spec)                       # template with the letter's structure

    role = {}
    for key in SINGLE_SLOTS:
        if ref_found[key] is not None:
            role[id(ref_found[key])] = key
    for key in ("body", "recipient"):
        for el in ref_found[key]:
            role[id(el)] = key
    new_flat = list(walk(document.element.body))
    ref_flat = list(walk(ref.element.body))
    para = lambda el, d: Paragraph(el, d._body)

    by_role = {"body": [], "recipient": []}
    if len(new_flat) != len(ref_flat):
        errors.append(f"paragraph structure differs from the template ({len(new_flat)} vs {len(ref_flat)} paragraphs)")
    for (loc, el), (_, rel) in zip(new_flat, ref_flat):
        kind = role.get(id(rel))
        p, rp = para(el, document), para(rel, ref)
        if para_signature(p) != para_signature(rp):
            errors.append(f"formatting of paragraph {loc} differs from template: "
                          f"{para_signature(p)} vs {para_signature(rp)}")
        if kind in (None, "signature"):         # head, contact block, signature, spacers: untouched
            if el_text(el) != el_text(rel):
                errors.append(("signature" if kind else f"fixed paragraph {loc}") + " differs from template")
            continue
        if kind in by_role:
            by_role[kind].append(el_text(el))
        else:
            by_role[kind] = el_text(el)
        if not el_text(el).strip():
            errors.append(f"empty {kind} paragraph ({loc})")
        if len(p.runs) != 1:
            errors.append(f"paragraph {loc} has {len(p.runs)} runs (expected 1)")

    body = by_role["body"]
    body_text = " ".join(body)
    written = [by_role.get("subject") or "", by_role.get("salutation") or ""] + body + by_role["recipient"]
    full_text = "\n".join(el_text(el) for _, el in new_flat)
    words = len(body_text.split())

    if words < words_min or words > words_max:
        warnings.append(f"body has {words} words (target {words_min}-{words_max})")
    if PLACEHOLDER.search("\n".join(written)):
        errors.append(f"placeholder left in text: {PLACEHOLDER.search(chr(10).join(written)).group(0)!r}")
    errors += title_problems(body_text)
    if len(set(t.strip() for t in body)) != len(body):
        errors.append("duplicate paragraphs")

    # no leftovers from the template letter's own content
    own = {"subject": el_text(pristine["subject"]) if pristine["subject"] is not None else None,
           "body": [el_text(e) for e in pristine["body"]],
           "recipient": [el_text(e) for e in pristine["recipient"]]}
    own_whole = {t.strip() for t in own["body"] + own["recipient"] + [own["subject"] or ""] if t.strip()}
    for text in [by_role.get("subject") or ""] + body + by_role["recipient"]:
        if text.strip() in own_whole:
            errors.append(f"template text left in letter: {text[:50]!r}")
    own_sentences = {s for t in own["body"] for s in _sentences(t)}
    for s in (s for t in body for s in _sentences(t)):
        if s in own_sentences:
            warnings.append(f"sentence taken over from the template letter: {s[:60]!r}")
    if pristine["salutation"] is not None and by_role.get("salutation") == el_text(pristine["salutation"]) \
            and not NEUTRAL_SALUTATION.match((by_role.get("salutation") or "").strip()):
        errors.append("salutation of the template letter left in letter")
    if "date" in by_role and by_role["date"] != format_date(letter_date(), lang, slots):
        errors.append(f"date wrong: {by_role['date']!r}")
    context = (spec.get("company", "") + " " + spec.get("role", "")).lower()
    leftovers = [str(x) for x in (_settings()["templates"].get("cover_letter_leftovers") or []) if str(x).strip()]
    for leftover in leftovers:
        if leftover in full_text and leftover.lower() not in context:
            errors.append(f"leftover from template letter: {leftover}")
    company_words = (spec.get("company") or "").split()
    if company_words and company_words[0].lower() not in full_text.lower():
        errors.append("company name does not appear in the letter")

    # formatting: page setup and header/footer parts equal the template
    if len(document.sections) != len(ref.sections):
        errors.append("section count differs from template")
    for n, (s, rs) in enumerate(zip(document.sections, ref.sections)):
        for attr in ("page_width", "page_height", "top_margin", "bottom_margin", "left_margin",
                     "right_margin", "header_distance", "footer_distance"):
            if getattr(s, attr) != getattr(rs, attr):
                errors.append(f"section {n} {attr} differs from template")
        if [p.text for p in s.header.paragraphs] != [p.text for p in rs.header.paragraphs]:
            errors.append("header differs from template")
        if [p.text for p in s.footer.paragraphs] != [p.text for p in rs.footer.paragraphs]:
            errors.append("footer differs from template")

    if not filename_rule().fullmatch(Path(docx_path).name):
        errors.append(f"file name must follow documents.letter_filename ({cfg_doc['letter_filename']})")
    with zipfile.ZipFile(docx_path) as z:
        props = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.startswith("docProps/"))
    for trace in ["python-docx", "MSIP_Label"] + leftovers:
        if trace in props:
            errors.append(f"document properties contain '{trace}'")
    problem = salutation_problem(spec.get("salutation"), lang)
    if problem:
        errors.append(problem)
    if by_role.get("salutation") is not None and by_role.get("salutation") != spec.get("salutation"):
        errors.append("salutation in the file differs from the spec")
    if len(spec.get("subject") or "") > 88:
        warnings.append(f"subject has {len(spec['subject'])} chars and may wrap to a second line")
    if slots.get("subject") is None and spec.get("subject"):
        warnings.append("the template has no subject slot - the subject is not in the letter")

    # style rules: the humanizer is mandatory; block findings stop the letter
    h_err, h_warn = style_findings([by_role.get("subject") or ""] + body, lang,
                                   ["Betreff"] + [f"Absatz {i + 1}" for i in range(len(body))])
    errors += h_err
    warnings += h_warn
    for term in review_terms():
        if re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", "\n".join(written)):
            warnings.append(f"mentions '{term}' (not evidenced in CV) - must be a stated gap, not a claim")

    # page count: real if a converter exists, otherwise a length budget against the template
    pages = page_count(docx_path)
    ref_texts = [own["subject"] or ""] + own["body"] + own["recipient"]
    ref_chars = sum(len(t) for t in ref_texts)
    new_chars = sum(len(t) for t in [by_role.get("subject") or ""] + body + by_role["recipient"])
    extra_paras = max(0, len(body) - len(own["body"]))
    breaks = sum(t.count("\n") for t in body)
    budget = ref_chars - extra_paras * 180 - breaks * 90  # extra paragraph ~ two lines, line break ~ one
    max_pages = int(spec.get("max_pages") or cfg_doc["max_pages"] or 1)   # the user may allow a second page
    if pages is not None:
        if pages > max_pages:
            errors.append(f"letter has {pages} pages")
        page_note = f"{pages} (measured)"
    else:
        # The budget only means something if the template is itself a full letter.
        full_template = len(" ".join(own["body"]).split()) >= words_min
        if new_chars > budget and max_pages == 1:
            if full_template:
                errors.append(f"text too long for one page: {new_chars} chars, budget {budget}")
            else:
                warnings.append("Seitenzahl nicht messbar (kein LibreOffice) und die Vorlage ist kürzer als ein "
                                "volles Anschreiben - bitte die Seitenzahl im Dokument selbst prüfen")
        page_note = (f"1 (length budget {new_chars}/{budget} chars; not measured)" if new_chars <= budget
                     else f"not measured ({new_chars} chars, one-page budget {budget}, allowed pages {max_pages})")

    return {"file": str(docx_path), "ok": not errors, "errors": errors, "warnings": warnings,
            "body_words": words, "body_paragraphs": len(body), "pages": page_note}


def template_facts(template=None, slots=None):
    """Numbers a live editor needs for its own length check (all taken from the template)."""
    slots, template = slot_map(slots), template_path(template)
    found = locate(docx.Document(str(template)), slots)
    one = lambda k: el_text(found[k]) if found[k] is not None else ""
    body = [el_text(e) for e in found["body"]]
    return {"ref_chars": sum(len(t) for t in [one("subject"), one("salutation"), one("closing"), one("signature")] + body),
            "ref_paras": len(body) + 4, "head_paras": 0, "body_paras": len(body),
            "signature_chars": len(one("signature")), "words_min": WORDS_MIN, "words_max": WORDS_MAX}


# ---------------------------------------------------------------- inspect / suggest

def browser_slots(template=None, slots=None):
    """The slot map in the shape the dashboard uses to rebuild a letter in the browser (job field
    `letter_slots`): indexes of paragraphs directly in the document body (tables skipped, counted
    from 0), body_end exclusive, date as {paragraph} or {table,row,cell,paragraph}.
    None if this template cannot be expressed that way (a slot other than the date inside a table,
    a date in a nested table). The recipient block has no counterpart there and is left out."""
    slots = slot_map(slots)
    document = docx.Document(str(template_path(template)))
    top = sum(1 for loc, _ in walk(document.element.body) if loc.startswith("p:"))

    def index(loc):
        m = re.fullmatch(r"p:(-?\d+)", str(loc or "").strip())
        if not m:
            return None
        n = int(m.group(1))
        return n + top if n < 0 else n

    out = {}
    for key, name in (("subject", "subject"), ("salutation", "salutation"), ("closing", "closing"),
                      ("body_start", "body_first"), ("body_end", "body_last")):
        if not slots.get(name):
            out[key] = None
            continue
        n = index(slots[name])
        if n is None:
            return None
        out[key] = n + 1 if key == "body_end" else n
    date = str(slots.get("date") or "").strip()
    m = re.fullmatch(r"tbl:(\d+):(\d+):(\d+)(?::(\d+))?", date)
    if not date:
        out["date"] = None
    elif m:
        out["date"] = {"table": int(m.group(1)), "row": int(m.group(2)), "cell": int(m.group(3)),
                       "paragraph": int(m.group(4) or 0)}
    elif index(date) is not None:
        out["date"] = {"paragraph": index(date)}
    else:
        return None
    lang = _settings()["language"]["default"] or "de"
    fmt = slots.get("date_format")
    fmt = (fmt.get(lang) if isinstance(fmt, dict) else fmt) or DATE_FORMAT.get(lang, DATE_FORMAT["en"])
    prefix = fmt.split("{d", 1)[0].split("{m", 1)[0].split("{y", 1)[0]
    out["date_prefix"] = prefix.replace("{city}", _settings()["person"]["city"] or "").lstrip(", ")[:60] \
        if "{" not in prefix.replace("{city}", "") else ""
    out["date_format"] = fmt
    out["remove"] = []
    return out


def inspect(path, extra=None):
    """Numbered list of all paragraphs with locator, text start, style and run count."""
    document = docx.Document(str(path))
    items = []
    for n, (loc, el) in enumerate(walk(document.element.body)):
        p = Paragraph(el, document._body)
        text = el_text(el).replace("\n", " ⏎ ")
        item = {"n": n, "loc": loc, "text": text[:60], "chars": len(text),
                "style": p.style.name if p.style is not None else None, "runs": len(p.runs)}
        if extra:
            item.update(extra(el, p))
        items.append(item)
    boxes = sum(1 for _ in document.element.body.iter(qn("w:txbxContent")))
    out = {"template": str(path), "paragraphs": items}
    if boxes:
        out["hinweis"] = (f"{boxes} Textfeld(er) in der Vorlage: Text in Textfeldern kann nicht ersetzt werden. "
                          "Liegt dort ein Teil, der sich ändern soll, bitte in Word in normalen Text umwandeln.")
    return out


DATE_PATTERNS = [
    (r"(\d{1,2})\.\s?(?:" + "|".join(MONTHS_DE) + r")\s\d{4}", "{d}. {month} {yyyy}", "de"),
    (r"\d{2}\.\d{2}\.\d{4}", "{dd}.{mm}.{yyyy}", "de"),
    (r"\d{1,2}\.\d{1,2}\.\d{4}", "{d}.{m}.{yyyy}", "de"),
    (r"(?:" + "|".join(MONTHS_EN) + r")\s\d{1,2},\s\d{4}", "{month} {d}, {yyyy}", "en"),
    (r"\d{1,2}(?:st|nd|rd|th)?\s(?:" + "|".join(MONTHS_EN) + r")\s\d{4}", "{d} {month} {yyyy}", "en"),
]
SALUTATION_START = re.compile(r"^(Sehr geehrte|Guten Tag|Hallo|Liebe[rs]? |Dear |Hello |To whom)", re.I)
CLOSING_START = re.compile(r"^(Mit freundlichen Grüßen|Mit freundlichem Gruß|Freundliche Grüße|Beste Grüße|Viele Grüße|"
                           r"Herzliche Grüße|Yours sincerely|Yours faithfully|Sincerely|Kind regards|Best regards)", re.I)


def suggest_slots(path):
    """Heuristic slot proposal. It is a starting point the assistant confirms with the user."""
    document = docx.Document(str(path))
    flat = [(loc, el_text(el).strip()) for loc, el in walk(document.element.body)]
    top = [(i, loc, text) for i, (loc, text) in enumerate(flat) if loc.startswith("p:")]
    slots = {k: None for k in ("date", "date_format", "recipient", "subject", "salutation",
                               "body_first", "body_last", "closing", "signature")}
    notes = []
    sal = next(((i, loc) for i, loc, t in top if SALUTATION_START.match(t)), None)
    clo = next(((i, loc) for i, loc, t in reversed(top) if CLOSING_START.match(t)), None)
    lang = "de"
    if sal:
        slots["salutation"] = sal[1]
        lang = "en" if re.match(r"(?i)dear|hello|to whom", flat[sal[0]][1]) else "de"
    else:
        notes.append("Keine Anrede erkannt (z. B. 'Sehr geehrte …' / 'Dear …').")
    if clo:
        slots["closing"] = clo[1]
        after = [loc for i, loc, t in top if i > clo[0] and t]
        if after:
            slots["signature"] = after[0]
    else:
        notes.append("Keine Grußformel erkannt; closing bleibt leer.")
    if sal:
        end = clo[0] if clo else len(flat)
        between = [loc for i, loc, t in top if sal[0] < i < end and t]
        if not clo and len(between) > 1:
            between = between[:-1]                       # without a closing the last line is likely the name
        if between:
            slots["body_first"], slots["body_last"] = between[0], between[-1]
        else:
            notes.append("Zwischen Anrede und Grußformel steht kein Text; body_first/body_last fehlen.")
    for i, (loc, text) in enumerate(flat):
        if len(text) > 70 or (sal and loc.startswith("p:") and i > sal[0]):
            continue
        for pattern, fmt, date_lang in DATE_PATTERNS:
            m = re.search(pattern, text)
            if not m:
                continue
            prefix, suffix = text[:m.start()], text[m.end():]
            if prefix.rstrip().endswith(","):
                prefix = "{city}, "
            own = prefix + fmt + suffix
            other = "en" if date_lang == "de" else "de"
            slots["date"] = loc
            slots["date_format"] = {date_lang: own, other: DATE_FORMAT[other]}
            break
        if slots["date"]:
            break
    if not slots["date"]:
        notes.append("Kein Datum erkannt; date bleibt leer (das Datum der Vorlage bliebe dann stehen).")
    if sal:
        before = [(i, loc, t) for i, loc, t in top if i < sal[0] and t and loc != slots["date"]]
        if before:
            slots["subject"] = before[-1][1]
            # recipient: a run of short lines ending in "postal code + town", closest before the subject
            block, seen_zip = [], False
            for i, loc, t in reversed(before[:-1]):
                is_zip = bool(re.match(r"^(D-|CH-|A-)?\d{4,5}\s+\S+", t))
                if not seen_zip:
                    if is_zip:
                        seen_zip, block = True, [(i, loc)]
                    continue
                if len(t) > 60 or is_zip or (block[0][0] - i) > 1 or "@" in t or len(block) >= 6:
                    break
                block.insert(0, (i, loc))
            if seen_zip and len(block) >= 2:
                slots["recipient"] = f"{block[0][1]}..{block[-1][1]}"
                notes.append("Empfängerblock vermutet – bitte prüfen, dass es nicht die eigene Adresse ist.")
        else:
            notes.append("Kein Betreff erkannt; subject bleibt leer.")
    notes.append(f"Sprache der Vorlage vermutlich: {lang}. Vorschlag bitte mit `inspect` vergleichen und bestätigen lassen.")
    return {"template": str(path), "slots": slots, "hinweise": notes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--spec", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--docx", required=True)
    v.add_argument("--spec", required=True)
    for name in ("inspect", "suggest-slots", "letterhead"):
        i = sub.add_parser(name)
        i.add_argument("--template")
    args = ap.parse_args()
    if args.cmd == "letterhead":
        print(json.dumps(letterhead(args.template), ensure_ascii=False, indent=1))
        return
    if args.cmd in ("inspect", "suggest-slots"):
        path = template_path(args.template)
        result = inspect(path) if args.cmd == "inspect" else suggest_slots(path)
        if args.cmd == "inspect":       # one paragraph per line keeps the list compact
            rows = ",\n  ".join(json.dumps(r, ensure_ascii=False) for r in result.pop("paragraphs"))
            head = json.dumps(result, ensure_ascii=False)[:-1]
            print(f'{head}, "paragraphs": [\n  {rows}\n]}}')
        else:
            print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    spec.setdefault("date", letter_date())
    out = build(spec) if args.cmd == "build" else Path(args.docx)
    result = validate(out, spec)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
