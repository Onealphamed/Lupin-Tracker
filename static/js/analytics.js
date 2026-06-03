/* Analytics view: KPI tiles, owner cards, per-stage progress bars,
   drilldown modal. Reads d.kpi + d.grid from /api/analytics.

   Independent of matrix-views.js and tocbank.js — touches only the
   #owner-strip / #kpi-strip / #stagebars / #drilldown elements. */

/* ── Domain knowledge ── */
// Which side owns each stage. Edit here when ownership changes; the
// owner cards, drilldown, and per-row blinker (matrix-views.js) all
// read this same map.
const STAGE_OWNERS = {
  "TOC Shared":   "OAM",
  "TOC Approved": "Lupin",
  "Design Plan":  "OAM",
  "CRD Upload":   "OAM",
};
const OWNER_META = {
  OAM:   {label: "OAM (Alphamed)", hue: "#4fc3f7"},
  Lupin: {label: "Lupin (Client)", hue: "#ff9e80"},
};

// Items that sit in the "Therapies" column but aren't actual therapy
// areas — they get their own tab so the Therapy-wise roll-ups stay
// clean. Case-insensitive on trimmed name.
const NON_THERAPY_ITEMS = new Set(["cpd", "newsletter"]);
function isNonTherapy(name) {
  return NON_THERAPY_ITEMS.has(String(name || "").trim().toLowerCase());
}

/* ── Owner-stat computation ── */
// Walk the full grid once → per-owner counts + the exact items behind
// each count, so the drilldown opens instantly without another scan.
function computeOwnerStats(grid) {
  const out = {
    OAM:   {done: 0, pending: 0, done_items: [], pending_items: []},
    Lupin: {done: 0, pending: 0, done_items: [], pending_items: []},
  };
  for (const row of (grid || [])) {
    for (const s of (row.stages || [])) {
      const owner = STAGE_OWNERS[s.name];
      if (!owner || !out[owner]) continue;
      const key = s.done ? "done" : "pending";
      out[owner][key]++;
      out[owner][key + "_items"].push({
        month: row.month, therapy: row.therapy, stage: s.name,
        value: s.value, comment: row.comment,
      });
    }
  }
  return out;
}

/* ── KPI strip ── */
function renderKpis(d) {
  const k = d.kpi || {};
  const stats = computeOwnerStats(d.grid);

  const ownerCards = ["OAM", "Lupin"].map(owner => {
    const s = stats[owner];
    const m = OWNER_META[owner];
    const total = s.done + s.pending;
    const pct = total ? Math.round(100 * s.done / total) : 0;
    const ownerStages = Object.entries(STAGE_OWNERS)
      .filter(([, o]) => o === owner).map(([n]) => n).join(" · ");
    return `<div class="owner-card" style="--owner-hue:${m.hue}">
      <div class="oc-head">
        <div>
          <div class="oc-title">${esc(m.label)}</div>
          <div class="oc-sub">${esc(ownerStages)}</div>
        </div>
        <div class="oc-pct">${pct}%</div>
      </div>
      <div class="oc-bar"><div class="fill" style="width:${pct}%"></div></div>
      <div class="oc-tiles">
        <button class="oc-tile done" data-owner="${owner}" data-state="done"
          title="See completed ${esc(m.label)} stages">
          <div class="oct-label">✅ Done</div>
          <div class="oct-value">${s.done}</div>
        </button>
        <button class="oc-tile pending" data-owner="${owner}" data-state="pending"
          title="See pending ${esc(m.label)} stages">
          <div class="oct-label">⬜ Pending</div>
          <div class="oct-value">${s.pending}</div>
        </button>
      </div>
    </div>`;
  }).join("");
  document.getElementById("owner-strip").innerHTML = ownerCards;

  // Therapy count excludes CPD/Newsletter (they live in the Non-therapy
  // tab) so the tile matches the Therapy-wise view exactly.
  const allNames = d.therapies_order || [];
  const therapyCount = allNames.filter(n => !isNonTherapy(n)).length;
  const nonTherapyCount = allNames.filter(n => isNonTherapy(n)).length;
  const small = [
    {label: "Months",       value: k.months ?? 0},
    {label: "Therapies",    value: therapyCount},
    {label: "Non-therapy",  value: nonTherapyCount},
  ];
  document.getElementById("kpi-strip").innerHTML = small.map(c =>
    `<div class="kpi"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`
  ).join("");

  // Bind clicks AFTER innerHTML so querySelectorAll sees new nodes.
  document.querySelectorAll("#owner-strip .oc-tile").forEach(btn => {
    btn.addEventListener("click", () => {
      const owner = btn.dataset.owner;
      const state = btn.dataset.state;
      openDrilldown(owner, state, stats[owner][state + "_items"]);
    });
  });
}

/* ── Per-stage progress bars ── */
function renderStageBars(per) {
  document.getElementById("stagebars").innerHTML = (per || []).map(s => `
    <div class="stagebar">
      <div class="sb-name"><span>${esc(s.name)}</span><span>${s.done}/${s.total} · ${s.pct}%</span></div>
      <div class="bar"><div class="fill" style="width:${s.pct}%"></div></div>
    </div>`).join("");
}

/* ── Drilldown modal ── */
function openDrilldown(owner, state, items) {
  const m = OWNER_META[owner];
  const byMonth = {};
  const monthOrder = [];
  for (const it of (items || [])) {
    const mo = it.month || "(no month)";
    if (!(mo in byMonth)) { byMonth[mo] = []; monthOrder.push(mo); }
    byMonth[mo].push(it);
  }
  const body = monthOrder.map(mo => {
    const rows = byMonth[mo].map(it =>
      `<tr>
        <td>${esc(it.therapy)}</td>
        <td>${esc(it.stage)}</td>
        <td>${esc(it.value || "—")}</td>
        <td class="dd-comment">${esc(it.comment || "")}</td>
      </tr>`).join("");
    return `<div class="dd-month">
      <div class="dd-month-head">🗓 ${esc(mo)} <span class="dd-count">${byMonth[mo].length}</span></div>
      <table class="dd-table">
        <thead><tr><th>Therapy</th><th>Stage</th><th>Sheet value</th><th>Comment</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join("");
  const stateLabel = state === "done" ? "✅ Completed" : "⬜ Pending";
  document.getElementById("dd-title").innerHTML =
    `${esc(m.label)} — ${stateLabel} <span style="color:var(--text-dim);font-weight:400">(${(items || []).length})</span>`;
  document.getElementById("dd-body").innerHTML = body ||
    `<div class="empty-state">Nothing here. 🎉</div>`;
  document.getElementById("drilldown").classList.add("open");
}
function closeDrilldown() {
  document.getElementById("drilldown").classList.remove("open");
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDrilldown();
});
