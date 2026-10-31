"""Monthly PDF (PRD 5.5). Section order is fixed; which sections appear and how many rows they have
comes entirely from the dataset (configuration + data), see PRD 9.5."""
from __future__ import annotations

import calendar
import io
from collections import defaultdict
from decimal import Decimal
from typing import BinaryIO

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer, Paragraph, Table, TableStyle, KeepTogether

from ..domain.enums import Bucket
from ..domain.money import ZERO
from .dataset import MonthlyData, pct
from .pdf_common import *  # noqa: F401,F403
from .pdf_common import (CW, F_BOLD, F_REG, GREEN, AMBER, ORANGE, RED, TEAL, TEAL_L, LINE, GREY, MARGIN, P, bar, base, cell, cellb,
                         cellr, colors, donut, h1, h2, kpi_row, make_footer, money, mm, note, stacked_bars, table, title_block,
                         waterfall, ParagraphStyle, PALETTE)

MON = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hidden(d: MonthlyData, name: str) -> bool:
    return name in d.settings.hidden_sections


def _light(p: float):
    return RED if p >= 100 else AMBER if p >= 80 else GREEN


def _bullets(items):
    out = []
    for t in items:
        out += [Paragraph("&bull;&nbsp; " + t, base), Spacer(1, 2)]
    return out


def _chg(a: Decimal, b: Decimal) -> str:
    return f"{float((a - b) / b * 100):+.0f}%" if b else "new"


# ------------------------------------------------------------------ sections
def summary(d: MonthlyData):
    st = []
    kp = []
    if d.nw:
        ch = d.nw.change
        kp.append(("Net worth", money(d.nw.snap.net_worth, 0), (f"{money(ch, 0, sign=True)} vs last snapshot" if d.nw.prev else "first snapshot"), TEAL))
    kp += [("Income", money(d.income), "this month", GREEN), ("Net spend", money(d.net_spend), f"Monthly {money(d.monthly_net,0)} + Yearly {money(d.yearly_net,0)}", ORANGE),
           ("Saved", money(d.saved), f"Savings rate {d.savings_rate:.0f}%", AMBER)]
    st += [title_block(f"{d.title} Monthly Report", f"Generated {d.generated:%a %-d %b %Y}  |  Home currency SGD  |  Net spend basis"), Spacer(1, 7), kpi_row(kp)]
    if d.prev.get("has"):
        pr = d.prev
        psaved = pr["income"] - pr["net"]
        rows = [["", "This month", "Last month", "Change"],
                ["Income", money(d.income), money(pr["income"]), _chg(d.income, pr["income"])],
                ["Net spend", money(d.net_spend), money(pr["net"]), _chg(d.net_spend, pr["net"])],
                ["  Monthly bucket", money(d.monthly_net), money(pr["monthly"]), _chg(d.monthly_net, pr["monthly"])],
                ["  Yearly bucket", money(d.yearly_net), money(pr["yearly"]), _chg(d.yearly_net, pr["yearly"])],
                ["Saved", money(d.saved), money(psaved), _chg(d.saved, psaved)]]
        st += [Paragraph("Compared with last month", h2), table(rows, [55 * mm, 40 * mm, 40 * mm, 35 * mm], align_right_cols=(1, 2, 3))]
    if d.trend6:
        st.append(Paragraph("Six-month income and net spend", h2))
        dr = Drawing(CW, 150)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 38, 24, CW - 55, 105
        bc.data = [[float(i) for _, i, _ in d.trend6], [float(n) for _, _, n in d.trend6]]
        bc.categoryAxis.categoryNames = [l for l, _, _ in d.trend6]
        top = max(max(bc.data[0]), max(bc.data[1]), 1)
        step = max(round(top / 4, -2), 100)
        bc.valueAxis.valueMin, bc.valueAxis.valueMax, bc.valueAxis.valueStep = 0, step * 5, step
        bc.valueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
        for ax in (bc.categoryAxis, bc.valueAxis):
            ax.labels.fontName, ax.labels.fontSize = F_REG, 7
        bc.valueAxis.visibleGrid, bc.valueAxis.gridStrokeColor = 1, LINE
        bc.bars[0].fillColor, bc.bars[1].fillColor = TEAL, ORANGE
        bc.bars.strokeColor = None
        bc.bars.strokeWidth = 0
        bc.groupSpacing = 14
        dr.add(bc)
        for x, c, t in ((CW - 150, TEAL, "Income"), (CW - 90, ORANGE, "Net spend")):
            dr.add(Rect(x, 138, 8, 8, fillColor=c, strokeColor=None))
            dr.add(String(x + 12, 139, t, fontName=F_REG, fontSize=7.5))
        st.append(dr)
    hl = []
    if d.nw:
        hl.append(f"Net worth is {money(d.nw.snap.net_worth, 0)}" + (f", {'up' if d.nw.change >= 0 else 'down'} {money(abs(d.nw.change), 0)}." if d.nw.prev else ".")
                  + (f" Liquid assets cover about {d.nw.runway} months of spending." if d.nw.runway else ""))
    if d.total_limit:
        hl.append(f"Monthly budget: {money(d.monthly_net, 0)} of {money(d.total_limit, 0)} used ({money(d.total_limit - d.monthly_net, 0)} left).")
    if d.yearly_limit:
        hl.append(f"Yearly bucket: {money(d.yearly_ytd, 0)} of {money(d.yearly_limit, 0)} used so far.")
    if d.people_rank and not _hidden(d, "people"):
        t = d.people_rank[0]
        hl.append(f"You spent the most with {t.name} this month ({money(t.spent, 0)} over {t.outings} outings).")
    owed = sum((r["owed"] for r in d.owed_rows), ZERO) + sum((c.outstanding for c in d.claim_rows), ZERO)
    if owed:
        hl.append(f"Money waiting on you: {money(owed)}.")
    if hl:
        st += [Paragraph("Highlights", h2), *_bullets(hl)]
    st += [Spacer(1, 6), Paragraph("Net spend counts the full amount you paid until friends repay or a claim is paid. A repayment then reduces the month the expense was made in, not the month it arrives.", note), PageBreak()]
    return st


def net_worth(d: MonthlyData):
    nw = d.nw
    if nw is None:
        return []
    st = [Paragraph("1. Net worth and assets", h1)]
    kp = [("Net worth", money(nw.snap.net_worth, 0), f"{money(nw.change, 0, sign=True)}" if nw.prev else "first snapshot", TEAL),
          ("Fixed assets", money(nw.snap.fixed, 0), "cash, banks, owed", GREEN), ("Variable assets", money(nw.snap.variable, 0), "market-priced", TEAL)]
    if nw.runway is not None:
        kp.append(("Liquid runway", f"{nw.runway} mo", f"Liquid {money(nw.liquid, 0)}", AMBER))
    if nw.recon is not None and not nw.recon.first:
        kp.append(("Reconciliation", "Balanced" if nw.recon.gap == 0 else "Gap", f"Gap {money(nw.recon.gap)}", GREEN if nw.recon.gap == 0 else RED))
    st.append(kpi_row(kp))
    if nw.asset_types:
        st += [Paragraph(f"Asset types (gross assets {money(nw.gross_assets, 0)})", h2),
               donut(_top_n(nw.asset_types), CW, 138, center=(money(nw.gross_assets, 0), "assets")),
               Paragraph(f"Liabilities shown separately: {money(nw.liabilities)}. Gross assets less liabilities = net worth.", note)]
    inv = [h for h in nw.holdings]
    if inv:
        st.append(Paragraph("Investment holdings", h2))
        stocks = [(r.holding.name, r.value) for r in inv if r.holding.type.value != "crypto"]
        crypto = [(r.holding.name, r.value) for r in inv if r.holding.type.value == "crypto"]
        cells = []
        if stocks:
            cells.append(donut(_top_n(stocks), CW / 2 + 10 if crypto else CW, 122, center=(money(sum((v for _, v in stocks), ZERO), 0), "stocks, ETFs"), fs=6.8))
        if crypto:
            cells.append(donut(_top_n(crypto), CW / 2 - 10 if stocks else CW, 122, center=(money(sum((v for _, v in crypto), ZERO), 0), "crypto"), fs=6.8))
        t = Table([cells], colWidths=[CW / 2 + 10, CW / 2 - 10] if len(cells) == 2 else [CW])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        st.append(t)
        rows = [["Holding", "Type", "Cost", "Value", "Gain / loss", "Return", "Month move"]]
        tc = tv = tm = ZERO
        ex = []
        for i, r in enumerate(inv, start=1):
            h = r.holding
            rows.append([h.name + (" *" if r.stale else ""), h.type.value.upper() if h.type.value == "etf" else h.type.value.title(), money(h.cost_basis, 0), money(r.value, 0),
                         money(r.gain, 0, sign=True), f"{r.return_pct:+.1f}%", money(r.month_move, 0, sign=True)])
            tc += h.cost_basis; tv += r.value; tm += r.month_move
            ex.append(("TEXTCOLOR", (4, i), (5, i), GREEN if r.gain >= 0 else RED))
        rows.append(["Total", "", money(tc, 0), money(tv, 0), money(tv - tc, 0, sign=True), f"{pct(tv - tc, tc):+.1f}%", money(tm, 0, sign=True)])
        n = len(rows)
        ex += [("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 7.6), ("BACKGROUND", (0, n - 1), (-1, n - 1), TEAL_L)]
        st.append(table(rows, [42 * mm, 18 * mm, 24 * mm, 24 * mm, 28 * mm, 20 * mm, 24 * mm], font=7.6, align_right_cols=(2, 3, 4, 5, 6), extra=ex))
        big = max(inv, key=lambda r: r.share_pct)
        flag = f" Largest holding: {big.holding.name} at {big.share_pct:.0f}% of investments" + (" (above the 30% flag)." if big.share_pct > 30 else ".")
        st.append(Paragraph("* price is stale (last known price shown)." + flag if any(r.stale for r in inv) else flag.strip(), note))
    st.append(PageBreak())
    if nw.trend:
        st += [Paragraph("Net worth trend, last 10 months (fixed and variable assets)", h2),
               stacked_bars([l for l, _, _ in nw.trend], [[float(f) for _, f, _ in nw.trend], [float(v) for _, _, v in nw.trend]],
                            ["Fixed assets", "Variable assets"], [TEAL, ORANGE], CW, 150,
                            _nice_max(max(float(f + v) for _, f, v in nw.trend)), _nice_max(max(float(f + v) for _, f, v in nw.trend)) / 5)]
    if nw.bridge:
        br = nw.bridge
        steps = [(f"{nw.prev.date:%-d %b}", float(br.opening), "total"), ("Income", float(br.income), "delta"), ("Net spend", -float(br.net_spend), "delta"),
                 ("Money owed\nto you", float(br.owed_created), "delta"), ("Market\ngains", float(br.market), "delta")]
        if br.adjustments:
            steps.append(("Adjust-\nments", float(br.adjustments), "delta"))
        steps.append((f"{nw.snap.date:%-d %b}", float(br.closing), "total"))
        lo, hi = _wf_bounds(steps)
        st += [Paragraph(f"Net worth bridge: {nw.prev.date:%-d %b} to {nw.snap.date:%-d %b}", h2), waterfall(steps, CW, 150, lo, hi),
               Paragraph(f"Cash basis, so it always adds up. The axis starts at {money(Decimal(lo), 0)} so the changes are visible. Moves into investments are transfers and do not change net worth.", note)]
    rows = [["Account", "Previous", "Now", "Change"]] + [[n, money(p), money(c), money(c - p, sign=True)] for n, p, c in nw.fixed_rows]
    rows.append(["Total fixed assets", money(nw.prev.fixed if nw.prev else ZERO), money(nw.snap.fixed), money(nw.snap.fixed - (nw.prev.fixed if nw.prev else ZERO), sign=True)])
    n = len(rows)
    st += [Paragraph("Fixed assets", h2), table(rows, [70 * mm, 36 * mm, 36 * mm, 38 * mm], align_right_cols=(1, 2, 3), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if nw.recon is not None and not nw.recon.first:
        rows = [["Account", "Expected", "You entered", "Gap"]] + [[r.account.name, money(r.expected), money(r.entered), money(r.gap, sign=True)] for r in nw.recon.rows]
        rows.append(["Total", "", "", money(nw.recon.gap, sign=True)])
        n = len(rows)
        st += [Paragraph("Reconciliation of fixed accounts", h2),
               table(rows, [70 * mm, 36 * mm, 36 * mm, 38 * mm], align_right_cols=(1, 2, 3),
                     extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8), ("BACKGROUND", (0, n - 1), (-1, n - 1), colors.HexColor("#E3F1E6") if nw.recon.gap == 0 else colors.HexColor("#F4B6B6"))])]
    st += [Spacer(1, 4), Paragraph("Reconciliation uses fixed assets only, so market moves never create a gap. Only a gap left after review is written off.", note), PageBreak()]
    return st


def _top_n(items, n=6):
    items = sorted(items, key=lambda kv: -kv[1])
    if len(items) <= n:
        return items
    return items[:n - 1] + [("Other", sum((v for _, v in items[n - 1:]), ZERO))]


def _nice_max(v: float) -> float:
    step = 10 ** max(len(str(int(v))) - 1, 1)
    return (int(v / step) + 1) * step


def _wf_bounds(steps):
    run, pts = 0.0, []
    for _, v, k in steps:
        run = v if k == "total" else run + v
        pts.append(run)
    lo, hi = min(pts), max(pts)
    span = max(hi - lo, 1)
    unit = 1000 if span > 2000 else 100
    return (int(lo / unit) - 1) * unit, (int(hi / unit) + 2) * unit


def budgets(d: MonthlyData):
    st = [Paragraph("2. Budget performance", h1), Paragraph("Monthly bucket (resets on the 1st, no rollover)", h2)]
    rows = [["Category", "Spent", "Limit", "Used", "Left", ""]]
    mon_rows = [r for r in d.cats if r.bucket == Bucket.MONTHLY]
    for r in mon_rows:
        if r.limit:
            rows.append([r.category.name, money(r.net), money(r.limit, 0), f"{r.used_pct:.0f}%", money(r.limit - r.net), bar(r.used_pct / 100, _light(r.used_pct), 38 * mm)])
        else:
            rows.append([f"{r.category.name} (no limit)", money(r.net), "-", "-", "-", ""])
    if d.total_limit:
        p = pct(d.monthly_net, d.total_limit)
        rows.append(["Total Monthly", money(d.monthly_net), money(d.total_limit, 0), f"{p:.0f}%", money(d.total_limit - d.monthly_net), bar(p / 100, _light(p), 38 * mm)])
    else:
        rows.append(["Total Monthly", money(d.monthly_net), "-", "-", "-", ""])
    n = len(rows)
    st.append(table(rows, [34 * mm, 28 * mm, 24 * mm, 16 * mm, 28 * mm, 45 * mm], align_right_cols=(1, 2, 3, 4),
                    extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8), ("BACKGROUND", (0, n - 1), (-1, n - 1), TEAL_L)]))
    if d.cumulative and d.total_limit:
        dr = Drawing(CW, 150)
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 38, 22, CW - 55, 105
        days = len(d.cumulative)
        lp.data = [[(a, float(b)) for a, b in d.cumulative], [(x, float(d.total_limit) * x / days) for x in range(1, days + 1)]]
        lp.lines[0].strokeColor, lp.lines[0].strokeWidth = ORANGE, 1.8
        lp.lines[1].strokeColor, lp.lines[1].strokeWidth, lp.lines[1].strokeDashArray = GREY, 1, [3, 2]
        lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 1, days
        lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = 0, float(d.total_limit) * 1.1
        lp.yValueAxis.valueStep = _nice_max(float(d.total_limit)) / 5
        for ax in (lp.xValueAxis, lp.yValueAxis):
            ax.labels.fontName, ax.labels.fontSize = F_REG, 7
        lp.yValueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
        lp.yValueAxis.visibleGrid, lp.yValueAxis.gridStrokeColor = 1, LINE
        dr.add(lp)
        st += [Paragraph("Cumulative Monthly-bucket spending vs even pace", h2), dr]
    if d.yearly_limit:
        ypct = pct(d.yearly_ytd, d.yearly_limit)
        elapsed = d.yearly_pace[1] if d.yearly_pace else None
        rows = [["Used so far", "Limit", "Left", "Year elapsed", ""],
                [money(d.yearly_ytd), money(d.yearly_limit, 0), money(d.yearly_limit - d.yearly_ytd), f"{elapsed*100:.0f}%" if elapsed is not None else "-",
                 bar(ypct / 100, _light(ypct), 46 * mm, marker=elapsed)]]
        st += [Paragraph(f"Yearly bucket (Jan to Dec {d.year})", h2), table(rows, [30 * mm, 28 * mm, 30 * mm, 28 * mm, 52 * mm], align_right_cols=(0, 1, 2, 3)),
               Paragraph("The black marker shows where an even spread would put you today.", note)]
    if d.yearly_items:
        rows = [["Date", "Yearly-bucket entry this month", "Category", "Net"]]
        from ..core.ledger import NetIndex  # noqa: F401  (net values are precomputed on the dataset)
        for x in d.yearly_items:
            c = d.names["cats"].get(x.category_id)
            rows.append([f"{x.spend_date.day} {calendar.month_abbr[x.spend_date.month]}", x.description, c.name if c else "?", money(x.amount - 0)])
        st += [Spacer(1, 4), table(rows, [20 * mm, 84 * mm, 40 * mm, 36 * mm], align_right_cols=(3,))]
    st.append(PageBreak())
    return st


def calendar_page(d: MonthlyData):
    st = [Paragraph("3. Calendar view (net spend by day)", h1)]
    cal = calendar.Calendar(firstweekday=0).monthdayscalendar(d.year, d.month)
    cw = 22.5 * mm
    hdr = [Paragraph(f'<font color="white"><b>{x}</b></font>', cell) for x in MON] + [Paragraph('<font color="white"><b>Week</b></font>', cellr)]
    data, extra = [hdr], [("BACKGROUND", (0, 0), (-1, 0), TEAL)]

    def shade(v, has):
        if not has:
            return colors.HexColor("#F1F3F4")
        v = float(v)
        return colors.HexColor("#E8F3EC" if v <= 50 else "#CFE6D6" if v <= 100 else "#FBE3B8" if v <= 200 else "#F6B97A" if v <= 400 else "#EE8B4B")

    no_entry = [x for x in range(1, calendar.monthrange(d.year, d.month)[1] + 1) if x not in d.day_totals]
    for wi, week in enumerate(cal, start=1):
        row, wk = [], ZERO
        for ci, day in enumerate(week):
            if day == 0:
                row.append("")
                continue
            v = d.day_totals.get(day, ZERO)
            wk += v
            marks = (" B" if day in d.bill_days else "") + (" L" if day in d.large_days else "")
            row.append(Paragraph(f'<font size="7" color="#6B7B82">{day}</font><font size="6.5" color="#C62828"><b>{marks}</b></font><br/><font size="9"><b>{money(v, 0) if v else "none"}</b></font>',
                                 ParagraphStyle("c", parent=cell, leading=11)))
            extra.append(("BACKGROUND", (ci, wi), (ci, wi), shade(v, day in d.day_totals)))
        row.append(Paragraph(f"<b>{money(wk, 0)}</b>", cellr))
        data.append(row)
    t = Table(data, colWidths=[cw] * 7 + [CW - 7 * cw], rowHeights=[8 * mm] + [17 * mm] * len(cal))
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.white), ("VALIGN", (0, 1), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("BOX", (0, 0), (-1, -1), 0.5, LINE)] + extra))
    st += [t, Spacer(1, 6)]
    leg = ", ".join(f"{day} {name}" for day, name in sorted(d.bill_days.items()))
    st.append(Paragraph(f"<b>B</b> = bill due that day ({leg or 'none'}).  <b>L</b> = a single expense of S$100 or more.  Shading runs from light (small days) to dark (heavy days); grey = no entries.", note))
    heavy = sorted(d.day_totals.items(), key=lambda kv: -kv[1])[:3]
    st += [Paragraph("Summary", h2), *_bullets([
        "Heaviest days: " + (", ".join(f"{k} {calendar.month_abbr[d.month]} ({money(v, 0)})" for k, v in heavy) or "none") + ".",
        f"Days with no entries: {', '.join(map(str, no_entry)) or 'none'}. If these were not zero-spend days, add the missing entries in the monthly review."]), PageBreak()]
    return st


def where_money_went(d: MonthlyData):
    st = [Paragraph("4. Where the money went", h1), Paragraph("By category (net spend)", h2)]
    tot = d.net_spend or Decimal(1)
    rows = [["Category", "Bucket", "Entries", "Net spend", "Share", ""]]
    for r in sorted(d.cats, key=lambda r: -r.net):
        rows.append([r.category.name, r.bucket.value.title(), str(r.entries), money(r.net), f"{pct(r.net, tot):.0f}%", bar(float(r.net / tot), TEAL if r.bucket == Bucket.MONTHLY else ORANGE, 40 * mm)])
    st.append(table(rows, [32 * mm, 22 * mm, 18 * mm, 30 * mm, 18 * mm, 50 * mm], align_right_cols=(2, 3, 4)))
    if d.groups:
        rows = [["Group", "Net spend", "Share", ""]] + [[k, money(v), f"{pct(v, tot):.0f}%", bar(float(v / tot), TEAL, 60 * mm)] for k, v in sorted(d.groups.items(), key=lambda kv: -kv[1])]
        st += [Paragraph("Who you spent with", h2), table(rows, [40 * mm, 35 * mm, 25 * mm, 80 * mm], align_right_cols=(1, 2))]
    if d.people_rank and not _hidden(d, "people"):
        rows = [["#", "Person", "Relationship", "Outings", "Spent with (your share)", "Avg per outing"]]
        for i, r in enumerate(d.people_rank, start=1):
            rows.append([str(i), r.name, r.relationship.title(), str(r.outings), money(r.spent), money(r.average)])
        st += [Spacer(1, 5), table(rows, [10 * mm, 38 * mm, 28 * mm, 20 * mm, 48 * mm, 36 * mm], align_right_cols=(3, 4, 5),
                                   extra=[("FONT", (0, 1), (-1, 1), F_BOLD, 8), ("BACKGROUND", (0, 1), (-1, 1), TEAL_L)]),
               Paragraph("Spent with = your own share of every entry the person is on (not what you paid for others), counted in full for each person present, so person totals overlap and can add up to more than the group totals. Outings are distinct days.", note)]
    if d.accounts_paid:
        tp = sum(d.accounts_paid.values(), ZERO) or Decimal(1)
        rows = [["Account", "Paid", "Share", ""]] + [[k, money(v), f"{pct(v, tp):.0f}%", bar(float(v / tp), TEAL, 60 * mm)] for k, v in sorted(d.accounts_paid.items(), key=lambda kv: -kv[1])]
        rows += [["Total paid", money(tp), "", ""], ["Net spend after repayments and claims", money(d.net_spend), "", ""]]
        n = len(rows)
        st += [Paragraph("By account (amount paid)", h2), table(rows, [60 * mm, 35 * mm, 20 * mm, 55 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, n - 2), (-1, n - 2), F_BOLD, 8), ("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    side = []
    if d.locations:
        side.append(table([["Top locations", "Net spend"]] + [[k, money(v)] for k, v in sorted(d.locations.items(), key=lambda kv: -kv[1])[:6]], [40 * mm, 35 * mm], align_right_cols=(1,)))
    if d.tags:
        side.append(table([["Tag", "Net spend"]] + [[k, money(v)] for k, v in sorted(d.tags.items(), key=lambda kv: -kv[1])], [40 * mm, 35 * mm], align_right_cols=(1,)))
    if side:
        t = Table([side + [""] * (2 - len(side))], colWidths=[CW / 2, CW / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        st += [Spacer(1, 6), t]
    st.append(PageBreak())
    return st


def biggest(d: MonthlyData):
    if not d.top:
        return []
    st = [Paragraph("5. Biggest and unusual expenses", h1), Paragraph("Top 5 single expenses (amount paid)", h2)]
    rows = [["Date", "Expense", "Category", "Paid"]]
    for x in d.top:
        c = d.names["cats"].get(x.category_id)
        rows.append([f"{x.spend_date.day} {calendar.month_abbr[x.spend_date.month]}", x.description, c.name if c else "?", money(x.amount)])
    st.append(table(rows, [20 * mm, 84 * mm, 40 * mm, 36 * mm], align_right_cols=(3,)))
    if d.unusual:
        st += [Paragraph("Worth a look", h2), *_bullets(d.unusual)]
    for t in d.trips_month:
        rows = [["Trip", "Dates", "Spent", "Per day", "Limit used"],
                [t.trip.name, f"{t.trip.start:%-d %b}" + (f" to {t.trip.end:%-d %b}" if t.trip.end else " onwards"), money(t.total), money(t.per_day),
                 f"{t.budget_used_pct:.0f}%" if t.budget_used_pct is not None else "-"]]
        st += [Paragraph("Trip", h2), table(rows, [30 * mm, 46 * mm, 32 * mm, 32 * mm, 30 * mm], align_right_cols=(2, 3, 4)),
               Paragraph("Trip spend counts under the Yearly bucket.", note)]
    st.append(PageBreak())
    return st


def owed(d: MonthlyData):
    st = [Paragraph("6. Money owed to you", h1), Paragraph("Friends (receivables)", h2)]
    if d.owed_rows:
        rows = [["Person", "Expense", "Date", "Owed", "Days open"]] + [[r["person"], r["desc"], f"{r['date']:%-d %b}", money(r["owed"]), str(r["days"])] for r in sorted(d.owed_rows, key=lambda r: r["date"])]
        rows.append(["", "Total outstanding", "", money(sum((r["owed"] for r in d.owed_rows), ZERO)), ""])
        n = len(rows)
        st.append(table(rows, [24 * mm, 70 * mm, 20 * mm, 30 * mm, 26 * mm], align_right_cols=(3, 4), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)]))
    else:
        st.append(Paragraph("Nothing owed to you this month.", base))
    if d.settled_rows:
        rows = [["Date", "Person", "Amount", "Account"]] + [[f"{r['date']:%-d %b}", r["person"], money(r["amount"]), r["account"]] for r in d.settled_rows]
        st += [Paragraph("Settled this month", h2), table(rows, [24 * mm, 40 * mm, 34 * mm, 40 * mm], align_right_cols=(2,))]
    st.append(Paragraph("Claims (reimbursements)", h2))
    if d.claim_rows:
        rows = [["Claimant", "Amount", "Submitted", "Status"]] + [[c.claimant, money(c.outstanding), f"{c.submitted:%-d %b}" if c.submitted else "-", c.status.value.title()] for c in d.claim_rows]
        st.append(table(rows, [40 * mm, 34 * mm, 36 * mm, 40 * mm], align_right_cols=(1,)))
    else:
        st.append(Paragraph("No claims outstanding.", base))
    st += [Spacer(1, 6), Paragraph("Both lists count as money you are owed in your net worth. When a friend repays or a claim is paid, the amount reduces the month of the original expense.", note), PageBreak()]
    return st


def obligations(d: MonthlyData):
    st, any_ = [Paragraph("7. Cards, insurance, subscriptions and fees", h1)], False
    if d.card_rows and not _hidden(d, "cards"):
        any_ = True
        rows = [["Card", "Cycle spend", "Statement / due", "Owed", "Utilisation"]]
        for c in d.card_rows:
            rows.append([f"{c.card.bank} {c.card.name}", money(c.spent), f"{c.card.statement_day}th / {c.next_due:%-d %b}", money(c.owed), f"{c.utilisation_pct:.0f}%"])
        st += [Paragraph("Credit cards", h2), table(rows, [44 * mm, 30 * mm, 38 * mm, 30 * mm, 24 * mm], align_right_cols=(1, 3, 4))]
    pol = d.policies.get("policies") if d.policies else []
    if pol and not _hidden(d, "insurance"):
        any_ = True
        rows = [["Policy", "Type", "Premium", "Frequency", "Next due"]] + [[f"{p.insurer} {p.product}", p.type, money(p.premium), p.frequency.replace("_", "-").title(), f"{p.next_due:%-d %b}"] for p in pol]
        rows.append(["Total per year", "", money(d.policies["annual"]), "", ""])
        n = len(rows)
        st += [Paragraph("Insurance", h2), table(rows, [50 * mm, 30 * mm, 28 * mm, 28 * mm, 24 * mm], align_right_cols=(2,), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if d.subs and not _hidden(d, "subscriptions"):
        any_ = True
        rows = [["Subscription", "Per month", "Per year"]]
        tm = ZERO
        for s in d.subs:
            m = s.amount if s.cycle == "monthly" else s.amount / 12
            tm += m
            rows.append([s.name, money(m), money(m * 12)])
        rows.append(["Total", money(tm), money(tm * 12)])
        n = len(rows)
        st += [Paragraph("Subscriptions", h2), table(rows, [70 * mm, 40 * mm, 40 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if d.fees and not _hidden(d, "fees"):
        any_ = True
        rows = [["Fee", "Date", "Amount"]] + [[x.description, f"{x.spend_date:%-d %b}", money(x.amount)] for x in d.fees]
        st += [Paragraph("Fees", h2), table(rows, [70 * mm, 40 * mm, 40 * mm], align_right_cols=(2,))]
    if not any_:
        return []
    st.append(PageBreak())
    return st


def perks(d: MonthlyData):
    st, any_ = [Paragraph("8. Vouchers, big-ticket items and warranties", h1)], False
    if d.voucher_rows and not _hidden(d, "vouchers"):
        any_ = True
        rows = [["Scheme", "Remaining", "Expires", "Days left", "Note"]]
        ex = []
        for i, r in enumerate(sorted(d.voucher_rows, key=lambda r: r["days_left"]), start=1):
            v = r["voucher"]
            rows.append([v.scheme + (f" ({v.label})" if v.label else ""), money(v.remaining), f"{v.expires:%-d %b %Y}", str(r["days_left"]), "Use soon" if r["days_left"] <= 30 else ""])
            ex.append(("TEXTCOLOR", (3, i), (4, i), RED if r["days_left"] <= 30 else AMBER if r["days_left"] <= 60 else GREEN))
        rows.append(["Total", money(sum((r["voucher"].remaining for r in d.voucher_rows), ZERO)), "", "", f"Used this month {money(d.voucher_used)}"])
        st += [Paragraph("Vouchers (not included in net worth)", h2), table(rows, [38 * mm, 28 * mm, 32 * mm, 22 * mm, 40 * mm], align_right_cols=(1, 3), extra=ex)]
    if d.items_month:
        any_ = True
        rows = [["Date", "Item", "Price", "Warranty ends"]] + [[f"{i.purchase_date:%-d %b}", i.name, money(i.price), f"{i.warranty_end:%-d %b %Y}" if i.warranty_end else "none"] for i in d.items_month]
        st += [Paragraph("Big-ticket purchases this month", h2), table(rows, [24 * mm, 64 * mm, 30 * mm, 40 * mm], align_right_cols=(2,))]
    if d.warranties:
        any_ = True
        rows = [["Item", "Warranty ends", "Days left"]] + [[i.name, f"{i.warranty_end:%-d %b %Y}", str(days)] for i, days in d.warranties]
        st += [Paragraph("Warranties ending within 60 days", h2), table(rows, [70 * mm, 40 * mm, 30 * mm], align_right_cols=(2,)), Paragraph("Use /item <name> in the group to get the receipt back.", note)]
    if not any_:
        return []
    st.append(PageBreak())
    return st


def appendix(d: MonthlyData):
    st = [Paragraph(f"Appendix: all entries ({d.title})", h1), Paragraph(f"{len(d.entries)} entries. Paid = amount you paid. Sorted by spend date.", note), Spacer(1, 4)]
    sc = ParagraphStyle("sc", parent=cell, fontSize=6.8, leading=8.2)
    rows = [["Date", "Description", "Category", "Bucket", "Account", "With", "Paid"]]
    for x in d.entries:
        c = d.names["cats"].get(x.category_id)
        accts = " + ".join(d.names["accts"][p.account_id].name if p.account_id in d.names["accts"] else "?" for p in x.payments)
        who = ", ".join(d.names["people"][p].name for p in x.people if p in d.names["people"]) or "Alone"
        rows.append([f"{x.spend_date.day:02d} {calendar.month_abbr[x.spend_date.month]}", P(x.description[:34], sc), c.name if c else "?", x.bucket.value.title(), P(accts[:24], sc), P(who, sc), money(x.amount)])
    rows.append(["", "Total paid", "", "", "", "", money(d.paid_total)])
    n = len(rows)
    st.append(table(rows, [14 * mm, 46 * mm, 20 * mm, 16 * mm, 28 * mm, 30 * mm, 26 * mm], font=6.8, align_right_cols=(6,),
                    extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 6.8), ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]))
    return st


def build(d: MonthlyData, out) -> None:
    story = []
    for section in (summary, net_worth, budgets, calendar_page, where_money_went, biggest, owed, obligations, perks, appendix):
        story += section(d)
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm, bottomMargin=17 * mm,
                            title=f"Monthly Report: {d.title}", author="Finance Bot")
    f = make_footer(f"{d.title} monthly report")
    doc.build(story, onFirstPage=f, onLaterPages=f)


def render(d: MonthlyData) -> bytes:
    buf = io.BytesIO()
    build(d, buf)
    return buf.getvalue()
