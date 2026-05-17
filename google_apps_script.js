/**
 * Lupin Tracker — Google Apps Script
 *
 * Paste this entire file into the sheet's Apps Script editor
 * (Extensions → Apps Script), Save, reload the sheet, then run `setup()`
 * once from the "Lupin Tracker" menu.
 *
 * Unlike the Zydus tracker there is NO Status column. A stage cell counts
 * as DONE only when its background is green. This script is what lets the
 * dashboard see that — gviz CSV cannot read cell colours, so the backend
 * calls action=read_grid here to get values AND backgrounds together.
 *
 * It does:
 *   1. seedRecipients()  – creates the Recipients tab (run once).
 *   2. doGet(e)          – styled HTML mirror of the data tab (full colour)
 *                          for the dashboard iframe.
 *   3. doPost(e)         – actions from Flask:
 *                            read_grid          → values + backgrounds
 *                            set_cell_done      → toggle a cell green/clear
 *                            register_recipient → add a Telegram chat
 *   4. onEditHook(e)     – installable onEdit; POSTs month/therapy/stage
 *                          context to /api/sheet-edit on VALUE edits.
 *   4b. onChangeHook(e)  – installable onChange (FORMAT); same fan-out for
 *                          COLOUR-only edits (painting a cell green), which
 *                          onEdit cannot see.
 *   5. weeklyDigest()    – Monday 9 AM; hits /api/weekly.
 */

// ───────────────────────────── config ─────────────────────────────

// PASTE YOUR RENDER URL HERE after deploying the Flask app.
// e.g. "https://lupin-tracker.onrender.com"
const DASHBOARD_URL = "REPLACE_WITH_RENDER_URL";

// Must match TICK_PASSWORD in the Render env vars.
const PASSWORD = "Alphamed@4321";

// Name of the main data tab. If the script can't find it, it falls back
// to the first sheet in the spreadsheet, so this rarely needs editing.
const TAB_DATA = "Tracker";
const TAB_RECIPIENTS = "Recipients";

// The green used when you (or the dashboard) mark a cell done.
const DONE_GREEN = "#b6d7a8";

// ───────────────────────────── menu ─────────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Lupin Tracker")
    .addItem("🌱 Create Recipients tab (run once)", "seedRecipients")
    .addSeparator()
    .addItem("⚙️ Install triggers (onEdit + weekly)", "installTriggers")
    .addItem("🛑 Remove all triggers", "removeAllTriggers")
    .addSeparator()
    .addItem("📨 Send weekly digest now", "weeklyDigestNow")
    .addItem("🔌 Test backend connection", "testConnection")
    .addToUi();
}

function setup() {
  onOpen();
  seedRecipients();
  installTriggers();
  SpreadsheetApp.getUi().alert(
    "Setup complete. Now deploy this script as a Web App " +
    "(Deploy → New deployment → Web app → Execute as: Me, Access: Anyone) " +
    "and paste the /exec URL into Render as APPS_SCRIPT_URL."
  );
}

// ──────────────────────── data tab resolver ────────────────────────

function _dataSheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name || TAB_DATA);
  if (sh) return sh;
  sh = ss.getSheetByName(TAB_DATA);
  if (sh) return sh;
  // Fall back to the first non-Recipients sheet.
  const all = ss.getSheets();
  for (let i = 0; i < all.length; i++) {
    if (all[i].getName() !== TAB_RECIPIENTS) return all[i];
  }
  return all[0] || null;
}

// ──────────────────────── seed Recipients ────────────────────────

function seedRecipients() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let recip = ss.getSheetByName(TAB_RECIPIENTS);
  if (!recip) recip = ss.insertSheet(TAB_RECIPIENTS);
  if (recip.getLastRow() === 0) {
    const headers = ["Name", "Role", "Chat ID", "Notify on edit?", "Weekly digest?", "Notes"];
    recip.getRange(1, 1, 1, headers.length).setValues([headers])
      .setFontWeight("bold").setBackground("#6aa84f").setFontColor("#fff");
    recip.appendRow(["(Auto-filled when you /start the Telegram bot)", "Brand Manager", "", "Yes", "Yes", ""]);
    recip.setFrozenRows(1);
    const yn = SpreadsheetApp.newDataValidation().requireValueInList(["Yes", "No"], true).build();
    recip.getRange(2, 4, 1000, 1).setDataValidation(yn);
    recip.getRange(2, 5, 1000, 1).setDataValidation(yn);
  }
  SpreadsheetApp.getUi().alert("Recipients tab ready.");
}

// ───────────────────────── doGet: iframe HTML ─────────────────────────

function doGet(e) {
  const tab = (e && e.parameter && e.parameter.tab) || TAB_DATA;
  const sheet = _dataSheet(tab);
  if (!sheet) {
    return HtmlService.createHtmlOutput('<div style="padding:40px;font-family:Arial">Sheet not found</div>')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (!lastRow || !lastCol) {
    return HtmlService.createHtmlOutput('<div style="padding:40px;font-family:Arial">Empty sheet</div>')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }
  const range = sheet.getRange(1, 1, lastRow, lastCol);
  const values = range.getDisplayValues();
  const bg = range.getBackgrounds();
  const fw = range.getFontWeights();

  let html = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>';
  html += 'html,body{margin:0;padding:0;font-family:arial,sans-serif;font-size:10pt;color:#000;background:#fff}';
  html += 'table{border-collapse:collapse;background:#fff;width:100%}';
  html += 'td{border:1px solid #d0d0d0;padding:3px 8px;white-space:nowrap}';
  html += 'tr:first-child td{background:#6aa84f;color:#fff;font-weight:bold;position:sticky;top:0;z-index:2}';
  html += '</style></head><body><table>';
  for (let r = 0; r < values.length; r++) {
    html += "<tr>";
    for (let c = 0; c < values[r].length; c++) {
      let v = String(values[r][c] || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      let style = "";
      if (r > 0 && bg[r][c] && bg[r][c] !== "#ffffff") style += "background:" + bg[r][c] + ";";
      if (fw[r][c] === "bold" && r > 0) style += "font-weight:bold;";
      html += '<td style="' + style + '">' + v + "</td>";
    }
    html += "</tr>";
  }
  html += "</table></body></html>";
  return HtmlService.createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .setTitle("Lupin Tracker");
}

// ───────────────────────── doPost: actions from Flask ─────────────────────────

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) {}
  if (body.password !== PASSWORD) {
    return _json({ ok: false, error: "bad password" });
  }
  try {
    if (body.action === "read_grid") return _actionReadGrid(body);
    if (body.action === "set_cell_done") return _actionSetCellDone(body);
    if (body.action === "register_recipient") return _actionRegisterRecipient(body);
    return _json({ ok: false, error: "unknown action" });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// Values + backgrounds for the whole data tab. This is the call that
// lets the dashboard see green = done.
function _actionReadGrid(body) {
  const sheet = _dataSheet(body.tab);
  if (!sheet) return _json({ ok: false, error: "data tab not found" });
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (!lastRow || !lastCol) return _json({ ok: true, headers: [], rows: [], backgrounds: [] });
  const range = sheet.getRange(1, 1, lastRow, lastCol);
  const values = range.getDisplayValues();
  const bg = range.getBackgrounds(); // includes header row; row 0 = headers
  return _json({
    ok: true,
    headers: values[0],
    rows: values.slice(1),
    backgrounds: bg.slice(1), // align with rows (data only)
  });
}

// Toggle a single stage cell. When marking done: paint it green and, if
// empty, stamp today's date. When clearing: remove the fill and the date.
// `row` / `col` are 1-based DATA coordinates (row 1 = first data row, i.e.
// sheet row 2 since the header is row 1).
function _actionSetCellDone(body) {
  const sheet = _dataSheet(body.tab);
  if (!sheet) return _json({ ok: false, error: "data tab not found" });
  const sheetRow = Number(body.row) + 1; // +1 to skip header
  const sheetCol = Number(body.col);
  if (!sheetRow || !sheetCol) return _json({ ok: false, error: "bad row/col" });
  const cell = sheet.getRange(sheetRow, sheetCol);
  if (body.done) {
    cell.setBackground(DONE_GREEN);
    if (!String(cell.getValue() || "").trim()) {
      cell.setValue(Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd-MM-yyyy"));
    }
  } else {
    cell.setBackground(null);
    cell.clearContent();
  }
  return _json({ ok: true });
}

function _actionRegisterRecipient(body) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(TAB_RECIPIENTS);
  if (!sheet) return _json({ ok: false, error: "Recipients tab missing" });
  const chatId = String(body.chat_id || "");
  const name = String(body.name || "Unknown");
  const last = sheet.getLastRow();
  if (last > 1) {
    const data = sheet.getRange(2, 1, last - 1, sheet.getLastColumn()).getValues();
    for (let i = 0; i < data.length; i++) {
      if (String(data[i][2]) === chatId) return _json({ ok: true, already: true });
    }
  }
  sheet.appendRow([name, "Team", chatId, "Yes", "Yes", "Auto-registered " + new Date().toISOString()]);
  return _json({ ok: true });
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ───────────────────────── colour helper ─────────────────────────

function _isGreen(hex) {
  if (!hex) return false;
  let h = String(hex).trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
  if (h.length !== 6) return false;
  const r = parseInt(h.substr(0, 2), 16);
  const g = parseInt(h.substr(2, 2), 16);
  const b = parseInt(h.substr(4, 2), 16);
  if (r > 235 && g > 235 && b > 235) return false;
  return g >= 60 && (g - r) >= 8 && (g - b) >= 8;
}

// ───────────────────────── notify helper ─────────────────────────

// Build month/therapy/stage context for a single cell and POST it to the
// Flask /api/sheet-edit webhook. Shared by onEditHook (value edits) and
// onChangeHook (colour-only edits).
function _notifyCell(sheet, row, col, oldValue, newValue) {
  if (row === 1) return; // header
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const header = headers[col - 1] || "";

  // Locate Month, Therapy and the stage columns by fuzzy header match.
  let monthCol = -1, therapyCol = -1, commentCol = -1;
  for (let i = 0; i < headers.length; i++) {
    const hs = String(headers[i]).toLowerCase();
    if (monthCol < 0 && hs.indexOf("month") >= 0) monthCol = i + 1;
    else if (therapyCol < 0 && hs.indexOf("therap") >= 0) therapyCol = i + 1;
    if (hs.indexOf("comment") >= 0 || hs.indexOf("remark") >= 0) commentCol = i + 1;
  }

  // Only the four stage columns are worth a colour alert (between
  // Therapies and Comments, header non-empty). Skip Month/Therapy/blank.
  const stageStart = therapyCol > 0 ? therapyCol + 1 : 0;
  const stageEnd = commentCol > 0 ? commentCol : headers.length + 1;
  const isStageCol = col > stageStart && col < stageEnd && String(header).trim() !== "";
  if (!isStageCol) return;

  // Month is forward-filled — walk up until a non-empty month cell.
  let month = "";
  if (monthCol > 0) {
    for (let r = row; r >= 2; r--) {
      const v = String(sheet.getRange(r, monthCol).getDisplayValue() || "").trim();
      if (v) { month = v; break; }
    }
  }
  const therapy = therapyCol > 0
    ? String(sheet.getRange(row, therapyCol).getDisplayValue() || "").trim()
    : "";

  const bg = sheet.getRange(row, col).getBackground();
  const payload = {
    password: PASSWORD,
    tab: sheet.getName(),
    row: row, col: col,
    month: month,
    therapy: therapy,
    stage: header,
    header: header,
    old_value: oldValue || "",
    new_value: newValue == null ? "" : String(newValue),
    is_done: _isGreen(bg),
    editor: (Session.getActiveUser() || {}).getEmail ? Session.getActiveUser().getEmail() : "",
  };
  if (DASHBOARD_URL && DASHBOARD_URL.indexOf("http") === 0) {
    try {
      UrlFetchApp.fetch(DASHBOARD_URL + "/api/sheet-edit", {
        method: "post", contentType: "application/json",
        payload: JSON.stringify(payload), muteHttpExceptions: true,
      });
    } catch (err) { /* best-effort */ }
  }
}

// ───────────────────────── onEdit hook → Flask ─────────────────────────
// Fires on VALUE/content edits (typing a date, "Yes", clearing a cell).

function onEditHook(e) {
  if (!e || !e.range) return;
  const sheet = e.range.getSheet();
  const dataSheet = _dataSheet(null);
  if (!dataSheet || sheet.getName() !== dataSheet.getName()) return;
  _notifyCell(sheet, e.range.getRow(), e.range.getColumn(),
              e.oldValue || "", String(e.value || ""));
}

// ───────────────────── onChange hook → Flask ─────────────────────
// Apps Script's onEdit does NOT fire on background-colour changes, only
// on value changes. onChange WITH changeType "FORMAT" does. So when a
// user paints a cell green (no typing), this is the trigger that fans
// the Telegram alert. We read the active selection (the cells just
// formatted) and notify for any stage cell among them.
//
// We deliberately ignore changeType "EDIT" here — onEditHook already
// covers value edits, so handling EDIT in both would double-notify.

function onChangeHook(e) {
  if (!e || e.changeType !== "FORMAT") return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dataSheet = _dataSheet(null);
  if (!dataSheet) return;
  let range;
  try { range = ss.getActiveRange(); } catch (err) { return; }
  if (!range) return;
  const sheet = range.getSheet();
  if (sheet.getName() !== dataSheet.getName()) return;

  const r0 = range.getRow();
  const c0 = range.getColumn();
  const nR = range.getNumRows();
  const nC = range.getNumColumns();
  // Cap the scan so a "select all → recolour" can't fan out hundreds of
  // messages. _notifyCell itself ignores non-stage columns.
  if (nR * nC > 60) return;
  for (let dr = 0; dr < nR; dr++) {
    for (let dc = 0; dc < nC; dc++) {
      _notifyCell(sheet, r0 + dr, c0 + dc, "", "");
    }
  }
}

// ───────────────────────── weekly digest ─────────────────────────

function weeklyDigest() {
  if (!DASHBOARD_URL || DASHBOARD_URL.indexOf("http") !== 0) return;
  UrlFetchApp.fetch(DASHBOARD_URL + "/api/weekly", {
    method: "post", contentType: "application/json",
    payload: JSON.stringify({ password: PASSWORD }), muteHttpExceptions: true,
  });
}

function weeklyDigestNow() {
  weeklyDigest();
  SpreadsheetApp.getUi().alert("Triggered weekly digest. Check Telegram.");
}

// ───────────────────────── trigger management ─────────────────────────

function installTriggers() {
  removeAllTriggers();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ScriptApp.newTrigger("onEditHook").forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger("onChangeHook").forSpreadsheet(ss).onChange().create();
  ScriptApp.newTrigger("weeklyDigest").timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  SpreadsheetApp.getUi().alert(
    "Triggers installed:\n" +
    "• onEdit — value edits (typing a date / Yes)\n" +
    "• onChange — colour-only edits (painting a cell green)\n" +
    "• weekly digest — Mon 9 AM"
  );
}

function removeAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
}

function testConnection() {
  const ui = SpreadsheetApp.getUi();
  if (!DASHBOARD_URL || DASHBOARD_URL.indexOf("http") !== 0) {
    ui.alert("Set DASHBOARD_URL at the top of this script first.");
    return;
  }
  try {
    const r = UrlFetchApp.fetch(DASHBOARD_URL + "/healthz", { muteHttpExceptions: true });
    ui.alert("Health check: HTTP " + r.getResponseCode() + "\n" + r.getContentText().substring(0, 200));
  } catch (err) {
    ui.alert("Connection failed: " + err);
  }
}
