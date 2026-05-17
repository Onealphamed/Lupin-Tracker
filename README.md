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
- Telegram bot: alerts on every sheet edit + a Monday 9 AM weekly digest

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
1. Telegram → DM `@BotFather` → `/newbot`.
2. Name it `Lupin Tracker`, username e.g. `lupin_tracker_bot`.
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
2. Sheet menu → **⚙️ Install triggers** (onEdit + weekly digest).
3. Point the Telegram webhook at the dashboard:
   `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://lupin-tracker.onrender.com/api/telegram`
4. DM your bot `/start` to register for reminders.

### Verify
- Visit the Render URL, log in. Open `…/api/diag?password=<TICK_PASSWORD>` — it
  should report `probe_ok: true` and `probe_has_backgrounds: true`.

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
