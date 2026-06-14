/* TOC Bank tab — independent of analytics; reads /api/toc-bank on its
   own. Touches only #toc-total and #toc-groups. */

async function refreshTocBank() {
  try {
    const r = await fetch("data/toc-bank.json", {cache: "no-store"});
    if (!r.ok) return;
    const d = await r.json();
    renderTocBank(d);
  } catch (e) { /* best-effort */ }
}

function renderTocBank(d) {
  document.getElementById("toc-total").textContent = d.total ?? 0;
  const wrap = document.getElementById("toc-groups");
  const groups = (d.therapies || []);
  if (!groups.length) {
    wrap.innerHTML = `<div class="empty-state">No entries in the TOC Bank tab yet.</div>`;
    return;
  }
  wrap.innerHTML = groups.map((g, idx) => {
    const rows = (g.items || []).map(it => {
      const headerCell = it.link
        ? `<a class="toc-link" href="${esc(it.link)}" target="_blank" rel="noopener">${esc(it.header)}</a>`
        : esc(it.header);
      const sub = it.comm_header
        ? `<span class="toc-sub">${esc(it.comm_header)}</span>` : "";
      const bucket = it.bucket
        ? `<span class="bucket-pill">${esc(it.bucket)}</span>` : "";
      return `<tr>
        <td class="sr">${esc(it.sr_no || "")}</td>
        <td>${headerCell}${sub}</td>
        <td class="bucket">${bucket}</td>
      </tr>`;
    }).join("");
    const open = idx === 0 ? "open" : "";
    return `<div class="group ${open}">
      <div class="group-head" onclick="this.parentElement.classList.toggle('open')">
        <div class="gh-left"><span class="caret">▶</span>
          <div><div class="gh-title">💊 ${esc(g.therapy)}</div>
            <div class="gh-sub">${g.count} article${g.count === 1 ? "" : "s"}</div></div>
        </div>
      </div>
      <div class="group-body">
        <table class="toc-table">
          <thead><tr><th>Sr.</th><th>Article header</th><th>Bucket</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}
