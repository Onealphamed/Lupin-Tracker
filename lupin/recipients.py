"""Recipients tab reader.

A row makes the cut if it has EITHER a Chat ID (for Telegram) OR an Email
(for SMTP/MailApp). Column matching is fuzzy — survives hand-made tabs
and header typos.

`opted_in` defaults BLANK to True: in production we discovered that a
strict "must be Yes" rule silently dropped people who registered via
/start and left the cell empty. Only an explicit No/false/0/x suppresses.
"""
from __future__ import annotations

from .sheets import gviz_csv, rows_as_dicts
from . import config


def list_recipients() -> list[dict[str, str]]:
    rows = rows_as_dicts(gviz_csv(config.TAB_RECIPIENTS))
    out: list[dict[str, str]] = []
    for r in rows:
        def col(*keywords: str) -> str:
            for k, v in r.items():
                kl = k.strip().lower()
                if any(kw in kl for kw in keywords):
                    return (v or "").strip()
            return ""

        chat_id = col("chat")
        email = col("email", "mail")
        if not chat_id and not email:
            continue

        def opted_in(v: str) -> bool:
            return v.strip().lower() not in ("no", "n", "false", "0", "✘", "✗", "x")

        out.append({
            "name": col("name") or "Unnamed",
            "role": col("role"),
            "chat_id": chat_id,
            "email": email,
            "notify_on_edit": opted_in(col("notify", "on edit")),
            "weekly_digest": opted_in(col("weekly", "digest")),
        })
    return out
