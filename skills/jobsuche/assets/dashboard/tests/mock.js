// In-memory stand-in for claude.use("db") and claude.use("downloads") that behaves like the platform:
// snapshot data is frozen, update() merges into an existing document asynchronously and rejects for a
// missing one. Used by test.js (run with tests/run.py or tests/run.sh).
// The config below is the built-in default plus one segment with its own tab ("schicht"), a separate
// search lane: with it the page must behave like a dashboard that has such a lane hard-wired.
(function () {
  const now = Date.now(), day = 86400000;
  const iso = (d) => new Date(now - d * day).toISOString().slice(0, 10);
  const base = (key, title, extra) => Object.assign({ key, company: "Firma " + key, title, location: "Musterstadt", country: "DE",
    score: 8.1, recommendation: "CONSIDER", salary_status: "UNKNOWN", first_seen: iso(1), report_date: iso(1),
    system_status: "RECOMMENDED", board: "new", applied_at: "", note: "", origin: "", scores: { fachlich: 8 }, skills: {} }, extra || {});
  const docs = {};
  [
    base("k_new", "Stelle Neu"),
    base("k_watch", "Stelle Merkliste", { board: "watch", system_status: "WATCHLIST" }),
    base("k_li", "Stelle LinkedIn", { board: "portal", system_status: "REVIEWED", origin: "linkedin", score_basis: "alert", portal_url: "https://www.linkedin.com/jobs/view/1/" }),
    base("k_xing", "Stelle XING", { board: "portal", system_status: "REVIEWED", origin: "xing" }),
    base("k_applied", "Stelle Beworben", { board: "applied", system_status: "APPLIED", applied_at: iso(3) }),
    base("k_interview", "Stelle Gespräch", { board: "interview", system_status: "APPLIED", applied_at: iso(9) }),
    base("k_declined", "Stelle Absage", { board: "declined", system_status: "APPLIED" }),
    base("k_rejected", "Stelle Kein Interesse", { board: "rejected", system_status: "REJECTED" }),
    base("k_expired", "Stelle Abgelaufen", { board: "new", system_status: "EXPIRED" }),
    base("k_aged", "Stelle Alter Alert", { board: "portal", system_status: "REVIEWED", origin: "linkedin", first_seen: iso(30) }),
    base("k_fail", "Stelle Speicherfehler"),
    base("k_gone_applied", "Stelle Beworben Offline", { board: "applied", system_status: "EXPIRED", applied_at: iso(5) }),
    base("k_dup", "Stelle Dublette", { system_status: "DUPLICATE" }),
    base("k_closedstate", "Stelle Offline erkannt", { open_state: "closed" }),
    base("k_note", "Stelle Notiz", { open_state: "open", open_checked: iso(0) }),
    base("k_low", "Stelle Low Score", { board: "low", system_status: "REVIEWED", score: 5.8, recommendation: "SKIP", report_date: iso(2), main_gap: "Python/SQL fehlen" }),
    base("k_schicht", "Stelle Schicht", { segment: "schicht", country: "AT", location: "Graz" }),
    base("k_schicht_title", "Projektingenieur Schicht 8/6", { country: "AT", location: "Wien" }),
    base("k_schicht_low", "Stelle Schicht Low", { segment: "schicht", board: "low", system_status: "REVIEWED", score: 6.2, recommendation: "SKIP", report_date: iso(2) }),
    base("k_schicht_alert", "Stelle Schicht Alert", { segment: "schicht", board: "portal", system_status: "REVIEWED", origin: "linkedin", score_basis: "alert" }),
    base("k_low_old", "Stelle Low Score Alt", { board: "low", system_status: "REVIEWED", score: 6.1, recommendation: "SKIP", report_date: iso(40), first_seen: iso(40) }),
    base("k_step", "Stelle Stepstone", { board: "portal", system_status: "REVIEWED", origin: "stepstone", score_basis: "alert" }),
    base("k_remote", "Stelle Remote", { segment: "remote" }),
    base("k_apply", "Stelle Ausfüllen", { cover_letter_name: "Anschreiben_Test.docx", cover_letter_b64: window.__DOCX_FIXTURE || "UEsDBA==", apply_url: "https://example.com/jobs/1",
      letter: window.__LETTER_FIXTURE, letter_slots: { remove: [2] } })
  ].forEach((d) => { docs[d.key] = d; });
  const deepFreeze = (o) => { Object.values(o).forEach((v) => { if (v && typeof v === "object") deepFreeze(v); }); return Object.freeze(o); };
  const listeners = [];
  window.__writes = [];
  window.__docs = docs;
  function emit() {
    const snap = { docs: Object.keys(docs).map((id) => { const data = deepFreeze(JSON.parse(JSON.stringify(docs[id]))); return Object.freeze({ id, exists: true, data: () => data, metadata: { fromCache: false, hasPendingWrites: false } }); }) };
    listeners.forEach((fn) => fn(snap));
  }
  window.__TOKEN = "TestToken1234";
  window.__CONFIG = {
    portals: [
      { id: "linkedin", label: "LinkedIn", search_url: "https://www.linkedin.com/jobs/search/?keywords={q}" },
      { id: "xing", label: "XING", search_url: "https://www.xing.com/jobs/search?keywords={q}" }
    ],
    segments: [{ id: "schicht", label: "Schicht", pattern: "\\bschicht\\b|wechselschicht", own_tab: true }],
    owner_label: "", trigger_token: window.__TOKEN, language: "de"
  };
  const store = {
    apply_requests: {}, letters: {},
    config: { ui: JSON.parse(JSON.stringify(window.__CONFIG)) },
    // a request nobody picked up for four hours: it must not block a new one
    run_requests: { run_stuck: { requested_at: new Date(now - 4 * 3600000).toISOString(), status: "requested", source: "dashboard" } }
  };
  const subs = { apply_requests: [], letters: [], config: [], run_requests: [] };
  window.__store = store; window.__reqs = store.apply_requests; window.__sets = [];
  // emits any set of documents to the subscribers of a collection, e.g. a late (stale) snapshot
  function emitSnap(name, col) {
    const snap = { docs: Object.keys(col).map((id) => { const data = deepFreeze(JSON.parse(JSON.stringify(col[id]))); return { id, exists: true, data: () => data }; }) };
    subs[name].forEach((fn) => fn(snap));
  }
  function emitCol(name) { emitSnap(name, store[name]); }
  window.__emitCol = emitCol; window.__emitSnap = emitSnap;
  const db = {
    collection(name) { return { onSnapshot(next) { if (subs[name]) { subs[name].push(next); setTimeout(() => emitCol(name), 5); } else { listeners.push(next); setTimeout(emit, 5); } return () => {}; } }; },
    doc(path) {
      const [col, id] = path.split("/");
      if (store[col]) return {
        set(d) { window.__sets.push({ col, id, data: JSON.parse(JSON.stringify(d)) }); return new Promise((res) => setTimeout(() => { store[col][id] = JSON.parse(JSON.stringify(d)); emitCol(col); res(); }, 20)); },
        delete() { return new Promise((res) => setTimeout(() => { delete store[col][id]; emitCol(col); res(); }, 20)); }
      };
      return {
        update(patch) {
          window.__writes.push({ id, patch: JSON.parse(JSON.stringify(patch)) });
          return new Promise((res, rej) => setTimeout(() => {
            if (!docs[id] || id === "k_fail") return rej({ code: "invalid_argument", message: "test failure" });
            Object.assign(docs[id], patch); emit(); res();
          }, 20));
        }
      };
    }
  };
  window.__downloads = [];   // every downloads.save() call, so tests can assert file names and content
  window.claude = { use: (n) => Promise.resolve(n === "db" ? db : n === "downloads" ? { save: (f) => { window.__downloads.push(f); return Promise.resolve(); } } : null) };
  window.addEventListener("error", (e) => { (window.__errors = window.__errors || []).push(String(e.message)); });
  window.addEventListener("unhandledrejection", (e) => { (window.__errors = window.__errors || []).push("rejection: " + String(e.reason && (e.reason.message || e.reason))); });
})();
