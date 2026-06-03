"""Email send + HTML body formatters.

`send()` tries SMTP. On Render's free tier outbound SMTP is blocked
(errno 101), so it returns every address as "failed" — the caller hands
`failed` + the rendered HTML back to Apps Script which delivers via
MailApp.sendEmail using the spreadsheet owner's Google account. Local
dev or paid Render plans can fill SMTP_USER + SMTP_PASSWORD to send
directly.

The two HTML formatters use inline styles only — Gmail strips <style>
blocks. Lupin's green theme: header bar #6aa84f, CTA also green.
"""
from __future__ import annotations

import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from . import config
from .telegram_client import html_escape


def send(to_addrs: list[str], subject: str, html_body: str, text_body: str = "") -> tuple[int, list[str]]:
    """Send an HTML email to each address. Returns (sent_count, failed)."""
    if not to_addrs:
        return 0, []
    seen: set[str] = set()
    addrs: list[str] = []
    for a in to_addrs:
        a = (a or "").strip()
        if not a or a in seen:
            continue
        seen.add(a)
        addrs.append(a)
    if not addrs:
        return 0, []
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        # SMTP not configured locally — let MailApp handle every address.
        return 0, addrs

    if not text_body:
        text_body = re.sub(r"<[^>]+>", "", html_body).strip()

    sent = 0
    failed = list(addrs)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            for addr in addrs:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = formataddr((config.SMTP_FROM_NAME, config.SMTP_FROM_ADDR or config.SMTP_USER))
                msg["To"] = addr
                msg.attach(MIMEText(text_body, "plain", "utf-8"))
                msg.attach(MIMEText(html_body, "html", "utf-8"))
                try:
                    server.sendmail(config.SMTP_FROM_ADDR or config.SMTP_USER, [addr], msg.as_string())
                    sent += 1
                    failed.remove(addr)
                except Exception:
                    pass
    except Exception:
        # Connection/auth-level failure — everything stays "failed".
        pass
    return sent, failed


def _kv(label: str, value_html: str) -> str:
    return (
        '<tr>'
        f'<td style="padding:6px 12px 6px 0;color:#718096;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:0.5px;width:110px;vertical-align:top">'
        f'{html_escape(label)}</td>'
        f'<td style="padding:6px 0;color:#1a202c">{value_html}</td>'
        '</tr>'
    )


def format_edit_email(
    month: str, therapy: str, stage: str, old: str, new: str,
    is_done: bool, editor: str,
) -> tuple[str, str]:
    """Build (subject, html_body) for a single-cell edit notification."""
    state_label = "✅ Completed" if is_done else "⬜ Pending"
    state_color = "#38a169" if is_done else "#dd6b20"
    state_bg = "#f0fff4" if is_done else "#fffaf0"

    bits = [b for b in (therapy, month) if b]
    subject = f"[Lupin] {stage or 'Update'} {('completed' if is_done else 'pending')}"
    if bits:
        subject += " — " + " / ".join(bits)

    rows_html: list[str] = []
    if month:
        rows_html.append(_kv("Month", html_escape(month)))
    if therapy:
        rows_html.append(_kv("Therapy", f"<b>{html_escape(therapy)}</b>"))
    if stage:
        rows_html.append(_kv("Stage", html_escape(stage)))
    rows_html.append(_kv(
        "Status",
        f'<span style="background:{state_bg};color:{state_color};'
        f'padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600">'
        f'{html_escape(state_label)}</span>',
    ))
    if old:
        rows_html.append(_kv(
            "Was",
            f'<code style="background:#f0f3f7;padding:2px 6px;border-radius:3px">'
            f'{html_escape(old)}</code>',
        ))
    if new:
        rows_html.append(_kv("Now", f"<b>{html_escape(new)}</b>"))

    cta = (
        f'<a href="{html_escape(config.DASHBOARD_PUBLIC_URL)}" '
        'style="display:inline-block;background:#6aa84f;color:#ffffff;'
        'text-decoration:none;padding:10px 18px;border-radius:4px;'
        'font-size:13px;font-weight:600">Open dashboard ↗</a>'
        if config.DASHBOARD_PUBLIC_URL else ""
    )
    foot = (f"Edited by {html_escape(editor)}" if editor else "") + " — Lupin Tracker"

    html = f"""\
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f5f7fa;padding:24px 0">
  <tr><td align="center">
    <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:14px;color:#1a202c">
      <tr><td style="padding:20px 24px;border-bottom:3px solid #6aa84f;background:#f8fafc;border-radius:8px 8px 0 0">
        <div style="font-size:18px;font-weight:700;color:#33691e">🟢 Lupin Tracker — sheet update</div>
      </td></tr>
      <tr><td style="padding:20px 24px">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          {''.join(rows_html)}
        </table>
        {('<div style="padding-top:20px">' + cta + '</div>') if cta else ''}
      </td></tr>
      <tr><td style="padding:12px 24px;border-top:1px solid #e2e8f0;color:#718096;font-size:11px;background:#f8fafc;border-radius:0 0 8px 8px">
        {html_escape(foot)}
      </td></tr>
    </table>
  </td></tr>
</table>"""
    return subject, html


def format_weekly_email(data: dict) -> tuple[str, str]:
    """Build (subject, html_body) for the Monday weekly digest. `data` is
    the JSON shape returned by analytics.analyze()."""
    k = data.get("kpi", {})
    per_stage = data.get("per_stage", [])
    months = data.get("months", [])
    progress = int(k.get("progress_pct", 0))
    done = int(k.get("done_cells", 0))
    total = int(k.get("total_cells", 0))
    pending = int(k.get("pending_cells", 0))

    subject = f"[Lupin] Weekly digest — {done}/{total} stages done · {progress}%"

    kpi_strip = f"""
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:20px">
          <tr>
            <td style="padding:14px;background:#f0fff4;border-radius:6px;width:33%;text-align:center">
              <div style="font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:0.5px">Progress</div>
              <div style="font-size:24px;font-weight:700;color:#38a169;margin-top:4px">{progress}%</div>
            </td>
            <td style="width:8px"></td>
            <td style="padding:14px;background:#f8fafc;border-radius:6px;width:33%;text-align:center">
              <div style="font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:0.5px">Stages done</div>
              <div style="font-size:24px;font-weight:700;color:#1a202c;margin-top:4px">{done} / {total}</div>
            </td>
            <td style="width:8px"></td>
            <td style="padding:14px;background:#fffaf0;border-radius:6px;width:33%;text-align:center">
              <div style="font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:0.5px">Pending</div>
              <div style="font-size:24px;font-weight:700;color:#dd6b20;margin-top:4px">{pending}</div>
            </td>
          </tr>
        </table>"""

    stage_rows = ""
    for s in per_stage:
        name = s.get("name", "")
        sdone = int(s.get("done", 0))
        stotal = int(s.get("total", 0))
        spct = int(s.get("pct", 0))
        bar_fill_w = max(1, spct)
        stage_rows += f"""
          <tr><td style="padding:8px 0">
            <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
              <span style="font-weight:600">{html_escape(name)}</span>
              <span style="color:#718096">{sdone}/{stotal} · {spct}%</span>
            </div>
            <div style="height:7px;background:#edf2f7;border-radius:4px;overflow:hidden">
              <div style="height:100%;width:{bar_fill_w}%;background:#6aa84f"></div>
            </div>
          </td></tr>"""

    month_rows = ""
    for mb in months:
        mname = mb.get("month", "")
        mdone = int(mb.get("done", 0))
        mtotal = int(mb.get("total", 0))
        mpct = int(mb.get("pct", 0))
        month_rows += (
            f'<tr>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #edf2f7;font-weight:600">{html_escape(mname)}</td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #edf2f7;color:#718096;font-size:12px">{mdone} / {mtotal}</td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #edf2f7;text-align:right;color:#6aa84f;font-weight:700">{mpct}%</td>'
            f'</tr>'
        )

    cta = (
        f'<a href="{html_escape(config.DASHBOARD_PUBLIC_URL)}" '
        'style="display:inline-block;background:#6aa84f;color:#ffffff;text-decoration:none;'
        'padding:10px 18px;border-radius:4px;font-size:13px;font-weight:600">Open dashboard ↗</a>'
        if config.DASHBOARD_PUBLIC_URL else ""
    )

    html = f"""\
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f5f7fa;padding:24px 0">
  <tr><td align="center">
    <table cellpadding="0" cellspacing="0" border="0" width="640" style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:14px;color:#1a202c">
      <tr><td style="padding:20px 24px;border-bottom:3px solid #6aa84f;background:#f8fafc;border-radius:8px 8px 0 0">
        <div style="font-size:18px;font-weight:700;color:#33691e">📊 Weekly digest — Lupin Tracker</div>
      </td></tr>
      <tr><td style="padding:20px 24px">
        {kpi_strip}

        <div style="font-size:13px;font-weight:700;color:#33691e;margin-bottom:8px;border-bottom:1px solid #e2e8f0;padding-bottom:6px">Stage-wise progress</div>
        <table cellpadding="0" cellspacing="0" border="0" width="100%">{stage_rows}</table>

        <div style="font-size:13px;font-weight:700;color:#33691e;margin:20px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:6px">Month-wise progress</div>
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="font-size:13px">{month_rows}</table>

        {('<div style="padding-top:20px">' + cta + '</div>') if cta else ''}
      </td></tr>
      <tr><td style="padding:12px 24px;border-top:1px solid #e2e8f0;color:#718096;font-size:11px;background:#f8fafc;border-radius:0 0 8px 8px">
        Sent every Monday at 09:00 — Lupin Tracker
      </td></tr>
    </table>
  </td></tr>
</table>"""
    return subject, html
