/* Theme toggle — light ↔ dark.

The initial data-theme attribute is set by a tiny inline script in
<head> of index.html (so the page never flashes the wrong theme on
reload). This module just updates the toggle icon and handles clicks.
State persists in localStorage under "lupin-theme". */

function _updateThemeIcon() {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var t = document.documentElement.getAttribute("data-theme") || "dark";
  btn.textContent = t === "dark" ? "☀️" : "🌙"; // icon shows the OTHER theme
  btn.title = "Switch to " + (t === "dark" ? "light" : "dark") + " theme";
}

function toggleTheme() {
  var cur = document.documentElement.getAttribute("data-theme") || "dark";
  var next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("lupin-theme", next); } catch (e) {}
  _updateThemeIcon();
}

// Sync the icon to whatever <head> already set as the initial theme.
_updateThemeIcon();
