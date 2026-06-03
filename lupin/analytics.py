"""Analytics: read the data tab, compute per-month / per-therapy roll-ups,
serve /api/analytics.

Layout of the data tab the analyzer expects:

    Months | (blank) | Therapies | TOC Shared | TOC Approved | Design Plan | CRD Upload | Comments

Header names are matched fuzzily — "Months" → any column containing
"month", "Therapies" → "therap", "Comments" → "comment"/"remark"/"note".
Stage columns are every non-empty header between Therapies and Comments.

Month forward-fills (the sheet writes it once at the top of each block).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify

from .auth import login_required
from .colors import is_green
from .sheets import read_grid

analytics_bp = Blueprint("analytics", __name__)

FALLBACK_STAGES = ["TOC Shared", "TOC Approved", "Design Plan", "CRD Upload"]


def _is_month_header(h: str) -> bool:
    return "month" in h.lower()


def _is_therapy_header(h: str) -> bool:
    return "therap" in h.lower()


def _is_comment_header(h: str) -> bool:
    return any(kw in h.lower() for kw in ("comment", "remark", "note"))


def analyze() -> dict[str, Any]:
    grid = read_grid()
    headers = grid["headers"]
    rows = grid["rows"]
    bgs = grid["backgrounds"]
    color_source = grid["color_source"]

    month_col = therapy_col = comment_col = None
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if month_col is None and _is_month_header(hs):
            month_col = i
        elif therapy_col is None and _is_therapy_header(hs):
            therapy_col = i
        elif _is_comment_header(hs):
            comment_col = i

    stage_cols: list[int] = []
    stage_names: list[str] = []
    if therapy_col is not None:
        end = comment_col if comment_col is not None else len(headers)
        for i in range(therapy_col + 1, end):
            name = (headers[i] or "").strip()
            if name:
                stage_cols.append(i)
                stage_names.append(name)
    if not stage_names:
        stage_names = FALLBACK_STAGES

    def cell_done(row_idx: int, col_idx: int, value: str) -> bool:
        if color_source and row_idx < len(bgs) and col_idx < len(bgs[row_idx]):
            return is_green(bgs[row_idx][col_idx])
        # No colour data → fall back to "has any value" estimate
        return bool((value or "").strip())

    months_order: list[str] = []
    therapies_order: list[str] = []
    grid_rows: list[dict[str, Any]] = []
    current_month = ""

    for ri, raw in enumerate(rows):
        def g(idx):
            return (raw[idx].strip() if idx is not None and idx < len(raw) else "")

        m = g(month_col)
        if m:
            current_month = m
        therapy = g(therapy_col)
        if not therapy and not any(g(c) for c in stage_cols):
            continue
        if not therapy:
            continue
        if current_month and current_month not in months_order:
            months_order.append(current_month)
        if therapy not in therapies_order:
            therapies_order.append(therapy)

        stages = []
        for sidx, col in enumerate(stage_cols):
            val = g(col)
            done = cell_done(ri, col, val)
            stages.append({
                "name": stage_names[sidx],
                "value": val,
                "done": done,
                "_col": col + 1,  # 1-based sheet column for the tick proxy
            })
        grid_rows.append({
            "month": current_month,
            "therapy": therapy,
            "stages": stages,
            "comment": g(comment_col),
            "done_count": sum(1 for s in stages if s["done"]),
            "total": len(stages),
            "_row": ri + 1,  # 1-based data-row index (sheet row = _row + 1)
        })

    # Aggregates per month and per therapy.
    def _blank_stage_tally():
        return {n: {"done": 0, "total": 0} for n in stage_names}

    months: dict[str, dict[str, Any]] = {}
    therapies: dict[str, dict[str, Any]] = {}
    total_cells = done_cells = 0
    per_stage = {n: {"done": 0, "total": 0} for n in stage_names}

    for gr in grid_rows:
        mth = gr["month"] or "(no month)"
        thp = gr["therapy"]
        mb = months.setdefault(mth, {
            "month": mth, "done": 0, "total": 0,
            "stages": _blank_stage_tally(), "therapies": {},
        })
        tb = therapies.setdefault(thp, {
            "therapy": thp, "done": 0, "total": 0,
            "stages": _blank_stage_tally(), "months": {},
        })
        mt = mb["therapies"].setdefault(thp, {"done": 0, "total": 0, "comment": gr["comment"]})
        tm = tb["months"].setdefault(mth, {"done": 0, "total": 0, "comment": gr["comment"]})

        for s in gr["stages"]:
            total_cells += 1
            mb["total"] += 1
            tb["total"] += 1
            mt["total"] += 1
            tm["total"] += 1
            mb["stages"][s["name"]]["total"] += 1
            tb["stages"][s["name"]]["total"] += 1
            per_stage[s["name"]]["total"] += 1
            if s["done"]:
                done_cells += 1
                mb["done"] += 1
                tb["done"] += 1
                mt["done"] += 1
                tm["done"] += 1
                mb["stages"][s["name"]]["done"] += 1
                tb["stages"][s["name"]]["done"] += 1
                per_stage[s["name"]]["done"] += 1

    def pct(d: int, t: int) -> int:
        return round(100 * d / t) if t else 0

    for mb in months.values():
        mb["pct"] = pct(mb["done"], mb["total"])
    for tb in therapies.values():
        tb["pct"] = pct(tb["done"], tb["total"])

    fully_done_rows = sum(1 for gr in grid_rows if gr["total"] and gr["done_count"] == gr["total"])
    pending_rows = len(grid_rows) - fully_done_rows

    return {
        "kpi": {
            "total_cells": total_cells,
            "done_cells": done_cells,
            "pending_cells": total_cells - done_cells,
            "progress_pct": pct(done_cells, total_cells),
            "total_rows": len(grid_rows),
            "fully_done_rows": fully_done_rows,
            "pending_rows": pending_rows,
            "months": len(months_order),
            "therapies": len(therapies_order),
        },
        "stages": stage_names,
        "per_stage": [
            {"name": n, "done": per_stage[n]["done"], "total": per_stage[n]["total"],
             "pct": pct(per_stage[n]["done"], per_stage[n]["total"])}
            for n in stage_names
        ],
        "months_order": months_order,
        "therapies_order": therapies_order,
        "months": [months[m] for m in months_order if m in months]
                  + [v for k, v in months.items() if k not in months_order],
        "therapies": [therapies[t] for t in therapies_order if t in therapies],
        "grid": grid_rows,
        "color_source": color_source,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


@analytics_bp.route("/api/analytics")
@login_required
def analytics_route():
    return jsonify(analyze())
