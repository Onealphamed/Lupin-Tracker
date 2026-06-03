"""TOC Bank reader: /api/toc-bank.

Sheet schema:

    Therapies | Sr. No | Article header | Header of communication | Link | Bucket

The Therapies column forward-fills (only the first row of each therapy
block carries the label). Header names are matched fuzzily so the user
can rename "Sr. No" → "S.No" or "Bucket" → "Category" without breaking
this view.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify

from . import config
from .auth import login_required
from .sheets import gviz_csv

tocbank_bp = Blueprint("tocbank", __name__)


@tocbank_bp.route("/api/toc-bank")
@login_required
def toc_bank():
    raw = gviz_csv(config.TAB_TOC)
    if not raw or len(raw) < 2:
        return jsonify({
            "therapies": [], "total": 0,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        })

    headers = [h.strip() for h in raw[0]]

    def col_idx(*keywords: str) -> int:
        for i, h in enumerate(headers):
            hl = h.lower()
            if any(k in hl for k in keywords):
                return i
        return -1

    c_therapy = col_idx("therap")
    c_sr = col_idx("sr.", "sr no", "s.no", "s no", "serial")
    c_article = col_idx("article")
    c_comm = col_idx("communication", "header of comm")
    c_link = col_idx("link", "url")
    c_bucket = col_idx("bucket", "category", "type")

    therapies_order: list[str] = []
    by_therapy: dict[str, list[dict]] = {}
    current_therapy = ""

    for row in raw[1:]:
        def g(i: int) -> str:
            return (row[i].strip() if 0 <= i < len(row) else "")

        t = g(c_therapy)
        if t:
            current_therapy = t
        article = g(c_article)
        if not article and not g(c_link):
            continue
        key = current_therapy or "(unspecified)"
        if key not in by_therapy:
            by_therapy[key] = []
            therapies_order.append(key)
        by_therapy[key].append({
            "sr_no": g(c_sr),
            "header": article,
            "comm_header": g(c_comm),
            "link": g(c_link),
            "bucket": g(c_bucket),
        })

    total = sum(len(v) for v in by_therapy.values())
    return jsonify({
        "therapies": [
            {"therapy": t, "count": len(by_therapy[t]), "items": by_therapy[t]}
            for t in therapies_order
        ],
        "total": total,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    })
