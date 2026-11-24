#!/usr/bin/env python3
"""Browser test of the dashboard page against an in-memory database (tests/mock.js).

Usage:
    python run.py                  headless Chrome/Edge/Chromium if found, else the default browser
    python run.py --browser PATH   a Chromium-family binary to run headless
    python run.py --browse PATH    the gstack "browse" binary
    python run.py --open           the default browser, visible (close the tab yourself)
    python run.py --make-fixture   rebuild tests/letter_fixture.docx and .json (needs python-docx)

The page is assembled in a temporary folder (fixtures, mock.js, the page, test.js), served on
127.0.0.1 and reports its own results back to this script. Prints one FAIL line per failed check,
then "N von N OK". The .docx the page builds is opened with python-docx when that is installed.
Exit code 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "jobsuche_cockpit.html"
FIXTURE_DOCX = HERE / "letter_fixture.docx"
FIXTURE_JSON = HERE / "letter_fixture.json"

# ---- neutral letter fixture -------------------------------------------------------------------
NAME = "ERIKA MUSTERMANN"
ADDRESS_RUNS = ["Musterstraße 1", " · ", "12345 Musterstadt", " · ", "erika.mustermann@example.com"]
KEYWORD_LINE = "PROJEKTLEITUNG · ANFORDERUNGEN · BEISPIELZEILE"   # removed by the rebuild (letter_slots.remove)
OLD_DATE = "Musterstadt, 2 January 2024"
SUBJECT = "Application as Project Manager Digital Services (m/f/d)"
SALUTATION = "Dear Ms Muster,"
BODY = [
    "Muster GmbH is moving its customer services onto one shared platform, and the role you describe "
    "sits exactly where that work gets decided: between the people who know the processes and the "
    "teams who build the software. That is the place where I have worked for the past six years.",
    "At Beispiel AG I led a programme that replaced four regional order systems with a single one. "
    "I gathered the requirements from eleven departments, turned them into a backlog the developers "
    "could plan with, and kept the scope stable through three releases. The last site went live two "
    "weeks ahead of plan.",
    "What I bring to a project like yours is a habit of writing things down early. Before any line "
    "of code was written, every requirement had an owner, an acceptance test and a reason. This made "
    "later change requests short discussions instead of long ones, and it gave the steering "
    "committee a plain view of cost and progress each month.",
    "I also enjoy the part of the work that happens after go-live. For the order platform I set up "
    "the first support rota, trained forty key users and tracked the open defects until the backlog "
    "was empty. Two of those key users now run the platform themselves.",
    "I would be glad to learn more about your roadmap and to show how my experience fits your "
    "plans. I can start after a notice period of three months and am happy to travel to Musterstadt "
    "for a conversation at any time that suits you.",
]
CLOSING = "Yours sincerely,"
SIGNATURE_RUNS = ["Erika ", "Mustermann"]


def make_fixture() -> int:
    """Writes the letter fixture: name, address, keyword line, 1x2 date table, subject, salutation,
    five body paragraphs, closing, signature - the positional layout the page falls back to."""
    try:
        import docx
        from docx.shared import Emu, Pt
    except ImportError:
        print("FAIL python-docx fehlt: pip install python-docx")
        return 2
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Emu(7560310), Emu(10692130)   # A4
    sec.left_margin = sec.right_margin = Emu(756285)
    sec.top_margin = sec.bottom_margin = Emu(558165)
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_paragraph().add_run(NAME).bold = True
    p = d.add_paragraph()
    for part in ADDRESS_RUNS:
        p.add_run(part)
    d.add_paragraph(KEYWORD_LINE)
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[1].paragraphs[0].add_run(OLD_DATE)
    d.add_paragraph().add_run(SUBJECT).bold = True
    d.add_paragraph(SALUTATION)
    for text in BODY:
        d.add_paragraph(text)
    d.add_paragraph(CLOSING)
    p = d.add_paragraph()
    for part in SIGNATURE_RUNS:
        p.add_run(part)
    d.save(str(FIXTURE_DOCX))
    signature = "".join(SIGNATURE_RUNS)
    after_head = [KEYWORD_LINE, SUBJECT, SALUTATION, *BODY, CLOSING, signature]
    letter = {
        "subject": SUBJECT, "salutation": SALUTATION, "paragraphs": BODY, "language": "en", "closing": CLOSING,
        # page budget of the reference letter: characters and paragraph count the one-page check compares with
        "ref_chars": sum(len(t) for t in after_head) + 400, "ref_paras": 12, "head_paras": 3,
        "signature_chars": len(signature), "words_min": 250, "words_max": 400, "edited": True,
    }
    FIXTURE_JSON.write_text(json.dumps(letter, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    words = len(" ".join(BODY).split())
    print(f"OK Fixture geschrieben: {FIXTURE_DOCX.name}, {FIXTURE_JSON.name} ({words} Wörter)")
    return 0


# ---- test page --------------------------------------------------------------------------------
HARNESS = """<script>
(function () {
  var sent = false;
  var timer = setInterval(function () {
    if (sent || document.title !== "DONE") return;
    sent = true; clearInterval(timer);
    fetch("/result", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results: window.__results || [], docx: window.__lastDocxB64 || "" }) });
  }, 200);
})();
</script>"""


def build_page(target: Path) -> None:
    letter = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    docx_b64 = base64.b64encode(FIXTURE_DOCX.read_bytes()).decode("ascii")
    for name in ("mock.js", "test.js"):
        shutil.copyfile(HERE / name, target / name)
    fixture = json.dumps(letter, ensure_ascii=False).replace("<", "\\u003c")
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>[hidden]{display:none!important}</style>"
        "<script>try { localStorage.clear(); } catch (e) {}\n"
        f'window.__LETTER_FIXTURE = {fixture}; window.__DOCX_FIXTURE = "{docx_b64}";</script>'
        '<script src="mock.js"></script></head><body>\n'
        + PAGE.read_text(encoding="utf-8")
        + '\n<script src="test.js"></script>\n' + HARNESS + "\n</body></html>\n"
    )
    (target / "index.html").write_text(html, encoding="utf-8")


def serve(root: Path, box: dict, done: threading.Event) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_POST(self):   # the page posts its results exactly once
            length = min(int(self.headers.get("Content-Length") or 0), 20_000_000)
            raw = self.rfile.read(length)
            if self.path == "/result" and not done.is_set():
                try:
                    box.update(json.loads(raw.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    box["error"] = "Ergebnis nicht lesbar"
                done.set()
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def find_chromium() -> str | None:
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge", "microsoft-edge"]
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    home = Path.home()
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidates += [Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe"]
    return next((str(c) for c in candidates if c.is_file()), None)


def open_with_browse(binary: str, url: str, cwd: Path) -> None:
    # cwd: the tool keeps its state folder (.gstack) in the working directory, which must not be the skill
    def run(*flags: str) -> subprocess.CompletedProcess:
        return subprocess.run([binary, *flags, "goto", url], cwd=str(cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    out = run()
    if "mismatch" in (out.stdout + out.stderr):   # the headless build does not fit this machine: visible window
        run("--headed")


def check_docx(data_b64: str, folder: Path) -> tuple[bool | None, str]:
    """The .docx built in the browser must open in python-docx with the fixture's layout."""
    try:
        import docx
    except ImportError:
        return None, "python-docx nicht installiert – Prüfung der Browser-Datei übersprungen"
    try:
        path = folder / "browser.docx"
        path.write_bytes(base64.b64decode(data_b64))
        d = docx.Document(str(path))
        p = [x.text for x in d.paragraphs]
        ok = (p[0] == NAME and p[1].startswith("Musterstraße") and KEYWORD_LINE not in p
              and "Im Browser frisch gebaut." in "\n".join(p)
              and d.tables[0].rows[0].cells[-1].text.startswith("Musterstadt, ") and OLD_DATE not in d.tables[0].rows[0].cells[-1].text)
        return ok, "python-docx öffnet die Browser-Datei: " + " | ".join(x[:25] for x in p[:4])
    except Exception as e:   # any failure to open or read the file is a failed check
        return False, f"python-docx öffnet die Browser-Datei: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Browser test of the dashboard page")
    ap.add_argument("--browse", default=os.environ.get("JOBSUCHE_BROWSE"), help="gstack browse binary")
    ap.add_argument("--browser", default=os.environ.get("JOBSUCHE_BROWSER"), help="Chromium-family binary, run headless")
    ap.add_argument("--open", action="store_true", help="use the default browser (visible)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds to wait for the page")
    ap.add_argument("--make-fixture", action="store_true", help="rebuild the letter fixture and exit")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.make_fixture:
        return make_fixture()
    for needed in (PAGE, FIXTURE_DOCX, FIXTURE_JSON, HERE / "mock.js", HERE / "test.js"):
        if not needed.is_file():
            print(f"FAIL Datei fehlt: {needed}")
            return 2

    with tempfile.TemporaryDirectory(prefix="jobsuche_dashtest_", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp) / "site"
        root.mkdir()
        build_page(root)
        box: dict = {}
        done = threading.Event()
        server = serve(root, box, done)
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        proc = None
        try:
            chromium = None if (args.open or args.browse) else (args.browser or find_chromium())
            if args.browse and not args.open:
                open_with_browse(os.path.expanduser(args.browse), url, root)
            elif chromium:
                proc = subprocess.Popen(
                    [chromium, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                     f"--user-data-dir={Path(tmp) / 'profile'}", url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(url)
            finished = done.wait(args.timeout)
        finally:
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            server.shutdown()
            server.server_close()
        if not finished or "error" in box:
            print("FAIL Kein Ergebnis vom Browser" + (f" ({box['error']})" if "error" in box else f" nach {args.timeout} s"))
            return 2
        results = [r for r in box.get("results", []) if isinstance(r, list) and len(r) >= 2]
        for r in results:
            if not r[1]:
                print(f"FAIL {r[0]} → {r[2] if len(r) > 2 else ''}")
        passed = sum(1 for r in results if r[1])
        print(f"{passed} von {len(results)} OK")
        docx_ok, text = check_docx(box.get("docx") or "", Path(tmp))
        print(("HINWEIS " if docx_ok is None else "OK " if docx_ok else "FAIL ") + text)
        return 0 if results and passed == len(results) and docx_ok is not False else 1


if __name__ == "__main__":
    sys.exit(main())
