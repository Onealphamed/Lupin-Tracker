"""Green-cell detection.

The whole "task done" signal on the dashboard is the cell background
being green-ish, so this is the most-trusted module. Same green rule
lives in `_isGreen()` inside `google_apps_script.js` — keep them in sync
if you ever change the threshold.
"""
from __future__ import annotations


def hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    if not h:
        return None
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def is_green(bg: str) -> bool:
    """True if a cell background reads as 'green' (the done signal).

    Tolerant of every common Google Sheets green: pale (#d9ead3), light
    (#b6d7a8), medium (#93c47d / #6aa84f), and pure (#00ff00 / #34a853).
    Rejects white/no-fill, greys, and non-green hues.
    """
    rgb = hex_to_rgb(bg)
    if rgb is None:
        return False
    r, g, b = rgb
    if r > 235 and g > 235 and b > 235:
        return False  # near-white / no fill
    return g >= 60 and (g - r) >= 8 and (g - b) >= 8
