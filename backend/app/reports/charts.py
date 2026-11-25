"""Daily traffic charts for the dossier (SVG) and the PDF (ReportLab).

One shared, pure geometry function so both renderings show exactly the same
picture: visitors as light bars, signups as accent bars on top, with the
date range labelled at the edges. Long tests are bucketed per week so the
chart stays readable.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors


def _bucket(series: list[dict[str, Any]], max_points: int = 31) -> list[tuple[str, int, int]]:
    """(label, visitors, signups) per day — or per week when the test ran long."""
    rows = [(str(p.get("date", "")), int(p.get("visitors", 0)), int(p.get("signups", 0))) for p in series]
    if len(rows) <= max_points:
        return rows
    weeks: dict[str, list[int]] = {}
    for date, visitors, signups in rows:
        try:
            day = _dt.date.fromisoformat(date)
        except ValueError:
            continue
        key = day.strftime("%G-W%V")  # ISO week: stable, sortable
        weeks.setdefault(key, [day.isoformat(), 0, 0])
        weeks[key][1] += visitors
        weeks[key][2] += signups
    return [(v[0], v[1], v[2]) for v in weeks.values()]


def trend_geometry(
    series: list[dict[str, Any]],
    *,
    width: float,
    height: float,
    pad_l: float = 6,
    pad_r: float = 6,
    pad_t: float = 14,
    pad_b: float = 16,
    gap: float = 2.5,
) -> dict[str, Any]:
    """Pure layout for the visitors/signups bar chart. No drawing, no I/O."""
    rows = _bucket(series)
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    bars: list[dict[str, float]] = []
    labels: list[tuple[float, str]] = []
    if rows:
        peak = max((max(v, s) for _d, v, s in rows), default=0) or 1
        step = inner_w / len(rows)
        # Cap the bar width so a single-day test renders as one honest bar
        # pair instead of two full-width bands.
        bar_w = min(max(2.0, step - gap), max(4.0, width * 0.04))
        for i, (date, visitors, signups) in enumerate(rows):
            x = pad_l + i * step + (step - bar_w) / 2
            bars.append({
                "x": x, "w": bar_w,
                "vh": max(1.0 if visitors else 0.0, inner_h * visitors / peak),
                "sh": max(1.5 if signups else 0.0, inner_h * signups / peak),
            })
            try:
                label = _dt.date.fromisoformat(date).strftime("%d %b")
            except ValueError:
                label = date[:10]
            # Never stack labels on top of each other (sparse, left to right).
            if not labels or (x + bar_w / 2) - labels[-1][0] >= width / 8:
                labels.append((x + bar_w / 2, label))
    return {"rows": rows, "bars": bars, "labels": labels, "inner_h": inner_h, "peak": max(
        (max(v, s) for _d, v, s in rows), default=0), "width": width, "height": height, "pad_b": pad_b}


def trend_svg(series: list[dict[str, Any]], *, width: int = 680, height: int = 150) -> str:
    """Server-rendered SVG for the dossier: no JS, CSP-safe, self-contained."""
    g = trend_geometry(series, width=width, height=height)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Daily visitors and signups since the test was locked" xmlns="http://www.w3.org/2000/svg">',
        f'<line x1="6" y1="{height - 16}" x2="{width - 6}" y2="{height - 16}" stroke="#D3DAE1" stroke-width="1"/>',
    ]
    base_y = height - 16
    for bar in g["bars"]:
        parts.append(f'<rect x="{bar["x"]:.1f}" y="{base_y - bar["vh"]:.1f}" width="{bar["w"]:.1f}" '
                     f'height="{bar["vh"]:.1f}" fill="#C9D6E4" rx="2"/>')
    for bar in g["bars"]:
        if bar["sh"] > 0:
            parts.append(f'<rect x="{bar["x"]:.1f}" y="{base_y - bar["sh"]:.1f}" width="{bar["w"]:.1f}" '
                         f'height="{bar["sh"]:.1f}" fill="#345B91" rx="2"/>')
    for x, label in g["labels"]:
        parts.append(f'<text x="{x:.1f}" y="{height - 3}" font-size="11" text-anchor="middle" fill="#5E6B78">{label}</text>')
    if not g["rows"]:
        parts.append(f'<text x="{width / 2}" y="{height / 2}" font-size="13" text-anchor="middle" fill="#5E6B78">'
                     f'No traffic yet. Share the page link to start collecting.</text>')
    parts.append("</svg>")
    return "".join(parts)


def trend_drawing(series: list[dict[str, Any]], width: float, height: float = 96) -> Drawing:
    """The same chart as a ReportLab Drawing for the PDF brief."""
    g = trend_geometry(series, width=width, height=height, pad_b=18)
    d = Drawing(width, height)
    base_y = height - 18
    for bar in g["bars"]:
        if bar["vh"] > 0:
            d.add(Rect(bar["x"], base_y - bar["vh"], bar["w"], bar["vh"],
                       fillColor=colors.HexColor("#C9D6E4"), strokeColor=None))
    for bar in g["bars"]:
        if bar["sh"] > 0:
            d.add(Rect(bar["x"], base_y - bar["sh"], bar["w"], bar["sh"],
                       fillColor=colors.HexColor("#345B91"), strokeColor=None))
    for x, label in g["labels"]:
        d.add(String(x, 2, label, fontName="Roboto", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#5E6B78")))
    return d
