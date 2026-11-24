#!/usr/bin/env python3
"""Job search engine: ATS fetch, deduplication, scoring rules, state, reports.

  fetch            query the official ATS feeds in 01_Config/companies.yaml, write new stubs
  detail           download the full posting text of fetched jobs from their ATS
  mail-candidates  turn exported LinkedIn/XING alert mails into deduplicated candidates
  indeed-mails     the same for Indeed alert mails read through the Gmail connector (JSON via --in)
  dedup            mark jobs in a candidates file as NEW / KNOWN / CHANGED
  finalize         score, build cover letters, update state, write report and packages
  set-status       change the status of one job (e.g. APPLIED, REJECTED)
  check-open       re-check every visible job (ATS APIs, closed wording); --in filters a candidate file
  backlog          jobs found but never evaluated, as candidates
  apply-replies    take over company answers to applications (confirmation, interview, rejection, offer)
  apply-package    collect link, availability and approved files for the form-filling session (local)
  mail-draft       unsent draft (Gmail connector JSON or .eml file) with letter + CV as PDF, for e-mail-only postings
  letters-apply    rebuild the .docx of cover letters the user edited in the dashboard
  dashboard-export write one JSON document per job for the dashboard database, plus the config/ui document
  dashboard-import take over statuses the user set in the dashboard
  run-requests     print the pending "start a run" requests of a dashboard export as one JSON line
  selftest         run the built-in checks

Judgement (reading postings, sub-scores, letter text) comes from Claude following the skill
instructions (SKILL.md of the "jobsuche" skill); everything arithmetic or stateful happens here.
Everything personal (name, places, roles, portals, mail mode) comes from 01_Config/.
"""
import argparse
import base64
import csv
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
import hashlib
import json
import math
import ssl
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings  # noqa: E402
import cover_letter  # noqa: E402

ROOT = settings.ROOT

CONFIG, STATE = ROOT / "01_Config", ROOT / "02_State"
MASTER, TRACKER = STATE / "jobs_master.csv", STATE / "applications_tracker.csv"
REJECTED, COMPANIES = STATE / "rejected_jobs.csv", STATE / "companies_seen.csv"

MASTER_COLS = ["job_key", "status", "first_seen", "last_seen", "report_date", "company", "title",
               "location", "country", "industry", "source", "url", "canonical_url", "job_id",
               "posted_date", "match_score", "match_category", "recommendation", "salary_text",
               "salary_status", "visa", "relocation", "remote", "is_ai_role", "stretch",
               "cover_letter_path", "package_path", "notes", "origin", "score_basis", "seen_on", "portal_url", "alias_keys",
               "open_state", "open_checked", "chance_score"]
TRACKER_COLS = ["date_found", "date_applied", "company", "role", "location", "country", "industry",
                "source", "job_url", "job_id", "match_score", "salary", "salary_currency",
                "salary_status", "visa", "relocation", "remote", "cover_letter_path",
                "application_status", "last_update", "notes", "job_key"]
REJECTED_COLS = ["job_key", "date", "company", "title", "location", "url", "match_score",
                 "rejected_by", "reason"]
EVENTS = STATE / "status_events.csv"           # application status changes read from company mails
EVENT_COLS = ["job_key", "date", "kind", "board", "source", "sender", "subject", "evidence", "recorded", "synced"]
REPLY_BOARD = {"confirmation": "applied", "interview": "interview", "declined": "declined", "offer": "offer"}
REPLY_RANK = {"confirmation": 0, "interview": 1, "offer": 2, "declined": 2}   # a later mail never steps back
COMPANY_COLS = ["company", "first_seen", "last_seen", "jobs_seen", "sources"]

STATUSES = ["NEW", "RECOMMENDED", "REVIEWED", "APPLIED", "REJECTED", "EXPIRED", "DUPLICATE",
            "WATCHLIST"]
USER_STATUSES = {"APPLIED", "REJECTED"}          # set by the user, never overwritten by a run
ACTIVE = {"NEW", "RECOMMENDED", "WATCHLIST"}
DEFAULT_PORTALS = ("linkedin", "xing")


def _portal_ids():
    """Alert sources that get their own dashboard tab: the ids in settings dashboard.portals."""
    try:
        items = settings.load()["dashboard"].get("portals") or []
    except Exception:   # an unreadable settings file is reported by the command that needs it
        items = []
    ids = [str(p.get("id") or "").strip().lower() for p in items if isinstance(p, dict)]
    return tuple(i for i in ids if i) or DEFAULT_PORTALS


PORTALS = _portal_ids()
PORTAL_DAYS = 21                                # how long an unpromoted alert job stays in its tab
LOW_DAYS = 30                                   # scored jobs below the report threshold: tab "Low Scoring Stellen"
CATEGORIES = [(9.0, "EXCEPTIONAL MATCH"), (8.5, "VERY STRONG MATCH"), (8.0, "STRONG MATCH"),
              (7.0, "INTERESTING / WATCHLIST")]
UA = {"User-Agent": "Mozilla/5.0 (compatible; jobsuche-skill/1.0)", "Accept": "application/json"}


# ---------------------------------------------------------------- helpers

class ConfigError(Exception):
    """A missing or unfilled config file or setting; main() prints the message and exits with 2."""


def _clean(node):
    """Placeholders (<...>) read as empty, so no command works with '<ORT 1>' as if it were a value."""
    if isinstance(node, dict):
        return {k: _clean(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_clean(v) for v in node if not settings.is_placeholder(v)]
    return "" if settings.is_placeholder(node) else node


def load_yaml(name):
    path = CONFIG / name
    if not path.exists():
        raise ConfigError(f"Konfigurationsdatei fehlt: 01_Config/{name} (Einrichtung des Skills ausführen).")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"01_Config/{name} ist kein gültiges YAML: {str(e).splitlines()[0]}")
    if not isinstance(data, dict):
        raise ConfigError(f"01_Config/{name} muss Schlüssel enthalten, ist aber leer oder eine Liste.")
    return _clean(data)


def cfg():
    """settings.yaml merged over the defaults (placeholders read as empty)."""
    try:
        return settings.load()
    except yaml.YAMLError as e:
        raise ConfigError(f"01_Config/settings.yaml ist kein gültiges YAML: {str(e).splitlines()[0]}")


def need(value, what):
    """A setting a command cannot work without; empty or still a placeholder -> one German line, exit 2."""
    if value in (None, "", [], {}):
        raise ConfigError(f"Einstellung fehlt: {what}.")
    return value


def load_profile(strict=True):
    """search_profile.yaml; strict=True also demands the parts every search needs."""
    profile = load_yaml("search_profile.yaml")
    if strict:
        need(profile.get("title_include"), "title_include in 01_Config/search_profile.yaml (Suchbegriffe im Titel)")
        need(profile.get("scoring_weights"), "scoring_weights in 01_Config/search_profile.yaml")
        lanes = [v for v in (profile.get("lanes") or {}).values() if isinstance(v, dict)]
        if not any(l.get("country") or l.get("countries") for l in lanes):
            raise ConfigError("Einstellung fehlt: lanes mit country in 01_Config/search_profile.yaml (mindestens eine Suchregion).")
    return profile


def load_rules():
    """salary_rules.yaml with a usable default target."""
    rules = load_yaml("salary_rules.yaml")
    default = rules.get("default") or {}
    try:
        float(default.get("min"))
    except (TypeError, ValueError):
        raise ConfigError("Einstellung fehlt: default.min in 01_Config/salary_rules.yaml (Mindestgehalt als Zahl).")
    need(default.get("currency"), "default.currency in 01_Config/salary_rules.yaml")
    return rules


def lanes_of(profile):
    """The search regions as (name, lane) sorted by priority (1 first)."""
    lanes = [(k, v) for k, v in (profile.get("lanes") or {}).items() if isinstance(v, dict)]
    return sorted(lanes, key=lambda kv: (kv[1].get("priority") or 99, kv[0]))


def lane_countries(profile):
    """ISO codes of every search region, most important first, without repeats."""
    out = []
    for _, lane in lanes_of(profile):
        for c in [lane.get("country")] + list(lane.get("countries") or []):
            c = str(c or "").strip().upper()
            if len(c) == 2 and c not in out:
                out.append(c)
    return out


def lane_places(profile, top_only=False):
    """Lower-case places of the search regions; top_only = only the region(s) with the best priority."""
    lanes = lanes_of(profile)
    if top_only and lanes:
        best = lanes[0][1].get("priority") or 99
        lanes = [kv for kv in lanes if (kv[1].get("priority") or 99) == best]
    out = []
    for _, lane in lanes:
        for place in lane.get("locations") or []:
            place = str(place or "").strip().lower()
            if place and place not in out:
                out.append(place)
    return out


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})


def norm(text):
    """Lower-case, strip accents, legal forms and gender tags; used for identity only."""
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ß", "ss"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\(?\b(m\s*/\s*w\s*/\s*d|w\s*/\s*m\s*/\s*d|f\s*/\s*m\s*/\s*[dx]|m\s*/\s*f\s*/\s*[dx]|"
                  r"all genders|gn)\b\)?", " ", text)
    text = re.sub(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|plc|corp|corporation|group|holding|& co)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def city(location):
    return norm(re.split(r"[,;/|(]", location or "")[0])


KEEP_PARAMS = {"gh_jid", "jobid", "job_id", "id", "jid", "reqid", "pid"}


def canonical_url(url):
    if not url:
        return ""
    p = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() in KEEP_PARAMS]
    path = re.sub(r"/(apply|application)/?$", "", p.path).rstrip("/")
    host = p.netloc.lower().removeprefix("www.")
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(query), ""))


def job_key(job):
    raw = "|".join([norm(job.get("company")), norm(job.get("title")), city(job.get("location"))])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def safe(text):
    return cover_letter.short_name(text or "x")


def fold(text):
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def fmt_de(iso):
    try:
        return dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def today():
    return dt.date.today().isoformat()


try:  # python.org builds on macOS ship without a CA bundle
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()


def http_json(url, body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA)
    if data:
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout, context=SSL_CONTEXT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# Role groups for the dashboard filters, checked in this order; "ai" comes from is_ai_role and
# "other" is the rest. The user's own list is `segments` in search_profile.yaml; this neutral
# default applies while that list is empty.
DEFAULT_SEGMENTS = [
    {"id": "program", "label": "Programm & Produkt", "own_tab": False,
     "pattern": r"program|programme|project|projekt|\bpmo\b|product|produkt|owner|roadmap|delivery"},
    {"id": "transformation", "label": "Transformation & Beratung", "own_tab": False,
     "pattern": r"consult|berat|process|prozess|business (engineer|analyst)|digitali|transformation|strateg"},
]
_SEGMENTS = None


def segments(profile=None):
    """[{id, label, pattern, own_tab}] from search_profile.yaml `segments`, else the neutral default."""
    global _SEGMENTS
    if profile is None and _SEGMENTS is not None:
        return _SEGMENTS
    try:
        source = profile if profile is not None else load_yaml("search_profile.yaml")
    except ConfigError:
        source = {}
    out = []
    for item in source.get("segments") or []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("pattern"):
            continue
        try:
            re.compile(str(item["pattern"]))
        except re.error as e:
            raise ConfigError(f"segments in 01_Config/search_profile.yaml: Muster von '{item['id']}' ist ungültig ({e}).")
        out.append({"id": str(item["id"]).strip().lower(), "label": str(item.get("label") or item["id"]),
                    "pattern": str(item["pattern"]), "own_tab": bool(item.get("own_tab"))})
    out = out or [dict(x) for x in DEFAULT_SEGMENTS]
    if profile is None:
        _SEGMENTS = out
    return out


def segment_of(job, segs=None):
    if job.get("segment"):
        return job["segment"]
    if str(job.get("is_ai_role")) in ("True", "true", "1"):
        return "ai"
    title = (job.get("title") or "").lower()
    for seg in (segments() if segs is None else segs):
        if re.search(seg["pattern"], title):
            return seg["id"]
    return "other"


def html_unescape(text):
    import html
    return html.unescape(text or "")


def category(score):
    for floor, name in CATEGORIES:
        if score >= floor:
            return name
    return "BELOW THRESHOLD"


# Triage reasons that are never valid (skill instructions, triage step): the AI cap as a reason to
# drop a single job (the cap limits the share in the report, it does not screen jobs out) and
# guesses about a posting nobody read. Further patterns: `banned_reason_patterns` in
# search_profile.yaml. A stub screened out for one of these stays NEW.
BANNED_REASONS = [
    re.compile(r"\b(AI|KI)[-/ ]*(/[-/ ]*(AI|KI)[-/ ]*)?Fokus|(AI|KI)-Obergrenze|(AI|KI)-Anteil", re.I),
    re.compile(r"\b(vermutlich|wahrscheinlich|presumably|probably)\b", re.I),
]


def banned_patterns(profile=None):
    """The fixed patterns plus the user's own from search_profile.yaml."""
    try:
        source = profile if profile is not None else load_yaml("search_profile.yaml")
    except ConfigError:
        source = {}
    extra = []
    for pattern in source.get("banned_reason_patterns") or []:
        try:
            extra.append(re.compile(str(pattern), re.I))
        except re.error as e:
            raise ConfigError(f"banned_reason_patterns in 01_Config/search_profile.yaml: '{pattern}' ist ungültig ({e}).")
    return BANNED_REASONS + extra


def banned_reason(reason, patterns=None):
    return any(p.search(reason or "") for p in (BANNED_REASONS if patterns is None else patterns))


def search_documented(note):
    """A pre-score note must list at least three attempts: "Versuche: Workday db: kein Treffer; Karriereseite 404; WebSearch nur Aggregatoren"."""
    n = (note or "").strip()
    tries = [x for x in n[9:].split(";") if x.strip()]
    # "nicht abgefragt" / "nicht versucht" is no attempt: otherwise a run can fill the format without searching
    real = [x for x in tries if not NO_TRY.search(x)]
    return n.lower().startswith("versuche:") and len(real) >= 3


NO_TRY = re.compile(r"nicht (abgefragt|versucht|gesucht|geprüft|aufgerufen)|not (tried|checked|queried)|übersprungen|"
                    r"skipped|nur (titel|alert)", re.I)


def core_role(profile):
    """Pattern of the core role families: an alert pre-score from 6.0 there must be scored from the posting.

    `core_role_terms` in search_profile.yaml; while that is empty the title_include terms count.
    """
    terms = [str(t).strip() for t in (profile.get("core_role_terms") or profile.get("title_include") or []) if str(t).strip()]
    return re.compile("|".join(re.escape(t) for t in terms) if terms else r"(?!x)x", re.I)


def reason_core(reason):
    """The reason without its 'Title (Company, Place):' prefix, so blanket reasons count as equal."""
    r = (reason or "").strip()
    if "): " in r:
        r = r.split("): ", 1)[1]
    return re.sub(r"\s+", " ", r).strip().lower()


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.rows = read_csv(MASTER)
        self.by_key = {r["job_key"]: r for r in self.rows}
        self.by_url = {r["canonical_url"]: r for r in self.rows if r.get("canonical_url")}
        # a job found through an alert keeps the portal link and the alert's own keys as further identities
        self.by_url.update({canonical_url(r["portal_url"]): r for r in self.rows if r.get("portal_url")})
        self.by_alias = {k: r for r in self.rows for k in (r.get("alias_keys") or "").split("|") if k}

    def find(self, job):
        """Return (row, reasons). reasons is non-empty when a known job may resurface."""
        key, url = job_key(job), canonical_url(job.get("url"))
        row = (self.by_url.get(url) or self.by_url.get(canonical_url(job.get("portal_url")))
               or self.by_key.get(key) or self.by_alias.get(key))
        if row is None and job.get("job_id"):
            for r in self.rows:
                if r.get("job_id") == str(job["job_id"]) and norm(r["company"]) == norm(job.get("company")):
                    row = r
                    break
        if row is None:  # same title, city or company written differently
            comp, title, town = norm(job.get("company")), norm(job.get("title")), city(job.get("location"))
            for r in self.rows:
                other, rcomp = city(r["location"]), norm(r["company"])
                same_company = comp and rcomp and (comp.startswith(rcomp) or rcomp.startswith(comp))
                if same_company and norm(r["title"]) == title and town and other \
                        and (town.startswith(other) or other.startswith(town)):
                    row = r      # "Musterstadt" / "Musterstadt am See", "Muster" / "Muster Industrie"
                    break
            if row is None and not town:   # Indeed suggestion mails carry no city: one same-title job at the company
                same = [r for r in self.rows if norm(r["title"]) == title and comp and norm(r["company"])
                        and (comp.startswith(norm(r["company"])) or norm(r["company"]).startswith(comp))]
                row = same[0] if len(same) == 1 else None
        if row is None:
            return None, []
        reasons = []
        new_id, old_id = str(job.get("job_id") or ""), row.get("job_id") or ""
        if new_id and old_id and new_id != old_id:
            reasons.append(f"new requisition id ({old_id} -> {new_id})")
        if job.get("salary_text") and not row.get("salary_text"):
            reasons.append("salary newly published")
        if job.get("visa_text") and not row.get("visa"):
            reasons.append("visa/sponsorship information added")
        if job.get("relocation_text") and not row.get("relocation"):
            reasons.append("relocation information added")
        old_posted, new_posted = row.get("posted_date") or "", job.get("posted_date") or ""
        if old_posted and new_posted and new_posted > old_posted:
            gap = (dt.date.fromisoformat(new_posted) - dt.date.fromisoformat(old_posted)).days
            if gap >= 14:
                reasons.append(f"re-posted ({old_posted} -> {new_posted})")
        if job.get("material_change"):
            reasons.append(f"description changed: {job['material_change']}")
        return row, reasons

    def upsert(self, job, **fields):
        row, _ = self.find(job)
        if row is None:
            row = {c: "" for c in MASTER_COLS}
            row.update(job_key=job_key(job), first_seen=today(), status="NEW")
            self.rows.append(row)
            self.by_key[row["job_key"]] = row
        base = {"company": job.get("company"), "title": job.get("title"),
                "location": job.get("location"), "country": job.get("country"),
                "industry": job.get("industry"), "source": job.get("source"),
                "url": job.get("url"), "canonical_url": canonical_url(job.get("url")),
                "job_id": job.get("job_id"), "posted_date": job.get("posted_date"),
                "salary_text": job.get("salary_text"), "visa": job.get("visa_text"),
                "relocation": job.get("relocation_text"), "remote": job.get("remote"),
                "portal_url": job.get("portal_url"),
                "alias_keys": "|".join(sorted(set(filter(None, (row.get("alias_keys") or "").split("|")))
                                              | set(job.get("alias_keys") or [])))}
        for k, v in {**base, **fields}.items():
            if v not in (None, ""):
                row[k] = v
        row["last_seen"] = today()
        if row["canonical_url"]:
            self.by_url[row["canonical_url"]] = row
        if row.get("portal_url"):
            self.by_url[canonical_url(row["portal_url"])] = row
        for k in (row.get("alias_keys") or "").split("|"):
            if k:
                self.by_alias[k] = row
        return row

    def save(self):
        write_csv(MASTER, self.rows, MASTER_COLS)


def touch_companies(jobs):
    rows = {r["company"]: r for r in read_csv(COMPANIES)}
    for j in jobs:
        name = j.get("company") or ""
        if not name:
            continue
        r = rows.setdefault(name, {"company": name, "first_seen": today(), "jobs_seen": "0", "sources": ""})
        r["last_seen"] = today()
        r["jobs_seen"] = str(int(r.get("jobs_seen") or 0) + 1)
        sources = set(filter(None, (r.get("sources") or "").split("|"))) | {j.get("source") or ""}
        r["sources"] = "|".join(sorted(filter(None, sources)))
    write_csv(COMPANIES, sorted(rows.values(), key=lambda r: r["company"].lower()), COMPANY_COLS)


# ---------------------------------------------------------------- ATS fetch

def _posted_days(text):
    """Workday 'Posted Today' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago' -> ISO date."""
    t = (text or "").lower()
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    else:
        m = re.search(r"(\d+)\+?\s*day", t)
        if not m:
            return None
        days = int(m.group(1))
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def fetch_greenhouse(c):
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{c['board']}/jobs")
    return [{"title": j["title"].strip(), "location": (j.get("location") or {}).get("name", ""),
             "url": j["absolute_url"], "job_id": str(j["id"]), "source": "ats_greenhouse",
             "posted_date": (j.get("first_published") or j.get("updated_at") or "")[:10] or None}
            for j in data.get("jobs", [])], True


def fetch_ashby(c):
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['board']}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        out.append({"title": j["title"].strip(), "location": "; ".join(filter(None, locs)),
                    "url": j.get("jobUrl"), "apply_url": j.get("applyUrl"), "job_id": j.get("id"),
                    "source": "ats_ashby", "posted_date": (j.get("publishedAt") or "")[:10] or None,
                    "remote": (j.get("workplaceType") or "").lower() or None})
    return out, True


WORKDAY_COUNTRY = {"NL": "9696868b09c64d52a62ee13b052383cc", "PL": "131d5ac7e3ee4d7b962bdc96e498e412",
                   "DE": "dcc5b7608d8644b3a93716604e78e995", "CH": "187134fccb084a0ea9b4b95f23890dbe",
                   "AT": "d004c0d1a6c84511ab048669fcdf9fd7", "CA": "a30a87ed25634629aa6c3958aa2b91ea",
                   "AU": "d903bb3fedad45039383f6de334ad4db", "CN": "6cb77610a8a543aea2d6bc10457e35d4"}
# Workday's country ids are the same on every tenant; further ones: `workday_country_ids` in companies.yaml.
# Country names as career sites write them (German and English), for feeds that filter by name.
COUNTRY_NAMES = {"DE": ["Deutschland", "Germany"], "AT": ["Österreich", "Austria"], "CH": ["Schweiz", "Switzerland"],
                 "NL": ["Niederlande", "Netherlands"], "BE": ["Belgien", "Belgium"], "LU": ["Luxemburg", "Luxembourg"],
                 "FR": ["Frankreich", "France"], "IT": ["Italien", "Italy"], "ES": ["Spanien", "Spain"],
                 "PT": ["Portugal"], "DK": ["Dänemark", "Denmark"], "SE": ["Schweden", "Sweden"],
                 "NO": ["Norwegen", "Norway"], "FI": ["Finnland", "Finland"], "PL": ["Polen", "Poland"],
                 "CZ": ["Tschechien", "Czech Republic", "Czechia"], "IE": ["Irland", "Ireland"],
                 "GB": ["Vereinigtes Königreich", "Großbritannien", "United Kingdom"],
                 "US": ["USA", "Vereinigte Staaten", "United States"], "CA": ["Kanada", "Canada"],
                 "AU": ["Australien", "Australia"], "NZ": ["Neuseeland", "New Zealand"], "CN": ["China"],
                 "JP": ["Japan"], "SG": ["Singapur", "Singapore"], "AE": ["Vereinigte Arabische Emirate", "United Arab Emirates"]}


def feed_defaults(c, profile, companies_cfg):
    """A feed entry completed from the search profile where it names no countries or places of its own."""
    c = dict(c)
    countries = lane_countries(profile)
    kind = c.get("type")
    if kind == "workday":
        c.setdefault("countries", countries)
        c["_country_ids"] = {**WORKDAY_COUNTRY, **{str(k).upper(): str(v) for k, v in
                                                   (companies_cfg.get("workday_country_ids") or {}).items()}}
    elif kind == "beesite" and not c.get("country_names"):
        c["country_names"] = [n for cc in countries for n in COUNTRY_NAMES.get(cc, [])]
    elif kind == "successfactors" and not c.get("locations"):
        c["locations"] = [str(x).lower() for x in profile.get("successfactors_cities") or []] or lane_places(profile)
    elif kind == "eightfold" and not c.get("location"):
        c["location"] = next((COUNTRY_NAMES[cc][-1] for cc in countries if cc in COUNTRY_NAMES), "")
    return c


def fetch_workday(c):
    base = f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}/jobs"
    fkey = c.get("country_facet", "locationCountry")   # some tenants call the facet "Country"
    ids = c.get("_country_ids") or WORKDAY_COUNTRY
    unknown = [x for x in c.get("countries") or [] if str(x).upper() not in ids]
    if unknown:
        raise ValueError(f"Workday-Länder-ID fehlt für {', '.join(map(str, unknown))} "
                         f"(workday_country_ids in 01_Config/companies.yaml ergänzen)")
    facets = {fkey: [ids[str(x).upper()] for x in c.get("countries") or []]}
    seen, out = set(), []
    places = [x.lower() for x in c.get("locations", [])]
    for q in c.get("queries", [""]):
        for page in range(c.get("max_pages", 5)):
            body = {"limit": 20, "offset": page * 20, "searchText": q,
                    "appliedFacets": facets if facets[fkey] else {}}
            try:
                data = http_json(base, body)
            except urllib.error.HTTPError as e:
                if e.code != 400 or not body["appliedFacets"]:
                    raise
                facets = {fkey: []}   # tenant has no country facet: filter by location text below
                body["appliedFacets"] = {}
                data = http_json(base, body)
            posts = data.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                loc = (j.get("locationsText") or "").lower()
                if places and not facets[fkey] and not any(x in loc for x in places) and "locations" not in loc:
                    continue
                req = next((b for b in j.get("bulletFields") or [] if re.match(r"^[A-Z]{1,4}[-_]?\d{4,}", b)),
                           path.rsplit("_", 1)[-1])
                out.append({"title": (j.get("title") or "").strip(), "location": j.get("locationsText", ""),
                            "url": f"https://{c['host']}/{c['site']}{path}", "job_id": req,
                            "source": "ats_workday", "posted_date": _posted_days(j.get("postedOn"))})
            if len(posts) < 20:
                break
    return out, False


def fetch_smartrecruiters(c):
    """The public postings API ignores free-text search, so page through the country feed."""
    out, offset = [], 0
    while offset < c.get("max_results", 3000):
        params = {"limit": 100, "offset": offset}
        if c.get("country"):
            params["country"] = c["country"]
        data = http_json(f"https://api.smartrecruiters.com/v1/companies/{c['board']}/postings?"
                         + urllib.parse.urlencode(params))
        content = data.get("content", [])
        for j in content:
            loc = j.get("location") or {}
            out.append({"title": j["name"].strip(),
                        "location": ", ".join(filter(None, [loc.get("city"), (loc.get("country") or "").upper()])),
                        "url": f"https://jobs.smartrecruiters.com/{c['board']}/{j['id']}",
                        "job_id": j.get("refNumber") or j["id"], "source": "ats_smartrecruiters",
                        "posted_date": (j.get("releasedDate") or "")[:10] or None})
        offset += 100
        if len(content) < 100:
            break
    return out, False


def strip_html(html):
    import html as htmllib
    text = re.sub(r"(?i)<(br|/p|/li|/h\d|/div|/tr)[^>]*>", "\n", htmllib.unescape(html or ""))
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def fetch_detail(row):
    """Full posting text from the ATS that listed the job. Returns None for other sources."""
    url, src = row["url"], row["source"]
    if src == "ats_greenhouse":
        m = re.search(r"boards?/([^/]+)/jobs/(\d+)|gh_jid=(\d+)", url)
        board = next(c["board"] for c in load_yaml("companies.yaml")["ats"]
                     if c["type"] == "greenhouse" and norm(c["company"]) == norm(row["company"]))
        d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{row['job_id']}")
        return strip_html(d.get("content"))
    if src == "ats_ashby":
        board = next(c["board"] for c in load_yaml("companies.yaml")["ats"]
                     if c["type"] == "ashby" and norm(c["company"]) == norm(row["company"]))
        for j in http_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")["jobs"]:
            if j.get("id") == row["job_id"]:
                comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
                return (f"Compensation: {comp}\n\n" if comp else "") + (j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")))
        return None
    if src == "ats_workday":
        p = urllib.parse.urlsplit(url)
        site, path = p.path.lstrip("/").split("/", 1)
        tenant = p.netloc.split(".")[0]
        info = http_json(f"https://{p.netloc}/wday/cxs/{tenant}/{site}/{path}")["jobPostingInfo"]
        head = "\n".join(f"{k}: {info.get(k)}" for k in ("title", "location", "additionalLocations", "startDate",
                                                           "timeType", "remoteType", "jobReqId") if info.get(k))
        return head + "\n\n" + strip_html(info.get("jobDescription"))
    if src == "ats_smartrecruiters":
        board, pid = url.rstrip("/").split("/")[-2:]
        d = http_json(f"https://api.smartrecruiters.com/v1/companies/{board}/postings/{pid}")
        sections = (d.get("jobAd") or {}).get("sections") or {}
        return "\n\n".join(f"{v.get('title')}\n{strip_html(v.get('text'))}" for v in sections.values() if v.get("text"))
    return None


def cmd_detail(args):
    state = State()
    out = ROOT / "07_Logs" / "runs" / args.date / "details"
    out.mkdir(parents=True, exist_ok=True)
    for key in args.keys.split(","):
        row = state.by_key.get(key.strip())
        if row is None:
            print(f"{key}: unknown key")
            continue
        try:
            text = fetch_detail(row)
        except (urllib.error.URLError, TimeoutError, KeyError, StopIteration, ValueError) as e:
            text = None
            print(f"{key}: {type(e).__name__}: {e}")
        if text:
            f = out / f"{key}.txt"
            f.write_text(f"{row['company']} – {row['title']}\n{row['location']} · posted {row['posted_date']}\n"
                         f"{row['url']}\n\n{text}", encoding="utf-8")
            print(f"{key}: {len(text)} chars -> {f.relative_to(ROOT)}")
        elif text is None:
            print(f"{key}: no ATS detail for source {row['source']} - open {row['url']}")


def http_text(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers={**UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
        return r.read().decode("utf-8", "replace")


def fetch_beesite(c):
    """BeeSite career portals: one JSON search, 100 per page; kept are jobs in the entry's country_names."""
    out, first = [], 1
    crit = [{"CriterionName": k, "CriterionValue": v} for k, v in (c.get("criteria") or {}).items()]
    countries = set(c.get("country_names") or [])   # empty: no country filter
    while True:
        data = {"LanguageCode": "DE", "SearchParameters": {"FirstItem": first, "CountItem": 100,
                "MatchedObjectDescriptor": ["PositionTitle", "PositionLocation.CityName", "PositionLocation.CountryName",
                                            "PositionURI", "PositionID", "PublicationStartDate", "OrganizationName"]},
                "SearchCriteria": crit}
        res = http_json(c["base"].rstrip("/") + "/search/?" + urllib.parse.urlencode({"data": json.dumps(data)}))["SearchResult"]
        items = res.get("SearchResultItems") or []
        for it in items:
            m = it["MatchedObjectDescriptor"]
            locs = m.get("PositionLocation") or [{}]
            if countries and not any(l.get("CountryName") in countries for l in locs):
                continue
            city = ", ".join(dict.fromkeys(l.get("CityName") or "" for l in locs
                                           if not countries or l.get("CountryName") in countries))
            out.append({"title": (m.get("PositionTitle") or "").strip(), "location": city, "url": m.get("PositionURI"),
                        "job_id": m.get("PositionID"), "source": "ats_beesite",
                        "posted_date": (m.get("PublicationStartDate") or "")[:10] or None})
        first += 100
        if not items or first > res.get("SearchResultCountAll", 0) or first > c.get("max_results", 4000):
            break
    return out, False


def fetch_successfactors(c):
    """SAP SuccessFactors career sites: /sitemap.xml lists every job as .../job/{City}-{Title}-{zip}/{id}/."""
    xml = http_text(c["base"].rstrip("/") + "/sitemap.xml")
    # places: the entry's own `locations`, else successfactors_cities / the lane places of the search profile
    cities = [str(x).lower() for x in c.get("locations") or []]
    brands = [b.lower() for b in c.get("brands", [])]
    out = []
    if "<item>" in xml:      # some sites serve an RSS job feed here instead of a sitemap
        countries = [x.upper() for x in c.get("countries", [])]
        for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
            tag = lambda t: html_unescape((re.search(rf"<{t}>([^<]*)</{t}>", it) or [None, ""])[1]).strip()
            loc, link = tag("g:location"), tag("link")
            cc = loc.rsplit(",", 1)[-1].strip().upper() if "," in loc else ""
            if countries and cc not in countries:
                continue
            if not countries and not any(x in loc.lower() for x in cities):
                continue
            title = re.sub(r"\s*\([^()]*\)\s*$", "", tag("title"))
            out.append({"title": title, "location": loc, "url": link, "job_id": tag("g:id"),
                        "source": "ats_successfactors", "posted_date": None})
        return out, False
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
        loc = html_unescape(loc)   # sitemaps escape "&" as "&amp;"
        m = re.search(r"/([^/]+)/job/([^/]+)/(\d+)/?$", loc) or re.search(r"()/job/([^/]+)/(\d+)/?$", loc)
        if not m:
            continue
        brand, slug, jid = m.group(1).lower(), urllib.parse.unquote(m.group(2)), m.group(3)
        if brands and brand not in brands:
            continue
        low = slug.lower()
        city = next((x for x in cities if low.startswith(x.replace(" ", "-") + "-")), None)
        if not city and c.get("any_city"):   # sites whose job URLs carry no city
            city = ""
        if city is None:
            continue
        title = slug[len(city):].strip("-")
        title = re.sub(r"-[A-Z]{0,3}-?\d[\d-]{3,}$", "", title)        # trailing zip / reference
        title = html_unescape(title).replace("_", " ")
        title = re.sub(r"\s+", " ", title.replace("-", " ")).strip()
        out.append({"title": title, "location": slug[:len(city)], "url": loc, "job_id": jid,
                    "source": "ats_successfactors", "posted_date": None})
    return out, False


def fetch_eightfold(c):
    """Eightfold career sites: /api/pcsx/search, 10 per call."""
    out, start = [], 0
    while start < c.get("max_results", 400):
        q = {"domain": c["domain"], "start": start}
        if c.get("location"):
            q["location"] = c["location"]
        data = http_json(f"https://{c['host']}/api/pcsx/search?" + urllib.parse.urlencode(q)).get("data") or {}
        pos = data.get("positions") or []
        for j in pos:
            out.append({"title": (j.get("name") or "").strip(), "location": "; ".join(j.get("locations") or []),
                        "url": f"https://{c['host']}/careers/job/{j['id']}", "job_id": j.get("displayJobId") or j["id"],
                        "source": "ats_eightfold",
                        "posted_date": dt.date.fromtimestamp(j["postedTs"]).isoformat() if j.get("postedTs") else None})
        start += len(pos) or 10
        if not pos or start >= data.get("count", 0):
            break
    return out, False


def fetch_adp(c):
    """ADP MyJobs: job-requisitions JSON with the org id header."""
    out, skip = [], 0
    while skip < c.get("max_results", 1000):
        url = f"https://myjobs.adp.com/public/staffing/v1/job-requisitions?$top=100&$skip={skip}"
        data = http_json_headers(url, {"orgoid": c["orgoid"]})
        reqs = data.get("jobRequisitions") or []
        for r in reqs:
            locs = r.get("requisitionLocations") or []
            wanted = c.get("countries") or ([c["country"]] if c.get("country") else [])
            if wanted and not any((l.get("address") or {}).get("country", {}).get("codeValue") in wanted for l in locs):
                continue
            city = ", ".join(dict.fromkeys((l.get("address") or {}).get("cityName", "") for l in locs))
            out.append({"title": (r.get("jobTitle") or "").strip(), "location": city,
                        "url": f"https://myjobs.adp.com/{c['site']}/cx/job-details?reqId={r['reqId']}",
                        "job_id": r.get("clientRequisitionID") or r["reqId"], "source": "ats_adp", "posted_date": None})
        skip += 100
        if len(reqs) < 100:
            break
    return out, False


def http_json_headers(url, headers):
    req = urllib.request.Request(url, headers={**UA, **headers})
    with urllib.request.urlopen(req, timeout=40, context=SSL_CONTEXT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_dvinci(c):
    """d.vinci: /jobPublication/list.json – no location field, the title often names it."""
    out = []
    for j in http_json(c["base"].rstrip("/") + "/jobPublication/list.json"):
        out.append({"title": (j.get("position") or "").strip(), "location": c.get("default_location", ""),
                    "url": j.get("jobPublicationURL"), "job_id": j.get("id"), "source": "ats_dvinci",
                    "posted_date": (j.get("startDate") or "")[:10] or None})
    return out, False


def fetch_recruitee(c):
    """Recruitee: /api/offers/."""
    out = []
    for j in http_json(c["base"].rstrip("/") + "/api/offers/").get("offers", []):
        locs = j.get("locations") or [{}]
        city = ", ".join(dict.fromkeys((l.get("city") or "") for l in locs)) or j.get("city") or ""
        country = ", ".join(dict.fromkeys((l.get("country_code") or l.get("country") or "") for l in locs))
        out.append({"title": (j.get("title") or j.get("sharing_title") or "").strip(),
                    "location": ", ".join(filter(None, [city, country])), "url": j.get("careers_url"),
                    "job_id": j.get("id"), "source": "ats_recruitee", "posted_date": (j.get("published_at") or j.get("created_at") or "")[:10] or None})
    return out, False


ADAPTERS = {"greenhouse": fetch_greenhouse, "ashby": fetch_ashby, "workday": fetch_workday,
            "smartrecruiters": fetch_smartrecruiters, "beesite": fetch_beesite, "successfactors": fetch_successfactors,
            "eightfold": fetch_eightfold, "adp": fetch_adp, "dvinci": fetch_dvinci, "recruitee": fetch_recruitee}


def title_ok(title, profile, exclusions, company=None):
    """A feed may bring its own title terms (an employer searched for a different role family): they are
    added to the profile's terms, and its own exclusions are added to the global ones."""
    t = title.lower()
    company = company or {}
    if any(x in t for x in (profile.get("title_exclude") or []) + (exclusions.get("title_terms") or [])
           + (company.get("title_exclude") or [])):
        return False
    return any(x in t for x in (profile.get("title_include") or []) + (company.get("title_include") or []))


def cmd_fetch(args):
    profile, exclusions = load_profile(), load_yaml("exclusions.yaml")
    companies_cfg = load_yaml("companies.yaml")
    feeds_cfg = [c for c in companies_cfg.get("ats") or [] if isinstance(c, dict) and c.get("company")]
    state, stubs, problems, counts, emitted = State(), [], [], {}, set()
    for c in feeds_cfg:
        if c.get("type") not in ADAPTERS:
            problems.append(f"{c['company']}: unbekannter Typ '{c.get('type')}' (möglich: {', '.join(sorted(ADAPTERS))})")
            continue
        try:
            jobs, full_feed = ADAPTERS[c["type"]](feed_defaults(c, profile, companies_cfg))
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as e:
            problems.append(f"{c['company']}: {type(e).__name__}: {e}")
            continue
        locations = [str(x).lower() for x in c.get("locations") or []]
        kept = []
        for j in jobs:
            j.update(company=c["company"], industry=c.get("industry"))
            loc = j["location"].lower()
            multi = c.get("multi_location_ok") and re.match(r"\d+ locations$", loc)   # Workday "2 Locations"
            if locations and not any(x in loc for x in locations) and not multi:
                continue
            if title_ok(j["title"], profile, exclusions, c):
                if c.get("segment"):
                    j["segment"] = c["segment"]
                kept.append(j)
        counts[c["company"]] = {"feed": len(jobs), "matching": len(kept)}
        if full_feed and jobs:  # a watched job that left a complete feed is closed
            live = {canonical_url(j["url"]) for j in jobs}
            for r in state.rows:
                if r["status"] in ACTIVE and r["source"] == jobs[0]["source"] \
                        and norm(r["company"]) == norm(c["company"]) and r["canonical_url"] not in live:
                    r["status"], r["notes"] = "EXPIRED", f"left the ATS feed on {today()}"
        for j in kept:
            if job_key(j) in emitted:      # same title and city posted twice by the employer
                continue
            emitted.add(job_key(j))
            row, reasons = state.find(j)
            if row is None:
                state.upsert(j)
                stubs.append({**j, "job_key": job_key(j), "dedup": "NEW"})
            elif reasons and row["status"] not in USER_STATUSES:
                stubs.append({**j, "job_key": row["job_key"], "dedup": "CHANGED", "change": reasons})
                state.upsert(j)
            elif row["status"] == "NEW":  # found earlier, never assessed
                stubs.append({**j, "job_key": row["job_key"], "dedup": "BACKLOG"})
                state.upsert(j)
            else:
                row["last_seen"] = today()
    state.save()
    touch_companies(stubs)
    stubs.sort(key=lambda j: j.get("posted_date") or "", reverse=True)
    out = ROOT / "07_Logs" / "runs" / args.date / "ats_candidates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    fresh = len(stubs)
    if out.exists():  # a second fetch on the same day adds to the first one instead of replacing it
        earlier = json.loads(out.read_text(encoding="utf-8")).get("jobs", [])
        have = {j["job_key"] for j in stubs}
        stubs += [j for j in earlier if j["job_key"] not in have]
        stubs.sort(key=lambda j: j.get("posted_date") or "", reverse=True)
    out.write_text(json.dumps({"date": args.date, "counts": counts, "problems": problems,
                               "jobs": stubs}, ensure_ascii=False, indent=1), encoding="utf-8")
    feeds = len(feeds_cfg)
    print(json.dumps({"written": str(out), "new_or_changed": fresh, "in_file_today": len(stubs),
                      "feeds_ok": feeds - len(problems), "feeds_failed": len(problems),
                      "network_blocked": bool(problems) and len(problems) == feeds,
                      "counts": counts, "problems": problems}, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- dedup

def cmd_dedup(args):
    data = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    jobs = data["jobs"] if isinstance(data, dict) else data
    state, seen, summary = State(), {}, {"NEW": 0, "KNOWN": 0, "CHANGED": 0, "DUPLICATE": 0}
    for j in jobs:
        key = job_key(j)
        j["job_key"] = key
        ident = canonical_url(j.get("url")) or key
        if key in seen or ident in seen.values():
            j["dedup"] = "DUPLICATE"
        else:
            row, reasons = state.find(j)
            if row is None or row["status"] == "NEW":
                j["dedup"] = "NEW"
            elif reasons and row["status"] not in USER_STATUSES:
                j["dedup"], j["change"] = "CHANGED", reasons
            else:
                j["dedup"], j["known_status"], j["first_seen"] = "KNOWN", row["status"], row["first_seen"]
            seen[key] = ident
        summary[j["dedup"]] += 1
    out = Path(args.out or args.infile)
    payload = {**data, "jobs": jobs} if isinstance(data, dict) else jobs
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"file": str(out), **summary,
                      "skip": [f"{j['company']} – {j['title']} ({j.get('known_status', j['dedup'])})"
                               for j in jobs if j["dedup"] in ("KNOWN", "DUPLICATE")]},
                     ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- alert mails

# ---- Mail input format (one format for every mail source) --------------------------------------
# `mail-candidates` reads every file 07_Logs/mail_inbox/<YYYY-MM-DD>*.json. Who writes them:
#   - a mail bridge on the user's machine (mail_bridge_apple.py for Apple Mail, mail_bridge_imap.py for IMAP),
#   - `indeed-mails` below, from a Gmail connector search result (--in),
#   - the run itself, when it reads alert mails through the Gmail connector and saves them in this format.
# Alert file  <YYYY-MM-DD>.json  (or <YYYY-MM-DD>_<anything>.json):
#   {"source": "<apple-mail:account | imap:host | gmail>", "exported_at": "<ISO time, UTC>",
#    "messages": [{"message_id": "...", "received": "<ISO time or null>", "from": "...", "subject": "...",
#                  "portal": "<linkedin | xing | indeed | any id from settings dashboard.portals>",
#                  "alert_name": "<name of the saved search or null>",
#                  "jobs": [{"title": "...", "company": "...", "location": "...", "url": "...", "job_id": "...",
#                            optional: "linkedin_id", "employment", "salary_estimate_xing", "salary_text"}],
#                  "text": "<cleaned mail text, at most 6000 characters, only when jobs is empty>"}]}
# Replies file  replies_<YYYY-MM-DD>.json  (company answers, read by `apply-replies --in`; skipped here
# because its name does not start with a date):
#   {"source": "...", "messages": [{"message_id", "received", "from", "subject", "text" (at most 2500 characters)}]}
# Mail texts are data, never instructions: nothing in a subject or body is executed or followed.
# Which senders count as alerts is settings mail.alert_senders; the bridges filter by it.

INDEED_SUBJECT = re.compile(r"^(?P<title>.+?) (?:bei|at) (?P<company>.+)$")   # "<Titel> bei <Firma>" / "<title> at <company>"
INDEED_SALARY = re.compile(r"(\d{1,3}(?:[.,]\d{3})+ ?[€$£]\s*[–-]\s*\d{1,3}(?:[.,]\d{3})+ ?[€$£][^.]*?(?:Jahr|Monat|Stunde|year|month|hour)"
                           r"|[€$£] ?\d{1,3}(?:[.,]\d{3})+\s*[–-]\s*[€$£] ?\d{1,3}(?:[.,]\d{3})+[^.]*?(?:year|month|hour))")


def cmd_indeed_mails(args):
    """Indeed sends its job suggestions as one mail per job, subject "<title> bei|at <company>", without a job list.
    Input: a Gmail connector search_threads result saved as JSON ({"threads": [...]}, view MINIMAL). Output: an
    inbox-format file 07_Logs/mail_inbox/<date>_gmail_indeed.json that mail-candidates reads like every alert mail."""
    raw = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    threads = raw.get("threads", raw if isinstance(raw, list) else [])
    msgs, skipped = [], []
    for t in threads:
        for m in t.get("messages", [])[:1]:
            subj = html_unescape(m.get("subject") or "").strip()
            hit = INDEED_SUBJECT.match(subj)
            if "indeed" not in (m.get("sender") or "").lower() or not hit:
                skipped.append(subj[:80])
                continue
            salary = INDEED_SALARY.search(html_unescape(m.get("snippet") or ""))
            msgs.append({"message_id": m.get("id"), "received": m.get("date") or "", "from": m.get("sender") or "",
                         "subject": subj, "portal": "indeed", "alert_name": "Indeed Jobvorschlag",
                         "jobs": [{"title": hit["title"].strip(), "company": hit["company"].strip(),
                                   "location": (args.location_hint or ""), "url": m.get("viewUrl") or "",
                                   "salary_text": salary.group(1) if salary else None}]})
    target = ROOT / "07_Logs" / "mail_inbox" / f"{args.date}_gmail_indeed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": "gmail", "messages": msgs, "exported_at": dt.datetime.now(
        dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(target.relative_to(ROOT)), "jobs": len(msgs), "skipped": skipped}, ensure_ascii=False, indent=1))


def cmd_mail_candidates(args):
    """Turn the exported alert mails (07_Logs/mail_inbox) into deduplicated candidates."""
    days = args.days or int(cfg()["mail"].get("days_back") or 2)
    since = (dt.date.fromisoformat(args.date) - dt.timedelta(days=days - 1)).isoformat()
    profile, exclusions = load_profile(), load_yaml("exclusions.yaml")
    prefer = lane_places(profile, top_only=True)      # of several cities of one posting, the nearest region wins
    priority_places = [str(x).lower() for x in profile.get("priority_places") or []] or prefer
    groups, files = {}, []
    for f in sorted((ROOT / "07_Logs" / "mail_inbox").glob("*.json")):
        if not (f.stem[:4].isdigit() and since <= f.stem[:10] <= args.date):   # <date>.json, <date>_gmail_indeed.json
            continue
        files.append(f.name)
        for m in json.loads(f.read_text(encoding="utf-8")).get("messages", []):
            if not m.get("portal"):
                continue
            for j in m.get("jobs") or []:
                if not j.get("title") or not j.get("company"):
                    continue
                job = {"title": html_unescape(j["title"]), "company": html_unescape(j["company"]),
                       "location": j.get("location") or "", "origin": m["portal"], "alert_name": m.get("alert_name"),
                       "portal_url": j.get("url") or "", "url": j.get("url") or "",
                       "salary_estimate_xing": j.get("salary_estimate_xing"), "salary_text": j.get("salary_text"),
                       "source": f"alert_{m['portal']}",
                       "received": (m.get("received") or "")[:10]}
                groups.setdefault((norm(job["company"]).split(" ")[0], norm(job["title"])), []).append(job)
    state, out, summary = State(), [], {"NEW": 0, "KNOWN": 0}
    for jobs in groups.values():   # one posting advertised for several cities counts once
        rank = lambda j: next((i for i, x in enumerate(prefer) if x in j["location"].lower()), len(prefer))
        jobs.sort(key=rank)
        best = dict(jobs[0])
        best["other_locations"] = sorted({j["location"] for j in jobs[1:]} - {best["location"]})
        best["job_key"] = job_key(best)
        best["alias_keys"] = sorted({job_key(j) for j in jobs})   # every city of the posting
        # target role in a priority location: must be assessed on the original posting, not by title
        best["priority"] = bool(title_ok(best["title"], profile, exclusions) and any(
            x in (best["location"] + " " + " ".join(best["other_locations"])).lower() for x in priority_places))
        row = next((r for r in (state.find(j)[0] for j in jobs) if r is not None), None)
        if row is None:
            best["dedup"] = "NEW"
        else:
            best.update(dedup="KNOWN", known_status=row["status"], job_key=row["job_key"])
            row["seen_on"] = "|".join(sorted(set(filter(None, (row.get("seen_on") or "").split("|"))) | {best["origin"]}))
        summary[best["dedup"]] += 1
        out.append(best)
    state.save()
    target = ROOT / "07_Logs" / "runs" / args.date / "mail_candidates.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"date": args.date, "files": files, "jobs": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"written": str(target.relative_to(ROOT)), "mail_files": files, **summary,
                      "priority_new": [f"{j['company']} – {j['title']}" for j in out if j["dedup"] == "NEW" and j["priority"]],
                      "by_portal": {p: sum(j["origin"] == p and j["dedup"] == "NEW" for j in out) for p in PORTALS}},
                     ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- scoring

def salary_assess(job, rules):
    """Return (status, compensation score, display text). Never estimates a figure."""
    sal = job.get("salary") or {}
    status = (sal.get("status") or "UNKNOWN").upper().replace(" ", "_")
    target = (rules.get("targets") or {}).get(job.get("country") or "", rules["default"])
    scores = rules["compensation_score"]
    text = job.get("salary_text") or "not stated"
    if status == "VERIFIED" and sal.get("min") is not None and sal.get("period") in ("month", "monthly", "Monat"):
        sal = {**sal, "min": sal["min"] * 12, "max": (sal.get("max") or sal["min"]) * 12}   # some countries state monthly pay
    per = {"hour": rules.get("hours_per_year", 1976), "hourly": rules.get("hours_per_year", 1976),
           "day": rules.get("days_per_year", 230), "daily": rules.get("days_per_year", 230)}.get(sal.get("period"))
    if status == "VERIFIED" and sal.get("min") is not None and per:   # hourly/daily contract rates: annualised, no overtime
        sal = {**sal, "min": sal["min"] * per, "max": (sal.get("max") or sal["min"]) * per}
    if status == "VERIFIED" and sal.get("min") is not None:
        cur = sal.get("currency") or target["currency"]
        fx, tfx = rules["fx_to_eur"].get(cur), rules["fx_to_eur"].get(target["currency"])
        ref = (sal["min"] + (sal.get("max") or sal["min"])) / 2
        ratio = (ref * fx) / (target["min"] * tfx)
        top_ratio = ((sal.get("max") or sal["min"]) * fx) / (target["min"] * tfx)
        if top_ratio < rules.get("below_target_tolerance", 1.0):
            status = "BELOW_TARGET"
        else:
            lo, hi = scores["VERIFIED_meets"]
            if ratio >= 1.0:
                score = lo + (hi - lo) * min(1.0, (ratio - 1.0) / 0.3)
            else:  # only the upper part of the range reaches the target
                score = lo - 1.0 if ratio >= 0.9 else lo - 2.0
            return "VERIFIED", round(score, 1), text
    if status == "VERIFIED":      # claimed verified without figures -> not usable
        status = "UNKNOWN"
    if status == "LIKELY" and not sal.get("evidence"):
        status = "UNKNOWN"        # LIKELY needs documented evidence
    return status, float(scores[status]), text


CHANCE_POINTS = {"met": 1.0, "partial": 0.5, "missing": 0.0}


def chance_score(job):
    """How many of the posting's must-haves the candidate can show: 0-10, None without a list.
    Separate from the match score, which also weighs the candidate's wishes (salary, place, strategy).
    A missing must-have marked as blocker (work permit, required degree, clearance) caps it at 3."""
    items = [m for m in job.get("must_haves") or [] if str(m.get("status") or "").lower() in CHANCE_POINTS]
    if not items:
        return None
    score = 10 * sum(CHANCE_POINTS[str(m["status"]).lower()] for m in items) / len(items)
    if job.get("hard_blocker") or any(m.get("blocker") and str(m["status"]).lower() == "missing" for m in items):
        score = min(score, 3.0)
    return float(Decimal(str(score)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def focus_penalty(job, profile):
    """Titles from focus.deprioritized_titles rank lower by focus.penalty (a role family the user
    wants less of, e.g. after repeated rejections there); focus.exempt_terms lift the deduction."""
    f = profile.get("focus") or {}
    t = fold(job.get("title"))
    if any(fold(x) in t for x in f.get("exempt_terms") or []):
        return 0.0
    return float(f.get("penalty") or 0) if any(fold(x) in t for x in f.get("deprioritized_titles") or []) else 0.0


def score_job(job, profile, rules):
    weights = profile["scoring_weights"]
    status, comp, sal_text = salary_assess(job, rules)
    s = dict(job["scores"])
    s["compensation"] = comp
    missing = [k for k in weights if k not in s]
    if missing:
        raise SystemExit(f"{job['company']} – {job['title']}: missing sub-scores {missing}")
    target = (rules.get("targets") or {}).get(job.get("country") or "", rules["default"])
    if status == "UNKNOWN" and rules.get("unknown_neutral") and not target.get("salary_required"):
        rest = [k for k in weights if k != "compensation"]    # no salary stated: neither a plus nor a minus
        s["compensation"] = round(sum(weights[k] * float(s[k]) for k in rest) / sum(weights[k] for k in rest), 1)
    total = float(Decimal(str(sum(Decimal(str(weights[k])) * Decimal(str(s[k])) for k in weights)))
                  .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if status == "BELOW_TARGET":
        total = min(total, rules["score_cap_below_target"])
    # salary_required on a country target: the floor is mandatory there, an unstated salary caps the score
    if target.get("salary_required") and status not in ("VERIFIED", "LIKELY", "BELOW_TARGET"):
        total = min(total, rules["score_cap_below_target"])
        job.setdefault("salary_note", f"Gehalt nicht belegt – in {job.get('country')} Pflicht (Ziel ≥ {target['min']:,} {target['currency']}/Jahr)")
    focus = focus_penalty(job, profile)
    if focus:
        total = float(Decimal(str(max(0.0, total - focus))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        note = str((profile.get("focus") or {}).get("note") or "").strip() or "nachrangige Rollenfamilie laut Suchprofil"
        job["focus_note"] = f"{note}: -{focus:.1f}"
    sel = profile["daily_selection"]
    rec = (job.get("recommendation") or "CONSIDER").upper()
    basis = job.get("score_basis") or "posting"
    if basis == "alert":            # scored from the alert line only: never recommended, stays in its portal tab
        rec = "SKIP"
        job.setdefault("skip_reason", "Vorab-Score aus den Alert-Daten; Originalanzeige nicht geprüft")
    elif rec == "APPLY" and not job.get("verified_open", True):
        rec = "CONSIDER"            # no application recommendation without a verified posting
    if rec == "SKIP":
        pass
    elif job.get("hard_blocker"):
        rec, total = "SKIP", min(total, 7.4)
    elif total < sel["min_score_report"]:
        rec = "SKIP"
    elif rec == "APPLY":
        strategic = sel["strategic_band"][0] <= total < sel["apply_threshold"] and job.get("strategic")
        if status == "BELOW_TARGET" or not (total >= sel["apply_threshold"] or strategic):
            rec = "CONSIDER"
    job.update(scores=s, match_score=total, match_category=category(total), recommendation=rec,
               salary_status=status, salary_display=sal_text, score_basis=basis, chance_score=chance_score(job))
    return job


def select_for_report(jobs, profile):
    """Apply the daily limits: 5-8 main picks, max 3 stretch, AI share cap."""
    sel = profile["daily_selection"]
    shown = sorted((j for j in jobs if j["recommendation"] != "SKIP"),
                   key=lambda j: j["match_score"], reverse=True)
    main, stretch, overflow = [], [], []
    for j in shown:
        (stretch if j.get("stretch") else main).append(j)
    overflow += main[sel["target_new_jobs"][1]:] + stretch[sel["max_stretch"]:]
    main, stretch = main[:sel["target_new_jobs"][1]], stretch[:sel["max_stretch"]]
    ai_cap = max(1, math.ceil(sel["max_ai_share"] * len(main)))
    ai = [j for j in main if j.get("is_ai_role")]
    for j in ai[ai_cap:]:
        main.remove(j)
        overflow.append(j)
    return main, stretch, overflow


# ---------------------------------------------------------------- documents

def bullets(items, empty="– (keine Angabe)"):
    return "\n".join(f"- {x}" for x in items) if items else empty


def job_summary_md(j, date):
    return f"""# {j['title']} – {j['company']}

| Feld | Wert |
|---|---|
| Job Title | {j['title']} |
| Company | {j['company']} |
| Location | {j.get('location') or '–'} ({j.get('country') or '–'}) |
| Posted | {j.get('posted_date') or 'unknown'} |
| URL | {j.get('url')} |
| Apply URL | {j.get('apply_url') or j.get('url')} |
| Job ID | {j.get('job_id') or '–'} |
| Salary | {j['salary_display']} ({j['salary_status']}) |
| Remote/Hybrid | {j.get('remote') or 'not stated'}{' – ' + j['remote_text'] if j.get('remote_text') else ''} |
| Relocation | {j.get('relocation_text') or 'not stated'} |
| Visa | {j.get('visa_text') or 'not stated'} |
| Experience required | {j.get('experience_required') or 'not stated'} |
| Source | {j.get('source') or '–'} |
| Retrieval date | {date} |
| Verified open | {'yes' if j.get('verified_open') else 'NO'} – {j.get('verification_note') or ''} |

Strukturierte Zusammenfassung der Ausschreibung (keine Vollkopie).

## Responsibilities

{bullets(j.get('responsibilities'))}

## Requirements

{bullets(j.get('requirements'))}

## Nice-to-have

{bullets(j.get('nice_to_have'))}
"""


def chance_md(j):
    if j.get("chance_score") is None:
        return ""
    mark = {"met": "erfüllt", "partial": "teilweise", "missing": "fehlt"}
    items = "".join(f"\n- {mark.get(str(m.get('status')).lower(), m.get('status'))}: {m.get('req')}"
                    + (" (Ausschluss)" if m.get("blocker") else "") for m in j.get("must_haves") or [])
    return f"\n\n**Chance: {j['chance_score']:.1f} / 10** (belegte Muss-Anforderungen){items}"


def match_analysis_md(j, weights):
    labels = {"fachlich": "A. Fachliche Passung", "transfer": "B. Transferierbare Erfahrung",
              "senioritaet": "C. Seniorität und Verantwortung", "compensation": "D. Compensation",
              "standort": "E. Standort / Visa / Relocation", "strategie": "F. Strategische Attraktivität"}
    rows = "\n".join(f"| {labels.get(k, k)} | {int(w * 100)} % | {float(j['scores'][k]):.1f} | {w * float(j['scores'][k]):.2f} |"
                     for k, w in weights.items())
    sk = j.get("skills") or {}
    return f"""# Match Analysis – {j['title']} ({j['company']})

**Match Score: {j['match_score']:.1f} / 10 – {j['match_category']}** · Empfehlung: **{j['recommendation']}**{chance_md(j)}

| Kategorie | Gewicht | Score | Beitrag |
|---|---|---|---|
{rows}

{j.get('score_rationale') or ''}

## Skill-Gap-Analyse

### MATCHED

{bullets(sk.get('matched'))}

### PARTIAL

{bullets(sk.get('partial'))}

### MISSING

{bullets(sk.get('missing'))}

### UNKNOWN

{bullets(sk.get('unknown'))}
"""


def application_notes_md(j):
    sal = j.get("salary") or {}
    return f"""# Application Notes – {j['title']} ({j['company']})

- **Match Score:** {j['match_score']:.1f} / 10 ({j['match_category']})
- **Empfehlung:** {j['recommendation']}
- **Job-Link:** {j.get('apply_url') or j.get('url')}
- **Gehalt:** {j['salary_display']}
- **Salary Confidence:** {j['salary_status']}{' – ' + sal['evidence'] if sal.get('evidence') else ''}
- **Visa:** {j.get('visa_text') or 'not stated'}
- **Relocation:** {j.get('relocation_text') or 'not stated'}
- **Recruiting Contact:** {j.get('contact') or 'in der Ausschreibung nicht genannt'}

## Wichtigste Argumente

{bullets(j.get('arguments'))}

## Mögliche Schwächen

{bullets(j.get('weaknesses'))}

## Screening-Risiken

{bullets(j.get('screening_risks'))}

## Wichtige Application Questions

{bullets(j.get('application_questions'))}

## CV-Hinweise (nur Vorschläge – Fakten werden nie geändert)

{bullets(j.get('cv_suggestions'), '– keine Anpassung nötig')}

## Vor dem Absenden prüfen (Freigabe nur durch dich, einzeln je Bewerbung)

- [ ] Anschreiben gelesen und freigegeben
- [ ] Screening-Fragen
- [ ] Gehaltsangabe
- [ ] Verfügbarkeit / Kündigungsfrist
- [ ] Relocation / Visa
- [ ] Freitextantworten
- [ ] personenbezogene Angaben
"""


def visa_cell(j, permit=()):
    """permit: countries where the user may work without a visa (search_profile.yaml work_permit_countries)."""
    parts = [p for p in (j.get("visa_text"), j.get("relocation_text")) if p]
    if parts:
        return " / ".join(parts)
    return "n/a (Arbeitserlaubnis vorhanden)" if j.get("country") in permit else "not stated"


def cell(text):
    return str(text or "–").replace("|", "/").replace("\n", " ")


def report_md(date, main, stretch, overflow, stats, permit=()):
    d = dt.date.fromisoformat(date)
    lines = [f"# Daily Job Report – {d.strftime('%d.%m.%Y')}", "",
             f"{sum(j['match_score'] >= 8.0 for j in main)} Strong Matches (≥ 8,0) · "
             f"{sum(j['match_score'] < 8.0 for j in main)} Watchlist · {len(stretch)} Stretch · "
             f"{stats['evaluated']} bewertet · {stats['skipped']} aussortiert · "
             f"{stats['known']} bereits bekannt (nicht erneut gezeigt)", "",
             "| Rank | Match | Company | Position | Location | Salary | Visa/Relocation | Why it fits | Main gap | Recommendation | Job link | Cover letter file |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ranked = main + stretch
    for i, j in enumerate(ranked, 1):
        salary = j["salary_display"] if j["salary_status"] == "VERIFIED" else \
            {"LIKELY": "LIKELY ≥ Ziel (nicht ausgeschrieben)", "UNKNOWN": "SALARY UNVERIFIED",
             "BELOW_TARGET": f"BELOW TARGET ({j['salary_display']})"}[j["salary_status"]]
        tag = " (Stretch)" if j.get("stretch") else ""
        lines.append(f"| {i} | {j['match_score']:.1f} | {cell(j['company'])} | {cell(j['title'])}{tag} | "
                     f"{cell(j.get('location'))} | {cell(salary)} | {cell(visa_cell(j, permit))} | {cell(j.get('why_fit'))} | "
                     f"{cell(j.get('main_gap'))} | {j['recommendation']} | [Link]({j.get('url')}) | "
                     f"{cell(j.get('cover_letter_path'))} |")
    for i, j in enumerate(ranked, 1):
        sk = j.get("skills") or {}
        lines += ["", f"## {i}. {j['company']} – {j['title']}", "",
                  f"**{j['match_score']:.1f}/10 · {j['match_category']} · {j['recommendation']}** · "
                  f"{j.get('location')} · posted {j.get('posted_date') or 'unknown'}",
                  "", f"- Warum: {j.get('why_fit')}", f"- Größte Lücke: {j.get('main_gap')}",
                  f"- MISSING: {', '.join(sk.get('missing') or []) or '–'}",
                  f"- Gehalt: {j['salary_display']} ({j['salary_status']})",
                  f"- Link: {j.get('url')}",
                  f"- Paket: {j.get('package_path') or '–'}"]
    if overflow:
        lines += ["", "## Zusätzlich auf der Watchlist (heute nicht im Fokus)", ""]
        lines += [f"- {j['match_score']:.1f} · {j['company']} – {j['title']} ({j.get('location')}) · {j.get('url')}"
                  for j in overflow]
    return "\n".join(lines) + "\n"


SALARY_LABEL = {"LIKELY": "LIKELY at target (not stated in posting)", "UNKNOWN": "SALARY UNVERIFIED",
                "BELOW_TARGET": "BELOW TARGET"}


def morning_md(date, main, stretch, replies=(), unmatched=(), closed=(), permit=()):
    d = dt.date.fromisoformat(date)
    strong = sum(j["match_score"] >= 8.0 for j in main)
    watch = len(main) - strong
    head = f"{strong} new strong match{'es' if strong != 1 else ''} found" if strong else "No new strong match today"
    if watch:
        head += f", {watch} more for the watchlist"
    if stretch:
        head += f", {len(stretch)} stretch"
    lines = [f"JOB SEARCH – {d.strftime('%d.%m.%Y')}", "", head + ".", ""]
    for i, j in enumerate(main + stretch, 1):
        salary = j["salary_display"] if j["salary_status"] == "VERIFIED" else SALARY_LABEL[j["salary_status"]]
        lines += [f"{i}. {j['company']} – {j['title']}{' (Stretch)' if j.get('stretch') else ''}",
                  f"Match: {j['match_score']:.1f}/10" + (f" · Chance: {j['chance_score']:.1f}/10"
                                                          if j.get("chance_score") is not None else ""),
                  f"Location: {j.get('location')}",
                  f"Salary: {salary}",
                  f"Visa/Relocation: {visa_cell(j, permit)}",
                  f"Why: {j.get('why_fit')}",
                  f"Gap: {j.get('main_gap')}",
                  f"Recommendation: {j['recommendation']}",
                  f"Job: {j.get('url')}",
                  f"Cover Letter: {j.get('cover_letter_path') or '–'}", ""]
    apply = [j for j in main + stretch if j["recommendation"] == "APPLY"][:3] or (main + stretch)[:3]
    if apply:
        lines += ["TODAY'S PRIORITY", ""]
        lines += [f"{i}. {j['company']} – {j['title']} ({j['match_score']:.1f})" for i, j in enumerate(apply, 1)]
    if replies or unmatched:
        lines += ["", "ANTWORTEN AUF BEWERBUNGEN", ""] + [f"- {x}" for x in replies]
        lines += [f"- ohne passende Stelle: {x}" for x in unmatched]
    if closed:
        lines += ["", f"NICHT MEHR VERFÜGBAR (entfernt): {len(closed)}", ""] + [f"- {x}" for x in closed]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- finalize

def cmd_finalize(args):
    date = args.date
    year = date[:4]
    data = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    profile, rules = load_profile(), load_rules()
    need(profile.get("daily_selection"), "daily_selection in 01_Config/search_profile.yaml")
    permit = {str(c).strip().upper() for c in profile.get("work_permit_countries") or []}
    banned_now = banned_patterns(profile)
    core = core_role(profile)
    state = State()
    previous = ROOT / "07_Logs" / "runs" / date / "scored_final.json"
    if previous.exists() and not args.replace:   # a further run on the same day adds to it, never wipes it
        fresh = {job_key(j) for j in data["jobs"]} | {j["job_key"] for j in data["jobs"] if j.get("job_key")}
        earlier = json.loads(previous.read_text(encoding="utf-8"))["jobs"]
        data["jobs"] = [j for j in earlier if j.get("job_key") not in fresh and job_key(j) not in fresh] + data["jobs"]
    seen = {}                           # one entry per job: a rescore with a differently spelled place replaces the earlier one
    for j in data["jobs"]:
        seen[j.get("job_key") or job_key(j)] = j
    data["jobs"] = list(seen.values())
    jobs = [score_job(j, profile, rules) for j in data["jobs"]]
    closed_now = []
    if not args.no_open_check:   # every posting is checked again right before it can reach the report
        res = check_many([j.get("apply_url") or j.get("url") or "" for j in jobs if not j.get("closed")])
        for j in jobs:
            if j.get("closed"):
                continue
            st, ev = res[j.get("apply_url") or j.get("url") or ""]
            j["open_state"], j["open_evidence"] = st, ev
            if st == "closed":
                j["closed"] = True
                closed_now.append(f"{j['company']} – {j['title']}")
            elif st == "open":
                j["open_checked"] = date
    main, stretch, overflow = select_for_report([j for j in jobs if not j.get("closed")], profile)
    shown = {id(j) for j in main + stretch}
    problems = []

    jd_dir = ROOT / "05_Job_Descriptions" / year / date
    for j in jobs:
        j["job_key"] = job_key(j)
        name = f"{safe(j['company'])}_{safe(j['title'])}"
        if j["recommendation"] != "SKIP":
            jd_dir.mkdir(parents=True, exist_ok=True)
            (jd_dir / f"{name}.md").write_text(job_summary_md(j, date), encoding="utf-8")
        # letter_requested: the user asked for an application to this job – letter and package
        # are built whatever the score; the score and recommendation stay as computed
        if (j["recommendation"] == "APPLY" and id(j) in shown) or j.get("letter_requested"):
            pkg = ROOT / "06_Application_Packages" / year / date / name
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "Job_Summary.md").write_text(job_summary_md(j, date), encoding="utf-8")
            (pkg / "Match_Analysis.md").write_text(match_analysis_md(j, profile["scoring_weights"]), encoding="utf-8")
            (pkg / "Application_Notes.md").write_text(application_notes_md(j), encoding="utf-8")
            j["package_path"] = str(pkg.relative_to(ROOT))
            spec = j.get("cover_letter")
            if not spec:
                problems.append(f"{j['company']} – {j['title']}: APPLY/letter_requested without cover_letter spec")
                continue
            spec = {**spec, "company": j["company"], "role": spec.get("role") or j["title"],
                    "language": spec.get("language") or j.get("posting_language") or "en", "date": date}
            out = cover_letter.build(spec)
            check = cover_letter.validate(out, spec)
            j["cover_letter_path"] = str(out.relative_to(ROOT))
            j["cover_letter_check"] = check
            shutil.copyfile(out, pkg / "Cover_Letter.docx")
            if not check["ok"]:
                problems.append(f"{j['company']} – {j['title']}: cover letter invalid: {check['errors']}")

    # state: user decisions (APPLIED / REJECTED) are never overwritten
    tracker = {r["job_key"]: r for r in read_csv(TRACKER)}
    rejected = {r["job_key"]: r for r in read_csv(REJECTED)}
    for j in jobs:
        if j.get("closed"):
            status = "EXPIRED"
        elif j.get("letter_requested") and not j.get("hard_blocker"):
            status = "RECOMMENDED"          # the user wants to apply: listed like a recommendation, letter ready
        elif j["recommendation"] == "SKIP" and j.get("origin") == "manual" and not j.get("hard_blocker"):
            status = "WATCHLIST"            # sent in by the user: always visible, on the Merkliste
        elif j["recommendation"] == "SKIP":
            status = "REVIEWED"
        elif id(j) in shown and j["recommendation"] == "APPLY":
            status = "RECOMMENDED"
        else:
            status = "WATCHLIST"
        existing, _ = state.find(j)
        keep_user = existing is not None and existing["status"] in USER_STATUSES
        row = state.upsert(j, report_date=date, match_score=f"{j['match_score']:.1f}",
                           match_category=j["match_category"], recommendation=j["recommendation"],
                           salary_status=j["salary_status"], is_ai_role=str(bool(j.get("is_ai_role"))),
                           stretch=str(bool(j.get("stretch"))),
                           cover_letter_path=j.get("cover_letter_path"), package_path=j.get("package_path"),
                           notes=j.get("hard_blocker") or j.get("main_gap"),
                           origin=j.get("origin"), score_basis=j.get("score_basis"),
                           open_state=j.get("open_state"), open_checked=j.get("open_checked"),
                           chance_score="" if j.get("chance_score") is None else f"{j['chance_score']:.1f}")
        j["job_key"] = row["job_key"]
        if not keep_user:
            row["status"] = status
        if status == "REVIEWED":
            rejected[row["job_key"]] = {"job_key": row["job_key"], "date": date, "company": j["company"],
                                        "title": j["title"], "location": j.get("location"), "url": j.get("url"),
                                        "match_score": f"{j['match_score']:.1f}", "rejected_by": "system",
                                        "reason": j.get("hard_blocker") or j.get("skip_reason")
                                        or f"score {j['match_score']:.1f} below report threshold"}
            continue
        sal = j.get("salary") or {}
        t = tracker.setdefault(row["job_key"], {"job_key": row["job_key"], "date_found": date,
                                                "application_status": "NOT_APPLIED"})
        t.update({"company": j["company"], "role": j["title"], "location": j.get("location"),
                  "country": j.get("country"), "industry": j.get("industry"), "source": j.get("source"),
                  "job_url": j.get("url"), "job_id": j.get("job_id"),
                  "match_score": f"{j['match_score']:.1f}",
                  "salary": j.get("salary_text") or "", "salary_currency": sal.get("currency") or "",
                  "salary_status": j["salary_status"], "visa": j.get("visa_text") or "",
                  "relocation": j.get("relocation_text") or "", "remote": j.get("remote") or "",
                  "cover_letter_path": j.get("cover_letter_path") or t.get("cover_letter_path") or "",
                  "last_update": date})
        if t["application_status"] == "NOT_APPLIED" and j.get("cover_letter_path"):
            t["application_status"] = "PREPARED"
    forced, banned = [], []
    for s in data.get("screened_out", []):       # stubs dropped at triage, kept out of future runs
        row = state.upsert(s)
        if row["status"] == "NEW" and (row.get("notes") or "").startswith(MUST_SCORE):
            forced.append(f"{row['company']} – {row['title']}")    # stays NEW: it has to be scored
            continue
        if row["status"] == "NEW" and banned_reason(s.get("reason"), banned_now):
            banned.append(f"{row['company']} – {row['title']}")    # stays NEW: the backlog brings it back
            continue
        if row["status"] == "NEW":
            row["status"], row["notes"] = "REVIEWED", s.get("reason") or "screened out at triage"
            rejected[row["job_key"]] = {"job_key": row["job_key"], "date": date, "company": s.get("company"),
                                        "title": s.get("title"), "location": s.get("location"),
                                        "url": s.get("url"), "match_score": "", "rejected_by": "system",
                                        "reason": row["notes"]}
    state.save()
    write_csv(TRACKER, list(tracker.values()), TRACKER_COLS)
    write_csv(REJECTED, list(rejected.values()), REJECTED_COLS)
    touch_companies(jobs)

    stats = {"evaluated": len(jobs), "skipped": sum(j["recommendation"] == "SKIP" for j in jobs),
             "known": int(data.get("known_skipped", 0)),
             "research_lanes": len(list((ROOT / "07_Logs" / "research").glob(f"{date}_lane_*.json"))),
             # the copied template and the filled example are no briefings of this search
             "research_briefs": len([f for f in (ROOT / "09_Documentation" / "research_briefs").glob("lane_*.md")
                                     if not re.match(r"lane_(TEMPLATE|BEISPIEL)", f.name)])}
    rep_dir = ROOT / "03_Daily_Reports" / year / date
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / f"Daily_Job_Report_{date}.md").write_text(report_md(date, main, stretch, overflow, stats, permit), encoding="utf-8")
    run_dir = ROOT / "07_Logs" / "runs" / date
    extra = {}
    for name in ("closed_today.json", "replies_applied.json"):
        f = run_dir / name
        if f.exists():
            extra.update(json.loads(f.read_text(encoding="utf-8")))
    closed_all = list(dict.fromkeys(extra.get("expired", []) + closed_now))
    morning = morning_md(date, main, stretch, replies=extra.get("applied", []),
                         unmatched=extra.get("unmatched", []), closed=closed_all, permit=permit)
    lane_jobs = sum(len(json.loads(f.read_text(encoding="utf-8")).get("jobs", []))
                    for f in (ROOT / "07_Logs" / "research").glob(f"{date}_lane_*.json"))
    if lane_jobs and not jobs:          # research found jobs, nothing was evaluated: say so, never "no match"
        morning += (f"\nWARNUNG: Die Recherche lieferte {lane_jobs} Stellen, bewertet wurde keine – Lauf "
                    f"unvollständig. Stellen aus 07_Logs/research/{date}_lane_*.json bewerten und finalize wiederholen.\n")
        problems.append(f"{lane_jobs} research jobs, 0 evaluated")
    if stats["research_lanes"] >= 4 and lane_jobs < 8:   # lanes have claimed sources "unreachable" that fetch reached
        morning += (f"\nWARNUNG: Die {stats['research_lanes']} Recherche-Agenten lieferten zusammen nur {lane_jobs} Stellen – Quellen in "
                    f"07_Logs/research/{date}_lane_*.json (sources_checked, problems) prüfen.\n")
        problems.append(f"research lanes delivered only {lane_jobs} jobs")
    unsearched = [f"{j['company']} – {j['title']}" for j in data["jobs"]
                  if j.get("score_basis") == "alert" and not search_documented(j.get("verification_note"))]
    if unsearched:                      # a pre-score needs documented attempts to find the original posting
        morning += (f"\nWARNUNG: {len(unsearched)} Vorab-Scores ohne dokumentierte Suche nach der Originalanzeige "
                    f"(verification_note): {'; '.join(unsearched[:6])}\n")
        problems.append(f"{len(unsearched)} alert pre-scores without a documented posting search")
    core_pre = [f"{j['company']} – {j['title']} ({j.get('match_score')})" for j in data["jobs"]
                if j.get("score_basis") == "alert" and (j.get("match_score") or 0) >= 6.0 and core.search(j.get("title") or "")
                and not search_documented(j.get("verification_note"))]   # searched for real and not found: fine
    if core_pre:                        # core roles from 6.0 are never left as a pre-score: too close to a real match
        morning += (f"\nWARNUNG: {len(core_pre)} Kernrollen ab Vorab-Note 6.0 nicht anhand der Originalanzeige bewertet – "
                    f"Anzeige suchen, neu bewerten, finalize wiederholen: {'; '.join(core_pre[:6])}\n")
        problems.append(f"{len(core_pre)} core-role alert pre-scores >= 6.0 not scored from the posting")
    mail_cfg = cfg()["mail"]
    indeed = [x for x in mail_cfg.get("alert_senders") or [] if "indeed" in str(x).lower()]
    # Indeed suggestions only arrive through the Gmail connector export; a run that forgets the step loses them silently
    if mail_cfg.get("mode") == "gmail" and indeed and not (ROOT / "07_Logs" / "mail_inbox" / f"{date}_gmail_indeed.json").exists():
        morning += (f"\nWARNUNG: Indeed-Jobvorschläge aus Gmail ({', '.join(map(str, indeed))}) nicht abgeholt – "
                    "search_threads speichern, indeed-mails, mail-candidates und finalize wiederholen.\n")
        problems.append("Indeed job mails from Gmail not fetched")
    mc = run_dir / "mail_candidates.json"
    if mc.exists():                     # every new alert job must be scored or screened out, none skipped
        handled = {job_key(j) for j in data["jobs"]} | {job_key(x) for x in data.get("screened_out", [])}
        handled |= {j.get("job_key") for j in data["jobs"]} | {x.get("job_key") for x in data.get("screened_out", [])}
        open_mail = [j for j in json.loads(mc.read_text(encoding="utf-8")).get("jobs", [])
                     if j.get("dedup") == "NEW" and j.get("job_key") not in handled and job_key(j) not in handled
                     and (state.find(j)[0] or {}).get("status", "NEW") == "NEW"]   # a same-day rerun only sees its own file
        if open_mail:
            morning += (f"\nWARNUNG: {len(open_mail)} neue Stellen aus den Job-Mails wurden weder bewertet noch "
                        f"aussortiert – sie kommen morgen erneut. Mail-Kandidaten vollständig bearbeiten und finalize wiederholen.\n")
            problems.append(f"{len(open_mail)} mail candidates neither scored nor screened out")
    if forced:
        morning += (f"\nWARNUNG: {len(forced)} Stellen mit Pflicht zur Bewertung wurden nur nach Titel aussortiert "
                    f"– sie bleiben offen und müssen bewertet werden: {'; '.join(forced[:8])}\n")
        problems.append(f"{len(forced)} must-score jobs screened out instead of scored")
    if banned:
        morning += (f"\nWARNUNG: {len(banned)} Stellen wurden mit unzulässiger Begründung aussortiert (KI-Obergrenze, "
                    f"Vermutung ohne gelesene Anzeige oder ein Muster aus banned_reason_patterns) – sie bleiben offen und "
                    f"kommen über den Rückstand erneut: {'; '.join(banned[:8])}\n")
        problems.append(f"{len(banned)} jobs screened out with a banned reason")
    same = {}
    for x in data.get("screened_out", []):
        r = reason_core(x.get("reason"))
        same[r] = same.get(r, 0) + 1
    blanket = {r: n for r, n in same.items() if n >= 10}
    if blanket:                         # each stub needs its own reason – a blanket one hides real matches
        n = sum(blanket.values())
        morning += (f"\nWARNUNG: {n} Stellen wurden mit derselben Sammelbegründung aussortiert – Triage "
                    f"unvollständig. Jede Stelle einzeln nach Titel beurteilen und finalize wiederholen.\n")
        problems.append(f"{n} jobs screened out with one blanket reason")
    if stats["research_lanes"] < stats["research_briefs"]:   # the lane briefings are the core of the search
        morning += (f"\nHINWEIS: Recherche unvollständig – heute liefen {stats['research_lanes']} von {stats['research_briefs']} "
                    f"Recherche-Briefings (09_Documentation/research_briefs/lane_*.md).\n")
    (rep_dir / f"Morning_Message_{date}.md").write_text(morning, encoding="utf-8")
    run_dir = ROOT / "07_Logs" / "runs" / date
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scored_final.json").write_text(json.dumps({"date": date, "jobs": jobs}, ensure_ascii=False, indent=1), encoding="utf-8")
    ai_main = sum(bool(j.get("is_ai_role")) for j in main)
    summary = {"date": date, "main": len(main), "stretch": len(stretch), "watchlist_overflow": len(overflow),
               "apply": sum(j["recommendation"] == "APPLY" for j in main + stretch),
               "ai_share_main": round(ai_main / len(main), 2) if main else 0, **stats,
               "report": str((rep_dir / f"Daily_Job_Report_{date}.md").relative_to(ROOT)),
               "cover_letters": [j["cover_letter_path"] for j in jobs if j.get("cover_letter_path")],
               "problems": problems}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    sys.exit(1 if problems else 0)


# ---------------------------------------------------------------- status / expiry

def apply_status(state, key, status, note="", date=None):
    row = state.by_key.get(key)
    if row is None:
        raise SystemExit(f"unknown job_key {key}")
    row["status"] = status
    if note:
        row["notes"] = note
    tracker = {r["job_key"]: r for r in read_csv(TRACKER)}
    t = tracker.get(key)
    if t:
        t["last_update"] = date or today()
        if status == "APPLIED":
            t["application_status"], t["date_applied"] = "APPLIED", t.get("date_applied") or date or today()
        elif status in ("REJECTED", "EXPIRED"):
            if t.get("application_status") != "APPLIED":
                t["application_status"] = status
        if note:
            t["notes"] = note
        write_csv(TRACKER, list(tracker.values()), TRACKER_COLS)
    if status == "REJECTED":
        rejected = {r["job_key"]: r for r in read_csv(REJECTED)}
        rejected[key] = {"job_key": key, "date": date or today(), "company": row["company"],
                         "title": row["title"], "location": row["location"], "url": row["url"],
                         "match_score": row["match_score"], "rejected_by": "user", "reason": note or "rejected by the user"}
        write_csv(REJECTED, list(rejected.values()), REJECTED_COLS)
    return row


def cmd_set_status(args):
    if args.status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    state = State()
    row = apply_status(state, args.key, args.status, args.note or "", args.date)
    state.save()
    print(f"{row['company']} – {row['title']}: {row['status']}")


CLOSED_MARKERS = (
    "no longer available", "no longer accepting", "no longer open", "position has been filled",
    "this job has expired", "job has expired", "posting has expired", "job not found", "job is closed",
    "this position is closed", "the job you are looking for", "page not found",
    "nicht mehr verfügbar", "ist nicht mehr aktiv", "nicht mehr online", "bereits besetzt", "stelle ist leider",
    "stellenanzeige ist nicht mehr", "diese stelle ist nicht mehr", "ausschreibung ist beendet",
    "n'est plus disponible", "plus d'actualité")
NOT_CHECKABLE = re.compile(r"^https://([a-z]+\.)?(linkedin|xing)\.com/|^https://(to|[a-z]{2})\.indeed\.com/|^https://(www\.)?indeed\.com/", re.I)


def _http(url, data=None, headers=None, timeout=25, max_bytes=400000):
    """(status, final_url, body) – status 0 on a network error. max_bytes=None reads the whole body."""
    req = urllib.request.Request(url, data=data, headers={**UA, "Accept": "*/*", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.status, resp.geturl(), (resp.read() if max_bytes is None else resp.read(max_bytes)).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception:                       # DNS, TLS, timeout, reset
        return 0, url, ""


def _visible_text(page):
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    return re.sub(r"\s+", " ", html_unescape(re.sub(r"<[^>]+>", " ", page))).lower()


def open_state(url):
    """Is the posting behind url still open? -> (state, evidence); state is open, closed or unknown.
    Public ATS APIs are asked first (exact); other pages are judged by status, redirect and wording."""
    if not url or not url.startswith("https://"):
        return "unknown", "no employer link"
    if NOT_CHECKABLE.search(url):
        return "unknown", "portal link only (not fetched)"
    u = urllib.parse.urlparse(url)
    host, parts = u.netloc.lower(), [x for x in u.path.split("/") if x]
    try:
        if "greenhouse.io" in host:
            gh_id = urllib.parse.parse_qs(u.query).get("gh_jid", [None])[0] or next((x for x in reversed(parts) if x.isdigit()), None)
            board = parts[0] if parts and parts[0] not in ("embed", "jobs") else urllib.parse.parse_qs(u.query).get("for", [None])[0]
            if gh_id and board:
                st, _, _ = _http(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{gh_id}")
                if st == 200:
                    return "open", "greenhouse api"
                if st == 404:
                    return "closed", "greenhouse api: 404"
        if host == "jobs.ashbyhq.com" and len(parts) >= 2:
            # whole board: a large board is ~14 MB, a 400 KB cut marked open postings as closed
            st, _, body = _http(f"https://api.ashbyhq.com/posting-api/job-board/{parts[0]}", timeout=60, max_bytes=None)
            if st == 200:
                return ("open", "ashby api") if parts[1] in body else ("closed", "ashby api: not on the board")
        if host == "jobs.lever.co" and len(parts) >= 2:
            st, _, _ = _http(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")
            if st in (200, 404):
                return ("open", "lever api") if st == 200 else ("closed", "lever api: 404")
        if host == "jobs.smartrecruiters.com" and len(parts) >= 2:
            pid = parts[1].split("-")[0]
            st, _, body = _http(f"https://api.smartrecruiters.com/v1/companies/{parts[0]}/postings/{pid}")
            if st == 404:
                return "closed", "smartrecruiters api: 404"
            if st == 200:
                return ("closed", "smartrecruiters api: inactive") if '"active":false' in body.replace(" ", "") else ("open", "smartrecruiters api")
        if host.endswith("myworkdayjobs.com") and "job" in parts:
            i = parts.index("job")
            site = parts[i - 1]
            st, _, body = _http(f"https://{host}/wday/cxs/{host.split('.')[0]}/{site}/{'/'.join(parts[i:])}",
                                headers={"Accept": "application/json"})
            if st == 404:
                return "closed", "workday api: 404"
            if st == 200 and '"jobPostingInfo"' in body:
                return "open", "workday api"
            if st == 200:     # 200 without posting data = bot wall or error page, not proof of a closed job
                return "unknown", "workday api: 200 without posting data"
    except Exception:                       # fall back to the page itself
        pass
    st, final, body = _http(url)
    if st in (404, 410):
        return "closed", f"HTTP {st}"
    if st == 0 or st >= 400:
        return "unknown", f"HTTP {st or 'error'}"
    fu = urllib.parse.urlparse(final)
    if "error=true" in fu.query or re.search(r"[?&](error|expired|notfound)=", fu.query or "", re.I):
        return "closed", "redirected to an error page"
    ids = [x for x in re.findall(r"\d{4,}", u.path)]
    if ids and not any(i in final for i in ids):
        return "closed", "redirected away from the posting"
    text = _visible_text(body)
    hit = next((m for m in CLOSED_MARKERS if m in text), None)
    if hit:
        return "closed", f'page says "{hit}"'
    return "open", f"HTTP {st}"


def check_many(urls, workers=12):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(zip(urls, ex.map(open_state, urls)))


def visible_rows(state):
    """Rows the dashboard or a report can show: everything active, applied, and recent alert jobs."""
    oldest = (dt.date.today() - dt.timedelta(days=PORTAL_DAYS)).isoformat()
    return [r for r in state.rows if r["status"] in ACTIVE | {"APPLIED"}
            or (r["status"] == "REVIEWED" and r.get("origin") in PORTALS and r["first_seen"] >= oldest)]


def cmd_check_open(args):
    """Without --in: re-check every visible job, closed ones become EXPIRED (applied ones only get a note).
    With --in: drop closed postings from a candidate file before they are evaluated."""
    if args.infile:
        path = Path(args.infile)
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = data["jobs"] if isinstance(data, dict) else data
        res = check_many([j.get("apply_url") or j.get("url") or "" for j in jobs])
        keep, dropped = [], []
        for j in jobs:
            st, ev = res[j.get("apply_url") or j.get("url") or ""]
            j["open_state"], j["open_evidence"] = st, ev
            (dropped if st == "closed" else keep).append(j)
        if isinstance(data, dict):
            data["jobs"] = keep
            data.setdefault("closed_dropped", []).extend({k: j.get(k) for k in ("company", "title", "url", "open_evidence")} for j in dropped)
        path.write_text(json.dumps(data if isinstance(data, dict) else keep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"kept": len(keep), "closed_dropped": [f"{j['company']} – {j['title']} ({j['open_evidence']})" for j in dropped]},
                         ensure_ascii=False, indent=1))
        return
    state = State()
    rows = visible_rows(state)
    res = check_many([r["url"] for r in rows])
    if rows and sum(st == "unknown" and ev.startswith("HTTP error") for st, ev in res.values()) > 0.8 * len(rows):
        raise SystemExit("check-open: almost no page reachable – network blocked? nothing changed")
    expired, applied_offline, unknown = [], [], []
    for r in rows:
        st, ev = res[r["url"]]
        r["open_state"] = st
        if st == "open":
            r["open_checked"] = today()
        elif st == "closed" and r["status"] == "APPLIED":
            r["notes"] = f"Anzeige offline seit {today()} ({ev})"
            applied_offline.append(f"{r['company']} – {r['title']}")
        elif st == "closed":
            r["status"], r["notes"] = "EXPIRED", f"closed on {today()}: {ev}"
            expired.append(r["job_key"])
        else:
            unknown.append(f"{r['company']} – {r['title']}: {ev}")
    state.save()
    for key in expired:
        apply_status(State(), key, "EXPIRED")
    closed_names = [f"{state.by_key[k]['company']} – {state.by_key[k]['title']}" for k in expired]
    run_dir = ROOT / "07_Logs" / "runs" / today()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "closed_today.json").write_text(json.dumps({"expired": closed_names, "applied_offline": applied_offline},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"checked": len(rows), "expired": closed_names, "applied_offline": applied_offline,
                      "not_checkable": len(unknown), "unknown_sample": unknown[:10]}, ensure_ascii=False, indent=1))


MUST_SCORE = "MUSS BEWERTET WERDEN"     # note on jobs the user or a review put back: triage may not drop them


def cmd_backlog(args):
    """Jobs in the state that were found but never evaluated (status NEW, last 14 days), as candidates."""
    oldest = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    jobs = [{"company": r["company"], "title": r["title"], "location": r["location"], "country": r["country"],
             "industry": r["industry"], "url": r["url"], "job_id": r["job_id"], "posted_date": r["posted_date"],
             "source": r["source"] or "backlog", "origin": r.get("origin") or "", "portal_url": r.get("portal_url") or "",
             "job_key": r["job_key"], "dedup": "NEW", "backlog": True,
             "must_score": (r.get("notes") or "").startswith(MUST_SCORE)}
            for r in State().rows if r["status"] == "NEW" and r["last_seen"] >= oldest and r["url"]]
    out = ROOT / "07_Logs" / "runs" / args.date / "backlog_candidates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": args.date, "jobs": jobs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"file": str(out.relative_to(ROOT)), "jobs": [f"{j['company']} – {j['title']}" for j in jobs]},
                     ensure_ascii=False, indent=1))


MANUAL_LETTERS = ROOT / "04_Cover_Letters" / "manual"   # base spec of letters the user asked for outside a run
LETTER_EDITS = ROOT / "04_Cover_Letters" / "edits"    # the user's edits from the dashboard editor, one JSON per job


def base_letter_spec(key):
    """The cover letter spec as finalize built it (company, role, language, date, output filled in)."""
    row = State().by_key.get(key)
    if row is None or not row["cover_letter_path"]:
        return None
    for f in sorted((ROOT / "07_Logs" / "runs").glob("*/scored_final.json"), reverse=True):
        for j in json.loads(f.read_text(encoding="utf-8"))["jobs"]:
            if j.get("job_key") == key and j.get("cover_letter") and j.get("cover_letter_path") == row["cover_letter_path"]:
                spec = j["cover_letter"]
                return {**spec, "company": j["company"], "role": spec.get("role") or j["title"],
                        "language": spec.get("language") or j.get("posting_language") or "en",
                        "date": spec.get("date") or f.parent.name, "output": str(ROOT / row["cover_letter_path"])}
    m = MANUAL_LETTERS / f"{key}.json"          # written by hand on the user's request, not by a daily run
    if m.exists():
        return {**json.loads(m.read_text(encoding="utf-8")), "output": str(ROOT / row["cover_letter_path"])}
    return None


def letter_spec(key):
    """The user's edited version if there is one, otherwise the generated letter."""
    f = LETTER_EDITS / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["spec"]
    return base_letter_spec(key)


def letter_field(key):
    """What the dashboard editor needs: the texts plus the numbers for its live checks."""
    spec = letter_spec(key)
    if not spec:
        return None
    # ref_chars, ref_paras, head_paras, signature_chars, words_min, words_max: measured on the user's template
    facts = cover_letter.template_facts()
    return {"subject": spec["subject"], "salutation": spec["salutation"], "paragraphs": spec["paragraphs"],
            "language": spec["language"], "closing": spec.get("closing") or cover_letter.CLOSING[spec["language"]],
            **facts, "edited": (LETTER_EDITS / f"{key}.json").exists()}


def cmd_letters_apply(args):
    """Rebuild the .docx of every letter the user edited in the dashboard (collection 'letters').
    Writes the status back via letters_batch.json (needs --versions for documents that exist)."""
    indir = Path(args.indir)
    docs = {}
    for f in indir.rglob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[f.stem] = d.get("data", d)
    versions = read_versions(args.versions) if args.versions else {}
    LETTER_EDITS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    writes, report = [], []
    for key, d in docs.items():
        if d.get("status") != "edited":
            continue
        base = base_letter_spec(key)
        if base is None:
            report.append(f"{key}: no generated letter to edit")
            continue
        spec = {**base, "subject": (d.get("subject") or base["subject"]).strip(),
                "salutation": (d.get("salutation") or base["salutation"]).strip(),
                "paragraphs": [x.strip() for x in d.get("paragraphs") or [] if x and x.strip()] or base["paragraphs"],
                "max_pages": d.get("max_pages") or base.get("max_pages") or 1}
        changed = (spec["paragraphs"], spec["subject"], spec["salutation"]) != \
            (base["paragraphs"], base["subject"], base["salutation"])
        if d.get("source") != "claude" and changed:     # the user's own wording: kept so the writing style can be learned from it
            log = STATE / "letter_edits_log.jsonl"
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"date": today(), "job_key": key, "company": base["company"], "role": base["role"],
                                    "generated": {"subject": base["subject"], "salutation": base["salutation"],
                                                  "paragraphs": base["paragraphs"]},
                                    "user": {"subject": spec["subject"], "salutation": spec["salutation"],
                                               "paragraphs": spec["paragraphs"]}}, ensure_ascii=False) + "\n")
        backup = Path(base["output"]).with_name(Path(base["output"]).stem + "_Vorschlag.docx")
        if Path(base["output"]).exists() and not backup.exists():
            shutil.copyfile(base["output"], backup)          # the generated version stays available
        built = cover_letter.build(spec)
        check = cover_letter.validate(built, spec)
        (LETTER_EDITS / f"{key}.json").write_text(json.dumps({"spec": spec, "edited_at": d.get("edited_at"),
                                                               "built_at": today(), "check": check},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
        status = {"status": "built" if check["ok"] else "invalid", "built_at": dt.datetime.now().isoformat(timespec="seconds"),
                  "check": {k: check[k] for k in ("ok", "errors", "warnings", "body_words", "pages")}}
        (out / f"{key}.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        w = {"op": "update", "collection": "letters", "doc_id": key, "file_path": str((out / f"{key}.json").resolve())}
        if key in versions:
            w["if_version"] = versions[key]
        writes.append(w)
        report.append(f"{key} {base['company']}: {status['status']} ({check['body_words']} words, {check['pages']})"
                      + (f" – {'; '.join(check['errors'])}" if check["errors"] else ""))
    for f in LETTER_EDITS.glob("*.json"):              # edit withdrawn in the dashboard: back to the generated letter
        if not args.full:                              # only a complete read of the collection may revert
            break
        if f.stem not in docs:
            base = base_letter_spec(f.stem)
            if base:
                backup = Path(base["output"]).with_name(Path(base["output"]).stem + "_Vorschlag.docx")
                if backup.exists():
                    backup.replace(base["output"])        # the generated version takes its place again
                else:
                    cover_letter.build(base)
            f.unlink()
            report.append(f"{f.stem}: edit withdrawn, generated letter restored")
    (out / "letters_batch.json").write_text(json.dumps(writes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"letters": report, "batch": str(out / "letters_batch.json") if writes else None}, ensure_ascii=False, indent=1))


LOCAL_APPLY = ROOT / "07_Logs" / "apply_local"     # git-ignored: holds contact data and file copies


def cv_file():
    """The unchanged CV as PDF (settings templates.cv_pdf), or None."""
    return settings.path(cfg()["templates"].get("cv_pdf"))


def to_pdf(docx_path):
    """PDF next to the .docx, or None if no PDF program works. The conversion lives in docs_pdf.py
    (engine: settings documents.pdf_engine); imported here so every other command runs without it."""
    try:
        import docs_pdf
    except ImportError:
        return None
    return docs_pdf.to_pdf(Path(docx_path))


def cmd_apply_package(args):
    """Everything the form-filling session needs for one job, written to a git-ignored folder."""
    conf = cfg()
    state = State()
    row = state.by_key.get(args.key)
    if row is None:
        raise SystemExit(f"unknown job_key {args.key}")
    details = {}
    for f in sorted((ROOT / "07_Logs" / "runs").glob("*/scored_final.json")):
        for j in json.loads(f.read_text(encoding="utf-8"))["jobs"]:
            if j.get("job_key") == args.key:
                details = j
    url = details.get("apply_url") or row["url"]
    st, ev = open_state(url)
    out = LOCAL_APPLY / args.key
    out.mkdir(parents=True, exist_ok=True)
    files, hints = [], []
    def add(label, path):
        if path and Path(path).exists():
            dest = out / Path(path).name
            if Path(path).resolve() != dest.resolve():      # the letter PDF is already built inside out/
                shutil.copyfile(path, dest)
            files.append({"label": label, "path": str(dest), "bytes": dest.stat().st_size,
                          "sha1": hashlib.sha1(dest.read_bytes()).hexdigest()[:12],
                          "modified": dt.datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%d.%m.%Y %H:%M")})
        else:
            hints.append(f"{label}: Datei fehlt oder konnte nicht erzeugt werden")
    if args.cv:                              # tailored CV for this job, else the current base CV in the posting's language
        import cv_tailor
        tailored = cv_tailor.tailored_for(args.key)
        if tailored:
            pdf = tailored.with_suffix(".pdf")
            add("Lebenslauf (auf die Stelle angepasst)", pdf if pdf.exists() else to_pdf(tailored))
        else:
            lang = details.get("posting_language") or "de"
            add("Lebenslauf", cv_tailor.base_pdf(lang) or cv_file())
    if args.cover_letter and row["cover_letter_path"]:
        letter = ROOT / row["cover_letter_path"]
        add("Anschreiben (.docx)", letter)
        if args.pdf and letter.exists():
            add("Anschreiben (PDF)", to_pdf(out / letter.name))
    # who applies: from the settings, so it does not depend on how the letter template is laid out
    sender = [x for x in (conf["person"].get("full_name"), conf["person"].get("city"), conf["mail"].get("address")) if x]
    package = {"job_key": args.key, "company": row["company"], "title": row["title"], "location": row["location"],
               "apply_url": url, "apply_email": apply_email(args.key, row), "open_state": st, "open_evidence": ev, "status": row["status"], "files": files,
               "hints": hints, "sender_block": sender, "answers": json.loads(args.answers) if args.answers else {},
               "profile": str((CONFIG / "candidate_profile.md").relative_to(ROOT))}
    (out / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in package.items() if k != "sender_block"} | {"package": str(out / "package.json")},
                     ensure_ascii=False, indent=1))


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
APPLY_WORDS = re.compile(r"bewerb|bewirb|unterlagen|application|apply|cv |resume|lebenslauf", re.I)


def job_text(key, row=None):
    """The stored posting text (05_Job_Descriptions) of a job, found by its URL, else ''."""
    row = row or State().by_key.get(key) or {}
    urls = {u for u in (row.get("url"), row.get("apply_url")) if u}
    for f in sorted((ROOT / "05_Job_Descriptions").rglob("*.md"), reverse=True):
        t = f.read_text(encoding="utf-8", errors="replace")
        if any(u in t for u in urls):
            return t
    return ""


def apply_email(key, row=None):
    """The address the posting asks applications to be sent to, if it names one (no form)."""
    text = job_text(key, row)
    for m in EMAIL_RE.finditer(text):
        around = text[max(0, m.start() - 160):m.end() + 40]
        if APPLY_WORDS.search(around) and not re.search(r"datenschutz|privacy|noreply|no-reply", around, re.I):
            return m.group(0).rstrip(".")
    return None


def _mail_body(lang, title, answers, swiss, name, extra=()):
    """Text of the application mail. name and extra (further signature lines such as address or
    phone) come from the settings; the wording itself is fixed and says nothing about the person."""
    start = ""
    hint, notice = (answers.get("hints") or "").strip(), (answers.get("notice") or "").strip()
    found = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", hint + " " + notice)
    if found:
        date = found.group(0)
        start = (f"Mein nächstmöglicher Eintrittstermin ist der {date}." if lang == "de"
                 else f"I could start on {date}.")
    elif notice:
        start = (f"Meine Kündigungsfrist beträgt {notice}." if lang == "de" else f"My notice period is {notice}.")
    sign = "\n".join([name] + [str(x) for x in extra if str(x).strip()])
    if lang == "de":
        lines = ["Sehr geehrte Damen und Herren,", "",
                 f"anbei sende ich Ihnen meine Bewerbung als {title}." + (f" {start}" if start else ""), "",
                 "Im Anhang finden Sie mein Anschreiben und meinen Lebenslauf.", "",
                 "Ich freue mich auf Ihre Rückmeldung.", "",
                 "Freundliche Grüsse" if swiss else "Mit freundlichen Grüßen"]
        text = "\n".join(lines)
        return (text.replace("ß", "ss") if swiss else text) + "\n" + sign     # Swiss spelling, the signature stays as written
    return "\n".join(["Dear Sir or Madam,", "",
                       f"Please find attached my application for the position of {title}." + (f" {start}" if start else ""), "",
                       "My cover letter and CV are attached.", "", "I look forward to hearing from you.", "",
                       "Kind regards"]) + "\n" + sign


def build_eml(sender_name, sender_address, to, subject, body, attachments):
    """An unsent message: the header X-Unsent: 1 makes mail programs open the file as a draft to edit."""
    import mimetypes
    from email.message import EmailMessage
    from email.utils import formataddr
    msg = EmailMessage()
    if sender_address:
        msg["From"] = formataddr((sender_name, sender_address))
    msg["To"], msg["Subject"], msg["X-Unsent"] = to, subject, "1"
    msg.set_content(body)
    for a in attachments:
        kind = mimetypes.guess_type(Path(a).name)[0] or "application/octet-stream"
        maintype, subtype = kind.split("/", 1)
        msg.add_attachment(Path(a).read_bytes(), maintype=maintype, subtype=subtype, filename=Path(a).name)
    return msg


def cmd_mail_draft(args):
    """An unsent draft with cover letter and CV as PDF, for postings that ask for applications by e-mail.
    mail.mode gmail: writes the arguments for the Gmail connector's create_draft to a JSON file; every other
    mode writes an .eml file with the header X-Unsent: 1. Both land in 07_Logs/apply_local/<key>/.
    Never sends: the user opens the draft, checks it and presses Send."""
    import mimetypes
    import cv_tailor
    conf = cfg()
    name = need(conf["person"].get("full_name"), "person.full_name in 01_Config/settings.yaml (Name unter der Bewerbungs-Mail)")
    mode = str(conf["mail"].get("mode") or "none").lower()
    state = State()
    row = state.by_key.get(args.key)
    if row is None:
        raise SystemExit(f"unknown job_key {args.key}")
    details = {}
    for f in sorted((ROOT / "07_Logs" / "runs").glob("*/scored_final.json")):
        for j in json.loads(f.read_text(encoding="utf-8"))["jobs"]:
            if j.get("job_key") == args.key:
                details = j
    to = (args.to or apply_email(args.key, row) or "").strip()
    if not to:
        raise SystemExit("Keine Bewerbungsadresse in der Anzeige gefunden – mit --to angeben.")
    if not EMAIL_RE.fullmatch(to):        # the address may come from a posting text: it is data, checked before use
        raise SystemExit(f"'{to[:80]}' ist keine gültige Mailadresse.")
    lang = args.lang or details.get("posting_language") or "de"
    out = LOCAL_APPLY / args.key
    out.mkdir(parents=True, exist_ok=True)
    attachments, hints = [], []
    if row["cover_letter_path"] and (ROOT / row["cover_letter_path"]).exists():
        letter = out / Path(row["cover_letter_path"]).name
        shutil.copyfile(ROOT / row["cover_letter_path"], letter)
        pdf = to_pdf(letter)
        if pdf is None:
            hints.append("Anschreiben nicht in PDF umgewandelt (documents.pdf_engine prüfen) – als .docx angehängt")
        attachments.append(pdf or letter)
    else:
        hints.append("Kein Anschreiben für diese Stelle vorhanden")
    tailored = cv_tailor.tailored_for(args.key)
    if tailored:
        cv = tailored.with_suffix(".pdf") if tailored.with_suffix(".pdf").exists() else to_pdf(tailored)
    else:
        cv = cv_tailor.base_pdf(lang) or cv_file()
    if cv and Path(cv).exists():
        dest = out / Path(cv).name
        if Path(cv).resolve() != dest.resolve():
            shutil.copyfile(cv, dest)
        attachments.append(dest)
    else:
        hints.append("Kein Lebenslauf als PDF gefunden (templates.cv_pdf in settings.yaml prüfen)")
    package = out / "package.json"
    answers = json.loads(package.read_text(encoding="utf-8")).get("answers", {}) if package.exists() else {}
    swiss = (row.get("country") or details.get("country")) == "CH"
    subject = (f"Bewerbung als {row['title']}" if lang == "de" else f"Application for {row['title']}")
    body = _mail_body(lang, row["title"], answers, swiss, name, conf["mail"].get("signature_lines") or [])
    try:                                 # wording check of the mail text; a finding is a hint, the draft is still written
        import humanizer
        hints += [f"Mailtext: {f['hint']} ({f['hit']})" for f in humanizer.audit(body, lang)]
    except ImportError:
        pass
    result = {"mode": mode, "to": to, "subject": subject, "attachments": [str(a) for a in attachments],
              "hints": hints, "sent": False}
    if args.dry_run:
        print(json.dumps(result | {"body": body}, ensure_ascii=False, indent=1))
        return
    if mode == "gmail":
        draft = {"to": [to], "subject": subject, "body": body,
                 "attachments": [{"filename": a.name, "mimeType": mimetypes.guess_type(a.name)[0] or "application/octet-stream",
                                  "content": base64.b64encode(a.read_bytes()).decode()} for a in attachments]}
        target = out / "gmail_draft.json"
        target.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        result |= {"draft_args": str(target),
                   "note": "Inhalt von draft_args an create_draft des Gmail-Connectors übergeben (nie senden); "
                           "du prüfst den Entwurf in Gmail und sendest selbst"}
    else:
        target = out / f"Bewerbung_{args.key}.eml"
        target.write_bytes(build_eml(name, conf["mail"].get("address"), to, subject, body, attachments).as_bytes())
        result |= {"eml": str(target),
                   "note": "Entwurf als .eml gespeichert – Datei im Mailprogramm öffnen, Anhänge prüfen; du sendest selbst"}
    print(json.dumps(result, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- replies to applications

def job_contacts():
    """Contact person per job key from the scored runs (the posting's 'Your contact person is ...')."""
    out = {}
    for f in sorted((ROOT / "07_Logs" / "runs").glob("*/scored_final.json")):
        for j in json.loads(f.read_text(encoding="utf-8")).get("jobs", []):
            if j.get("contact") and j.get("job_key"):
                out[j["job_key"]] = j["contact"]
    return out


def match_reply_fallback(rp, cands, rows, norm, contacts=None):
    """A reply without a role whose sender is named differently than the job's company. Unique hit wins, in this order:
    the posting's contact person in the sender, the sender's mail domain in the job URL, the one job with a letter."""
    alive = lambda rs: [r for r in rs if r["status"] not in ("DUPLICATE", "REJECTED", "EXPIRED", "CLOSED")]
    live = alive(cands or rows)          # contact and domain are specific enough to search all jobs
    sender = norm(rp.get("from"))
    contacts = job_contacts() if contacts is None else contacts
    hit = [r for r in live if contacts.get(r["job_key"]) and norm(contacts[r["job_key"]]) in sender]
    if len(hit) == 1:
        return hit[0]
    dom = re.search(r"@([a-z0-9.-]+)", (rp.get("from") or "").lower())
    label = dom.group(1).split(".")[-2] if dom and dom.group(1).count(".") >= 1 else ""
    if label and label not in ("gmail", "googlemail", "outlook", "t-online", "web", "gmx", "myworkday", "successfactors",
                               "greenhouse", "ashbyhq", "smartrecruiters", "personio", "workday", "dvinci", "softgarden"):
        hit = [r for r in live if label in (r.get("url") or "").lower()]
        if len(hit) == 1:
            return hit[0]
    hit = [r for r in alive(cands) if r.get("cover_letter_path")]   # same company only
    return hit[0] if len(hit) == 1 else None


def cmd_apply_replies(args):
    """Take over what companies answered (from the Gmail connector or a mail bridge, classified by the run).
    Input: {"replies": [{"job_key"?, "company", "role"?, "kind": confirmation|interview|declined|offer,
            "date", "source", "from", "subject", "evidence"}]}"""
    replies = json.loads(Path(args.infile).read_text(encoding="utf-8")).get("replies", [])
    state = State()
    events = read_csv(EVENTS)
    seen = {(e["job_key"], e["date"], e["kind"], e["subject"]) for e in events}
    last = {}
    for e in events:
        if e["job_key"] not in last or e["date"] >= last[e["job_key"]]["date"]:
            last[e["job_key"]] = e
    tracker = {r["job_key"]: r for r in read_csv(TRACKER)}
    applied, unmatched = [], []
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", fold(x or "")).strip()
    for rp in replies:
        kind = rp.get("kind")
        if kind not in REPLY_BOARD:
            unmatched.append({**rp, "why": "unknown kind"})
            continue
        row = state.by_key.get(rp.get("job_key") or "")
        if row is None:          # same company and (if a role is named) the same role words
            co = norm(rp.get("company"))
            words = set(norm(rp.get("role")).split()) - {"m", "w", "d", "f", "x", "all", "genders", "und", "and"}
            cands = [r for r in state.rows if co and r["status"] != "DUPLICATE"
                     and (co in norm(r["company"]) or norm(r["company"]).split(" ")[0] == co.split(" ")[0])]
            if words:
                scored = sorted(((len(words & set(norm(r["title"]).split())) / len(words), r) for r in cands),
                                key=lambda x: -x[0])
                row = scored[0][1] if scored and scored[0][0] >= 0.6 else None
            else:
                applied_cands = [r for r in cands if r["status"] == "APPLIED"]
                row = applied_cands[0] if len(applied_cands) == 1 else None
            if row is None:      # sender named differently than the job (a subsidiary or the group's HR service)
                row = match_reply_fallback(rp, cands, state.rows, norm)
        if row is None and rp.get("company") and rp.get("role"):
            # an application the user sent outside this system: track it from now on
            row = state.upsert({"company": rp["company"], "title": rp["role"], "location": rp.get("location") or "",
                                "country": rp.get("country") or "", "url": rp.get("url") or "", "source": "mail"},
                               origin="mail", notes="aus Bewerbungs-Mail übernommen")
        if row is None:
            unmatched.append({**rp, "why": "Stelle nicht eindeutig – im Dashboard selbst zuordnen"})
            continue
        key, date = row["job_key"], (rp.get("date") or today())[:10]
        if (key, date, kind, rp.get("subject") or "") in seen:
            continue
        prev = last.get(key)
        if prev and prev["date"] > date:
            continue
        if prev and prev["date"] == date and REPLY_RANK[kind] < REPLY_RANK.get(prev["kind"], 0):
            continue
        if prev and kind == "confirmation" and prev["kind"] in ("interview", "offer", "declined"):
            continue
        ev = {"job_key": key, "date": date, "kind": kind, "board": REPLY_BOARD[kind], "source": rp.get("source") or "",
              "sender": rp.get("from") or "", "subject": (rp.get("subject") or "")[:160],
              "evidence": (rp.get("evidence") or "")[:240], "recorded": today(), "synced": ""}
        events.append(ev)
        last[key] = ev
        seen.add((key, date, kind, ev["subject"]))
        row["status"] = "APPLIED"
        t = tracker.setdefault(key, {"job_key": key, "date_found": row["first_seen"], "company": row["company"],
                                     "role": row["title"], "location": row["location"], "country": row["country"],
                                     "job_url": row["url"], "match_score": row["match_score"]})
        t["application_status"] = {"confirmation": "APPLIED", "interview": "INTERVIEW",
                                   "declined": "DECLINED", "offer": "OFFER"}[kind]
        t["date_applied"] = t.get("date_applied") or date
        t["last_update"], t["notes"] = date, f"Mail {date}: {ev['subject']}"
        applied.append(f"{row['company']} – {row['title']}: {LABEL_KIND[kind]} (Mail vom {date})")
    state.save()
    write_csv(EVENTS, events, EVENT_COLS)
    write_csv(TRACKER, list(tracker.values()), TRACKER_COLS)
    run_dir = ROOT / "07_Logs" / "runs" / args.date
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "replies_applied.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"applied": [], "unmatched": []}
    old["applied"] += applied
    old["unmatched"] += [f"{u.get('company') or u.get('from')}: {u.get('subject')} ({u['why']})" for u in unmatched]
    out.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"applied": applied, "unmatched": old["unmatched"]}, ensure_ascii=False, indent=1))


LABEL_KIND = {"confirmation": "Eingangsbestätigung → Beworben", "interview": "Einladung → Im Gespräch",
              "declined": "Absage", "offer": "Zusage / Angebot"}


# ---------------------------------------------------------------- dashboard

# every newly reported job starts in "Neu"; the Merkliste is filled by the user in the dashboard
BOARD = {"RECOMMENDED": "new", "WATCHLIST": "new", "APPLIED": "applied", "REJECTED": "rejected",
         "EXPIRED": "closed"}
BOARD_TO_STATUS = {"applied": "APPLIED", "interview": "APPLIED", "offer": "APPLIED",
                   "rejected": "REJECTED", "declined": "APPLIED", "watch": "WATCHLIST"}
SYSTEM_ONLY = ("board", "applied_at", "note", "reopened")      # owned by the user in the dashboard


def read_versions(path):
    """doc_id -> version from the text an ArtifactData list returned (saved to a file by the run)."""
    text = Path(path).read_text(encoding="utf-8")
    pairs = re.findall(r'"([0-9a-f]{12})"\s+\d+ bytes\s+version (\d+)', text)
    pairs += re.findall(r'"([0-9a-f]{12})" (\d+)(?=[,\]])', text)
    return {k: int(v) for k, v in pairs}


def head_time_utc():
    """Commit time of HEAD in UTC (ISO, Z) - the newest state this checkout has merged.
    None when the workspace is no git checkout (or git is not installed): then there is nothing to guard."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct"], capture_output=True, text=True)
        ts = int(out.stdout.strip() or 0)
    except (OSError, ValueError):
        ts = 0
    if not ts:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


JOB_ID = re.compile(r"^[0-9a-f]{12}$")
RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]{1,40}$")
RUN_STATES = ("requested", "running", "done", "failed")


def ui_config(conf=None, profile=None):
    """The dashboard's document config/ui: tabs, role groups, the start button's token. Only settings
    that are no secret and that the page needs to draw itself; no address, no mail account, no path."""
    conf = conf or cfg()
    dash = conf.get("dashboard") or {}
    portals = [{"id": str(p["id"]).strip().lower(), "label": str(p.get("label") or p["id"]),
                "search_url": str(p.get("search_url") or "")}
               for p in dash.get("portals") or [] if isinstance(p, dict) and str(p.get("id") or "").strip()]
    segs = [dict(x) for x in segments(profile)]
    for tab in dash.get("segment_tabs") or []:      # a tab of its own for a role group, set in settings.yaml
        if not isinstance(tab, dict) or not str(tab.get("id") or "").strip():
            continue
        tid = str(tab["id"]).strip().lower()
        seg = next((x for x in segs if x["id"] == tid), None)
        if seg is None:
            seg = {"id": tid, "label": str(tab.get("label") or tid), "pattern": "", "own_tab": True}
            segs.append(seg)
        seg["own_tab"] = True
        if tab.get("label"):
            seg["label"] = str(tab["label"])
    name = str((conf.get("person") or {}).get("full_name") or "").split()
    return {"portals": portals, "segments": segs, "owner_label": name[0] if name else "",
            "trigger_token": str(dash.get("trigger_token") or ""),
            "language": str((conf.get("language") or {}).get("default") or "de")}


def run_requests(indir):
    """Start requests from the dashboard (collection run_requests) found in an export folder, oldest
    first: [{id, requested_at, status}]. Only an id of the fixed form, a timestamp and a known status
    are read – a request is data and carries nothing that could reach a run as an instruction."""
    out = []
    for f in sorted(Path(indir).rglob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        doc = doc.get("data", doc) if isinstance(doc, dict) else None
        if not isinstance(doc, dict):
            continue
        rid = doc.get("id") if isinstance(doc.get("id"), str) else f.stem
        requested = doc.get("requested_at")
        if not RUN_ID.match(rid) or doc.get("status") not in RUN_STATES or not isinstance(requested, str):
            continue
        try:
            dt.datetime.fromisoformat(requested.replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append({"id": rid, "requested_at": requested, "status": doc["status"]})
    return sorted(out, key=lambda r: (r["requested_at"], r["id"]))


RUN_NEXT = {"running": ("requested",), "done": ("requested", "running"), "failed": ("requested", "running")}


def run_request_updates(found, mark, ids=None, note="", now=None):
    """Batch entries that move requests to `mark`. A request is finished by its status (done/failed),
    never by deleting the document: the page shows the last run from it."""
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = re.sub(r"\s+", " ", str(note or "")).strip()[:120]
    out = []
    for r in found:
        if r["status"] not in RUN_NEXT[mark] or (ids is not None and r["id"] not in ids):
            continue
        data = {"status": mark, "status_note": note}
        data["started_at" if mark == "running" else "finished_at"] = now
        out.append({"op": "update", "collection": "run_requests", "doc_id": r["id"], "data": data})
    return out


def cmd_run_requests(args):
    """Prints the ids of the requests nobody has picked up yet as one compact JSON line and nothing else.
    With --mark and --out it also writes the status updates as a batch file for the dashboard db."""
    found = run_requests(args.indir)
    if args.mark:
        if not args.out:
            raise ConfigError("run-requests --mark braucht --out <Datei> für die Batch-Datei.")
        ids = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids else None
        Path(args.out).write_text(json.dumps(run_request_updates(found, args.mark, ids, args.note), ensure_ascii=False),
                                  encoding="utf-8")
    print(json.dumps([r["id"] for r in found if r["status"] == "requested"], separators=(",", ":")))


def letter_slots(slots, city="", lang="de"):
    """templates.cover_letter_slots (locators of cover_letter.py) in the shape the dashboard reads when it
    rebuilds a letter: indexes of the body's paragraphs, body_end exclusive. None when the slots are not
    set or use something the page cannot follow (a nested table, a body that ends with the last paragraph
    counted from the end): the page then falls back to the stored file."""
    slots = slots or {}
    def index(loc):
        m = re.fullmatch(r"p:(-?\d+)", str(loc or "").strip())
        return int(m.group(1)) if m else None
    first, last, salutation = index(slots.get("body_first")), index(slots.get("body_last")), index(slots.get("salutation"))
    if first is None or last is None or salutation is None or last == -1:
        return None
    out = {"salutation": salutation, "body_start": first, "body_end": last + 1}
    for key in ("subject", "closing"):
        if slots.get(key):
            if index(slots[key]) is None:
                return None
            out[key] = index(slots[key])
    date = slots.get("date")
    if not date:
        out["date"] = None                               # the template has no date line
    elif index(date) is not None:
        out["date"] = {"paragraph": index(date)}
    else:
        m = re.fullmatch(r"tbl:(-?\d+):(-?\d+):(-?\d+)(?::(-?\d+))?", str(date).strip())
        if not m:
            return None
        out["date"] = {"table": int(m.group(1)), "row": int(m.group(2)), "cell": int(m.group(3)), "paragraph": int(m.group(4) or 0)}
    fmt = slots.get("date_format")
    fmt = fmt.get(lang) if isinstance(fmt, dict) else fmt
    if fmt and out["date"] is not None:                  # the text in front of the first date field
        prefix = re.split(r"\{(?:d|dd|m|mm|month|yyyy|yy)\}", str(fmt), maxsplit=1)[0].replace("{city}", city or "")
        out["date_prefix"] = (prefix if city else re.sub(r"^\s*,\s*", "", prefix))[:60]
    return out


def cv_name(key, lang):
    """File name of the CV that goes with this job (tailored one first), or "". Nothing is converted here."""
    try:
        import cv_tailor
        tailored = cv_tailor.tailored_for(key)
        if tailored:
            return tailored.with_suffix(".pdf").name
        base = cv_tailor.base_pdf(lang or "de", convert=False)
    except (ImportError, SystemExit, OSError, ValueError):
        base = None
    base = base or cv_file()
    return Path(base).name if base else ""


def cmd_dashboard_export(args):
    """One JSON file per job for the dashboard db (collection 'jobs'), the document config/ui, plus a manifest."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    details = {}
    for f in sorted((ROOT / "07_Logs" / "runs").glob("*/scored_final.json")):
        for j in json.loads(f.read_text(encoding="utf-8"))["jobs"]:
            details[j["job_key"]] = j
    manifest = []
    # documents already in the dashboard db (from an ArtifactData list with out_dir): update instead of set
    existing, existing_ui = {}, None
    if args.existing:
        for f in Path(args.existing).rglob("*.json"):
            if f.stem == "versions":
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            if f.stem == "ui" and isinstance(d, dict):
                existing_ui = d.get("data", d)
            if not JOB_ID.match(f.stem) or not isinstance(d, dict):   # config/ui, run_requests: no job documents
                continue
            existing[f.stem] = d.get("data", d)
    versions = read_versions(args.versions) if args.versions else {}
    missing = [k for k in existing if k not in versions]
    if existing and missing:
        raise SystemExit(f"dashboard-export: no version for {len(missing)} existing documents – save the list "
                         "result text and pass it with --versions (writes to existing documents need if_version)")
    events = read_csv(EVENTS)
    latest = {}                          # the newest mail per job decides; older ones are history
    for e in events:
        if e["job_key"] not in latest or (e["date"], REPLY_RANK.get(e["kind"], 0)) >= \
                (latest[e["job_key"]]["date"], REPLY_RANK.get(latest[e["job_key"]]["kind"], 0)):
            latest[e["job_key"]] = e
    pending = {k: e for k, e in latest.items() if not e["synced"]}
    oldest = (dt.date.today() - dt.timedelta(days=PORTAL_DAYS)).isoformat()
    low_oldest = (dt.date.today() - dt.timedelta(days=LOW_DAYS)).isoformat()
    unchanged, skipped = 0, []
    # --guard-newer (daily run): a document exported after this checkout's last commit was written from a
    # newer state (a local session) - never overwrite it from here; pull, re-read, re-export.
    guard = head_time_utc() if getattr(args, "guard_newer", False) else None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    segs = segments()
    conf = cfg()
    slot_cfg, home = conf["templates"].get("cover_letter_slots") or {}, conf["person"].get("city") or ""
    for r in State().rows:
        prev = existing.get(r["job_key"])
        if guard and prev and str(prev.get("exported_at") or "") > guard:
            skipped.append(r["job_key"])
            continue
        portal = r["status"] == "REVIEWED" and r.get("origin") in PORTALS and r["first_seen"] >= oldest
        low = (r["status"] == "REVIEWED" and not portal and bool(r["match_score"])      # scored from the posting,
               and (r.get("score_basis") or "posting") != "alert"                     # below the threshold
               and max(r["report_date"] or "", r["last_seen"] or "") >= low_oldest and r.get("open_state") != "closed")
        if r["status"] not in BOARD and not portal and not low and r["job_key"] not in existing:
            continue
        j = details.get(r["job_key"], {})
        doc = {"key": r["job_key"], "company": r["company"], "title": r["title"],
               "location": r["location"], "country": r["country"], "industry": r["industry"],
               "url": r["url"], "apply_url": j.get("apply_url") or r["url"],
               "posted_date": r["posted_date"], "first_seen": r["first_seen"],
               "report_date": r["report_date"], "score": float(r["match_score"] or 0),
               "category": r["match_category"], "recommendation": r["recommendation"],
               "chance": float(r["chance_score"]) if r.get("chance_score") else None,
               "must_haves": j.get("must_haves") or [], "focus_note": j.get("focus_note") or "",
               "salary_text": r["salary_text"], "salary_status": r["salary_status"],
               "visa": r["visa"], "relocation": r["relocation"], "remote": r["remote"],
               "is_ai": r["is_ai_role"] == "True", "stretch": r["stretch"] == "True",
               "why_fit": j.get("why_fit", ""), "main_gap": j.get("main_gap", ""),
               "scores": j.get("scores", {}), "skills": j.get("skills", {}),
               "arguments": j.get("arguments", []), "weaknesses": j.get("weaknesses", []),
               "screening_risks": j.get("screening_risks", []),
               "experience_required": j.get("experience_required") or "",
               "language": j.get("posting_language") or "", "system_status": r["status"],
               "origin": r.get("origin") or "", "seen_on": r.get("seen_on") or "",
               "score_basis": r.get("score_basis") or "posting", "portal_url": j.get("portal_url") or "",
               "salary_estimate_xing": j.get("salary_estimate_xing") or "", "alert_name": j.get("alert_name") or "",
               "other_locations": j.get("other_locations") or [], "skip_reason": j.get("skip_reason") or "",
               "segment": segment_of({**r, **{k: v for k, v in j.items() if k in ("segment", "is_ai_role", "industry")}}, segs),
               "open_state": r.get("open_state") or "", "open_checked": r.get("open_checked") or "",
               "cover_letter_name": "", "cover_letter_b64": ""}
        if r["status"] == "REVIEWED" and not portal and not low:     # an old alert or low job: no longer listed
            doc["system_status"] = "EXPIRED"
        mails = sorted((e["date"], e["kind"]) for e in events if e["job_key"] == r["job_key"])
        if mails:                        # for the "Auswertung" tab: when the company first confirmed and first answered
            conf = [d for d, k in mails if k == "confirmation"]
            reply = [d for d, k in mails if k in ("interview", "declined", "offer")]
            if conf:
                doc["confirmed_at"] = conf[0]
            if reply:
                doc["replied_at"] = reply[0]
        if r["cover_letter_path"] and (ROOT / r["cover_letter_path"]).exists():
            p = ROOT / r["cover_letter_path"]
            doc["cover_letter_name"] = p.name
            doc["cover_letter_b64"] = base64.b64encode(p.read_bytes()).decode()
            doc["letter"] = letter_field(r["job_key"])
            shape = letter_slots(slot_cfg, home, doc["language"] or conf["language"].get("default") or "de")
            if shape:                    # where the page finds subject, salutation, body and date in this file
                doc["letter_slots"] = shape
            name = cv_name(r["job_key"], doc["language"])
            if name:
                doc["cv_name"] = name
        board = "portal" if portal else "low" if low else ("watch" if r.get("origin") == "manual" and r["recommendation"] == "SKIP"
                                         and r["status"] == "WATCHLIST" else BOARD.get(r["status"], "closed"))
        update = dict(doc)
        if existing.get(r["job_key"], {}).get("board") in ("portal", "low") and board not in ("portal", "low", "closed"):
            update["board"] = board      # "portal"/"low" are set by the system: a promoted job moves to "Neu"
        ev = pending.get(r["job_key"])
        if ev:                           # a company mail moves the job (the user can still move it back)
            update["board"] = board = ev["board"]
            update["status_note"] = doc["status_note"] = f"Laut Mail vom {fmt_de(ev['date'])}: {ev['subject']}"
            first = min(e["date"] for e in events if e["job_key"] == r["job_key"])   # the earliest mail ~ applied
            if not existing.get(r["job_key"], {}).get("applied_at"):
                update["applied_at"] = first
            for e in events:
                if e["job_key"] == r["job_key"] and not e["synced"]:
                    e["synced"] = today()
        old = existing.get(r["job_key"])
        if old is not None and all(old.get(k) == v for k, v in update.items()):
            unchanged += 1
            continue
        update["exported_at"] = doc["exported_at"] = stamp     # not part of the change check above
        (out / f"{r['job_key']}.json").write_text(json.dumps(update, ensure_ascii=False), encoding="utf-8")
        # 'board', 'applied_at' and 'note' belong to the user: set once, never updated by a run
        (out / f"{r['job_key']}.new.json").write_text(
            json.dumps({**doc, "board": board, "applied_at": update.get("applied_at", "") if ev else "",
                        "note": ""}, ensure_ascii=False),
            encoding="utf-8")
        exists = r["job_key"] in existing
        entry = {"op": "update" if exists else "set", "collection": "jobs", "doc_id": r["job_key"],
                 "file_path": str((out / f"{r['job_key']}{'' if exists else '.new'}.json").resolve())}
        if exists and versions:
            entry["if_version"] = versions[r["job_key"]]
        manifest.append(entry)
    write_csv(EVENTS, events, EVENT_COLS)
    ui = ui_config()
    ui_state = "unchanged"
    if existing_ui != ui:                # the page reads its tabs and role groups from this one document
        (out / "config_ui.json").write_text(json.dumps(ui, ensure_ascii=False), encoding="utf-8")
        entry = {"op": "set", "collection": "config", "doc_id": "ui", "file_path": str((out / "config_ui.json").resolve())}
        if existing_ui is not None and args.versions:
            found = re.search(r'"ui"\s+\d+ bytes\s+version (\d+)|"ui" (\d+)(?=[,\]])',
                              Path(args.versions).read_text(encoding="utf-8"))
            if found:
                entry["if_version"] = int(found.group(1) or found.group(2))
        manifest.append(entry)
        ui_state = "written"
    batches = [manifest[i:i + 50] for i in range(0, len(manifest), 50)]
    for n, b in enumerate(batches, 1):
        (out / f"batch_{n}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"changed": len(manifest), "unchanged": unchanged, "skipped_newer": skipped, "config_ui": ui_state,
                      "set": sum(m["op"] == "set" for m in manifest),
                      "update": sum(m["op"] == "update" for m in manifest),
                      "batches": [str(out / f"batch_{n}.json") for n in range(1, len(batches) + 1)]}, indent=1))


def cmd_dashboard_import(args):
    """Read documents exported from the dashboard db and take over the user's decisions."""
    state, changes = State(), []
    pending = [r["id"] for r in run_requests(args.indir) if r["status"] == "requested"]
    for f in sorted(Path(args.indir).rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc = doc.get("data", doc) if isinstance(doc, dict) else None
        # only job documents carry decisions; config/ui and run_requests are handled elsewhere
        if not isinstance(doc, dict) or not JOB_ID.match(str(doc.get("key") or "")):
            continue
        key, board = doc.get("key"), doc.get("board")
        row = state.by_key.get(key)
        target = BOARD_TO_STATUS.get(board)
        if row is not None and row["status"] == "EXPIRED" and target != "APPLIED":
            continue             # a posting that is gone is never reactivated from the dashboard
        if board == "new" and row is not None and row["status"] in ("APPLIED", "REJECTED", "REVIEWED"):
            # taken back or promoted in the dashboard ("Doch nicht beworben", "Wieder aufnehmen", "In Neu übernehmen")
            target = "RECOMMENDED" if row["recommendation"] == "APPLY" else "WATCHLIST"
            if row["status"] == "REJECTED":
                write_csv(REJECTED, [r for r in read_csv(REJECTED) if r["job_key"] != key], REJECTED_COLS)
        if row is None or target is None or row["status"] == target:
            continue
        note = (doc.get("note") or "") + (f" [dashboard: {board}]" if board not in ("applied", "rejected") else "")
        apply_status(state, key, target, note.strip(), (doc.get("applied_at") or "")[:10] or None)
        changes.append(f"{row['company']} – {row['title']}: {target} ({board})")
    state.save()
    print(json.dumps({"changes": changes, "run_requests": pending}, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- selftest

def cmd_selftest(_args):
    """Checks the logic with fixtures of its own, so it passes in a fresh workspace whose config
    still holds placeholders. Nothing is fetched, nothing in the workspace is changed."""
    import tempfile
    a = {"company": "Muster AG", "title": "Projektmanager (m/w/d)", "location": "Düsseldorf, DE",
         "url": "https://www.example.com/jobs/123/?utm_source=x&gh_jid=9"}
    b = {"company": "muster", "title": "Projektmanager", "location": "Dusseldorf",
         "url": "https://example.com/jobs/123?gh_jid=9&ref=li"}
    c = {"company": "Muster", "title": "Projektmanager", "location": "Bremen"}
    assert job_key(a) == job_key(b), "same job, different spelling must share a key"
    assert job_key(a) != job_key(c), "different city must be a different job"
    assert city("Überlingen am Bodensee").startswith(city("Überlingen")), "city variants must be comparable"
    segs = segments({"segments": [
        {"id": "shift", "label": "Schichtmodell", "pattern": r"wechselschicht|\bschicht", "own_tab": True},
        {"id": "energy", "label": "Energie", "pattern": r"solar|wind|energie"},
        {"id": "quality", "label": "Qualität", "pattern": r"qualit|audit|systems engineer"},
        {"id": "program", "label": "Programm", "pattern": r"program|project|projekt"},
        {"id": "transformation", "label": "Transformation", "pattern": r"consult|process|change"},
        {"id": "broken"}]})                                   # no pattern: ignored
    assert [x["id"] for x in segs] == ["shift", "energy", "quality", "program", "transformation"] and segs[0]["own_tab"]
    assert segment_of({"title": "Qualitätsingenieur Solar"}, segs) == "energy"
    assert segment_of({"title": "Qualitätsmanager (m/w/d)"}, segs) == "quality"
    assert segment_of({"title": "Technical Program Manager"}, segs) == "program"
    assert segment_of({"title": "Project Manager AI", "is_ai_role": True}, segs) == "ai"
    assert segment_of({"title": "Senior Consultant Process Excellence"}, segs) == "transformation"
    assert segment_of({"title": "IT Systems Engineer, Platform Management"}, segs) == "quality"
    assert segment_of({"title": "Organizational Change Manager"}, segs) == "transformation"
    assert segment_of({"title": "Applikationsingenieur Windkraft (m/w/d)"}, segs) == "energy"
    assert segment_of({"title": "Projektingenieur | Schicht 8/6"}, segs) == "shift"
    assert segment_of({"title": "Systems Engineer", "segment": "shift"}, segs) == "shift"
    assert segment_of({"title": "Koch"}, segs) == "other"
    default = segments({})
    assert [x["id"] for x in default] == [x["id"] for x in DEFAULT_SEGMENTS], "empty list: the neutral default"
    assert segment_of({"title": "Technical Project Manager"}, default) == "program"
    feed = {"title_include": ["integration"], "title_exclude": ["fitter"]}
    assert title_ok("Integration Lead", {"title_include": ["manager"]}, {}, feed)
    assert not title_ok("Integration Fitter", {"title_include": ["manager"]}, {}, feed)
    assert not title_ok("Integration Lead", {"title_include": ["manager"]}, {})
    assert canonical_url(a["url"]) == canonical_url(b["url"]), "tracking parameters must be ignored"
    profile = {"scoring_weights": {"fachlich": 0.30, "transfer": 0.20, "senioritaet": 0.15, "compensation": 0.15,
                                   "standort": 0.10, "strategie": 0.10},
               "daily_selection": {"target_new_jobs": [5, 8], "max_stretch": 3, "min_score_report": 7.0,
                                   "apply_threshold": 8.5, "strategic_band": [8.0, 8.4], "max_ai_share": 0.4},
               "focus": {"penalty": 0.5, "note": "", "deprioritized_titles": ["quality engineer", "systems engineer"],
                         "exempt_terms": ["solar"]},
               "title_include": ["projekt", "manager"], "title_exclude": ["werkstudent"],
               "core_role_terms": ["office manager", "projekt"],
               "banned_reason_patterns": [r"ohne (fach|branchen)[- ]", r"über der ebene"]}
    rules = {"targets": {"CH": {"currency": "CHF", "min": 120000}, "SE": {"currency": "SEK", "min": 650000, "salary_required": True}},
             "default": {"currency": "EUR", "min": 60000}, "hours_per_year": 1976, "days_per_year": 230,
             "fx_to_eur": {"EUR": 1.0, "CHF": 1.05, "SEK": 0.088},
             "compensation_score": {"VERIFIED_meets": [8.0, 10.0], "LIKELY": 7.0, "UNKNOWN": 5.5, "BELOW_TARGET": 2.0},
             "unknown_neutral": True, "below_target_tolerance": 0.95, "score_cap_below_target": 7.9}
    assert abs(sum(profile["scoring_weights"].values()) - 1.0) < 1e-9, "weights must sum to 1"
    try:                                   # the workspace's own weights, once the profile is filled in
        own = load_yaml("search_profile.yaml").get("scoring_weights") or {}
        assert not own or abs(sum(float(v) for v in own.values()) - 1.0) < 1e-9, "scoring_weights in search_profile.yaml must sum to 1"
    except ConfigError:
        pass
    base = {"company": "X", "title": "Y", "country": "DE", "recommendation": "APPLY",
            "scores": {"fachlich": 9, "transfer": 9, "senioritaet": 9, "standort": 9, "strategie": 9}}
    unknown = score_job(json.loads(json.dumps(base)), profile, rules)
    assert unknown["salary_status"] == "UNKNOWN" and unknown["match_score"] == 9.0, unknown["match_score"]   # no salary stated is neutral
    low = score_job({**json.loads(json.dumps(base)), "salary_text": "50k",
                     "salary": {"status": "VERIFIED", "min": 45000, "max": 50000, "currency": "EUR"}}, profile, rules)
    assert low["salary_status"] == "BELOW_TARGET" and low["match_score"] <= 7.9 and low["recommendation"] != "APPLY"
    hourly = salary_assess({"country": "CH", "salary": {"status": "VERIFIED", "min": 70, "max": 80, "currency": "CHF", "period": "hour"}}, rules)
    assert hourly[0] == "VERIFIED", hourly        # 70-80 CHF/h x 1976 h is above 120,000 CHF
    low_hourly = salary_assess({"country": "CH", "salary": {"status": "VERIFIED", "min": 40, "max": 45, "currency": "CHF", "period": "hour"}}, rules)
    assert low_hourly[0] == "BELOW_TARGET", low_hourly
    guess = score_job({**json.loads(json.dumps(base)), "salary": {"status": "LIKELY"}}, profile, rules)
    assert guess["salary_status"] == "UNKNOWN", "LIKELY without evidence must fall back to UNKNOWN"
    blocked = score_job({**json.loads(json.dumps(base)), "hard_blocker": "citizenship"}, profile, rules)
    assert blocked["recommendation"] == "SKIP"
    assert title_ok("Projektmanager (m/w/d)", profile, {}) and not title_ok("Werkstudent Projekt", profile, {})
    st = State.__new__(State)
    st.rows = [{c: "" for c in MASTER_COLS} | {"job_key": "k1", "company": "Beispiel Consulting", "title": "AI Manager", "location": "Munich",
                                              "portal_url": "https://www.linkedin.com/jobs/view/42/", "alias_keys": job_key(c)}]
    st.by_key, st.by_url = {"k1": st.rows[0]}, {canonical_url("https://www.linkedin.com/jobs/view/42/"): st.rows[0]}
    st.by_alias = {job_key(c): st.rows[0]}
    assert st.find({"company": "Beispiel Consulting DACH", "title": "AI Manager", "location": "Berlin",
                    "portal_url": "https://www.linkedin.com/comm/jobs/view/42/?x=1".replace("/comm", "")})[0] is st.rows[0]
    assert st.find(c)[0] is st.rows[0], "alias keys must identify a renamed alert job"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        v = tmp / "selftest_versions.txt"
        v.write_text('- "0071568fc50a"  1474 bytes  version 3\n[2 more …: "6f0cb4d47bb1" 1, "73bd697d6fa1" 2]', encoding="utf-8")
        assert read_versions(v) == {"0071568fc50a": 3, "6f0cb4d47bb1": 1, "73bd697d6fa1": 2}, read_versions(v)
        # start requests from the dashboard: only well-formed ones count, the oldest first
        req = tmp / "run_requests"
        req.mkdir()
        for name, doc in {"run_20260102T080000Z": {"id": "run_20260102T080000Z", "requested_at": "2026-01-02T08:00:00.000Z", "status": "requested"},
                          "run_20260101T080000Z": {"data": {"id": "run_20260101T080000Z", "requested_at": "2026-01-01T08:00:00Z", "status": "requested"}},
                          "run_20260101T070000Z": {"id": "run_20260101T070000Z", "requested_at": "2026-01-01T07:00:00Z", "status": "done"},
                          "run_bad": {"id": "run_x; rm -rf", "requested_at": "2026-01-01T07:00:00Z", "status": "requested"},
                          "run_nodate": {"id": "run_nodate", "requested_at": "sofort", "status": "requested"},
                          "0071568fc50a": {"key": "0071568fc50a", "board": "watch"}}.items():
            (req / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
        found = run_requests(tmp)
        assert [r["id"] for r in found if r["status"] == "requested"] == ["run_20260101T080000Z", "run_20260102T080000Z"], found
        assert len(found) == 3
        ups = run_request_updates(found, "running", now="2026-01-02T09:00:00Z")
        assert [u["doc_id"] for u in ups] == ["run_20260101T080000Z", "run_20260102T080000Z"] and ups[0]["op"] == "update"
        assert ups[0]["data"] == {"status": "running", "status_note": "", "started_at": "2026-01-02T09:00:00Z"}
        fin = run_request_updates(found, "failed", {"run_20260102T080000Z"}, "x" * 200, "2026-01-02T09:30:00Z")
        assert len(fin) == 1 and len(fin[0]["data"]["status_note"]) == 120 and fin[0]["data"]["finished_at"]
        # an application mail as an unsent file
        att = tmp / "Anschreiben.pdf"
        att.write_bytes(b"%PDF-1.4 test")
        eml = build_eml("Erika Mustermann", "erika@example.com", "jobs@example.com", "Bewerbung als Projektleiterin", "Text", [att])
        assert eml["X-Unsent"] == "1" and eml["To"] == "jobs@example.com" and "Erika Mustermann" in eml["From"]
        assert [x.get_filename() for x in eml.iter_attachments()] == ["Anschreiben.pdf"]
    body = _mail_body("de", "Projektleiterin", {"notice": "3 Monate"}, True, "Erika Mustermann", ["Musterstraße 1", ""])
    assert "Freundliche Grüsse\nErika Mustermann\nMusterstraße 1" in body and "Kündigungsfrist beträgt 3 Monate" in body, body
    assert _mail_body("en", "Project Manager", {"hints": "frei ab 01.03.2027"}, False, "Erika Mustermann").endswith("Kind regards\nErika Mustermann")
    ui = ui_config({"person": {"full_name": "Erika Mustermann"}, "language": {"default": "en"},
                    "mail": {"address": "erika@example.com"},
                    "dashboard": {"url": "https://example.com/d", "trigger_token": "abc12345",
                                  "portals": [{"id": "Indeed", "label": "Indeed", "search_url": "https://de.indeed.com/jobs?q={q}"}, {"label": "ohne id"}],
                                  "segment_tabs": [{"id": "program", "label": "Projekte"}]}}, {"segments": []})
    assert sorted(ui) == ["language", "owner_label", "portals", "segments", "trigger_token"], "config/ui carries UI settings only"
    assert ui["owner_label"] == "Erika" and ui["language"] == "en" and [x["id"] for x in ui["portals"]] == ["indeed"]
    assert next(x for x in ui["segments"] if x["id"] == "program") | {"pattern": ""} == {"id": "program", "label": "Projekte", "pattern": "", "own_tab": True}
    assert "example.com/d" not in json.dumps(ui) and "erika@" not in json.dumps(ui)
    shape = letter_slots({"subject": "p:3", "salutation": "p:4", "body_first": "p:5", "body_last": "p:-3", "closing": "p:-2",
                          "signature": "p:-1", "date": "tbl:0:0:1", "date_format": {"de": "{city}, {d}. {month} {yyyy}"}}, "Musterstadt", "de")
    assert shape == {"subject": 3, "salutation": 4, "body_start": 5, "body_end": -2, "closing": -2,
                     "date": {"table": 0, "row": 0, "cell": 1, "paragraph": 0}, "date_prefix": "Musterstadt, "}, shape
    assert letter_slots({"salutation": "p:1", "body_first": "p:2", "body_last": "p:4", "date": "p:0"}) == \
        {"salutation": 1, "body_start": 2, "body_end": 5, "date": {"paragraph": 0}}
    assert letter_slots({}) is None and letter_slots({"salutation": "p:1", "body_first": "p:2", "body_last": "p:-1"}) is None
    assert letter_slots({"salutation": "tbl:0:0:0/tbl:0:0:0", "body_first": "p:2", "body_last": "p:4"}) is None
    mine = banned_patterns(profile)
    assert banned_reason("AI Strategy Manager (Muster SE, Musterstadt): AI-/KI-Fokusrolle ohne Branchenbezug")
    assert banned_reason("Beispiel GmbH: nicht über 7,0 realistisch (Prozessrolle ohne Fach- oder Methodenbezug)", mine)
    assert not banned_reason("Beispiel GmbH: nicht über 7,0 realistisch (Prozessrolle ohne Fach- oder Methodenbezug)"), "own patterns only with the profile"
    assert banned_reason("Program Manager (Beispiel AG, Musterstadt): Alert ohne Detailanzeige, vermutlich über der Ebene des Profils")
    assert not banned_reason("Project Manager (Muster GmbH, Wien): Österreich ohne belegte Umzugshilfe", mine)
    sev = {"fachlich": 7, "transfer": 7, "senioritaet": 7, "standort": 7, "strategie": 7}
    assert score_job({"company": "X", "title": "Y", "country": "DE", "scores": dict(sev)}, profile, rules)["match_score"] == 7.0, "unknown salary is neutral"
    assert score_job({"company": "X", "title": "Y", "country": "SE", "scores": dict(sev)}, profile, rules)["match_score"] < 7.0, "salary_required: a stated salary is needed"
    assert search_documented("Versuche: Workday db: kein Treffer; Karriereseite 404; WebSearch nur Aggregatoren")
    assert not search_documented("Nur Alert-Zeile, Originalanzeige nicht gelesen.")
    assert not search_documented("Versuche: ATS/Karriereseite: in diesem Lauf nicht abgefragt; WebSearch: nicht versucht; "
                                 "Alert-Mail: nur Titel, Firma, Ort gelesen")
    core = core_role(profile)
    assert core.search("Office Manager & Assistenz") and not core.search("Softwareentwickler SAP")
    assert core_role({"title_include": ["projekt"]}).search("Projektleiter") and not core_role({}).search("Projektleiter")
    rows = [{"job_key": "a", "status": "WATCHLIST", "company": "MUSTERWERK group", "url": "https://jobs.musterwerkgroup.example/x",
             "cover_letter_path": "x.docx"},
            {"job_key": "b", "status": "REVIEWED", "company": "MUSTERWERK group", "url": "https://jobs.musterwerkgroup.example/y",
             "cover_letter_path": ""}]
    nm = lambda x: re.sub(r"[^a-z0-9]+", " ", fold(x or "")).strip()
    assert match_reply_fallback({"from": "Max Beispiel (Musterwerkgroup)"}, rows, rows, nm, {"a": "Max Beispiel"})["job_key"] == "a"
    assert match_reply_fallback({"from": "HR <jobs@musterwerkgroup.example>"}, rows, rows, nm, {})["job_key"] == "a"   # letter
    assert match_reply_fallback({"from": "x"}, [], rows, nm, {}) is None
    h = INDEED_SUBJECT.match("Senior Technical Project Manager (all genders) bei Muster GmbH")
    assert h and h["company"] == "Muster GmbH" and h["title"].startswith("Senior Technical")
    assert reason_core("A (X, Berlin): Führungsrolle über der Ebene") == reason_core("B (Y, Köln): Führungsrolle  über der Ebene")
    assert open_state("https://www.linkedin.com/jobs/view/1/")[0] == "unknown", "portal links are never fetched"
    assert not any(m in _visible_text("<p>Auch wenn Du nicht mehr aktiv entwickelst</p>") for m in CLOSED_MARKERS)
    assert any(m in _visible_text("<p>Das gewünschte Inserat ist nicht mehr aktiv</p>") for m in CLOSED_MARKERS)
    assert "no longer available" in _visible_text("<p>This job is <b>no longer available</b></p><script>x='no'</script>")
    assert "nicht mehr verfügbar" not in _visible_text("<script>t='nicht mehr verfügbar'</script><p>Bewerben</p>")
    assert REPLY_BOARD["declined"] == "declined" and REPLY_RANK["confirmation"] < REPLY_RANK["interview"]
    mh = [{"req": "a", "status": "met"}, {"req": "b", "status": "partial"}, {"req": "c", "status": "missing"}, {"req": "d", "status": "met"}]
    assert chance_score({"must_haves": mh}) == 6.3 and chance_score({}) is None, "chance = met + half partial, scaled to 10"
    assert chance_score({"must_haves": mh[:2] + [{"req": "US work permit", "status": "missing", "blocker": True}]}) == 3.0
    assert focus_penalty({"title": "Lead Quality Engineer (all genders)"}, profile) == 0.5
    assert focus_penalty({"title": "Quality Engineer Solar (m/w/d)"}, profile) == 0.0, "an exempt term lifts the deduction"
    assert focus_penalty({"title": "Office Manager"}, profile) == 0.0
    assert focus_penalty({"title": "Systems Engineer"}, {}) == 0.0, "no focus section: no deduction"
    assert score_job({"company": "X", "title": "Systems Engineer", "country": "DE", "scores": dict(sev)}, profile, rules)["match_score"] == 6.5
    assert cover_letter.salutation_problem("Sehr geehrte Frau Mustermann,", "de") is None
    assert cover_letter.salutation_problem("Guten Tag Erika Mustermann,", "de"), "never first and last name"
    assert cover_letter.salutation_problem("Dear Erika Mustermann,", "en"), "never first and last name"
    page = ROOT / "10_Dashboard" / "jobsuche_cockpit.html"
    if page.exists():                      # the dashboard is optional; where it is installed its boards must be known
        dashboard = page.read_text(encoding="utf-8")
        for b in set(re.findall(r'move\("[^"]+", "(\w+)"', dashboard)) | {"watch", "new"}:
            assert b in BOARD_TO_STATUS or b in ("new", "closed"), f"dashboard board '{b}' unknown to dashboard-import"
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch"); p.add_argument("--date", default=today()); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("detail"); p.add_argument("--keys", required=True); p.add_argument("--date", default=today()); p.set_defaults(fn=cmd_detail)
    p = sub.add_parser("mail-candidates"); p.add_argument("--date", default=today()); p.add_argument("--days", type=int, default=None, help="default: mail.days_back in settings.yaml")
    p.set_defaults(fn=cmd_mail_candidates)
    p = sub.add_parser("indeed-mails"); p.add_argument("--in", dest="infile", required=True); p.add_argument("--date", default=today())
    p.add_argument("--location-hint", default=""); p.set_defaults(fn=cmd_indeed_mails)
    p = sub.add_parser("dedup"); p.add_argument("--in", dest="infile", required=True); p.add_argument("--out"); p.set_defaults(fn=cmd_dedup)
    p = sub.add_parser("finalize"); p.add_argument("--in", dest="infile", required=True); p.add_argument("--date", default=today())
    p.add_argument("--append", action="store_true", help="(default) add to the jobs already finalized for this date")
    p.add_argument("--replace", action="store_true", help="discard the jobs already finalized for this date")
    p.add_argument("--no-open-check", action="store_true", help="skip the availability check (offline tests only)")
    p.set_defaults(fn=cmd_finalize)
    p = sub.add_parser("set-status"); p.add_argument("--key", required=True); p.add_argument("--status", required=True)
    p.add_argument("--note"); p.add_argument("--date"); p.set_defaults(fn=cmd_set_status)
    p = sub.add_parser("check-open"); p.add_argument("--in", dest="infile"); p.set_defaults(fn=cmd_check_open)
    p = sub.add_parser("letters-apply"); p.add_argument("--in", dest="indir", required=True)
    p.add_argument("--out", required=True); p.add_argument("--versions")
    p.add_argument("--full", action="store_true", help="--in holds the whole 'letters' collection: letters missing there were withdrawn and are reverted")
    p.set_defaults(fn=cmd_letters_apply)
    p = sub.add_parser("apply-package"); p.add_argument("--key", required=True)
    p.add_argument("--cv", action="store_true"); p.add_argument("--cover-letter", action="store_true")
    p.add_argument("--pdf", action="store_true", help="also convert the cover letter to PDF (engine: documents.pdf_engine)")
    p.add_argument("--answers", help="JSON with the user's answers from the dashboard (salary, notice, start)")
    p.set_defaults(fn=cmd_apply_package)
    p = sub.add_parser("mail-draft"); p.add_argument("--key", required=True)
    p.add_argument("--to", help="application address (default: read from the stored posting)")
    p.add_argument("--lang", choices=["de", "en"]); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_mail_draft)
    p = sub.add_parser("backlog"); p.add_argument("--date", default=today()); p.set_defaults(fn=cmd_backlog)
    p = sub.add_parser("apply-replies"); p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--date", default=today()); p.set_defaults(fn=cmd_apply_replies)
    p = sub.add_parser("dashboard-export"); p.add_argument("--out", required=True); p.add_argument("--existing")
    p.add_argument("--versions", help="file with the text of the ArtifactData list result (doc ids and versions)")
    p.add_argument("--guard-newer", action="store_true",
                   help="daily run: skip documents exported after this checkout's last commit (written from a newer state)")
    p.set_defaults(fn=cmd_dashboard_export)
    p = sub.add_parser("dashboard-import"); p.add_argument("--in", dest="indir", required=True); p.set_defaults(fn=cmd_dashboard_import)
    p = sub.add_parser("run-requests"); p.add_argument("--in", dest="indir", required=True)
    p.add_argument("--mark", choices=sorted(RUN_NEXT), help="also write the status updates for the requests as a batch file")
    p.add_argument("--ids", help="comma-separated request ids for --mark (default: every request the status may follow)")
    p.add_argument("--note", default="", help="status_note for --mark, at most 120 characters")
    p.add_argument("--out", help="batch file for --mark"); p.set_defaults(fn=cmd_run_requests)
    p = sub.add_parser("selftest"); p.set_defaults(fn=cmd_selftest)
    args = ap.parse_args()
    try:
        args.fn(args)
    except ConfigError as e:             # missing or unfilled config: one line, no traceback
        print(f"Abbruch: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
