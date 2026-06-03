# Lupin Tracker

Live, **month-wise** and **therapy-wise** content tracker powered by a single Google Sheet.

There is **no Status column**. A stage is *done* only when its cell is filled **green**;
an empty / uncoloured cell is *pending*. Exactly two states — that's it.

**What you get**
- KPI strip: overall %, stages done, pending, rows fully done, month & therapy counts
- Per-stage progress bars (TOC Shared → TOC Approved → Design Plan → CRD Upload)
- **Month-wise** view: collapsible card per month with a Therapy × Stage matrix + comments
- **Therapy-wise** view: collapsible card per therapy with a Month × Stage matrix + comments
- Click any cell to toggle it green/clear directly from the dashboard
- Live iframe mirror of the actual sheet (true colours)
- Telegram bot: alerts on every sheet edit **including colour-only changes**
  (painting a cell green) + a Monday 9 AM weekly digest
- Email alerts on the same events: per-edit notification + weekly digest in
  inline-styled HTML (delivered via Apps Script `MailApp` — uses the
  spreadsheet owner's Google account, so no SMTP creds are required)

The Google Sheet is the **single source of truth**. The dashboard reads it live; the
bot fires on edits.

> **Why an Apps Script is required:** Google's public CSV export cannot see cell
> background colours. Since completion *is* the green fill, the dashboard reads
> values **and** colours through the Apps Script Web App. Until that's wired the
> dashboard falls back to a value-based estimate and shows an amber banner.

---

## Sheet shape

| Months | (blank) | Therapies | TOC Shared | TOC Approved | Design Plan | CRD Upload | Comments |
|--------|---------|-----------|------------|--------------|-------------|------------|----------|
| May    |         | Respi     | 30-04-2026 | 11-05-2026   |             |            | … |
|        |         | Derma     | 08-05-2026 | 14-05-2026   |             |            | … |

- The **Months** label only appears on the first row of each month block — the
  dashboard forward-fills it down automatically.
- The blank spacer column is ignored.
- The four middle columns are *stages*. Their text (a date / "Yes" / blank) is
  informational; **the green background is what marks a stage done.**
- Column/stage names are detected fuzzily — you can rename or add stages and the
  dashboard adapts.

---

## One-time setup (~15 minutes)

### Step 1 — Share the sheet
Open the sheet → **Share** → "Anyone with the link" → **Viewer**.

### Step 2 — Create the Telegram bot

> ⚠️ **Create a brand-new bot — do NOT reuse the Zydus bot token.**
> Lupin is a different client. Each tracker is isolated only if it has its
> **own** bot token (its own `TELEGRAM_BOT_TOKEN`) and its **own** sheet's
> `Recipients` tab. They never cross-notify because:
> - the token is per-Render-service (not in the code), and
> - recipients live in this sheet's `Recipients` tab, separate from Zydus's.
>
> The single way a Lupin update could ever reach a Zydus client is if you
> paste the *same* token into both — so use a separate bot here.

1. Telegram → DM `@BotFather` → `/newbot`.
2. Name it `Lupin Tracker`, username e.g. `lupin_tracker_bot`
   (must be different from the Zydus bot).
3. Copy the **bot token** (looks like `7891234567:AAH...`).

### Step 3 — Paste the Apps Script
1. Sheet → **Extensions → Apps Script**.
2. Delete the default code → paste all of [`google_apps_script.js`](./google_apps_script.js).
3. **Save**, reload the sheet → a **Lupin Tracker** menu appears.
4. Menu → **🌱 Create Recipients tab (run once)**. Authorize when prompted.
5. **Deploy → New deployment → Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
   - Deploy → copy the **/exec URL**.

> Don't run "Install triggers" yet — do it after Step 5, once the Render URL exists.

### Step 4 — Deploy the dashboard on Render
1. Push this repo to GitHub (private is fine).
2. [render.com](https://render.com) → New → Web Service → connect the repo.
   `render.yaml` is picked up automatically.
3. Set environment variables:
   - `TRACKER_SHEET_ID` = `1iVYMDAIafpNMKieIJbLCiRplxeBokOGHe_knWQBhTJY`
   - `APPS_SCRIPT_URL` = the /exec URL from Step 3
   - `TELEGRAM_BOT_TOKEN` = the bot token from Step 2
   - `DASHBOARD_PASSWORD` = a login password
   - `TICK_PASSWORD` = **must match** `PASSWORD` in `google_apps_script.js`
4. Deploy → note the URL, e.g. `https://lupin-tracker.onrender.com`.

### Step 5 — Connect the two
1. In `google_apps_script.js` set `DASHBOARD_URL` to the Render URL, **Save**, redeploy.
2. Sheet menu → **⚙️ Install triggers** (onEdit + onChange + weekly digest).
   Re-run this whenever you paste an updated script.
3. Point the Telegram webhook at the dashboard:
   `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://lupin-tracker.onrender.com/api/telegram`
4. DM your bot `/start` to register for reminders.

### Verify
- Visit the Render URL, log in. Open `…/api/diag?password=<TICK_PASSWORD>` — it
  should report `probe_ok: true` and `probe_has_backgrounds: true`.

### Adding email recipients
The **Recipients** tab now has an **Email** column alongside Chat ID. A row is
kept if it has *either* a Chat ID (for Telegram) *or* an Email (for SMTP/MailApp),
or both. The same `Notify on edit?` / `Weekly digest?` toggles govern both
channels — so to email someone the per-edit alert, set their email and tick
`Yes` in `Notify on edit?`.

Emails are delivered through Apps Script `MailApp.sendEmail` (it uses *your*
Google account — no SMTP creds, no App Password needed). Daily quota: 100
recipients/day on consumer Gmail, 1500 on Google Workspace — well beyond a
tracker's needs.

If you ever upgrade to a paid Render plan (outbound SMTP unblocked), fill in
`SMTP_USER` + `SMTP_PASSWORD` (Gmail App Password) and the backend will send
directly via SMTP; MailApp only kicks in for addresses SMTP couldn't reach.

---

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in values
python app.py               # http://localhost:5003
```

Without `APPS_SCRIPT_URL` the dashboard runs in value-based-estimate mode
(amber banner) — useful for UI work without Google auth.

---

## How completion is decided

A cell is **done** iff its background is greenish — tolerant of every common
Google Sheets green (pale `#d9ead3`, light `#b6d7a8`, medium `#6aa84f`, pure
`#00ff00`/`#34a853`). White/no-fill and greys are *pending*. The same rule lives
in both `app.py` (`_is_green`) and `google_apps_script.js` (`_isGreen`) so the
dashboard and the sheet always agree.

Clicking a cell on the dashboard calls `/api/tick`, which asks Apps Script to
paint the cell green (stamping today's date if empty) or clear it.

The green-detection rule (`green ≥ 60`, `g − r ≥ 8`, `g − b ≥ 8`, not near-white)
lives in two places that must stay in sync: `lupin/colors.py:is_green` and
`google_apps_script.js:_isGreen`. The threshold is the same in both.

---

## Project layout

The code is split by feature so changes to one area don't affect another.

```
Lupin-Tracker/
├── app.py                       # thin entry: app = create_app()
├── lupin/                       # Flask package
│   ├── __init__.py              # create_app() factory + blueprint wiring
│   ├── config.py                # all env vars
│   ├── colors.py                # green-cell detector (pure functions)
│   ├── sheets.py                # gviz CSV + Apps Script proxy
│   ├── recipients.py            # Recipients tab reader (fuzzy columns)
│   ├── analytics.py             # /api/analytics + analyze()
│   ├── tocbank.py               # /api/toc-bank
│   ├── telegram_client.py       # _tg() + /api/telegram webhook
│   ├── email_client.py          # SMTP send + HTML body formatters
│   ├── notifications.py         # /api/sheet-edit + /api/weekly
│   ├── auth.py                  # /login + /logout + login_required
│   └── core.py                  # /, /healthz, /api/tick, /iframe, /api/diag
├── static/
│   ├── css/dashboard.css        # all styles (themes + components)
│   └── js/
│       ├── util.js              # esc(), query()
│       ├── theme.js             # light/dark toggle
│       ├── analytics.js         # KPI tiles, owner cards, drilldown modal
│       ├── matrix-views.js      # month/therapy/non-therapy + cell toggle + blinker
│       ├── tocbank.js           # TOC Bank view
│       └── app.js               # refresh orchestrator + tabs + search
├── templates/
│   ├── index.html               # dashboard markup (no inline CSS/JS)
│   └── login.html               # password gate
└── google_apps_script.js        # single paste file (matches Apps Script editor)
```

**Why each thing lives where it does:**
- Each backend module is a Flask Blueprint registered in `create_app()`. Want to
  add a new endpoint? Create a new module, expose a Blueprint, register it. Want
  to change Telegram behaviour? Only `telegram_client.py` and `notifications.py`
  are involved — analytics, TOC bank, login, sheets are untouched.
- The JS files are loaded in dependency order in `index.html` (util → theme →
  analytics → matrix-views → tocbank → app). Each one only touches the DOM nodes
  it owns; you can rewrite `tocbank.js` without breaking the month-wise view.
- Jinja-templated values reach JS via a tiny `window.LUPIN_BOOT` block in the
  HTML — the static `.js` files stay pure JavaScript (Flask serves them as-is,
  no Jinja parsing) so they're cacheable and lintable.
- `google_apps_script.js` stays a single file by design: Google's Apps Script
  editor expects one paste per project. Splitting it would mean more pasting
  for you on every update, with no benefit.
