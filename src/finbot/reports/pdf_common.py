"""PDF building blocks shared by the monthly, yearly and help-guide renderers."""
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", os.path.expanduser("~/.fonts")]


def _register_fonts():
    for d in _FONT_DIRS:
        reg, bold = os.path.join(d, "DejaVuSans.ttf"), os.path.join(d, "DejaVuSans-Bold.ttf")
        if os.path.exists(reg) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("DV", reg))
            pdfmetrics.registerFont(TTFont("DV-B", bold))
            pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")
            return "DV", "DV-B"
    return "Helvetica", "Helvetica-Bold"          # fallback: still works, minus a few symbols


F_REG, F_BOLD = _register_fonts()

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer
from reportlab.graphics.shapes import Drawing, Rect, String, Line


TEAL = colors.HexColor("#0F4C5C")
TEAL_L = colors.HexColor("#E3EEF1")
ORANGE = colors.HexColor("#E36414")
GREEN = colors.HexColor("#2E7D32")
RED = colors.HexColor("#C62828")
AMBER = colors.HexColor("#F2A900")
INK = colors.HexColor("#1B2A30")
GREY = colors.HexColor("#6B7B82")
LINE = colors.HexColor("#D5DEE2")
ZEBRA = colors.HexColor("#F6F9FA")
TRACK = colors.HexColor("#E6EBEE")

W, H = A4
MARGIN = 15 * mm
CW = W - 2 * MARGIN

base = ParagraphStyle("base", fontName=F_REG, fontSize=8.6, leading=12, textColor=INK)
small = ParagraphStyle("small", parent=base, fontSize=7.2, leading=9.5, textColor=GREY)
h1 = ParagraphStyle("h1", parent=base, fontName=F_BOLD, fontSize=15, leading=19, textColor=TEAL, spaceAfter=3, keepWithNext=1)
h2 = ParagraphStyle("h2", parent=base, fontName=F_BOLD, fontSize=10.5, leading=14, textColor=TEAL, spaceBefore=9, spaceAfter=4, keepWithNext=1)
cell = ParagraphStyle("cell", parent=base, fontSize=8, leading=10.2)
cellb = ParagraphStyle("cellb", parent=cell, fontName=F_BOLD)
cellr = ParagraphStyle("cellr", parent=cell, alignment=2)
cellrb = ParagraphStyle("cellrb", parent=cellr, fontName=F_BOLD)
note = ParagraphStyle("note", parent=base, fontSize=8, leading=11, textColor=GREY)


def money(x, dec=2, sign=False):
    s = f"{abs(x):,.{dec}f}"
    if x < 0:
        return "-S$" + s
    return ("+" if sign and x > 0 else "") + "S$" + s


def P(text, style=cell):
    return Paragraph(text, style)


def table(data, widths, header=True, zebra=True, align_right_cols=(), font=8, extra=None, repeat=1):
    t = Table(data, colWidths=widths, repeatRows=repeat if header else 0)
    st = [
        ("FONT", (0, 0), (-1, -1), F_REG, font),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
    ]
    if header:
        st += [
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), F_BOLD, font),
        ]
    if zebra:
        for r in range(1 if header else 0, len(data)):
            if (r % 2) == 0:
                st.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    for c in align_right_cols:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if extra:
        st += extra
    t.setStyle(TableStyle(st))
    return t


def bar(pct, color=TEAL, w=40 * mm, h=3.6 * mm, marker=None):
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=TRACK, strokeColor=None))
    d.add(Rect(0, 0, w * max(0.0, min(pct, 1.0)), h, fillColor=color, strokeColor=None))
    if marker is not None:
        x = w * max(0.0, min(marker, 1.0))
        d.add(Line(x, -1, x, h + 1, strokeColor=INK, strokeWidth=1))
    return d


def kpi_row(items, width=CW):
    """items: list of (label, value, sub, color)"""
    n = len(items)
    cells = []
    for label, value, sub, col in items:
        hexcol = col.hexval()[2:] if hasattr(col, "hexval") else "1B2A30"
        cells.append(
            [
                Paragraph(f'<font size="7" color="#6B7B82">{label}</font>', base),
                Paragraph(f'<font size="14" color="#{hexcol}"><b>{value}</b></font>', ParagraphStyle("kv", parent=base, leading=19)),
                Paragraph(f'<font size="7" color="#6B7B82">{sub}</font>', ParagraphStyle("ks", parent=base, fontSize=7, leading=9)),
            ]
        )
    data = [[c for c in cells]]
    t = Table(data, colWidths=[width / n] * n)
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), TEAL_L),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def title_block(title, subtitle):
    t = Table(
        [[Paragraph(f'<font size="17" color="white"><b>{title}</b></font>', ParagraphStyle("tt", parent=base, leading=22))],
         [Paragraph(f'<font size="8" color="#CFE3E8">{subtitle}</font>', base)]],
        colWidths=[CW],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
                ("LINEBELOW", (0, -1), (-1, -1), 3, ORANGE),
            ]
        )
    )
    return t


def make_footer(label):
    def _footer(canv, doc):
        canv.saveState()
        canv.setFont(F_REG, 7)
        canv.setFillColor(GREY)
        canv.drawString(MARGIN, 9 * mm, f"Finance Bot  |  {label}  |  Sample data for illustration")
        canv.drawRightString(W - MARGIN, 9 * mm, f"Page {doc.page}")
        canv.setStrokeColor(LINE)
        canv.line(MARGIN, 12 * mm, W - MARGIN, 12 * mm)
        canv.restoreState()
    return _footer


# ---------- charts ----------
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Circle

PALETTE = [TEAL, ORANGE, colors.HexColor("#4C9F70"), colors.HexColor("#F2A900"),
           colors.HexColor("#7B6CA8"), colors.HexColor("#5B8DB8"), colors.HexColor("#B5651D"), GREY]


def donut(items, w, h, center=None, fs=7.2, dec=0):
    d = Drawing(w, h)
    r = min(h - 12, w * 0.40) / 2
    cx, cy = r + 6, h / 2
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = cx - r, cy - r, 2 * r, 2 * r
    pie.data = [float(v) for _, v in items]
    pie.labels = [""] * len(items)
    pie.startAngle = 90
    pie.direction = "clockwise"
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    for i in range(len(items)):
        pie.slices[i].fillColor = PALETTE[i % len(PALETTE)]
    d.add(pie)
    d.add(Circle(cx, cy, r * 0.58, fillColor=colors.white, strokeColor=None))
    if center:
        d.add(String(cx, cy + 2, center[0], fontName=F_BOLD, fontSize=8.5, textAnchor="middle", fillColor=INK))
        d.add(String(cx, cy - 8, center[1], fontName=F_REG, fontSize=6.5, textAnchor="middle", fillColor=GREY))
    total = sum(float(v) for _, v in items) or 1.0
    lx = cx + r + 14
    row = 13.0
    y0 = cy + (len(items) * row) / 2 - 9
    for i, (lab, v) in enumerate(items):
        y = y0 - i * row
        d.add(Rect(lx, y, 7, 7, fillColor=PALETTE[i % len(PALETTE)], strokeColor=None))
        d.add(String(lx + 11, y + 0.5, lab, fontName=F_REG, fontSize=fs, fillColor=INK))
        d.add(String(w - 4, y + 0.5, f"{money(v, dec)}  {float(v) / total * 100:.0f}%", fontName=F_REG, fontSize=fs, textAnchor="end", fillColor=GREY))
    return d


def stacked_bars(cats, series, names, cols, w, h, vmax, step, k=True):
    d = Drawing(w, h)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 36, 24, w - 52, h - 44
    bc.data = series
    bc.categoryAxis.categoryNames = cats
    bc.categoryAxis.style = "stacked"
    bc.categoryAxis.labels.fontName = F_REG
    bc.categoryAxis.labels.fontSize = 7
    bc.valueAxis.labels.fontName = F_REG
    bc.valueAxis.labels.fontSize = 6.8
    bc.valueAxis.valueMin, bc.valueAxis.valueMax, bc.valueAxis.valueStep = 0, vmax, step
    bc.valueAxis.labelTextFormat = (lambda v: f"{v/1000:.0f}k") if k else (lambda v: f"{v:,.0f}")
    bc.valueAxis.visibleGrid = 1
    bc.valueAxis.gridStrokeColor = LINE
    for i, c in enumerate(cols):
        bc.bars[i].fillColor = c
    bc.bars.strokeColor = None
    bc.bars.strokeWidth = 0
    bc.groupSpacing = 7
    d.add(bc)
    x = w - 20
    for nme, c in reversed(list(zip(names, cols))):
        tw = len(nme) * 4.2 + 14
        x -= tw
        d.add(Rect(x, h - 12, 8, 8, fillColor=c, strokeColor=None))
        d.add(String(x + 11, h - 11, nme, fontName=F_REG, fontSize=7.2))
    return d


def waterfall(steps, w, h, floor, ceil):
    """steps: list of (label, value, kind) kind in 'total','delta'"""
    d = Drawing(w, h)
    left, right, bot, top = 40, w - 10, 30, h - 22
    n = len(steps)
    slot = (right - left) / n
    bw = slot * 0.6

    def Y(v):
        return bot + (v - floor) / (ceil - floor) * (top - bot)

    d.add(Line(left, bot, right, bot, strokeColor=GREY, strokeWidth=0.6))
    for g in range(int(floor), int(ceil) + 1, 2000):
        d.add(Line(left, Y(g), right, Y(g), strokeColor=LINE, strokeWidth=0.4))
        d.add(String(left - 4, Y(g) - 2.5, f"{g:,.0f}", fontName=F_REG, fontSize=6.3, textAnchor="end", fillColor=GREY))
    run = 0
    for i, (lab, val, kind) in enumerate(steps):
        x = left + i * slot + (slot - bw) / 2
        if kind == "total":
            y0, y1 = floor, val
            run = val
            col = TEAL
            txt = f"{val:,.0f}"
        else:
            y0, y1 = run, run + val
            run += val
            col = GREEN if val >= 0 else RED
            txt = f"{val:+,.0f}"
        lo, hi = min(Y(y0), Y(y1)), max(Y(y0), Y(y1))
        d.add(Rect(x, lo, bw, max(hi - lo, 1), fillColor=col, strokeColor=None))
        d.add(String(x + bw / 2, hi + 3, txt, fontName=F_BOLD, fontSize=7, textAnchor="middle", fillColor=INK))
        parts = lab.split("\n")
        for j, p in enumerate(parts):
            d.add(String(x + bw / 2, bot - 10 - j * 8, p, fontName=F_REG, fontSize=6.8, textAnchor="middle", fillColor=INK))
    return d
