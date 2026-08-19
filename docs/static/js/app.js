/* Orchestrator — LIVE build.

   Reads the Google Sheet directly in the browser (gviz JSONP, so it works
   cross-origin from any static host) and computes the analytics client-side,
   so the dashboard always reflects the current sheet — new months appear
   automatically, no snapshot to regenerate.

   Completion is VALUE-BASED: a stage counts as done when its cell has a
   value (a date / "Yes"). gviz cannot read cell background colours, so the
   green fill isn't visible here — filled cells are treated as done. */

// ── config ──
const SHEET_ID = "1iVYMDAIafpNMKieIJbLCiRplxeBokOGHe_knWQBhTJY";
const TOC_TAB  = "TOC Bank";
const NOTES_TAB = "Notes";
const STAGE_NAMES = ["TOC Shared", "TOC Approved", "Design Plan", "CRD Upload"];
// Fixed column layout of the data tab (0-based):
//   0 Months | 1 (blank) | 2 Therapies | 3 TOC Shared | 4 TOC Approved
//   5 Design Plan | 6 CRD Upload | 7 Comments
const COL = { month: 0, therapy: 2, stages: [3, 4, 5, 6], comment: 7 };

window.STAGES = STAGE_NAMES.slice();
let _data = null;

// ── gviz JSONP loader (script tag → no CORS needed) ──
function gvizLoad(sheetName, headerRows) {
  return new Promise(function (resolve, reject) {
    const cb = "__gv" + Math.random().toString(36).slice(2);
    const s = document.createElement("script");
    const timer = setTimeout(function () { cleanup(); reject(new Error("timeout")); }, 20000);
    function cleanup() { clearTimeout(timer); try { delete window[cb]; } catch (e) {} s.remove(); }
    window[cb] = function (resp) { cleanup(); resolve(resp); };
    let url = "https://docs.google.com/spreadsheets/d/" + SHEET_ID +
      "/gviz/tq?headers=" + (headerRows == null ? 0 : headerRows) + "&tqx=out:json;responseHandler:" + cb;
    if (sheetName) url += "&sheet=" + encodeURIComponent(sheetName);
    s.onerror = function () { cleanup(); reject(new Error("script error")); };
    s.src = url;
    document.head.appendChild(s);
  });
}

// gviz cell → display string (prefer the formatted value, e.g. "09-07-2026")
function _cell(c) {
  if (c == null) return "";
  if (c.f != null && c.f !== "") return String(c.f);
  if (c.v != null) return String(c.v);
  return "";
}
function tableToGrid(table) {
  const rows = (table && table.rows) || [];
  return rows.map(function (row) { return (row.c || []).map(_cell); });
}

// ── analytics (value-based), skipping repeated header rows ──
function analyzeGrid(grid) {
  const monthsOrder = [], therapiesOrder = [], gridRows = [];
  let curMonth = "";
  for (let ri = 0; ri < grid.length; ri++) {
    const raw = grid[ri];
    const g = function (i) { return (i < raw.length ? String(raw[i] || "").trim() : ""); };
    const mCell = g(COL.month), tCell = g(COL.therapy);
    // skip the sheet header and any repeated "Months … Therapies …" rows
    if (mCell === "Months" || tCell === "Therapies") continue;
    if (mCell) curMonth = mCell;
    const therapy = tCell;
    if (!therapy) continue;
    if (curMonth && monthsOrder.indexOf(curMonth) < 0) monthsOrder.push(curMonth);
    if (therapiesOrder.indexOf(therapy) < 0) therapiesOrder.push(therapy);
    const stages = COL.stages.map(function (col, s) {
      const val = g(col);
      return { name: STAGE_NAMES[s], value: val, done: val !== "", _col: col + 1 };
    });
    gridRows.push({
      month: curMonth, therapy: therapy, stages: stages, comment: g(COL.comment),
      done_count: stages.filter(function (s) { return s.done; }).length,
      total: stages.length, _row: ri,
    });
  }

  const pct = function (d, t) { return t ? Math.round(100 * d / t) : 0; };
  const blankStage = function () { const o = {}; STAGE_NAMES.forEach(function (n) { o[n] = { done: 0, total: 0 }; }); return o; };
  const months = {}, therapies = {};
  const perStage = {}; STAGE_NAMES.forEach(function (n) { perStage[n] = { done: 0, total: 0 }; });
  let totalCells = 0, doneCells = 0;

  gridRows.forEach(function (gr) {
    const mb = months[gr.month] || (months[gr.month] = { month: gr.month, done: 0, total: 0, stages: blankStage(), therapies: {} });
    const tb = therapies[gr.therapy] || (therapies[gr.therapy] = { therapy: gr.therapy, done: 0, total: 0, stages: blankStage(), months: {} });
    const mt = mb.therapies[gr.therapy] || (mb.therapies[gr.therapy] = { done: 0, total: 0, comment: gr.comment });
    const tm = tb.months[gr.month] || (tb.months[gr.month] = { done: 0, total: 0, comment: gr.comment });
    gr.stages.forEach(function (s) {
      totalCells++; mb.total++; tb.total++; mt.total++; tm.total++;
      mb.stages[s.name].total++; tb.stages[s.name].total++; perStage[s.name].total++;
      if (s.done) {
        doneCells++; mb.done++; tb.done++; mt.done++; tm.done++;
        mb.stages[s.name].done++; tb.stages[s.name].done++; perStage[s.name].done++;
      }
    });
  });
  Object.keys(months).forEach(function (m) { months[m].pct = pct(months[m].done, months[m].total); });
  Object.keys(therapies).forEach(function (t) { therapies[t].pct = pct(therapies[t].done, therapies[t].total); });
  const fullyDone = gridRows.filter(function (gr) { return gr.total && gr.done_count === gr.total; }).length;

  return {
    kpi: {
      total_cells: totalCells, done_cells: doneCells, pending_cells: totalCells - doneCells,
      progress_pct: pct(doneCells, totalCells), total_rows: gridRows.length,
      fully_done_rows: fullyDone, pending_rows: gridRows.length - fullyDone,
      months: monthsOrder.length, therapies: therapiesOrder.length,
    },
    stages: STAGE_NAMES.slice(),
    per_stage: STAGE_NAMES.map(function (n) {
      return { name: n, done: perStage[n].done, total: perStage[n].total, pct: pct(perStage[n].done, perStage[n].total) };
    }),
    months_order: monthsOrder, therapies_order: therapiesOrder,
    months: monthsOrder.map(function (m) { return months[m]; }),
    therapies: therapiesOrder.map(function (t) { return therapies[t]; }),
    grid: gridRows, color_source: true, updated_at: new Date().toISOString(),
  };
}

// ── TOC bank (Therapies | Sr. No | Article header | Header of comm | Link | Bucket) ──
function buildToc(grid) {
  const order = [], by = {};
  let cur = "";
  for (let ri = 0; ri < grid.length; ri++) {
    const raw = grid[ri];
    const g = function (i) { return (i < raw.length ? String(raw[i] || "").trim() : ""); };
    const t = g(0);
    if (t === "Therapies") continue;               // header row
    if (t) cur = t;
    const article = g(2), link = g(4);
    if (!article && !link) continue;
    const key = cur || "(unspecified)";
    if (!by[key]) { by[key] = []; order.push(key); }
    by[key].push({ sr_no: g(1), header: article, comm_header: g(3), link: link, bucket: g(5) });
  }
  let total = 0; order.forEach(function (k) { total += by[k].length; });
  return { total: total, therapies: order.map(function (k) { return { therapy: k, count: by[k].length, items: by[k] }; }) };
}

// ── Meeting notes (Notes tab: Date | Meeting | Note | Status) ──
function _parseDMY(s) {
  if (!s) return 0;
  const m = String(s).match(/(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{2,4})/);
  if (m) { let y = +m[3]; if (y < 100) y += 2000; return new Date(y, +m[2] - 1, +m[1]).getTime(); }
  const d = Date.parse(s); return isNaN(d) ? 0 : d;
}
function renderNotes(resp) {
  const wrap = document.getElementById("notes-groups");
  const help = '<div class="notes-empty">No meeting notes yet.<br>' +
    'Add a <b>Notes</b> tab to the Google Sheet with columns ' +
    '<b>Date&nbsp;·&nbsp;Meeting&nbsp;·&nbsp;Note&nbsp;·&nbsp;Status</b>, type your weekly / monthly points, and they show up here.</div>';
  if (!resp || resp.status === "error" || !resp.table || !resp.table.rows) { wrap.innerHTML = help; return; }
  const grid = tableToGrid(resp.table);   // headers=1 → data rows only
  const groups = []; let curDate = "", curMeeting = "";
  for (let i = 0; i < grid.length; i++) {
    const raw = grid[i];
    const g = function (j) { return (j < raw.length ? String(raw[j] || "").trim() : ""); };
    const date = g(0), meeting = g(1), note = g(2), status = g(3);
    if (date) curDate = date;
    if (meeting) curMeeting = meeting;
    if (!note) continue;
    const key = curDate + "||" + curMeeting;
    let grp = null;
    for (let k = 0; k < groups.length; k++) { if (groups[k].key === key) { grp = groups[k]; break; } }
    if (!grp) { grp = { key: key, date: curDate, meeting: curMeeting, points: [] }; groups.push(grp); }
    grp.points.push({ note: note, status: status });
  }
  if (!groups.length) { wrap.innerHTML = help; return; }
  groups.sort(function (a, b) { return _parseDMY(b.date) - _parseDMY(a.date); });
  wrap.innerHTML = groups.map(function (grp) {
    const items = grp.points.map(function (p) {
      let pill = "";
      const st = String(p.status || "").toLowerCase();
      if (st) {
        const cls = (st.indexOf("done") >= 0 || st.indexOf("closed") >= 0 || st.indexOf("complete") >= 0) ? "done" : "open";
        pill = ' <span class="notes-status ' + cls + '">' + esc(p.status) + '</span>';
      }
      return "<li>" + esc(p.note) + pill + "</li>";
    }).join("");
    const meeting = grp.meeting ? '<span class="notes-meeting">' + esc(grp.meeting) + '</span>' : "";
    const date = grp.date ? '<span class="notes-date">📅 ' + esc(grp.date) + '</span>'
                          : '<span class="notes-date">📝 Note</span>';
    return '<div class="panel notes-card"><div class="notes-head">' + date + meeting + '</div>' +
      '<ul class="notes-list">' + items + '</ul></div>';
  }).join("");
}

// ── load + render ──
async function loadAll() {
  const lu = document.getElementById("last-updated");
  try {
    const dataResp = await gvizLoad(null);            // first sheet = data tab
    const d = analyzeGrid(tableToGrid(dataResp.table));
    _data = d;
    window.STAGES = d.stages;
    lu.textContent = "Live · updated " + new Date().toLocaleString();
    document.getElementById("color-banner").classList.add("hidden");
    renderKpis(d);
    renderStageBars(d.per_stage);
    renderMonthView(d);
    renderTherapyView(d);
    renderNonTherapyView(d);
  } catch (e) {
    lu.textContent = "⚠️ Could not load live data";
    console.error("data load failed", e);
  }
  try {
    const tocResp = await gvizLoad(TOC_TAB);
    renderTocBank(buildToc(tableToGrid(tocResp.table)));
  } catch (e) { console.error("toc load failed", e); }
  try {
    const notesResp = await gvizLoad(NOTES_TAB, 1);
    renderNotes(notesResp);
  } catch (e) { renderNotes(null); }
}

/* ── Tabs ── */
document.querySelectorAll(".tab-btn").forEach(function (b) {
  b.addEventListener("click", function () {
    document.querySelectorAll(".tab-btn").forEach(function (x) { x.classList.remove("active"); });
    document.querySelectorAll(".view").forEach(function (x) { x.classList.remove("active"); });
    b.classList.add("active");
    document.getElementById("view-" + b.dataset.view).classList.add("active");
    const v = b.dataset.view;
    document.getElementById("toolbar").style.display = (v === "sheet" || v === "toc" || v === "notes") ? "none" : "flex";
  });
});

/* ── Search debounce + expand/collapse all ── */
let _t = null;
document.getElementById("search").addEventListener("input", function () {
  clearTimeout(_t);
  _t = setTimeout(function () {
    if (_data) { renderMonthView(_data); renderTherapyView(_data); renderNonTherapyView(_data); }
  }, 140);
});
document.getElementById("expand-all").addEventListener("click", function () {
  document.querySelectorAll(".view.active .group").forEach(function (g) { g.classList.add("open"); });
});
document.getElementById("collapse-all").addEventListener("click", function () {
  document.querySelectorAll(".view.active .group").forEach(function (g) { g.classList.remove("open"); });
});

/* ── Initial load + refresh every 5 min while open ── */
loadAll();
setInterval(loadAll, 300000);
