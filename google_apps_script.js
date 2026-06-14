/**
 * Lupin Tracker — Weekly Digest (SERVER-LESS)
 *
 * Self-contained Google Apps Script. The Flask backend on Render is gone
 * (the dashboard is now a static site), so this script no longer talks to
 * any server — it reads the sheet directly (values + green fills), builds
 * the digest, and emails it via MailApp using the spreadsheet owner's own
 * Google account. No SMTP creds, no API, no DASHBOARD_URL.
 *
 * Setup (one time):
 *   1. Extensions → Apps Script. Delete everything, paste THIS file, Save.
 *   2. Reload the sheet → a "Lupin Digest" menu appears.
 *   3. Menu → "📅 Install Friday 7:30 PM trigger" (authorise when asked).
 *   4. Menu → "📨 Send digest now" to test — check your inbox.
 *
 * Recipients: the "Recipients" tab, any row with Weekly digest? = Yes and
 * an Email. If none are set, it falls back to the sheet owner's email.
 */

// ───────────────────────────── config ─────────────────────────────
const TAB_DATA = "Tracker";              // falls back to the first non-Recipients sheet
const TAB_RECIPIENTS = "Recipients";
const DASHBOARD_URL = "https://lupin-tracker-1.onrender.com";  // live static dashboard (for the email button)

// ───────────────────────────── menu ─────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Lupin Digest")
    .addItem("📨 Send digest now (test)", "weeklyDigestNow")
    .addSeparator()
    .addItem("📅 Install Friday 7:30 PM trigger", "installDigestTrigger")
    .addItem("🛑 Remove all triggers", "removeAllTriggers")
    .addToUi();
}

// ──────────────────────── data tab resolver ────────────────────────
function _dataSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(TAB_DATA);
  if (sh) return sh;
  const all = ss.getSheets();
  for (let i = 0; i < all.length; i++) {
    if (all[i].getName() !== TAB_RECIPIENTS) return all[i];
  }
  return all[0] || null;
}

// ───────────────────────── green detector ─────────────────────────
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

// ───────────────────────── analytics (live, green-based) ─────────────────────────
function analyzeSheet() {
  const sheet = _dataSheet();
  if (!sheet) throw new Error("Data tab not found");
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  const rng = sheet.getRange(1, 1, lastRow, lastCol);
  const vals = rng.getDisplayValues();
  const bg = rng.getBackgrounds();
  const headers = vals[0];

  // locate columns (fuzzy)
  let monthCol = -1, therapyCol = -1, commentCol = -1;
  for (let i = 0; i < headers.length; i++) {
    const hs = String(headers[i] || "").toLowerCase();
    if (monthCol < 0 && hs.indexOf("month") >= 0) monthCol = i;
    else if (therapyCol < 0 && hs.indexOf("therap") >= 0) therapyCol = i;
    if (hs.indexOf("comment") >= 0 || hs.indexOf("remark") >= 0 || hs.indexOf("note") >= 0) commentCol = i;
  }
  const stageCols = [], stageNames = [];
  const end = commentCol >= 0 ? commentCol : headers.length;
  for (let i = therapyCol + 1; i < end; i++) {
    if (String(headers[i] || "").trim()) { stageCols.push(i); stageNames.push(String(headers[i]).trim()); }
  }

  const perStage = stageNames.map(function (n) { return { name: n, done: 0, total: 0 }; });
  const months = {}, monthsOrder = [];
  let totalCells = 0, doneCells = 0, totalRows = 0, fullyDone = 0;
  const openItems = [];
  let curMonth = "";

  for (let r = 1; r < vals.length; r++) {
    const m = monthCol >= 0 ? String(vals[r][monthCol] || "").trim() : "";
    if (m) curMonth = m;
    const therapy = therapyCol >= 0 ? String(vals[r][therapyCol] || "").trim() : "";
    if (!therapy) continue;
    totalRows++;
    if (!(curMonth in months)) { months[curMonth] = { done: 0, total: 0 }; monthsOrder.push(curMonth); }
    let rowDone = 0;
    for (let s = 0; s < stageCols.length; s++) {
      const c = stageCols[s];
      const green = _isGreen(bg[r][c]);
      perStage[s].total++; months[curMonth].total++; totalCells++;
      if (green) { perStage[s].done++; months[curMonth].done++; doneCells++; rowDone++; }
    }
    if (rowDone === stageCols.length) fullyDone++;
    const comment = commentCol >= 0 ? String(vals[r][commentCol] || "").trim() : "";
    if (comment) openItems.push({ month: curMonth, therapy: therapy, comment: comment });
  }

  const pct = function (d, t) { return t ? Math.round(100 * d / t) : 0; };
  return {
    overallPct: pct(doneCells, totalCells),
    doneCells: doneCells, totalCells: totalCells,
    totalRows: totalRows, fullyDone: fullyDone, pendingRows: totalRows - fullyDone,
    perStage: perStage.map(function (s) { return { name: s.name, done: s.done, total: s.total, pct: pct(s.done, s.total) }; }),
    months: monthsOrder.map(function (m) { return { month: m, done: months[m].done, total: months[m].total, pct: pct(months[m].done, months[m].total) }; }),
    openItems: openItems,
  };
}

// ───────────────────────── email body ─────────────────────────
function _bar(pct, color) {
  return '<table cellpadding="0" cellspacing="0" style="width:100%;background:#eef2f5;border-radius:4px;height:9px"><tr>' +
    '<td style="width:' + pct + '%;background:' + color + ';border-radius:4px;height:9px;font-size:0">&nbsp;</td>' +
    '<td style="font-size:0">&nbsp;</td></tr></table>';
}
function _esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function buildDigestHtml(a) {
  const tz = Session.getScriptTimeZone();
  const dateStr = Utilities.formatDate(new Date(), tz, "EEE, dd MMM yyyy");
  let stageRows = a.perStage.map(function (s) {
    return '<tr><td style="padding:5px 0;font:13px Arial;color:#222;width:130px">' + _esc(s.name) + '</td>' +
      '<td style="padding:5px 8px">' + _bar(s.pct, "#16a34a") + '</td>' +
      '<td style="padding:5px 0;font:700 13px Arial;color:#16a34a;width:80px;text-align:right">' + s.done + '/' + s.total + ' · ' + s.pct + '%</td></tr>';
  }).join("");
  let monthRows = a.months.map(function (m) {
    var color = m.pct >= 80 ? "#16a34a" : (m.pct >= 50 ? "#7cc24a" : "#f0b24a");
    return '<tr><td style="padding:4px 0;font:13px Arial;color:#222;width:170px">' + _esc(m.month) + '</td>' +
      '<td style="padding:4px 8px">' + _bar(m.pct, color) + '</td>' +
      '<td style="padding:4px 0;font:700 13px Arial;color:#333;width:50px;text-align:right">' + m.pct + '%</td></tr>';
  }).join("");
  let openRows = a.openItems.length
    ? a.openItems.map(function (it) {
        return '<tr><td style="padding:4px 8px;font:12px Arial;color:#444;border-bottom:1px solid #eee">' + _esc(it.month) + '</td>' +
          '<td style="padding:4px 8px;font:12px Arial;color:#444;border-bottom:1px solid #eee">' + _esc(it.therapy) + '</td>' +
          '<td style="padding:4px 8px;font:12px Arial;color:#b4540c;border-bottom:1px solid #eee">' + _esc(it.comment) + '</td></tr>';
      }).join("")
    : '<tr><td colspan="3" style="padding:8px;font:12px Arial;color:#16a34a">No open notes 🎉</td></tr>';

  return '' +
'<div style="max-width:640px;margin:0 auto;font-family:Arial,sans-serif;background:#fff;border:1px solid #e4e9ef;border-radius:10px;overflow:hidden">' +
  '<div style="background:linear-gradient(120deg,#0f1a14,#16351f);padding:18px 22px;color:#fff">' +
    '<div style="font-size:18px;font-weight:700">🟢 Lupin Tracker — Weekly Digest</div>' +
    '<div style="font-size:12px;color:#9dd7b4;margin-top:3px">' + dateStr + '</div>' +
  '</div>' +
  '<div style="padding:20px 22px">' +
    '<table cellpadding="0" cellspacing="0" style="width:100%"><tr>' +
      '<td style="font:800 40px Arial;color:#16a34a;line-height:1">' + a.overallPct + '%</td>' +
      '<td style="padding-left:14px;font:13px Arial;color:#555">overall complete<br>' +
        '<b>' + a.doneCells + '</b> of <b>' + a.totalCells + '</b> stage-tasks · <b>' + a.fullyDone + '</b>/' + a.totalRows + ' content pieces fully done</td>' +
    '</tr></table>' +
    '<div style="font:700 12px Arial;color:#2a3744;text-transform:uppercase;letter-spacing:.5px;margin:18px 0 6px">Stage funnel</div>' +
    '<table cellpadding="0" cellspacing="0" style="width:100%">' + stageRows + '</table>' +
    '<div style="font:700 12px Arial;color:#2a3744;text-transform:uppercase;letter-spacing:.5px;margin:18px 0 6px">By month</div>' +
    '<table cellpadding="0" cellspacing="0" style="width:100%">' + monthRows + '</table>' +
    '<div style="font:700 12px Arial;color:#2a3744;text-transform:uppercase;letter-spacing:.5px;margin:18px 0 6px">Open notes</div>' +
    '<table cellpadding="0" cellspacing="0" style="width:100%;border:1px solid #eee;border-radius:6px">' + openRows + '</table>' +
    '<div style="margin-top:22px;text-align:center">' +
      '<a href="' + DASHBOARD_URL + '" style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:11px 22px;border-radius:8px">Open the dashboard ↗</a>' +
    '</div>' +
    '<div style="margin-top:16px;font:11px Arial;color:#9aa6b2;text-align:center">Sent automatically every Friday · Lupin Tracker</div>' +
  '</div>' +
'</div>';
}

// ───────────────────────── recipients ─────────────────────────
function getDigestRecipients() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(TAB_RECIPIENTS);
  const out = [];
  if (sh && sh.getLastRow() > 1) {
    const data = sh.getRange(1, 1, sh.getLastRow(), sh.getLastColumn()).getDisplayValues();
    const hdr = data[0].map(function (h) { return String(h || "").toLowerCase(); });
    let emailCol = -1, weeklyCol = -1;
    for (let i = 0; i < hdr.length; i++) {
      if (emailCol < 0 && hdr[i].indexOf("email") >= 0) emailCol = i;
      if (weeklyCol < 0 && (hdr[i].indexOf("weekly") >= 0 || hdr[i].indexOf("digest") >= 0)) weeklyCol = i;
    }
    for (let r = 1; r < data.length; r++) {
      const email = emailCol >= 0 ? String(data[r][emailCol] || "").trim() : "";
      const weekly = weeklyCol >= 0 ? String(data[r][weeklyCol] || "").trim().toLowerCase() : "yes";
      if (email && email.indexOf("@") > 0 && (weekly === "yes" || weekly === "")) {
        if (out.indexOf(email) < 0) out.push(email);
      }
    }
  }
  if (!out.length) {
    const owner = (Session.getEffectiveUser() && Session.getEffectiveUser().getEmail()) || "";
    if (owner) out.push(owner);
  }
  return out;
}

// ───────────────────────── send ─────────────────────────
function sendWeeklyDigest() {
  const a = analyzeSheet();
  const html = buildDigestHtml(a);
  const subject = "Lupin Tracker — Weekly Digest (" + a.overallPct + "% complete)";
  const recipients = getDigestRecipients();
  let sent = 0;
  for (let i = 0; i < recipients.length; i++) {
    try {
      MailApp.sendEmail({ to: recipients[i], subject: subject, htmlBody: html, name: "Lupin Tracker" });
      sent++;
    } catch (err) { Logger.log("MailApp failed for %s: %s", recipients[i], err); }
  }
  Logger.log("Weekly digest sent to %s recipient(s): %s", sent, recipients.join(", "));
  return { sent: sent, recipients: recipients };
}

function weeklyDigestNow() {
  const res = sendWeeklyDigest();
  SpreadsheetApp.getUi().alert(
    "Weekly digest sent to " + res.sent + " recipient" + (res.sent === 1 ? "" : "s") + ":\n" +
    (res.recipients.join("\n") || "(none configured)")
  );
}

// ───────────────────────── triggers ─────────────────────────
function installDigestTrigger() {
  removeAllTriggers();
  ScriptApp.newTrigger("sendWeeklyDigest")
    .timeBased().onWeekDay(ScriptApp.WeekDay.FRIDAY).atHour(19).nearMinute(30).create();
  const tz = Session.getScriptTimeZone();
  SpreadsheetApp.getUi().alert(
    "Installed: weekly digest every Friday ~7:30 PM (" + tz + ").\n\n" +
    "Google fires time triggers within about a 15-minute window, so it " +
    "arrives between ~7:30 and 7:45 PM. Check Project Settings if the time " +
    "zone is wrong."
  );
}

function removeAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
}
