"""Google Sheet I/O.

Two read paths:

  1. Public gviz CSV  — fast, anonymous, but value-only (no colours, no
     access to private sheets).
  2. Apps Script Web App `read_grid` action — works for private sheets
     AND returns cell backgrounds, which is what makes green-cell
     completion detection possible.

`_apps_script_post` knows the Apps Script Web App's 302-redirect quirk
(the original /exec POST returns 302, the redirected GET delivers the
JSON body). The 5-hop redirect cap is a guard against the (very rare)
case where the redirect chain loops.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any
from urllib.parse import urlencode

import requests

from . import config


def apps_script_post(payload: dict, max_redirects: int = 5) -> tuple[int, str]:
    """POST to the Apps Script Web App; follow 302 with GET to get the body."""
    if not config.APPS_SCRIPT_URL:
        return (-1, "APPS_SCRIPT_URL not configured")
    url, method, last = config.APPS_SCRIPT_URL, "POST", None
    try:
        for _ in range(max_redirects):
            if method == "POST":
                r = requests.post(url, json=payload, timeout=20, allow_redirects=False)
            else:
                r = requests.get(url, timeout=20, allow_redirects=False)
            last = r
            if r.status_code in (301, 302, 303):
                loc = r.headers.get("Location") or ""
                if not loc:
                    break
                url, method = loc, "GET"
                continue
            if r.status_code in (307, 308):
                loc = r.headers.get("Location") or ""
                if not loc:
                    break
                url = loc
                continue
            return (r.status_code, r.text)
        return (
            last.status_code if last is not None else -1,
            last.text if last is not None else "no response",
        )
    except Exception as e:
        return (-1, f"exception: {e}")


def read_grid() -> dict[str, Any]:
    """Return {headers, rows, backgrounds, color_source} for the data tab.

    Primary path: Apps Script (values + backgrounds; color_source=True).
    Fallback: gviz CSV (values only; color_source=False, dashboard shows
    the amber estimate banner).
    """
    if config.APPS_SCRIPT_URL:
        status, text = apps_script_post({
            "password": config.TICK_PASSWORD,
            "action": "read_grid",
            "tab": config.TAB_DATA,
        })
        if status == 200:
            try:
                data = json.loads(text)
                if data.get("ok") and data.get("headers"):
                    return {
                        "headers": [str(h) for h in data["headers"]],
                        "rows": [[("" if v is None else str(v)) for v in r]
                                 for r in data.get("rows", [])],
                        "backgrounds": data.get("backgrounds", []),
                        "color_source": True,
                    }
            except Exception:
                pass

    if config.SHEET_ID:
        qs = urlencode({"tqx": "out:csv", "sheet": config.TAB_DATA})
        url = f"https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/gviz/tq?{qs}"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                rows = list(csv.reader(io.StringIO(r.content.decode("utf-8", "replace"))))
                if rows:
                    return {
                        "headers": [str(h) for h in rows[0]],
                        "rows": [[str(c) for c in row] for row in rows[1:]],
                        "backgrounds": [],
                        "color_source": False,
                    }
        except Exception:
            pass

    return {"headers": [], "rows": [], "backgrounds": [], "color_source": False}


def gviz_csv(tab_name: str) -> list[list[str]]:
    """Read an arbitrary tab as a CSV grid. Used for Recipients and TOC
    Bank — both fall back to Apps Script `read_grid` so private sheets
    still work.
    """
    if not config.SHEET_ID:
        return []
    qs = urlencode({"tqx": "out:csv", "sheet": tab_name})
    url = f"https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/gviz/tq?{qs}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return list(csv.reader(io.StringIO(r.content.decode("utf-8", "replace"))))
    except Exception:
        pass
    if config.APPS_SCRIPT_URL:
        status, text = apps_script_post({
            "password": config.TICK_PASSWORD,
            "action": "read_grid",
            "tab": tab_name,
        })
        if status == 200:
            try:
                d = json.loads(text)
                if d.get("ok") and d.get("headers"):
                    return [d["headers"]] + [
                        [("" if v is None else str(v)) for v in r]
                        for r in d.get("rows", [])
                    ]
            except Exception:
                pass
    return []


def rows_as_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    """[headers, row1, row2, ...] → [{header: cell, ...}, ...]."""
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        if not any((c or "").strip() for c in r):
            continue
        out.append({h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(headers)})
    return out
