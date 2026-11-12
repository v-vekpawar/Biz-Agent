"""
Decision brief PDF (ReportLab, pure Python: no GTK, no browser, no temp files).

Layout: page 1 is the decision (verdict, top 3 risks, next step); page 2 is the
customer test with the threshold ruler; the appendix lists every source and the
method. Bytes are built in memory and returned; nothing is written to disk.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from xml.sax.saxutils import escape

from ..services.stats import pct

FONT_DIR = Path(__file__).parent / "fonts"
_registered = False

INK = colors.HexColor("#14202B")
MUTED = colors.HexColor("#5E6B78")
LINE = colors.HexColor("#D9DFE5")
WASH = colors.HexColor("#F3F5F7")
ACCENT = colors.HexColor("#1D3FBB")

TONE = {  # verdict key -> (foreground, background)
    "go": (colors.HexColor("#0F7B5F"), colors.HexColor("#E3F4EE")),
    "pivot": (colors.HexColor("#9A5B00"), colors.HexColor("#FBF0DC")),
    "stop": (colors.HexColor("#B3261E"), colors.HexColor("#FBE6E4")),
    "keep_running": (colors.HexColor("#3E4F6B"), colors.HexColor("#E8ECF3")),
    "inconclusive": (colors.HexColor("#3E4F6B"), colors.HexColor("#E8ECF3")),
    "untested": (colors.HexColor("#3E4F6B"), colors.HexColor("#E8ECF3")),
    "none": (colors.HexColor("#3E4F6B"), colors.HexColor("#E8ECF3")),
}
LEVEL = {  # risk level -> (label, colour)
    "critical": ("Critical", colors.HexColor("#B3261E")),
    "open": ("Open", colors.HexColor("#9A5B00")),
    "thin": ("Thin support", colors.HexColor("#9A5B00")),
    "partial": ("Partly supported", colors.HexColor("#3E4F6B")),
    "low": ("Lower risk", colors.HexColor("#0F7B5F")),
}


def _fonts() -> None:
    global _registered
    if _registered:
        return
    for name, file in (("Roboto", "Roboto-Regular.ttf"), ("Roboto-Medium", "Roboto-Medium.ttf"),
                       ("Roboto-Bold", "Roboto-Bold.ttf"), ("Roboto-Italic", "Roboto-Italic.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily("Roboto", normal="Roboto", bold="Roboto-Bold", italic="Roboto-Italic", boldItalic="Roboto-Bold")
    _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Roboto", textColor=INK, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", fontSize=22, leading=26, fontName="Roboto-Bold", textColor=INK, spaceAfter=3),
        "meta": ParagraphStyle("meta", fontSize=9, leading=12, textColor=MUTED, fontName="Roboto"),
        "h2": ParagraphStyle("h2", fontSize=12.5, leading=16, fontName="Roboto-Bold", textColor=INK, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body", fontSize=9.6, leading=13.6, **base),
        "small": ParagraphStyle("small", fontSize=8.2, leading=11, fontName="Roboto", textColor=MUTED),
        "cell": ParagraphStyle("cell", fontSize=8.6, leading=11, **base),
        "cellb": ParagraphStyle("cellb", fontSize=9.4, leading=12.6, fontName="Roboto-Medium", textColor=INK),
        "verdict": ParagraphStyle("verdict", fontSize=19, leading=22, fontName="Roboto-Bold"),
        "mono": ParagraphStyle("mono", fontSize=7.2, leading=9.5, fontName="Roboto", textColor=MUTED),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def _ruler(m: dict[str, Any], width: float = 170 * mm) -> Drawing:
    f, s = m["failure_rate"], m["success_rate"]
    lo, hi, rate = m["lower"], m["upper"], m["rate"]
    top = min(1.0, round(max(s * 1.7, hi if m["trials"] else 0, 0.1) + 0.04, 2))
    h = 40
    d = Drawing(width, h)

    def x(v: float) -> float:
        return 4 + (min(max(v, 0), top) / top) * (width - 8)

    y, bar = 12, 14
    d.add(Rect(x(0), y, x(f) - x(0), bar, fillColor=colors.HexColor("#F4D7D4"), strokeColor=None))
    d.add(Rect(x(f), y, x(s) - x(f), bar, fillColor=colors.HexColor("#F6E5C4"), strokeColor=None))
    d.add(Rect(x(s), y, x(top) - x(s), bar, fillColor=colors.HexColor("#CDEBDF"), strokeColor=None))
    d.add(Line(x(f), y - 3, x(f), y + bar + 3, strokeColor=colors.HexColor("#7A3B36"), strokeWidth=1))
    d.add(Line(x(s), y - 3, x(s), y + bar + 3, strokeColor=colors.HexColor("#0F5F49"), strokeWidth=1))
    d.add(String(x(f), y + bar + 6, f"floor {pct(f)}", fontName="Roboto", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#7A3B36")))
    d.add(String(x(s), y + bar + 6, f"target {pct(s)}", fontName="Roboto", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#0F5F49")))
    if m["trials"] > 0:
        cy = y + bar / 2
        d.add(Line(x(lo), cy, x(hi), cy, strokeColor=INK, strokeWidth=2))
        d.add(Line(x(lo), cy - 4, x(lo), cy + 4, strokeColor=INK, strokeWidth=2))
        d.add(Line(x(hi), cy - 4, x(hi), cy + 4, strokeColor=INK, strokeWidth=2))
        d.add(Circle(x(rate), cy, 3.4, fillColor=INK, strokeColor=colors.white, strokeWidth=1))
        d.add(String(x(lo), y - 9, pct(lo), fontName="Roboto", fontSize=7, textAnchor="middle", fillColor=INK))
        d.add(String(x(hi), y - 9, pct(hi), fontName="Roboto", fontSize=7, textAnchor="middle", fillColor=INK))
    else:
        d.add(String(width / 2, y + 4, "no data yet", fontName="Roboto", fontSize=8, textAnchor="middle", fillColor=MUTED))
    return d


def _chrome(canvas, doc, title: str) -> None:
    canvas.saveState()
    w, h = A4
    canvas.setFont("Roboto", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, h - 11 * mm, "Biz-Agent  |  Decision brief")
    canvas.drawRightString(w - 18 * mm, h - 11 * mm, title[:70])
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, h - 13 * mm, w - 18 * mm, h - 13 * mm)
    canvas.drawRightString(w - 18 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def render_brief_pdf(data: dict[str, Any]) -> bytes:
    _fonts()
    st = _styles()
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=19 * mm,
                          bottomMargin=16 * mm, title=f"Decision brief: {data['title']}", author="Biz-Agent")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=lambda c, d: _chrome(c, d, data["title"]))])
    W = doc.width
    story: list[Any] = []

    # ---- page 1: the decision -------------------------------------------
    story.append(_p(data["title"], st["title"]))
    story.append(_p(f"Prepared for {data['owner']}  |  {data['generated_at'].strftime('%d %b %Y')}", st["meta"]))
    story.append(Spacer(1, 8))
    facts = [(k, v) for k, v in data["facts"] if v]
    story.append(_p(data["idea"][:700] + ("..." if len(data["idea"]) > 700 else ""), st["body"]))
    if facts:
        story.append(Spacer(1, 4))
        story.append(Paragraph("  |  ".join(f"<font color='#5E6B78'>{escape(k)}</font> {escape(str(v)[:90])}" for k, v in facts), st["small"]))
    story.append(Spacer(1, 12))

    v = data["verdict"]
    fg, bg = TONE.get(v["key"], TONE["none"])
    vstyle = ParagraphStyle("v", parent=st["verdict"], textColor=fg)
    panel = Table(
        [[[_p(v["label"], vstyle), Spacer(1, 3), _p(v["basis"], st["small"]), Spacer(1, 5), _p(v["detail"], st["body"])]]],
        colWidths=[W],
    )
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 4, fg),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    story.append(panel)

    risks = data["risks"]
    if risks:
        story.append(_p("What is most likely to sink this idea", st["h2"]))
        rows = []
        for r in risks[:3]:
            label, colour = LEVEL[r["level"]]
            ev = r["evidence"]
            left = Paragraph(f"<font color='{colour.hexval().replace('0x', '#')}'><b>{escape(label)}</b></font>", st["cell"])
            right = [
                _p(r["statement"], st["cellb"]),
                Spacer(1, 2),
                _p(r["headline"], st["cell"]),
                _p(f"Sources: {ev['supports']} for, {ev['contradicts']} against, {ev['verified']} verified", st["small"]),
            ]
            rows.append([left, right])
        t = Table(rows, colWidths=[28 * mm, W - 28 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(t)
    else:
        story.append(_p("No assumptions have been analysed yet.", st["body"]))

    # ---- page 2: the customer test ----------------------------------------
    story.append(PageBreak())
    sp = data["sprint"]
    story.append(_p("The customer test", st["h2"]))
    if sp is None:
        story.append(_p("No customer test has been run for this idea yet. Desk research can rank the risks, but only real "
                        "people responding to a real page, or agreeing to a real commitment, can show demand.", st["body"]))
    else:
        ev = sp["evaluation"]
        info = Table([
            [_p("Claim", st["small"]), _p(sp["claim"], st["cell"])],
            [_p("Audience", st["small"]), _p(sp["audience"], st["cell"])],
            [_p("Locked", st["small"]), _p(f"{sp['locked_at'].strftime('%d %b %Y, %H:%M UTC')}, before any data was collected", st["cell"])],
            [_p("Deadline", st["small"]), _p(f"{sp['deadline']} (end of day UTC)", st["cell"])],
            [_p("Fingerprint", st["small"]), _p(sp["protocol_hash"] or "", st["mono"])],
        ], colWidths=[24 * mm, W - 24 * mm])
        info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(info)
        for m in ev["metrics"]:
            role = "decides the verdict" if m["role"] == "primary" else "supporting"
            block = [
                Spacer(1, 8),
                _p(f"{m['label']} ({role})", st["cellb"]),
                _p(f"{m['successes']} of {m['trials']} {m['trial_unit']}  |  observed {pct(m['rate'])}  |  "
                   f"range {pct(m['lower'])} to {pct(m['upper'])} at {int(m['confidence'] * 100)}% confidence", st["cell"]),
                Spacer(1, 4),
                _ruler(m, W),
                _p(m["reason"], st["small"]),
            ]
            story.append(KeepTogether(block))
        c = ev["counts"]
        story.append(Spacer(1, 8))
        story.append(_p(f"Signups: {c['signups']} counted, {c['signups_excluded']} excluded. Conversations logged: "
                        f"{c['interviews']} ({c['committed']} committed, {c['interested']} interested, {c['declined']} declined).", st["small"]))
        for note in ev["notes"]:
            story.append(Spacer(1, 3))
            story.append(_p(note, st["small"]))

    rest = risks[3:]
    if rest:
        story.append(_p("Other assumptions", st["h2"]))
        rows = [[_p(LEVEL[r["level"]][0], st["cell"]), _p(r["statement"], st["cell"])] for r in rest[:10]]
        t = Table(rows, colWidths=[28 * mm, W - 28 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)

    # ---- appendix ---------------------------------------------------------
    story.append(PageBreak())
    story.append(_p("Sources", st["h2"]))
    ev_rows = data["evidence"]
    if not ev_rows:
        story.append(_p("No sources were collected.", st["body"]))
    else:
        head = [_p("#", st["small"]), _p("Source", st["small"]), _p("Type", st["small"]), _p("Checked", st["small"])]
        rows = [head]
        for r in ev_rows[:60]:
            label = r["title"][:90] + (f"  ({r['domain']})" if r["domain"] else "")
            cell = Paragraph(
                f'<link href="{escape(r["url"], {chr(34): "&quot;"})}" color="#1D3FBB">{escape(label)}</link>' if r["url"] else escape(label),
                st["cell"],
            )
            rows.append([_p(r["id"], st["cell"]), cell, _p(r["kind"].replace("_", " "), st["cell"]),
                         _p("verified" if r["verification"] == "verified" else "not verified", st["cell"])])
        t = Table(rows, colWidths=[9 * mm, W - 9 * mm - 28 * mm - 24 * mm, 28 * mm, 24 * mm], repeatRows=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                               ("BACKGROUND", (0, 0), (-1, 0), WASH), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)
        if len(ev_rows) > 60:
            story.append(_p(f"{len(ev_rows) - 60} more sources are available in the app.", st["small"]))

    story.append(_p("Method and limits", st["h2"]))
    for line in (
        "Risks come from an AI-assisted extraction of the assumptions behind the idea, desk research for and against each one, "
        "a check that each source supports what was claimed, and a fixed ranking rule. The ranking and every count are computed by code.",
        "Desk research can find reasons an idea may fail. It cannot show that people will sign up or pay. That evidence comes only from the customer test.",
        "The customer verdict uses a Wilson score interval and thresholds locked before data collection. Waitlist signups show interest, not willingness to pay.",
    ):
        story.append(_p(line, st["body"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()
