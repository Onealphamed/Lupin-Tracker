/* Orchestrator — STATIC build.

   Adapted from the live app for GitHub Pages: reads the baked-in
   data/analytics.json + data/toc-bank.json snapshots instead of the
   Flask API, shows a "static snapshot" label, and does not poll. */

window.STAGES = (window.LUPIN_BOOT && window.LUPIN_BOOT.stages) || [];
let _data = null;

async function refresh() {
  const r = await fetch("data/analytics.json", {cache: "no-store"});
  const d = await r.json();
  _data = d;
  if (Array.isArray(d.stages) && d.stages.length) window.STAGES = d.stages;
  document.getElementById("last-updated").textContent = "📷 Static snapshot";
  document.getElementById("color-banner").classList.toggle("hidden", !!d.color_source);
  renderKpis(d);
  renderStageBars(d.per_stage);
  renderMonthView(d);
  renderTherapyView(d);
  renderNonTherapyView(d);
  refreshTocBank(); // separate endpoint, separate cadence
}

/* ── Tabs ── */
document.querySelectorAll(".tab-btn").forEach(b => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById("view-" + b.dataset.view).classList.add("active");
    // Search/expand-all toolbar only makes sense for the matrix views.
    const v = b.dataset.view;
    document.getElementById("toolbar").style.display = (v === "sheet" || v === "toc") ? "none" : "flex";
  });
});

/* ── Search debounce + expand/collapse all ── */
let _t = null;
document.getElementById("search").addEventListener("input", () => {
  clearTimeout(_t);
  _t = setTimeout(() => {
    if (_data) { renderMonthView(_data); renderTherapyView(_data); renderNonTherapyView(_data); }
  }, 140);
});
document.getElementById("expand-all").addEventListener("click", () =>
  document.querySelectorAll(".view.active .group").forEach(g => g.classList.add("open")));
document.getElementById("collapse-all").addEventListener("click", () =>
  document.querySelectorAll(".view.active .group").forEach(g => g.classList.remove("open")));

/* ── Live-sheet view is a static link panel (see index.html). ── */

/* ── Initial paint only — no polling in the static build. ── */
refresh();
