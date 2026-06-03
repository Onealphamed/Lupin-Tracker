/* Shared helpers used by every other dashboard module.
   Pure functions — no side effects, no DOM mutation. */

// HTML-escape a value before injecting it into innerHTML. Catches the
// five characters that matter for HTML + attribute contexts.
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Current value of the filter search box, lowercased and trimmed.
// Returns "" when the input doesn't exist yet (e.g. modal opened
// before the toolbar rendered).
function query() {
  var el = document.getElementById("search");
  return (el && el.value || "").toLowerCase().trim();
}
