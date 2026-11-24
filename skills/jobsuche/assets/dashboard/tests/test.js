// Clicks every move button in every tab and checks where the job ends up, in the page and in the db;
// then the config-driven tabs, the "Job suche starten" button and the letter rebuild. Needs mock.js.
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const tab = async (id) => { document.getElementById("tab-" + id).click(); await sleep(30); };
  const rowOf = (title) => [...document.querySelectorAll("article.job")].find((a) => a.querySelector(".title").textContent === title);
  const btn = (row, label) => [...row.querySelectorAll("button.btn")].find((b) => b.textContent === label);
  const shown = async (id, title) => { await tab(id); return !!rowOf(title); };
  const results = [];
  const check = async (name, fromTab, title, label, toTab, key, board) => {
    let ok = true, why = [];
    await tab(fromTab);
    const row = rowOf(title);
    if (!row) { results.push([name, false, "Zeile nicht in " + fromTab]); return; }
    const b = btn(row, label);
    if (!b) { results.push([name, false, "Button fehlt: " + label + " (vorhanden: " + [...row.querySelectorAll("button.btn")].map((x) => x.textContent).join(" | ") + ")"]); return; }
    b.click();
    await sleep(150);
    if (await shown(fromTab, title) && fromTab !== toTab && fromTab !== "all") { ok = false; why.push("noch in " + fromTab); }
    if (!(await shown(toTab, title))) { ok = false; why.push("nicht in " + toTab); }
    if (window.__docs[key].board !== board) { ok = false; why.push("db.board=" + window.__docs[key].board); }
    results.push([name, ok, why.join(", ")]);
  };
  for (let i = 0; i < 100 && !document.querySelector("article.job"); i++) await sleep(100);   // first snapshot
  await sleep(100);
  await check("Neu → Beworben", "new", "Stelle Neu", "Als beworben markieren", "applied", "k_new", "applied");
  const appliedAt = window.__docs.k_new.applied_at;
  results.push(["  Bewerbungsdatum gesetzt", !!appliedAt, appliedAt]);
  await check("Beworben → Gespräch", "applied", "Stelle Neu", "Einladung / Gespräch", "interview", "k_new", "interview");
  await check("Gespräch → Beworben", "interview", "Stelle Neu", "Zurück zu Beworben", "applied", "k_new", "applied");
  await check("Beworben → Absage", "applied", "Stelle Beworben", "Absage erhalten", "declined", "k_applied", "declined");
  await check("Absage → Zurück zu Beworben", "declined", "Stelle Beworben", "Zurück zu Beworben", "applied", "k_applied", "applied");
  await check("Beworben → Doch nicht beworben", "applied", "Stelle Neu", "Doch nicht beworben", "new", "k_new", "new");
  results.push(["  Bewerbungsdatum gelöscht", window.__docs.k_new.applied_at === "", window.__docs.k_new.applied_at]);
  await check("Neu → Merkliste", "new", "Stelle Neu", "Auf die Merkliste", "watch", "k_new", "watch");
  await check("Merkliste → Zurück zu Neu", "watch", "Stelle Neu", "Zurück zu Neu", "new", "k_new", "new");
  await check("Merkliste → Beworben", "watch", "Stelle Merkliste", "Als beworben markieren", "applied", "k_watch", "applied");
  await check("Neu → Kein Interesse", "new", "Stelle Neu", "Kein Interesse", "rejected", "k_new", "rejected");
  await check("Kein Interesse → Wieder aufnehmen", "rejected", "Stelle Neu", "Wieder aufnehmen", "new", "k_new", "new");
  await check("LinkedIn → In Neu übernehmen", "linkedin", "Stelle LinkedIn", "In „Neu“ übernehmen", "new", "k_li", "new");
  await check("XING → Auf die Merkliste", "xing", "Stelle XING", "Auf die Merkliste", "watch", "k_xing", "watch");
  await check("Gespräch → Absage", "interview", "Stelle Gespräch", "Absage erhalten", "declined", "k_interview", "declined");
  await check("Kein Interesse (Altbestand) → Wieder aufnehmen", "rejected", "Stelle Kein Interesse", "Wieder aufnehmen", "new", "k_rejected", "new");
  for (const [title, why] of [["Stelle Abgelaufen", "abgelaufen"], ["Stelle Alter Alert", "Alert älter 21 Tage"], ["Stelle Dublette", "Dublette"], ["Stelle Offline erkannt", "offline erkannt"]]) {
    let seenIn = [];
    for (const t of ["new", "linkedin", "xing", "watch", "applied", "interview", "offer", "declined", "rejected", "all"]) if (await shown(t, title)) seenIn.push(t);
    results.push(["Nirgends sichtbar: " + why, !seenIn.length, "sichtbar in " + seenIn.join(",")]);
  }
  results.push(["Kein Reiter „Geschlossen“", !document.getElementById("tab-closed"), ""]);
  // low scoring jobs: own tab for 30 days, not in "Neu", can be taken over
  results.push(["Reiter „Low Scoring Stellen“ vorhanden", !!document.getElementById("tab-low") && document.getElementById("tab-low").textContent.includes("Low Scoring Stellen"), ""]);
  results.push(["Low-Score-Stelle im eigenen Reiter, nicht in Neu", await shown("low", "Stelle Low Score") && !(await shown("new", "Stelle Low Score")), ""]);
  await tab("low");
  results.push(["Low-Score-Stelle zeigt „Low Score“", /Low Score/.test(rowOf("Stelle Low Score").textContent), ""]);
  results.push(["Low-Score-Stelle älter als 30 Tage ausgeblendet", !(await shown("low", "Stelle Low Score Alt")), ""]);
  await check("Low Scoring → In Neu übernehmen", "low", "Stelle Low Score", "In „Neu“ übernehmen", "new", "k_low", "new");
  // segment with its own tab ("schicht" in the mock config): new, alert and low-scoring jobs of that lane
  // live there; they follow the status tabs once the user acts on one
  results.push(["Reiter „Schicht“ vorhanden", !!document.getElementById("tab-schicht"), ""]);
  for (const title of ["Stelle Schicht", "Projektingenieur Schicht 8/6", "Stelle Schicht Low", "Stelle Schicht Alert"])
    results.push(["Schicht im eigenen Reiter, nicht in Neu/Low/LinkedIn: " + title,
      await shown("schicht", title) && !(await shown("new", title)) && !(await shown("low", title)) && !(await shown("linkedin", title)), ""]);
  results.push(["Normale Stelle nicht im Schicht-Reiter", !(await shown("schicht", "Stelle Notiz")), ""]);
  await tab("schicht");
  results.push(["Schicht ohne „In Neu übernehmen“", !btn(rowOf("Stelle Schicht Alert"), "In „Neu“ übernehmen"), ""]);
  await check("Schicht → Merkliste", "schicht", "Stelle Schicht", "Auf die Merkliste", "watch", "k_schicht", "watch");
  await check("Schicht Merkliste → Zurück (in Schicht)", "watch", "Stelle Schicht", "Zurück zu Neu", "schicht", "k_schicht", "new");
  await check("Schicht → Beworben", "schicht", "Stelle Schicht Low", "Als beworben markieren", "applied", "k_schicht_low", "applied");
  await tab("applied");
  const ga = rowOf("Stelle Beworben Offline");
  results.push(["Beworben + offline bleibt sichtbar mit Hinweis", !!ga && /Anzeige nicht mehr online/.test(ga.textContent), ga ? "" : "fehlt"]);
  await check("Alle → Beworben", "all", "Stelle Merkliste", "Einladung / Gespräch", "interview", "k_watch", "interview");
  await check("Gespräch → Zusage", "interview", "Stelle Merkliste", "Zusage erhalten", "offer", "k_watch", "offer");
  await check("Zusage → Zurück zu Im Gespräch", "offer", "Stelle Merkliste", "Zurück zu Im Gespräch", "interview", "k_watch", "interview");
  // a LinkedIn job straight to applied, then undo via the toast
  await tab("new");
  await check("Neu → Beworben (für Rückgängig)", "new", "Stelle LinkedIn", "Als beworben markieren", "applied", "k_li", "applied");
  document.getElementById("toastUndo").click(); await sleep(150);
  results.push(["Rückgängig im Hinweis", window.__docs.k_li.board === "new" && await shown("new", "Stelle LinkedIn"), "db.board=" + window.__docs.k_li.board]);
  // a failed write is rolled back and reported
  await tab("new");
  btn(rowOf("Stelle Speicherfehler"), "Als beworben markieren").click(); await sleep(150);
  results.push(["Speicherfehler: zurückgesetzt + Meldung", await shown("new", "Stelle Speicherfehler") && !document.getElementById("toast").hidden && /fehlgeschlagen/.test(document.getElementById("toastText").textContent), document.getElementById("toastText").textContent]);
  // note
  await tab("new");
  const r = rowOf("Stelle Notiz"); r.querySelector("details").open = true;
  results.push(["Hinweis „online geprüft“", /online geprüft/.test(r.textContent), ""]);
  const ta = r.querySelector("textarea"); ta.focus(); ta.value = "Testnotiz"; ta.dispatchEvent(new Event("change")); ta.blur(); await sleep(150);
  results.push(["Notiz gespeichert", window.__docs.k_note.note === "Testnotiz", "db.note=" + window.__docs.k_note.note]);
  // apply request flow
  await tab("new");
  let ra = rowOf("Stelle Ausfüllen");
  btn(ra, "Bewerbung ausfüllen lassen").click(); await sleep(50);
  ra = rowOf("Stelle Ausfüllen");
  const panel = ra.querySelector(".apply");
  results.push(["Ausfüllhilfe öffnet sich", !!panel, ""]);
  const go = [...panel.querySelectorAll("button")].find((b) => b.textContent === "Auftrag anlegen");
  results.push(["Auftrag erst nach Freigabe-Haken möglich", go.disabled === true, ""]);
  const boxes = panel.querySelectorAll('input[type="checkbox"]');
  results.push(["Lebenslauf + Anschreiben vorausgewählt, PDF nicht", boxes[0].checked && boxes[1].checked && !boxes[2].checked, ""]);
  panel.querySelectorAll('input[type="text"]')[0].value = "95.000 €";
  const okBox = boxes[boxes.length - 1]; okBox.checked = true; okBox.dispatchEvent(new Event("change"));
  results.push(["Freigabe-Haken schaltet Button frei", go.disabled === false, ""]);
  go.click(); await sleep(150);
  const rq = window.__reqs.k_apply || {};
  results.push(["Auftrag gespeichert (Dateien, Antworten, Status)", rq && rq.status === "requested" && rq.files.cv && rq.files.cover_letter && !rq.files.cover_letter_pdf && rq.answers.salary === "95.000 €", JSON.stringify(rq).slice(0, 120)]);
  ra = rowOf("Stelle Ausfüllen");
  results.push(["Hinweis „vorgemerkt“ an der Stelle", /Ausfüll-Auftrag vorgemerkt/.test(ra.textContent) && !ra.querySelector(".apply"), ""]);
  results.push(["Deutlicher Kasten „Claude soll diese Bewerbung ausfüllen“", !!ra.querySelector(".reqbox") && /Bewerbungen ausfüllen/.test(ra.querySelector(".reqbox").textContent), ""]);
  btn(ra, "Auftrag zurückziehen").click(); await sleep(150);
  ra = rowOf("Stelle Ausfüllen");
  results.push(["Auftrag zurückziehen", !window.__reqs.k_apply && !!btn(ra, "Bewerbung ausfüllen lassen"), ""]);
  await tab("applied");
  results.push(["Kein Ausfüll-Button bei beworbenen Stellen", !rowOf("Stelle Beworben Offline").textContent.includes("ausfüllen lassen"), ""]);
  // stale page must not overwrite newer server text
  await tab("new");
  let rs = rowOf("Stelle Ausfüllen");
  btn(rs, "Anschreiben bearbeiten").click(); await sleep(60);
  rs = rowOf("Stelle Ausfüllen");
  const s1 = rs.querySelector(".editor textarea"); s1.focus(); s1.blur(); await sleep(1500);
  results.push(["Ohne Tippen wird nichts gespeichert", !window.__store.letters.k_apply, JSON.stringify(window.__store.letters.k_apply || null).slice(0, 60)]);
  window.__store.letters.k_apply = { subject: "Neu vom Server", salutation: "Dear Ms Muster,", paragraphs: ["Neuer Einstieg vom Server.", "Zwei", "Drei", "Vier", "Fünf"], status: "built" };
  window.__emitCol("letters"); await sleep(120);
  rs = rowOf("Stelle Ausfüllen");
  results.push(["Neuere Fassung aus der Datenbank wird angezeigt", rs.querySelector(".editor textarea").value === "Neuer Einstieg vom Server.", rs.querySelector(".editor textarea").value.slice(0, 40)]);
  const s2 = rs.querySelector(".editor textarea"); s2.focus(); s2.value = "Vom Nutzer getippt."; s2.dispatchEvent(new Event("input")); s2.blur(); await sleep(400);
  results.push(["Nach dem Tippen wird gespeichert", (window.__store.letters.k_apply.paragraphs || [])[0] === "Vom Nutzer getippt." && window.__store.letters.k_apply.status === "edited", ""]);
  btn(rowOf("Stelle Ausfüllen"), "Editor schließen").click(); await sleep(60);
  delete window.__store.letters.k_apply; window.__emitCol("letters"); await sleep(120);
  // late echo of an earlier autosave must not replace what was typed afterwards
  await tab("new");
  let rl2 = rowOf("Stelle Ausfüllen");
  btn(rl2, "Anschreiben bearbeiten").click(); await sleep(60);
  rl2 = rowOf("Stelle Ausfüllen");
  const e1 = rl2.querySelector(".editor textarea");
  e1.focus(); e1.value = "Erster Zwischenstand."; e1.dispatchEvent(new Event("input")); await sleep(1500);
  const stale = JSON.parse(JSON.stringify(window.__store.letters.k_apply));
  e1.value = "Endgültiger Text vom Nutzer."; e1.dispatchEvent(new Event("input")); e1.blur(); await sleep(300);
  const latest = JSON.parse(JSON.stringify(window.__store.letters.k_apply));
  window.__store.letters.k_apply = stale; window.__emitCol("letters"); await sleep(150);   // late echo
  window.__store.letters.k_apply = latest;
  rl2 = rowOf("Stelle Ausfüllen");
  results.push(["Verspätete Zwischenstand-Bestätigung überschreibt die Anzeige nicht", rl2.querySelector(".editor textarea").value === "Endgültiger Text vom Nutzer.", rl2.querySelector(".editor textarea").value]);
  results.push(["Datenbank hat den endgültigen Text", latest.paragraphs[0] === "Endgültiger Text vom Nutzer.", latest.paragraphs[0]]);
  window.__store.letters.k_apply = { ...latest, paragraphs: ["Neuer vom Lauf.", "b", "c", "d", "e"], edited_at: new Date(Date.now() + 60000).toISOString() };
  window.__emitCol("letters"); await sleep(150);
  results.push(["Wirklich neuere Fassung wird übernommen", rowOf("Stelle Ausfüllen").querySelector(".editor textarea").value === "Neuer vom Lauf.", ""]);
  btn(rowOf("Stelle Ausfüllen"), "Editor schließen").click(); await sleep(60);
  delete window.__store.letters.k_apply; window.__emitCol("letters"); await sleep(120);
  // cover letter editor
  await tab("new");
  let rl = rowOf("Stelle Ausfüllen");
  btn(rl, "Anschreiben bearbeiten").click(); await sleep(60);
  rl = rowOf("Stelle Ausfüllen");
  let ed = rl.querySelector(".editor");
  results.push(["Editor öffnet sich mit Betreff, Anrede und 5 Absätzen", !!ed && ed.querySelectorAll("input").length === 2 && ed.querySelectorAll("textarea").length === 5, ed ? ed.querySelectorAll("textarea").length + " Absätze" : "fehlt"]);
  const chipText = () => [...rowOf("Stelle Ausfüllen").querySelectorAll(".editor .checks .chip")].map((c) => c.textContent).join(" | ");
  results.push(["Live-Prüfung: Wörter, eine Seite, Anrede", /Wörter/.test(chipText()) && /eine Seite/.test(chipText()) && /Anrede korrekt|Salutation/.test(chipText()), chipText()]);
  const sal = ed.querySelectorAll("input")[1];
  sal.focus(); sal.value = "Dear Erika Muster,"; sal.dispatchEvent(new Event("input"));
  results.push(["Vor- und Nachname in der Anrede wird markiert", /never first and last name/.test(chipText()), chipText()]);
  sal.value = "Dear Ms Muster,"; sal.dispatchEvent(new Event("input"));
  results.push(["„Dear Ms Muster,“ gilt als korrekt", /Anrede korrekt/.test(chipText()), chipText()]);
  const lta = ed.querySelectorAll("textarea")[0];
  lta.focus(); lta.value = "I am excited to apply. " + lta.value; lta.dispatchEvent(new Event("input"));
  results.push(["Floskel wird live erkannt", /Floskel/.test(chipText()), chipText()]);
  lta.value = lta.value.replace("I am excited to apply. ", "Geänderter Einstieg. "); lta.dispatchEvent(new Event("input"));
  await sleep(1500);
  const L = window.__store.letters.k_apply || {};
  results.push(["Automatisch gespeichert (Anrede + Absatz)", L.status === "edited" && L.salutation === "Dear Ms Muster," && /^Geänderter Einstieg/.test(L.paragraphs[0]), JSON.stringify(L).slice(0, 100)]);
  results.push(["Fokus bleibt beim Tippen im Editor", document.activeElement === lta, document.activeElement && document.activeElement.tagName]);
  lta.blur(); await sleep(100);
  // the run rebuilt the docx and reports back
  window.__store.letters.k_apply = { ...window.__store.letters.k_apply, status: "built", check: { ok: true, errors: [], warnings: [], body_words: 312, pages: "1 (measured)" } };
  window.__emitCol("letters"); await sleep(80);
  rl = rowOf("Stelle Ausfüllen");
  results.push(["Rückmeldung „übernommen“ sichtbar", /übernommen/.test(rl.textContent) && /312 Wörter/.test(rl.textContent), ""]);
  ed = rl.querySelector(".editor");
  results.push(["Editor zeigt die gespeicherte Fassung", ed.querySelectorAll("input")[1].value === "Dear Ms Muster,", ed.querySelectorAll("input")[1].value]);
  btn(rl, "Absatz hinzufügen").click(); await sleep(60);
  rl = rowOf("Stelle Ausfüllen");
  results.push(["Absatz hinzufügen", rl.querySelectorAll(".editor textarea").length === 6, ""]);
  btn(rl, "Absatz entfernen").click(); await sleep(1500);
  results.push(["Absatz entfernen + speichern", rowOf("Stelle Ausfüllen").querySelectorAll(".editor textarea").length === 5 && (window.__store.letters.k_apply.paragraphs || []).length === 5, ""]);
  // "Anschreiben (.docx)" builds a fresh file from the editor text, also when it is not saved yet
  rl = rowOf("Stelle Ausfüllen");
  const t2 = rl.querySelectorAll(".editor textarea")[1];
  t2.focus(); t2.value = "Im Browser frisch gebaut.\nZweite Zeile."; t2.dispatchEvent(new Event("input"));
  btn(rl, "Anschreiben (.docx)").click(); await sleep(1200);
  const dl = (window.__downloads || []).slice(-1)[0];
  let dx = "";
  if (dl && window.JSZip) dx = await (await window.JSZip.loadAsync(dl.data)).file("word/document.xml").async("string");
  results.push(["Download enthält ungespeicherten Text", /Im Browser frisch gebaut\.<\/w:t><w:br\/><w:t xml:space="preserve">Zweite Zeile\./.test(dx), dx ? "" : "kein docx"]);
  results.push(["Download trägt das heutige Datum", dx.includes(letterDate("en")) && !dx.includes("2 January 2024") && dx.includes("Musterstadt, " + letterDate("en")), letterDate("en")]);
  results.push(["Zeile unter dem Namen entfernt", !!dx && !dx.includes("BEISPIELZEILE") && dx.includes("ERIKA MUSTERMANN"), ""]);
  results.push(["Anrede und Betreff aus dem Editor", dx.includes("Dear Ms Muster,") && dx.includes(rl.querySelectorAll(".editor input")[0].value.replace(/&/g, "&amp;")), ""]);
  results.push(["Dateiname bleibt", dl && dl.filename === "Anschreiben_Test.docx", dl && dl.filename]);
  await sleep(300);
  results.push(["Klick speichert die Änderung auch", ((window.__store.letters.k_apply || {}).paragraphs || [])[1] === "Im Browser frisch gebaut.\nZweite Zeile.", ""]);
  if (dl) { const buf = new Uint8Array(await dl.data.arrayBuffer()); let bin = ""; for (const x of buf) bin += String.fromCharCode(x); window.__lastDocxB64 = btoa(bin); }
  const jz = window.JSZip; window.JSZip = undefined;
  btn(rowOf("Stelle Ausfüllen"), "Anschreiben (.docx)").click(); await sleep(200);
  window.JSZip = jz;
  results.push(["Ohne Neubau: gespeicherte Fassung + Hinweis", (window.__downloads || []).length >= 2 && /letzten Lauf/.test(document.getElementById("toastText").textContent), document.getElementById("toastText").textContent]);
  t2.blur(); await sleep(100);
  window.__store.letters.k_apply = { ...window.__store.letters.k_apply, status: "invalid", check: { ok: false, errors: ["letter has 2 pages"] } };
  window.__emitCol("letters"); await sleep(80);
  results.push(["Fehler beim Übernehmen wird angezeigt", /letter has 2 pages/.test(rowOf("Stelle Ausfüllen").textContent), ""]);
  btn(rowOf("Stelle Ausfüllen"), "Auf den Vorschlag zurücksetzen").click(); await sleep(150);
  results.push(["Zurücksetzen löscht die Änderung", !window.__store.letters.k_apply, ""]);

  // ---- config-driven tabs, portals and segments (collection config, document ui)
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  const store = window.__store, CONFIG = window.__CONFIG, $id = (x) => document.getElementById(x);
  const copy = (o) => JSON.parse(JSON.stringify(o));
  const setConfig = async (c) => { if (c === null) delete store.config.ui; else store.config.ui = copy(c); window.__emitCol("config"); await sleep(80); };
  const tabIds = () => [...document.querySelectorAll("#tabs .tab")].map((b) => b.id.replace("tab-", "")).join(",");
  const selected = () => (document.querySelector('#tabs .tab[aria-selected="true"]') || {}).id;
  const linkOf = (row, text) => [...row.querySelectorAll("a")].find((a) => a.textContent === text);
  const TAIL = "low,watch,applied,interview,offer,declined,rejected,all,stats";
  await tab("watch");
  const lx = linkOf(rowOf("Stelle XING"), "Auf XING suchen ↗");
  results.push(["Portal-Suchlink aus search_url (XING)", !!lx && lx.href === "https://www.xing.com/jobs/search?keywords=Stelle%20XING%20Firma%20k_xing", lx ? lx.href : "fehlt"]);
  await tab("new");
  results.push(["Portal-Link „Auf LinkedIn öffnen“", !!linkOf(rowOf("Stelle LinkedIn"), "Auf LinkedIn öffnen ↗"), ""]);
  results.push(["Unbekannte Herkunft landet im ersten Portal-Reiter", await shown("linkedin", "Stelle Stepstone") && ![...rowOf("Stelle Stepstone").querySelectorAll(".chip")].some((c) => /^aus /.test(c.textContent)), ""]);
  await tab("schicht");
  let remembered = ""; try { remembered = JSON.parse(localStorage.getItem("jobcockpit") || "{}").tab; } catch (e) { remembered = "(kein localStorage)"; }
  results.push(["Gewählter Reiter wird gemerkt", remembered === "schicht" || remembered === "(kein localStorage)", String(remembered)]);
  await setConfig(null);   // no config document: built-in defaults
  results.push(["Standard-Konfiguration: Reiter Neu, LinkedIn, XING, Status", tabIds() === "new,linkedin,xing," + TAIL, tabIds()]);
  results.push(["Standard: gemerkter Reiter fehlt → „Neu“ wird gezeigt", selected() === "tab-new", String(selected())]);
  results.push(["Standard: Stellen ohne eigene Spur stehen in „Neu“", !!rowOf("Stelle Schicht") && !!rowOf("Projektingenieur Schicht 8/6") && !!rowOf("Stelle Remote"), ""]);
  results.push(["Standard: Regeltext nennt LinkedIn und XING", /^LinkedIn und XING zeigen/.test($id("rules").textContent) && !/Schicht/.test($id("rules").textContent), $id("rules").textContent.slice(0, 60)]);
  await setConfig(CONFIG);
  results.push(["Reiter kehrt mit der Konfiguration zurück (gemerkte Auswahl)", selected() === "tab-schicht" && !!rowOf("Stelle Schicht"), String(selected())]);
  await setConfig(null);
  results.push(["Standard: Alert-Stelle der Spur im Portal-Reiter, mit „In Neu übernehmen“", await shown("linkedin", "Stelle Schicht Alert") && !!btn(rowOf("Stelle Schicht Alert"), "In „Neu“ übernehmen"), ""]);
  results.push(["Standard aus buildConfig: Müll als Eingabe", [null, "x", [1], 7, { portals: "x", segments: {} }].every((v) => { const c = buildConfig(v); return c.portals.map((p) => p.id).join() === "linkedin,xing" && c.segments.length === 4 && !c.segments.some((x) => x.own_tab); }), ""]);
  // one more portal and one more segment with its own tab
  const C2 = copy(CONFIG);
  C2.portals.push({ id: "stepstone", label: "StepStone", search_url: "https://www.stepstone.de/jobs/{q}" });
  C2.segments.push({ id: "remote", label: "Remote", own_tab: true });
  C2.owner_label = "Erika Mustermann";
  await setConfig(C2);
  results.push(["Zusatz-Portal und Segment-Reiter: Reihenfolge", tabIds() === "new,schicht,remote,linkedin,xing,stepstone," + TAIL, tabIds()]);
  results.push(["Zusatz-Portal: Stelle im eigenen Reiter", await shown("stepstone", "Stelle Stepstone") && !(await shown("linkedin", "Stelle Stepstone")), ""]);
  await tab("stepstone");
  const rsx = rowOf("Stelle Stepstone"), ls = rsx && linkOf(rsx, "Auf StepStone suchen ↗");
  results.push(["Zusatz-Portal: Chip und Suchlink", !!rsx && /aus StepStone/.test(rsx.textContent) && !!ls && ls.href === "https://www.stepstone.de/jobs/Stelle%20Stepstone%20Firma%20k_step", ls ? ls.href : "fehlt"]);
  results.push(["Segment mit eigenem Reiter: nicht in Neu", await shown("remote", "Stelle Remote") && !(await shown("new", "Stelle Remote")), ""]);
  results.push(["Muster aus der Konfiguration ordnet nach Titel zu", await shown("schicht", "Projektingenieur Schicht 8/6") && !(await shown("new", "Projektingenieur Schicht 8/6")), ""]);
  results.push(["Besitzer-Label im Kopf", $id("owner").textContent === "Erika Mustermann" && !$id("owner").hidden, $id("owner").textContent]);
  results.push(["Regeltext nennt alle Portale und eigenen Reiter", /^LinkedIn, XING und StepStone zeigen/.test($id("rules").textContent) && /„Remote“ zeigt/.test($id("rules").textContent), ""]);
  await tab("xing");
  results.push(["Leerer Portal-Reiter erklärt sich", /aus deinen XING-Job-Mails/.test($id("list").textContent), $id("list").textContent.slice(0, 80)]);
  await tab("stats"); await tab("new");
  // invalid values are ignored, labels stay text
  const BAD = { portals: [{ id: "Bad Id", label: "X", search_url: "https://x.example.com/{q}" }, { id: "new", label: "Clash" }, "text", null, 7,
      { id: "stepstone", label: '<img src=x onerror="window.__xss=1">', search_url: "javascript:alert(1)//{q}" },
      { id: "plain", label: "Plain", search_url: "http://example.com/?q={q}" }, { id: "plain", label: "Doppelt" }],
    segments: [{ id: "bad", label: "Kaputt", pattern: "(", own_tab: true }, { id: "long", label: "Lang", pattern: "a".repeat(201) }, { id: "<x>", label: "no", own_tab: true },
      { id: "stepstone", label: "Clash", own_tab: true }, { id: "okseg", label: "<b>fett</b>", pattern: "^Stelle Notiz$" }, []],
    owner_label: { a: 1 }, trigger_token: "short", language: 5 };
  await setConfig(BAD);
  results.push(["Ungültig: nur gültige, eindeutige Ids werden Reiter", tabIds() === "new,bad,stepstone,plain," + TAIL, tabIds()]);
  results.push(["Ungültig: Label mit Markup bleibt Text", $id("tab-stepstone").textContent.includes("<img src=x") && !document.querySelector("#tabs img") && window.__xss === undefined, $id("tab-stepstone").textContent]);
  await tab("stepstone");
  const rbad = rowOf("Stelle Stepstone");
  results.push(["Ungültig: search_url ohne https ergibt keinen Link", !!rbad && ![...rbad.querySelectorAll("a")].some((a) => /suchen/.test(a.textContent)) && !document.querySelector('a[href^="javascript"]'), ""]);
  const cb = buildConfig(BAD);
  results.push(["Ungültig: http-Link, Token, Sprache, Besitzer verworfen", cb.portalById.get("plain").search_url === "" && cb.portalById.get("plain").label === "Plain" && cb.token === "" && cb.language === "" && cb.owner === "" && $id("owner").hidden, ""]);
  results.push(["Ungültig: kaputtes und zu langes Muster verworfen", !cb.rules.some((r) => r[0] === "bad" || r[0] === "long") && cb.segById.has("bad") && cb.segById.has("long") && !cb.segById.has("<x>"), ""]);
  results.push(["Ungültig: Segment darf keinen belegten Reiter übernehmen", cb.segById.get("stepstone").own_tab === false && cb.segById.get("bad").own_tab === true, ""]);
  await tab("new");
  const rn = rowOf("Stelle Notiz");
  results.push(["Ungültig: Segment-Label mit Markup bleibt Text", !!rn && rn.textContent.includes("<b>fett</b>") && ![...document.querySelectorAll("b")].some((b) => b.textContent === "fett"), ""]);
  await setConfig(C2);
  await check("Zusatz-Portal → In Neu übernehmen", "stepstone", "Stelle Stepstone", "In „Neu“ übernehmen", "new", "k_step", "new");
  await setConfig(CONFIG);
  results.push(["Konfiguration wiederhergestellt", tabIds() === "new,schicht,linkedin,xing," + TAIL, tabIds()]);

  // ---- "Job suche starten"
  const RB = $id("runBtn"), RS = $id("runStatus"), RUNS = store.run_requests;
  const emitRuns = async (col) => { window.__emitSnap("run_requests", col || RUNS); await sleep(40); };
  const runSets = () => window.__sets.filter((x) => x.col === "run_requests");
  const triggers = () => window.__downloads.filter((f) => /\.trigger$/.test(String(f.filename)));
  const agoIso = (min) => new Date(Date.now() - min * 60000).toISOString();
  results.push(["Start-Schaltfläche sichtbar, deutsch beschriftet", !$id("runBox").hidden && RB.textContent === "Job suche starten" && !!RB.title && !!$id(RB.getAttribute("aria-describedby")), ""]);
  results.push(["Über 3 Stunden alte Anfrage blockiert nicht", !RB.disabled && /^Anfrage von .* nicht abgeschlossen/.test(RS.textContent), RS.textContent]);
  RB.click();
  results.push(["Während des Schreibens gesperrt", RB.disabled && RS.textContent === "Wird angefragt …", RS.textContent]);
  await sleep(150);
  const id1 = Object.keys(RUNS).find((k) => k !== "run_stuck") || "", d1 = copy(RUNS[id1] || {});
  results.push(["Anfrage geschrieben: Id und genau drei Felder", /^run_\d{8}T\d{9}Z$/.test(id1) && Object.keys(d1).sort().join() === "requested_at,source,status" && d1.status === "requested" && d1.source === "dashboard"
    && id1 === "run_" + String(d1.requested_at).replace(/[-:.]/g, "") && new Date(d1.requested_at).toISOString() === d1.requested_at, id1 + " " + JSON.stringify(d1)]);
  const tg = triggers();
  results.push(["Startdatei: Name mit Token, Inhalt nur die Id", tg.length === 1 && tg[0].filename === "jobsuche-start-" + window.__TOKEN + ".trigger" && (await tg[0].data.text()) === id1, tg.map((f) => f.filename).join()]);
  results.push(["Nach der Anfrage gesperrt + Status „Angefragt“", RB.disabled && /^Angefragt \d\d:\d\d – wird beim nächsten Abholen gestartet$/.test(RS.textContent), RS.textContent]);
  RB.click(); startRun(); await sleep(120);
  results.push(["Zweiter Klick legt keine zweite Anfrage an", runSets().length === 1 && triggers().length === 1, String(runSets().length)]);
  RUNS[id1] = { ...d1, status: "running", started_at: new Date().toISOString() }; await emitRuns();
  results.push(["Status „Läuft seit“", RB.disabled && /^Läuft seit \d\d:\d\d$/.test(RS.textContent), RS.textContent]);
  await emitRuns({ run_stuck: RUNS.run_stuck });   // late snapshot from before the click
  results.push(["Veralteter Snapshot ohne die Anfrage gibt nicht frei", RB.disabled && /^Läuft seit/.test(RS.textContent), RS.textContent]);
  await emitRuns({});
  results.push(["Leerer Snapshot gibt nicht frei", RB.disabled, ""]);
  await emitRuns({ [id1]: d1 });   // out-of-order echo of the earlier state
  results.push(["Verspätetes „requested“ setzt „running“ nicht zurück", RB.disabled && /^Läuft seit/.test(RS.textContent), RS.textContent]);
  const run1 = copy(RUNS[id1]);
  RUNS[id1] = { ...run1, status: "done", finished_at: new Date().toISOString() }; await emitRuns();
  results.push(["Nach „done“ wieder frei + „Letzter Lauf fertig“", !RB.disabled && /^Letzter Lauf fertig \d\d:\d\d$/.test(RS.textContent), RS.textContent]);
  await emitRuns({ [id1]: run1 });
  results.push(["Verspätetes „running“ sperrt nach „done“ nicht wieder", !RB.disabled && /^Letzter Lauf fertig/.test(RS.textContent), RS.textContent]);
  RUNS.run_a = { requested_at: agoIso(181), status: "running", source: "dashboard" }; await emitRuns();
  results.push(["3-Stunden-Regel: 3:01 h alter Lauf blockiert nicht", !RB.disabled, RS.textContent]);
  RUNS.run_b = { requested_at: agoIso(170), status: "requested", source: "dashboard" }; await emitRuns();
  results.push(["3-Stunden-Regel: 2:50 h alte Anfrage blockiert", RB.disabled && /^Angefragt /.test(RS.textContent), RS.textContent]);
  await emitRuns({ [id1]: RUNS[id1] });   // newest doc alone, older pending one missing
  results.push(["Neuerer fertiger Lauf gibt eine ältere offene Anfrage nicht frei", RB.disabled, RS.textContent]);
  RUNS.run_b = { ...RUNS.run_b, status: "done", finished_at: new Date().toISOString() }; await emitRuns();
  results.push(["Frei, sobald die offene Anfrage fertig ist", !RB.disabled, RS.textContent]);
  RUNS["evil id"] = { status: "requested", requested_at: new Date().toISOString() };
  RUNS.run_x = { status: "constructor", requested_at: new Date().toISOString() };
  RUNS.run_y = { status: "requested", requested_at: "nonsense" };
  RUNS.run_z = "requested";
  await emitRuns();
  results.push(["Fehlerhafte Anfrage-Dokumente werden ignoriert", !RB.disabled && /^Letzter Lauf fertig/.test(RS.textContent), RS.textContent]);
  ["evil id", "run_x", "run_y", "run_z"].forEach((k) => delete RUNS[k]);
  await sleep(5); RB.click(); await sleep(150);
  const id2 = Object.keys(RUNS).filter((k) => /^run_\d/.test(k) && k !== id1)[0] || "";
  RUNS[id2] = { ...RUNS[id2], status: "failed", status_note: "<b>Fehler</b>\n  beim   Start " + "x".repeat(300) }; await emitRuns();
  results.push(["„Fehlgeschlagen“: Notiz als Text, höchstens 120 Zeichen, wieder frei", !!id2 && !RB.disabled && RS.textContent.startsWith("Fehlgeschlagen: <b>Fehler</b> beim Start xxx") && RS.textContent.length === "Fehlgeschlagen: ".length + 120 && !RS.querySelector("*"), RS.textContent.slice(0, 60) + " (" + RS.textContent.length + ")"]);
  const noTok = copy(CONFIG); delete noTok.trigger_token;
  await setConfig(noTok);
  const nSets = runSets().length, nTrig = triggers().length;
  RB.click(); await sleep(150);
  results.push(["Ohne Token: Anfrage ja, Startdatei nein", runSets().length === nSets + 1 && triggers().length === nTrig && RB.disabled, runSets().length + "/" + triggers().length]);
  const id3 = runSets().slice(-1)[0].id; RUNS[id3] = { ...RUNS[id3], status: "done" }; await emitRuns();
  await setConfig({ ...copy(CONFIG), trigger_token: "../kein gültiges Token" });
  RB.click(); await sleep(150);
  results.push(["Ungültiges Token: Anfrage ja, Startdatei nein", runSets().length === nSets + 2 && triggers().length === nTrig, runSets().length + "/" + triggers().length]);
  const id4 = runSets().slice(-1)[0].id; RUNS[id4] = { ...RUNS[id4], status: "done" }; await emitRuns();
  results.push(["Alle Startdateien tragen denselben festen Namen", triggers().length === 2 && triggers().every((f) => f.filename === "jobsuche-start-" + window.__TOKEN + ".trigger"), ""]);
  results.push(["Anfragen enthalten nie Freitext", runSets().every((x) => Object.keys(x.data).sort().join() === "requested_at,source,status" && x.data.source === "dashboard" && x.data.status === "requested"), ""]);
  await setConfig(CONFIG);
  const keepDb = state.db; state.db = null; renderRun();
  const hiddenNoDb = $id("runBox").hidden;
  state.db = keepDb; renderRun();
  results.push(["Ohne Datenbank ist die Start-Schaltfläche ausgeblendet", hiddenNoDb && !$id("runBox").hidden, ""]);

  // ---- letter rebuild with explicit slots (letter_slots) and without
  const docXml = async (blob) => (await window.JSZip.loadAsync(blob)).file("word/document.xml").async("string");
  const draft = { subject: "Betreff neu", salutation: "Guten Tag Frau Muster,", paragraphs: ["Absatz eins.", "Absatz zwei."] };
  const when = new Date(2026, 0, 5, 12, 0, 0);
  let sx = "", sErr = "";
  try {
    sx = await docXml(await buildLetterDocx({ cover_letter_b64: window.__DOCX_FIXTURE, letter: { language: "de", closing: "Mit freundlichen Grüßen" },
      letter_slots: { subject: 3, salutation: 4, body_start: 5, body_end: -2, closing: -2, date: { table: 0, row: 0, cell: -1, paragraph: 0 }, date_prefix: "Beispielort, ", remove: [2, 3, 99, "x"] } }, draft, when));
  } catch (e) { sErr = String(e && e.message); }
  results.push(["letter_slots: Positionen, Datumspräfix, Entfernen", sx.includes("Beispielort, 5. Januar 2026") && sx.includes("Betreff neu") && sx.includes("Guten Tag Frau Muster,") && sx.includes("Absatz eins.") && sx.includes("Absatz zwei.")
    && sx.includes("Mit freundlichen Grüßen") && sx.includes("ERIKA MUSTERMANN") && !sx.includes("BEISPIELZEILE") && !sx.includes("Musterstadt, 2 January"), sErr]);
  const countP = (x) => (x.match(/<w:p[ >]/g) || []).length;
  let px = "";
  try { px = await docXml(await buildLetterDocx({ cover_letter_b64: window.__DOCX_FIXTURE, letter: { language: "en" } }, draft, when)); } catch (e) { sErr = String(e && e.message); }
  results.push(["Ohne letter_slots: Aufbau nach Position, nichts entfernt", px.includes("Musterstadt, 5 January 2026") && px.includes("BEISPIELZEILE") && px.includes("Absatz zwei.") && px.includes("Yours sincerely,") && countP(px) === countP(sx) + 1, sErr + " " + countP(px) + "/" + countP(sx)]);
  let nx = "";
  try { nx = await docXml(await buildLetterDocx({ cover_letter_b64: window.__DOCX_FIXTURE, letter: { language: "en" }, letter_slots: { date: null } }, draft, when)); } catch (e) { sErr = String(e && e.message); }
  results.push(["letter_slots.date = null lässt das Datum unberührt", nx.includes("Musterstadt, 2 January 2024") && nx.includes("Absatz eins."), sErr]);
  let threw = false;
  try { await buildLetterDocx({ cover_letter_b64: window.__DOCX_FIXTURE, letter: { language: "en" }, letter_slots: { subject: 99 } }, draft, when); } catch (e) { threw = true; }
  results.push(["Unpassende letter_slots brechen den Neubau ab (Rückfall auf gespeicherte Datei)", threw, ""]);
  // follow-up reminders and the extended statistics
  try {
  await setConfig(copy(CONFIG));
  await tab("stats");
  const panel = () => document.querySelector("section.followup");
  const dueText = () => (panel() ? panel().textContent : "");
  results.push(["Nachfassen: fällige Bewerbung in der Auswertung", /Nachfassen fällig \(1\)/.test(dueText()) && /Firma k_follow – Stelle Nachfassen/.test(dueText()), dueText().slice(0, 120)]);
  results.push(["Nachfassen: Höchstzahl und beantwortete Bewerbung fehlen", !/Erledigt|Beantwortet/.test(dueText()), dueText().slice(0, 160)]);
  results.push(["Nachfassen: frische Bewerbung noch nicht fällig", !/k_gone_applied|k_applied –/.test(dueText()), ""]);
  results.push(["Auswertung: Trichter und Tabelle nach Bewertung", !!document.querySelector("section.funnel") && /Ohne Antwort seit 30 Tagen/.test($id("list").textContent) && /Nach Bewertung/.test($id("list").textContent) && /8,5 bis 8,9/.test($id("list").textContent), ""]);
  await tab("applied");
  results.push(["Nachfassen: Hinweis im Reiter „Beworben“ und Chip an der Stelle", !!panel() && /Nachfassen fällig/.test(rowOf("Stelle Nachfassen").textContent) && !/Nachfassen fällig/.test(rowOf("Stelle Nachfassen Erledigt").textContent), ""]);
  panel().querySelector("button.btn").click();
  await sleep(150);
  const fdoc = window.__docs.k_follow;
  results.push(["Nachfassen: Klick vermerkt Datum und Zähler", fdoc.followup_count === 1 && fdoc.followup_at === new Date().toISOString().slice(0, 10) && fdoc.board === "applied", JSON.stringify([fdoc.followup_at, fdoc.followup_count])]);
  await tab("applied");
  results.push(["Nachfassen: danach nicht mehr fällig, Chip „nachgefasst am“", !panel() && /nachgefasst am/.test(rowOf("Stelle Nachfassen").textContent), dueText().slice(0, 80)]);
  const C3 = copy(CONFIG); C3.followup_days = 4; C3.followup_max = 3;
  await setConfig(C3); await tab("applied");
  results.push(["Nachfassen: Frist und Höchstzahl aus der Konfiguration", /Stelle Beworben Offline/.test(dueText()) && /Erledigt/.test(dueText()) && /Anzeige nicht mehr online/.test(dueText()), dueText().slice(0, 200)]);
  const cf = buildConfig({ followup_days: "7", followup_max: 0 });
  results.push(["Nachfassen: ungültige Werte fallen auf 14 Tage / 2-mal zurück", cf.followupDays === 14 && cf.followupMax === 2, ""]);
  await setConfig(copy(CONFIG));
  } catch (e) { results.push(["Nachfassen: Testblock läuft durch", false, String(e && e.stack || e).slice(0, 300)]); }
  results.push(["Keine JS-Fehler", !(window.__errors || []).length, (window.__errors || []).join(" | ")]);
  window.__results = results;
  document.title = "DONE";
})();
