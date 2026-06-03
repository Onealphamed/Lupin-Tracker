/* Orchestrator — wires the feature modules together.

   - refresh(): fetch /api/analytics, dispatch to each view renderer,
     then fire-and-forget refresh the TOC Bank.
   - Tab switching.
   - Search debounce + expand/collapse-all buttons.
   - Live-sheet iframe initialisation.
   - 60-second polling interval. */

// Boot values injected by the Jinja template (window.LUPIN_BOOT). The
// embedded fallback list keeps `window.STAGES` valid for the first
// paint, before /api/analytics has returned.
window.STAGES = (window.LUPIN_BOOT && window.LUPIN_BOOT.stages) || [];
let _data = null;

async function refresh() {
  const r = await fetch("/api/analytics", {cache: "no-store"});
  const d = await r.json();
  _data = d;
  if (Array.isArray(d.stages) && d.stages.length) window.STAGES = d.stages;
  document.getElementById("last-updated").textContent =
    "Updated " + new Date(d.updated_at).toLocaleTimeString();
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

/* ── Live-sheet iframe ── */
(function initIframe() {
  const boot = window.LUPIN_BOOT || {};
  const url = boot.apps_script_url || "";
  const tab = boot.data_tab || "";
  const iframe = document.getElementById("sheet-iframe");
  if (url) {
    iframe.src = url + "?tab=" + encodeURIComponent(tab);
  } else {
    iframe.srcdoc = '<div style="padding:40px;font-family:Arial">APPS_SCRIPT_URL not configured on the server.</div>';
  }
})();

/* ── Initial paint + 60-second polling ── */
refresh();
setInterval(refresh, 60000);
