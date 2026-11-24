#!/usr/bin/env python3
"""The dashboard on this computer, for assistants that cannot publish a claude.ai artifact.

  python 08_Scripts/dashboard_local.py serve [--port 8765] [--open]   serve the page on 127.0.0.1
  python 08_Scripts/dashboard_local.py apply-batch FILE [FILE ...]     apply batch files of jobsearch.py
  python 08_Scripts/dashboard_local.py versions --collection jobs --out FILE   versions of one collection (for --versions)
  python 08_Scripts/dashboard_local.py run-status --id ID --status running|done|failed [--note TEXT]
  python 08_Scripts/dashboard_local.py selftest

The page is the same file as the published one (10_Dashboard/jobsuche_cockpit.html). A small script
put in front of it provides window.claude.use("db" | "downloads") on top of this server; the
documents live as JSON files in 02_State/dashboard_db/<collection>/<id>.json ({"version", "data"}),
the layout `jobsearch.py dashboard-import --in` and `dashboard-export --existing` read.

Safety: the server listens on 127.0.0.1 only, answers only requests addressed to that name
(no DNS rebinding), and accepts a write only with the session key built into the page it served
(no other website can write). The page may write only what the published page writes; config is
read-only. A start request carries nothing into the run: the button calls run_local.start_requested(),
whose text is a constant.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

ROOT = cfg.ROOT
STORE = ROOT / "02_State" / "dashboard_db"
PAGE = ROOT / "10_Dashboard" / "jobsuche_cockpit.html"
COLLECTIONS = ("jobs", "letters", "apply_requests", "config", "run_requests")
# what the page itself may do; everything else is written by the scripts (apply-batch, run-status)
PAGE_WRITES = {"jobs": ("update",), "letters": ("set", "delete"), "apply_requests": ("set", "delete"),
               "run_requests": ("set",)}
DOC_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RUN_ID = re.compile(r"^run_[A-Za-z0-9_-]{1,40}$")
RUN_STATES = ("requested", "running", "done", "failed")
MAX_BODY = 4 * 1024 * 1024
DEFAULT_PORT = 8765
LOCK = threading.Lock()


# ---------------------------------------------------------------- store

def _file(col, doc_id):
    if col not in COLLECTIONS or not DOC_ID.match(doc_id or ""):
        raise ValueError("unknown collection or document id")
    return STORE / col / f"{doc_id}.json"


def read_doc(col, doc_id):
    """(version, data) or (0, None) when the document does not exist."""
    try:
        raw = json.loads(_file(col, doc_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, None
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        return 0, None
    return int(raw.get("version") or 1), raw["data"]


def _write(col, doc_id, version, data):
    target = _file(col, doc_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"version": version, "data": data}, handle, ensure_ascii=False)
    os.replace(tmp, target)


def write_doc(col, doc_id, op, data=None, if_version=None):
    """set | update | delete. Returns (ok, code). update needs an existing document, as on the platform."""
    with LOCK:
        version, current = read_doc(col, doc_id)
        if if_version is not None and current is not None and int(if_version) != version:
            return False, "version_conflict"
        if op == "delete":
            _file(col, doc_id).unlink(missing_ok=True)
            return True, "deleted"
        if not isinstance(data, dict):
            return False, "invalid_argument"
        if op == "update":
            if current is None:
                return False, "not_found"
            data = {**current, **data}
        elif op != "set":
            return False, "invalid_argument"
        _write(col, doc_id, version + 1, data)
        return True, "written"


def list_docs(col):
    folder = STORE / col
    out = []
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        version, data = read_doc(col, f.stem) if DOC_ID.match(f.stem) else (0, None)
        if data is not None:
            out.append({"id": f.stem, "version": version, "data": data})
    return out


def signature(col):
    """Changes whenever a document of the collection changes; cheap enough to ask every few seconds."""
    folder = STORE / col
    h = hashlib.sha256()
    if folder.is_dir():
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if entry.name.endswith(".json"):
                st = entry.stat()
                h.update(f"{entry.name}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- commands for the run

def apply_batch(files):
    """Apply the batch files written by `jobsearch.py dashboard-export` / `letters-apply`."""
    done, failed = 0, []
    for name in files:
        entries = json.loads(Path(name).read_text(encoding="utf-8"))
        entries = entries.get("writes", []) if isinstance(entries, dict) else entries
        for e in entries:
            try:
                data = None
                if e.get("op") != "delete":
                    data = e["data"] if "data" in e else json.loads(Path(e["file_path"]).read_text(encoding="utf-8"))
                ok, code = write_doc(e["collection"], e["doc_id"], e.get("op"), data, e.get("if_version"))
            except (OSError, ValueError, KeyError) as err:
                ok, code = False, type(err).__name__
            if ok:
                done += 1
            else:
                failed.append({"collection": e.get("collection"), "doc_id": e.get("doc_id"), "code": code})
    return {"written": done, "failed": failed}


def versions_text(only=None):
    """One line per collection in the form jobsearch.py's --versions reads: ["id" version,...].
    Jobs and letters share their ids, so a file for --versions holds one collection (only=...)."""
    lines = []
    for col in [only] if only else COLLECTIONS:
        lines.append(f"{col}: [" + ",".join(f'"{d["id"]}" {d["version"]}' for d in list_docs(col)) + "]")
    return "\n".join(lines) + "\n"


def run_status(run_id, status, note=""):
    if not RUN_ID.match(run_id or "") or status not in RUN_STATES:
        return False, "invalid_argument"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    patch = {"status": status, "status_note": str(note or "")[:120]}
    patch["started_at" if status == "running" else "finished_at"] = stamp
    if status == "requested":
        patch = {"status": status}
    return write_doc("run_requests", run_id, "update", patch)


def start_requested_run(run_id):
    """The button was pressed: open the assistant with the fixed text. Never raises."""
    try:
        import run_local
        ok, message = run_local.start_requested()
    except Exception as err:                           # missing program, broken settings
        ok, message = False, f"Der Lauf ließ sich nicht starten ({type(err).__name__})."
    if not ok:
        run_status(run_id, "failed", message)
    return ok, message


# ---------------------------------------------------------------- page

SHIM = r"""<script>
/* Local stand-in for the data access the published page gets from claude.ai. */
(function () {
  const KEY = "__SESSION__";
  const call = (path, body) => fetch(path, { method: body ? "POST" : "GET", cache: "no-store",
    headers: body ? { "Content-Type": "application/json", "X-Jobsuche-Session": KEY } : {}, body: body ? JSON.stringify(body) : undefined });
  const watchers = {};
  function poll(col) {
    const w = watchers[col];
    call("/api/db/" + col + "?sig=" + encodeURIComponent(w.sig)).then((r) => r.status === 204 ? null : r.ok ? r.json() : Promise.reject(r.status))
      .then((res) => {
        w.failed = false;
        if (!res) return;
        w.sig = res.sig;
        const snap = { docs: res.docs.map((d) => ({ id: d.id, exists: true, data: () => d.data, metadata: { fromCache: false, hasPendingWrites: false } })) };
        w.next.forEach((fn) => fn(snap));
      })
      .catch(() => { if (!w.failed) { w.failed = true; w.err.forEach((fn) => fn && fn({ code: "unavailable" })); } });
  }
  function write(path, op, data) {
    const [col, id] = path.split("/");
    return call("/api/db/" + col + "/" + encodeURIComponent(id), { op, data }).then((r) => r.json().then((res) => {
      if (!r.ok) return Promise.reject({ code: res.code || "unavailable", message: res.code || "" });
      if (watchers[col]) poll(col);
    }));
  }
  const db = {
    collection(col) {
      return { onSnapshot(next, err) {
        const w = watchers[col] || (watchers[col] = { sig: "", next: [], err: [], failed: false, timer: setInterval(() => poll(col), 3000) });
        w.next.push(next); w.err.push(err); w.sig = ""; poll(col);
        return () => { w.next = w.next.filter((fn) => fn !== next); };
      } };
    },
    doc(path) { return { set: (d) => write(path, "set", d), update: (d) => write(path, "update", d), delete: () => write(path, "delete") }; }
  };
  const downloads = { save(file) {
    // the start signal needs no file here: the server starts the run when the request is stored
    if (/^jobsuche-start-.*\.trigger$/.test(String(file && file.filename))) return Promise.resolve();
    const a = document.createElement("a"), url = URL.createObjectURL(file.data);
    a.href = url; a.download = file.filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return Promise.resolve();
  } };
  window.claude = { use: (name) => Promise.resolve(name === "db" ? db : name === "downloads" ? downloads : null) };
})();
</script>
"""


def page_html(session):
    html = PAGE.read_text(encoding="utf-8")
    shim = SHIM.replace("__SESSION__", session)
    at = html.find("<script")
    return shim + html if at < 0 else html[:at] + shim + html[at:]


class Handler(BaseHTTPRequestHandler):
    server_version = "JobsucheLokal"
    session = ""
    port = DEFAULT_PORT
    starter = staticmethod(start_requested_run)

    def log_message(self, *_args):                      # no request log: paths carry document ids
        pass

    def _send(self, status, body=b"", kind="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _local(self):
        """Only requests addressed to this computer by name; a foreign page's request is refused."""
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.lower() in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}")

    def do_GET(self):
        if not self._local():
            return self._json(403, {"code": "forbidden"})
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            try:
                return self._send(200, page_html(self.session).encode("utf-8"), "text/html; charset=utf-8")
            except OSError:
                return self._send(500, "Die Seite 10_Dashboard/jobsuche_cockpit.html fehlt.".encode("utf-8"),
                                  "text/plain; charset=utf-8")
        parts = url.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "db"] and parts[2] in COLLECTIONS:
            sig = signature(parts[2])
            if (parse_qs(url.query).get("sig") or [""])[0] == sig:
                return self._send(204)
            docs = [{"id": d["id"], "data": d["data"]} for d in list_docs(parts[2])]
            return self._json(200, {"sig": sig, "docs": docs})
        return self._json(404, {"code": "not_found"})

    def do_POST(self):
        if not self._local() or not secrets.compare_digest(self.headers.get("X-Jobsuche-Session") or "", self.session):
            return self._json(403, {"code": "forbidden"})
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if len(parts) != 4 or parts[:2] != ["api", "db"] or not 0 < length <= MAX_BODY:
            return self._json(400, {"code": "invalid_argument"})
        col, doc_id = parts[2], parts[3]
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return self._json(400, {"code": "invalid_argument"})
        op = body.get("op") if isinstance(body, dict) else None
        if op not in PAGE_WRITES.get(col, ()) or not DOC_ID.match(doc_id):
            return self._json(403, {"code": "permission_denied"})
        data = body.get("data")
        if col == "run_requests":                       # only a fresh request of the fixed form, never a status change
            if not (RUN_ID.match(doc_id) and isinstance(data, dict) and data.get("status") == "requested"
                    and isinstance(data.get("requested_at"), str) and len(data["requested_at"]) <= 40
                    and read_doc(col, doc_id)[1] is None):
                return self._json(400, {"code": "invalid_argument"})
            data = {"requested_at": data["requested_at"], "status": "requested", "source": "dashboard"}
        ok, code = write_doc(col, doc_id, op, data)
        if not ok:
            return self._json(404 if code == "not_found" else 400, {"code": code})
        if col == "run_requests":
            threading.Thread(target=self.starter, args=(doc_id,), daemon=True).start()
        return self._json(200, {"ok": True})


def make_server(port, session=None, starter=None):
    handler = type("BoundHandler", (Handler,), {"session": session or secrets.token_urlsafe(24), "port": port})
    if starter is not None:
        handler.starter = staticmethod(starter)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]             # port 0 in tests: the one the system chose
    return server


def serve(port, open_browser=False):
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Dashboard läuft: {url}  (beenden mit Strg+C)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------- selftest

def selftest():
    """Runs against a temporary folder and a server on a free port; the workspace is not touched."""
    global STORE, PAGE
    import urllib.error
    import urllib.request
    keep = STORE, PAGE
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    with tempfile.TemporaryDirectory() as tmp:
        STORE, PAGE = Path(tmp) / "db", Path(tmp) / "page.html"
        PAGE.write_text("<title>t</title>\n<script>var page = 1;</script>", encoding="utf-8")
        key = "0123456789ab"
        doc_file = Path(tmp) / "doc.json"
        doc_file.write_text(json.dumps({"key": key, "board": "new"}), encoding="utf-8")
        batch = Path(tmp) / "batch_1.json"
        batch.write_text(json.dumps([{"op": "set", "collection": "jobs", "doc_id": key, "file_path": str(doc_file)},
                                     {"op": "update", "collection": "jobs", "doc_id": "ffffffffffff", "data": {"a": 1}}]),
                         encoding="utf-8")
        res = apply_batch([batch])
        check("batch: set written, update of a missing document refused",
              res["written"] == 1 and res["failed"][0]["code"] == "not_found")
        check("versions text carries id and version", f'"{key}" 1' in versions_text("jobs") and key not in versions_text("letters"))
        check("stale if_version refused", write_doc("jobs", key, "update", {"x": 1}, if_version=7) == (False, "version_conflict"))
        check("matching if_version accepted", write_doc("jobs", key, "update", {"x": 1}, if_version=1)[0]
              and read_doc("jobs", key) == (2, {"key": key, "board": "new", "x": 1}))
        check("path tricks refused", _raises(lambda: _file("jobs", "../x")) and _raises(lambda: _file("secrets", "a")))

        started = []
        server = make_server(0, session="sess", starter=lambda rid: started.append(rid))
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def req(path, body=None, headers=None):
            r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                       headers=headers or {}, method="POST" if body is not None else "GET")
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, resp.read().decode("utf-8")
            except urllib.error.HTTPError as err:
                return err.code, err.read().decode("utf-8")

        ok = {"X-Jobsuche-Session": "sess", "Content-Type": "application/json"}
        status, html = req("/")
        check("page served with the data access in front of its first script",
              status == 200 and 0 < html.find("window.claude") < html.find("var page") and '"sess"' in html)
        status, body = req("/api/db/jobs")
        listing = json.loads(body)
        check("collection listed", status == 200 and listing["docs"][0]["id"] == key)
        check("unchanged collection answers 204", req("/api/db/jobs?sig=" + listing["sig"])[0] == 204)
        check("write without the session key refused", req(f"/api/db/jobs/{key}", {"op": "update", "data": {"board": "watch"}},
                                                           {"Content-Type": "application/json"})[0] == 403)
        check("request from a foreign page refused", req(f"/api/db/jobs/{key}", {"op": "update", "data": {"board": "watch"}},
                                                         {**ok, "Origin": "https://example.com"})[0] == 403)
        check("request under a foreign host name refused", req("/api/db/jobs", None, {"Host": "example.com"})[0] == 403)
        check("page may update a job", req(f"/api/db/jobs/{key}", {"op": "update", "data": {"board": "watch"}}, ok)[0] == 200
              and read_doc("jobs", key)[1]["board"] == "watch")
        check("changed collection is sent again", req("/api/db/jobs?sig=" + listing["sig"])[0] == 200)
        check("page may not replace or delete a job", req(f"/api/db/jobs/{key}", {"op": "set", "data": {}}, ok)[0] == 403
              and req(f"/api/db/jobs/{key}", {"op": "delete"}, ok)[0] == 403)
        check("page may not write the config", req("/api/db/config/ui", {"op": "set", "data": {"a": 1}}, ok)[0] == 403)
        check("update of a missing job answers 404", req("/api/db/jobs/aaaaaaaaaaaa", {"op": "update", "data": {"a": 1}}, ok)[0] == 404)
        rid = "run_20260101T000000000Z"
        status, _ = req(f"/api/db/run_requests/{rid}", {"op": "set", "data": {
            "requested_at": "2026-01-01T00:00:00.000Z", "status": "requested", "source": "dashboard", "prompt": "x"}}, ok)
        for _ in range(50):
            if started:
                break
            threading.Event().wait(0.02)
        check("start request stored without extra fields and the run started once",
              status == 200 and started == [rid] and sorted(read_doc("run_requests", rid)[1]) == ["requested_at", "source", "status"])
        check("a second write to the same request refused", req(f"/api/db/run_requests/{rid}", {"op": "set", "data": {
            "requested_at": "2026-01-01T00:00:00.000Z", "status": "requested"}}, ok)[0] == 400 and started == [rid])
        check("page cannot set a run to done", req("/api/db/run_requests/run_x", {"op": "set", "data": {
            "requested_at": "2026-01-01T00:00:00.000Z", "status": "done"}}, ok)[0] == 400)
        check("run-status finishes the request and keeps the document",
              run_status(rid, "done", "n" * 200)[0] and read_doc("run_requests", rid)[1]["status"] == "done"
              and len(read_doc("run_requests", rid)[1]["status_note"]) == 120 and "finished_at" in read_doc("run_requests", rid)[1])
        check("run-status refuses an id of another form", run_status("../x", "done") == (False, "invalid_argument"))
        check("letters: set and delete", req(f"/api/db/letters/{key}", {"op": "set", "data": {"status": "edited"}}, ok)[0] == 200
              and req(f"/api/db/letters/{key}", {"op": "delete"}, ok)[0] == 200 and read_doc("letters", key)[1] is None)
        big = {"op": "set", "data": {"t": "x" * (MAX_BODY + 10)}}
        try:
            too_big = req(f"/api/db/letters/{key}", big, ok)[0] == 400
        except OSError:                                 # the server may close the connection before the body is sent
            too_big = True
        check("oversized body refused", too_big and read_doc("letters", key)[1] is None)
        server.shutdown()
        server.server_close()
    STORE, PAGE = keep
    for name, good in checks:
        print(("OK   " if good else "FEHLER ") + name)
    passed = sum(good for _, good in checks)
    print(f"{passed} von {len(checks)} OK")
    return passed == len(checks)


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int)
    p.add_argument("--open", action="store_true")
    p = sub.add_parser("apply-batch")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("versions")
    p.add_argument("--out", required=True)
    p.add_argument("--collection", required=True, choices=COLLECTIONS)
    p = sub.add_parser("run-status")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=RUN_STATES[1:])
    p.add_argument("--note", default="")
    sub.add_parser("selftest")
    args = parser.parse_args()
    if args.cmd == "serve":
        port = args.port or int((cfg.load().get("dashboard") or {}).get("local_port") or DEFAULT_PORT)
        serve(port, args.open)
    elif args.cmd == "apply-batch":
        res = apply_batch(args.files)
        print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        sys.exit(1 if res["failed"] else 0)
    elif args.cmd == "versions":
        Path(args.out).write_text(versions_text(args.collection), encoding="utf-8")
        print(json.dumps({args.collection: len(list_docs(args.collection))}, separators=(",", ":")))
    elif args.cmd == "run-status":
        ok, code = run_status(args.id, args.status, args.note)
        print(code)
        sys.exit(0 if ok else 1)
    else:
        sys.exit(0 if selftest() else 1)


if __name__ == "__main__":
    main()
