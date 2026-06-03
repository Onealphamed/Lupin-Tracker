/* Month-wise + Therapy-wise + Non-therapy views.

   All three are the same shape — collapsible cards with a row-per-item
   matrix of stage cells — so they share `_renderTherapyLike`. The cell
   toggle (click → POST /api/tick → refresh) and the per-row blinker
   live here too, since they only matter on these views. */

/* ── Per-row pending indicator (chain model) ──
   The four stages are sequential: TOC Shared → TOC Approved → Design
   Plan → CRD Upload. Each waits on the previous. The TRUE blocker on a
   row is the FIRST pending stage in that order; stages pending after
   it are just queued behind it. So at most ONE dot is shown, colored
   for the owner of the first pending stage. (No dot when fully done.)

   Example: row with TOC Shared ✓ + everything else pending → only the
   Lupin dot shows (TOC Approved is the blocker; Lupin owns it). */
function rowBlinkers(g) {
  for (const s of (g.stages || [])) {
    if (s.done) continue;
    const owner = STAGE_OWNERS[s.name];
    if (!owner) return "";
    const cls = owner === "OAM" ? "oam" : "lupin";
    return `<span class="row-blink-wrap"><span class="row-blink ${cls}" `
         + `title="${esc(owner)} blocker — next up: ${esc(s.name)}"></span></span>`;
  }
  return "";
}

/* ── Cell renderer + tick toggle ──
   STAGES is set as window.STAGES by app.js on the first analytics
   fetch (falls back to the Jinja-rendered list embedded in the page). */
function cellHtml(s, g) {
  const cls = s.done ? "done" : "pending";
  const tick = s.done ? "✓" : "○";
  const label = s.value ? esc(s.value) : (s.done ? "Done" : "—");
  return `<td><span class="cell ${cls}" title="Click to toggle '${esc(s.name)}' for ${esc(g.therapy)} (${esc(g.month)})"
    data-row="${g._row}" data-col="${s._col}" data-done="${s.done ? 1 : 0}"
    onclick="toggleCell(this)"><span class="tick">${tick}</span>${label}</span></td>`;
}

async function toggleCell(el) {
  const row = el.getAttribute("data-row");
  const col = el.getAttribute("data-col");
  const done = el.getAttribute("data-done") === "1";
  el.style.opacity = "0.5";
  try {
    const r = await fetch("/api/tick", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({row: Number(row), col: Number(col), done: !done}),
    });
    const d = await r.json();
    if (d.ok) { await refresh(); }
    else { alert("Could not update cell: " + (d.error || "unknown")); el.style.opacity = "1"; }
  } catch (e) { alert("Update failed: " + e); el.style.opacity = "1"; }
}

/* ── Month-wise view ──
   One collapsible card per month, therapy × stage matrix inside. */
function renderMonthView(d) {
  const q = query();
  const wrap = document.getElementById("month-groups");
  const byMonthTherapy = {};
  for (const g of d.grid) {
    (byMonthTherapy[g.month] = byMonthTherapy[g.month] || []).push(g);
  }
  const html = (d.months || []).map((mb, idx) => {
    const rows = (byMonthTherapy[mb.month] || []).filter(g => {
      if (!q) return true;
      return (g.month   || "").toLowerCase().includes(q) ||
             (g.therapy || "").toLowerCase().includes(q) ||
             (g.comment || "").toLowerCase().includes(q);
    });
    if (q && !rows.length) return "";
    const stageHead = window.STAGES.map(s => `<th>${esc(s)}</th>`).join("");
    const body = rows.map(g => {
      const cells = g.stages.map(s => cellHtml(s, g)).join("");
      return `<tr><td class="rowname">${rowBlinkers(g)}${esc(g.therapy)}</td>${cells}
        <td class="comment">${esc(g.comment || "")}</td></tr>`;
    }).join("");
    const open = (idx === 0 || q) ? "open" : "";
    return `<div class="group ${open}">
      <div class="group-head" onclick="this.parentElement.classList.toggle('open')">
        <div class="gh-left"><span class="caret">▶</span>
          <div><div class="gh-title">🗓 ${esc(mb.month)}</div>
            <div class="gh-sub">${mb.done}/${mb.total} stages · ${Object.keys(mb.therapies || {}).length} therapies</div></div>
        </div>
        <div style="text-align:right"><div class="gh-pct">${mb.pct}%</div></div>
      </div>
      <div class="group-body">
        <div class="group-bar"><div class="fill" style="width:${mb.pct}%"></div></div>
        <table class="matrix"><thead><tr><th>Therapy</th>${stageHead}<th>Comments</th></tr></thead>
        <tbody>${body}</tbody></table>
      </div></div>`;
  }).join("");
  wrap.innerHTML = html || `<div class="empty-state">No months match "${esc(q)}".</div>`;
}

/* ── Shared renderer for Therapy-wise and Non-therapy ──
   Both lay out one collapsible card per "therapy" name with a Month ×
   Stage matrix; they only differ in which names get through (`accept`)
   and how the empty state reads. */
function _renderTherapyLike(d, containerId, accept, icon, emptyLabel) {
  const q = query();
  const wrap = document.getElementById(containerId);
  const byTherapy = {};
  for (const g of d.grid) {
    if (!accept(g.therapy)) continue;
    (byTherapy[g.therapy] = byTherapy[g.therapy] || []).push(g);
  }
  const groups = (d.therapies || []).filter(tb => accept(tb.therapy));
  const html = groups.map((tb, idx) => {
    const rows = (byTherapy[tb.therapy] || []).filter(g => {
      if (!q) return true;
      return (g.month   || "").toLowerCase().includes(q) ||
             (g.therapy || "").toLowerCase().includes(q) ||
             (g.comment || "").toLowerCase().includes(q);
    });
    if (q && !rows.length) return "";
    const stageHead = window.STAGES.map(s => `<th>${esc(s)}</th>`).join("");
    const body = rows.map(g => {
      const cells = g.stages.map(s => cellHtml(s, g)).join("");
      return `<tr><td class="rowname">${rowBlinkers(g)}${esc(g.month)}</td>${cells}
        <td class="comment">${esc(g.comment || "")}</td></tr>`;
    }).join("");
    const open = (idx === 0 || q) ? "open" : "";
    return `<div class="group ${open}">
      <div class="group-head" onclick="this.parentElement.classList.toggle('open')">
        <div class="gh-left"><span class="caret">▶</span>
          <div><div class="gh-title">${icon} ${esc(tb.therapy)}</div>
            <div class="gh-sub">${tb.done}/${tb.total} stages · ${Object.keys(tb.months || {}).length} months</div></div>
        </div>
        <div style="text-align:right"><div class="gh-pct">${tb.pct}%</div></div>
      </div>
      <div class="group-body">
        <div class="group-bar"><div class="fill" style="width:${tb.pct}%"></div></div>
        <table class="matrix"><thead><tr><th>Month</th>${stageHead}<th>Comments</th></tr></thead>
        <tbody>${body}</tbody></table>
      </div></div>`;
  }).join("");
  wrap.innerHTML = html || `<div class="empty-state">No ${esc(emptyLabel)} ${q ? `match "${esc(q)}"` : "to show"}.</div>`;
}

function renderTherapyView(d) {
  _renderTherapyLike(d, "therapy-groups", n => !isNonTherapy(n), "💊", "therapies");
}
function renderNonTherapyView(d) {
  _renderTherapyLike(d, "non-therapy-groups", n => isNonTherapy(n), "📰", "non-therapy items");
}
