"""Yearly PDF (PRD 6.6). Same data-driven rules as the monthly report (PRD 9.5)."""
from __future__ import annotations

import calendar
import io
from decimal import Decimal

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..domain.money import ZERO
from .dataset import YearlyData, pct
from .pdf_common import (A4, AMBER, CW, F_BOLD, F_REG, GREEN, LINE, MARGIN, ORANGE, RED, TEAL, TEAL_L, ParagraphStyle, bar, base, colors,
                         h1, h2, kpi_row, make_footer, money, mm, note, table, title_block)

MN = [calendar.month_abbr[i] for i in range(1, 13)]


def _bul(items):
    out = []
    for t in items:
        out += [Paragraph("&bull;&nbsp; " + t, base), Spacer(1, 2)]
    return out


def _hidden(d, name):
    return name in d.settings.hidden_sections


def summary(d: YearlyData):
    kp = [("Income", money(d.income, 0), "", GREEN), ("Net spend", money(d.net_spend, 0), f"Monthly {money(d.monthly_total, 0)} + Yearly {money(d.yearly_total, 0)}", ORANGE),
          ("Saved", money(d.saved, 0), f"Savings rate {d.savings_rate:.0f}%", TEAL)]
    if d.nw_start and d.nw_end:
        ch = d.nw_end.net_worth - d.nw_start.net_worth
        kp.append(("Net worth", money(d.nw_end.net_worth, 0), f"{money(ch, 0, sign=True)} this year", TEAL))
    st = [title_block(f"{d.year} Yearly Report", f"Generated {d.generated:%a %-d %b %Y}  |  Home currency SGD  |  Net spend basis"), Spacer(1, 7), kpi_row(kp),
          Paragraph("Income vs net spend by month", h2)]
    dr = Drawing(CW, 165)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 38, 24, CW - 55, 120
    bc.data = [[float(m["income"]) for m in d.months], [float(m["net"]) for m in d.months]]
    bc.categoryAxis.categoryNames = MN
    top = max(max(bc.data[0]), max(bc.data[1]), 1)
    step = max(round(top / 4, -3), 500)
    bc.valueAxis.valueMin, bc.valueAxis.valueMax, bc.valueAxis.valueStep = 0, step * 5, step
    bc.valueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
    for ax in (bc.categoryAxis, bc.valueAxis):
        ax.labels.fontName, ax.labels.fontSize = F_REG, 7
    bc.valueAxis.visibleGrid, bc.valueAxis.gridStrokeColor = 1, LINE
    bc.bars[0].fillColor, bc.bars[1].fillColor = TEAL, ORANGE
    bc.bars.strokeColor = None
    bc.bars.strokeWidth = 0
    bc.groupSpacing = 8
    dr.add(bc)
    for x, c, t in ((CW - 150, TEAL, "Income"), (CW - 90, ORANGE, "Net spend")):
        dr.add(Rect(x, 152, 8, 8, fillColor=c, strokeColor=None))
        dr.add(String(x + 12, 153, t, fontName=F_REG, fontSize=7.5))
    st.append(dr)
    n = max(sum(1 for m in d.months if m["mon"]), 1)
    over = d.over_months()
    hl = [f"You saved {money(d.saved, 0)}, or {d.savings_rate:.0f}% of income.",
          f"Monthly bucket: {money(d.monthly_total, 0)} for the year, about {money(d.monthly_total / n, 0)} a month." + (f" You went over the total limit in {', '.join(MN[i] for i in over)}." if over else "")]
    if d.yearly_limit:
        hl.append(f"Yearly bucket: {money(d.yearly_total, 0)} of {money(d.yearly_limit, 0)} used ({pct(d.yearly_total, d.yearly_limit):.0f}%).")
    if d.people_rank and not _hidden(d, "people"):
        r = d.people_rank
        hl.append(f"You spent the most with {r[0].name}: {money(r[0].spent, 0)} over {r[0].outings} outings" + (f", ahead of {r[1].name} ({money(r[1].spent, 0)})." if len(r) > 1 else "."))
    if d.nw_start and d.nw_end:
        hl.append(f"Net worth grew {money(d.nw_end.net_worth - d.nw_start.net_worth, 0)}: {money(d.saved, 0)} from saving and {money(d.market_gain, 0)} from market moves.")
    st += [Paragraph("Highlights", h2), *_bul(hl), PageBreak()]
    return st


def month_table(d: YearlyData):
    st = [Paragraph("1. Month by month", h1)]
    rows = [["Month", "Income", "Monthly", "Yearly", "Net spend", "Saved", "Rate", "Net worth"]]
    ex = []
    for i, m in enumerate(d.months):
        rows.append([MN[i], money(m["income"], 0), money(m["mon"], 0), money(m["yr"], 0), money(m["net"], 0), money(m["saved"], 0),
                     f"{pct(m['saved'], m['income']):.0f}%" if m["income"] else "-", money(m["nw"], 0) if m["nw"] is not None else "-"])
        if i in d.over_months():
            ex.append(("TEXTCOLOR", (2, i + 1), (2, i + 1), RED))
        if m["saved"] < 0:
            ex.append(("TEXTCOLOR", (5, i + 1), (5, i + 1), RED))
    rows.append(["Year", money(d.income, 0), money(d.monthly_total, 0), money(d.yearly_total, 0), money(d.net_spend, 0), money(d.saved, 0), f"{d.savings_rate:.0f}%",
                 money(d.nw_end.net_worth, 0) if d.nw_end else "-"])
    ex += [("FONT", (0, 13), (-1, 13), F_BOLD, 8), ("BACKGROUND", (0, 13), (-1, 13), TEAL_L)]
    st.append(table(rows, [18 * mm, 24 * mm, 24 * mm, 22 * mm, 24 * mm, 24 * mm, 14 * mm, 30 * mm], align_right_cols=tuple(range(1, 8)), extra=ex))
    st += [Spacer(1, 4), Paragraph("Red = over the total Monthly limit, or a month where spending exceeded income. Net worth is the month-end snapshot.", note), PageBreak()]
    return st


def budgets(d: YearlyData):
    st = [Paragraph("2. Budget performance", h1), Paragraph("Monthly bucket by category (limits x 12)", h2)]
    rows = [["Category", "Spent", "Limit", "Used", "Months over", ""]]
    for name, vals in sorted(d.mon_matrix.items(), key=lambda kv: -sum(kv[1])):
        lims = d.cat_limits.get(name)
        total = sum(vals, ZERO)
        if lims and all(lims):
            lim = sum((l for l in lims), ZERO)
            p = pct(total, lim)
            rows.append([name, money(total, 0), money(lim, 0), f"{p:.0f}%", ", ".join(MN[i] for i in d.cat_over(name)) or "None", bar(min(p / 100, 1), RED if p >= 100 else AMBER if p >= 80 else GREEN, 38 * mm)])
        else:
            rows.append([f"{name} (no limit)", money(total, 0), "-", "-", "-", ""])
    st.append(table(rows, [34 * mm, 26 * mm, 26 * mm, 16 * mm, 30 * mm, 46 * mm], align_right_cols=(1, 2, 3)))
    if d.yr_matrix:
        tot = d.yearly_total or Decimal(1)
        rows = [["Category", "Spent", "Share of bucket", ""]]
        for name, vals in sorted(d.yr_matrix.items(), key=lambda kv: -sum(kv[1])):
            s = sum(vals, ZERO)
            rows.append([name, money(s, 0), f"{pct(s, tot):.0f}%", bar(float(s / tot), ORANGE, 55 * mm)])
        rows.append(["Total", money(d.yearly_total, 0), f"{pct(d.yearly_total, d.yearly_limit):.0f}% of {money(d.yearly_limit, 0)}" if d.yearly_limit else "", ""])
        n = len(rows)
        st += [Paragraph("Yearly bucket by category", h2), table(rows, [52 * mm, 30 * mm, 40 * mm, 58 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if d.groups:
        tot = d.net_spend or Decimal(1)
        rows = [["With", "Net spend", "Share", ""]] + [[k, money(v, 0), f"{pct(v, tot):.0f}%", bar(float(v / tot), TEAL, 60 * mm)] for k, v in sorted(d.groups.items(), key=lambda kv: -kv[1])]
        st += [Paragraph("Who you spent with (groups)", h2), table(rows, [40 * mm, 35 * mm, 25 * mm, 80 * mm], align_right_cols=(1, 2))]
    if d.accounts:
        tot = d.net_spend or Decimal(1)
        rows = [["Account", "Paid", "Share", ""]] + [[k, money(v, 0), f"{pct(v, tot):.0f}%", bar(float(v / tot), TEAL, 60 * mm)] for k, v in sorted(d.accounts.items(), key=lambda kv: -kv[1])]
        st += [Paragraph("By account (amount paid)", h2), table(rows, [40 * mm, 35 * mm, 25 * mm, 80 * mm], align_right_cols=(1, 2))]
    st.append(PageBreak())
    return st


def _heat(v, lo, hi):
    if hi == lo or not v:
        return colors.white
    t = float((v - lo) / (hi - lo))
    a, b = (0xFB, 0xE3, 0xB8), (0xF2, 0xA9, 0x6A)
    c = [int(a[i] + (b[i] - a[i]) * t) for i in range(3)]
    return colors.Color(c[0] / 255, c[1] / 255, c[2] / 255)


def _matrix(rowsd, totals, d, limits=None, label="Total"):
    rows, ex = [[""] + MN + ["Year"]], []
    for ri, (k, vals) in enumerate(sorted(rowsd.items(), key=lambda kv: -sum(kv[1])), start=1):
        rows.append([k] + [f"{v:,.0f}" if v else "-" for v in vals] + [f"{sum(vals, ZERO):,.0f}"])
        nz = [v for v in vals if v]
        lo, hi = (min(nz), max(nz)) if nz else (ZERO, ZERO)
        lims = limits.get(k) if limits else None
        for ci, v in enumerate(vals, start=1):
            if lims and lims[ci - 1] and v > lims[ci - 1]:
                ex += [("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#F4B6B6")), ("TEXTCOLOR", (ci, ri), (ci, ri), RED), ("FONT", (ci, ri), (ci, ri), F_BOLD, 6.8)]
            else:
                ex.append(("BACKGROUND", (ci, ri), (ci, ri), _heat(v, lo, hi)))
    n = len(rows)
    rows.append([label] + [f"{totals[i]:,.0f}" for i in range(12)] + [f"{sum(totals, ZERO):,.0f}"])
    ex += [("FONT", (0, n), (-1, n), F_BOLD, 6.8), ("BACKGROUND", (0, n), (-1, n), TEAL_L), ("FONT", (13, 1), (13, n), F_BOLD, 6.8),
           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    return table(rows, [26 * mm] + [11 * mm] * 12 + [22 * mm], font=6.8, align_right_cols=tuple(range(1, 14)), zebra=False, extra=ex)


def category_matrix(d: YearlyData):
    st = [Paragraph("3. Category by month", h1), Paragraph("Net spend by category for every month. Red cells are over that month's limit; shading shows how heavy the month was for the category.", note)]
    if d.mon_matrix:
        st += [Paragraph("Monthly bucket", h2), _matrix(d.mon_matrix, [m["mon"] for m in d.months], d, d.cat_limits, "Total Monthly")]
        over = d.over_months()
        co = [f"{c} in {', '.join(MN[i] for i in d.cat_over(c))}" for c in d.mon_matrix if d.cat_over(c)]
        st += [Spacer(1, 3), Paragraph(("Over a limit: " + "; ".join(co) + ". " if co else "No category went over its limit. ") + (f"Total Monthly went over its limit in {', '.join(MN[i] for i in over)}." if over else ""), note)]
    if d.yr_matrix:
        st += [Paragraph("Yearly bucket", h2), _matrix(d.yr_matrix, [m["yr"] for m in d.months], d, None, "Total Yearly")]
    st += [Paragraph("All spending", h2), table([[""] + MN + ["Year"], ["Net spend"] + [f"{m['net']:,.0f}" for m in d.months] + [f"{d.net_spend:,.0f}"]],
                                              [26 * mm] + [11 * mm] * 12 + [22 * mm], font=6.8, align_right_cols=tuple(range(1, 14)),
                                              extra=[("FONT", (0, 1), (-1, 1), F_BOLD, 6.8), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]), PageBreak()]
    return st


def trips_and_owed(d: YearlyData):
    st = [Paragraph("4. Trips, big purchases and money owed", h1)]
    if d.trips:
        rows = [["Trip", "Dates", "Total", "Per day", "Top categories"]]
        for t in d.trips:
            top = ", ".join(f"{k} {money(v, 0)}" for k, v in sorted(t.by_category.items(), key=lambda kv: -kv[1])[:3])
            rows.append([t.trip.name, f"{t.trip.start:%-d %b}" + (f" to {t.trip.end:%-d %b}" if t.trip.end else ""), money(t.total, 0), money(t.per_day, 0), top])
        rows.append(["Total", "", money(sum((t.total for t in d.trips), ZERO), 0), "", ""])
        n = len(rows)
        st += [Paragraph("Trips", h2), table(rows, [22 * mm, 34 * mm, 22 * mm, 20 * mm, 82 * mm], font=7.6, align_right_cols=(2, 3), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 7.6)]),
               Paragraph("Trip spend counts under the Yearly bucket.", note)]
    if d.items:
        rows = [["Date", "Item", "Price", "Warranty ends"]] + [[f"{i.purchase_date:%-d %b}", i.name, money(i.price), f"{i.warranty_end:%-d %b %Y}" if i.warranty_end else "none"] for i in sorted(d.items, key=lambda i: i.purchase_date)]
        rows.append(["", "Total", money(sum((i.price for i in d.items), ZERO)), ""])
        n = len(rows)
        st += [Paragraph("Big-ticket purchases", h2), table(rows, [24 * mm, 66 * mm, 30 * mm, 50 * mm], align_right_cols=(2,), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    o = d.owed
    rows = [["", "Amount"], ["Lent to friends this year", money(o["lent"])], ["Repaid", money(o["repaid"])], ["Outstanding now", money(o["outstanding"])],
            ["Claims submitted", money(o["claims_submitted"])], ["Claims reimbursed", money(o["claims_paid"])]]
    st += [Paragraph("Money owed to you", h2), table(rows, [90 * mm, 40 * mm], align_right_cols=(1,))]
    st.append(PageBreak())
    return st


def perks(d: YearlyData):
    st, any_ = [Paragraph("5. Cards, rewards, fees and perks", h1)], False
    if d.cards_value and not _hidden(d, "cards"):
        any_ = True
        rows = [["Card", "Spent", "Earned", "Est. value", "Annual fee", "Net"]]
        for c in d.cards_value:
            rows.append([f"{c['card'].bank} {c['card'].name}", money(c["spend"], 0), f"{c['earned']:,.0f}", money(c["value"]), money(c["fee"]), money(c["net"], sign=True)])
        rows.append(["Total", money(sum((c["spend"] for c in d.cards_value), ZERO), 0), "", money(sum((c["value"] for c in d.cards_value), ZERO)),
                     money(sum((c["fee"] for c in d.cards_value), ZERO)), money(sum((c["net"] for c in d.cards_value), ZERO), sign=True)])
        n = len(rows)
        st += [Paragraph("Rewards vs annual fees", h2), table(rows, [38 * mm, 26 * mm, 24 * mm, 28 * mm, 26 * mm, 28 * mm], align_right_cols=(1, 2, 3, 4, 5), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if any(d.fees.values()) and not _hidden(d, "fees"):
        any_ = True
        rows = [["Fee", "Amount"]] + [[k, money(v)] for k, v in d.fees.items()] + [["Total", money(sum(d.fees.values(), ZERO))]]
        n = len(rows)
        st += [Paragraph("Fees paid", h2), table(rows, [90 * mm, 40 * mm], align_right_cols=(1,), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if d.subs_list and not _hidden(d, "subscriptions"):
        any_ = True
        rows = [["Subscription", "Per month", "Per year"]] + [[s.name, money(s.amount if s.cycle == "monthly" else s.amount / 12), money(s.amount * (12 if s.cycle == "monthly" else 1))] for s in d.subs_list]
        rows.append(["Total", money(d.subs[0]), money(d.subs[1])])
        n = len(rows)
        st += [Paragraph("Subscriptions", h2), table(rows, [70 * mm, 40 * mm, 40 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    pol = d.insurance.get("policies") if d.insurance else []
    if pol and not _hidden(d, "insurance"):
        any_ = True
        tot = d.insurance["annual"] or Decimal(1)
        rows = [["Policy", "Premium per year", "Share"]] + [[f"{p.insurer} {p.product}", money(p.premium * {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}[p.frequency]),
                                                           f"{float(p.premium * {'monthly': 12, 'quarterly': 4, 'half_yearly': 2, 'yearly': 1}[p.frequency] / tot * 100):.0f}%"] for p in pol]
        rows.append(["Total", money(d.insurance["annual"]), "100%"])
        n = len(rows)
        st += [Paragraph("Insurance", h2), table(rows, [70 * mm, 45 * mm, 35 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, n - 1), (-1, n - 1), F_BOLD, 8)])]
    if any(d.vouchers.values()) and not _hidden(d, "vouchers"):
        any_ = True
        rows = [["", "Amount"], ["Received", money(d.vouchers["received"])], ["Used", money(d.vouchers["used"])], ["Expired unused", money(d.vouchers["expired"])]]
        st += [Paragraph("Vouchers", h2), table(rows, [70 * mm, 40 * mm], align_right_cols=(1,), extra=[("TEXTCOLOR", (1, 3), (1, 3), RED if d.vouchers["expired"] else colors.black)])]
    if not any_:
        return []
    st.append(PageBreak())
    return st


def net_worth(d: YearlyData):
    if not (d.nw_start and d.nw_end):
        return []
    s, e = d.nw_start, d.nw_end
    ch = e.net_worth - s.net_worth
    st = [Paragraph("6. Net worth", h1), kpi_row([("Start of year", money(s.net_worth, 0), f"{s.date:%-d %b %Y}", TEAL), ("End of year", money(e.net_worth, 0), f"{e.date:%-d %b %Y}", TEAL),
                                                  ("Growth", money(ch, 0, sign=True), f"{pct(ch, s.net_worth):+.1f}%", GREEN if ch >= 0 else RED)])]
    pts = [(i, float(m["nw"])) for i, m in enumerate(d.months, start=1) if m["nw"] is not None]
    if len(pts) >= 2:
        dr = Drawing(CW, 170)
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 44, 24, CW - 62, 125
        lp.data = [pts]
        lp.lines[0].strokeColor, lp.lines[0].strokeWidth = TEAL, 2
        lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 1, 12
        lp.xValueAxis.valueSteps = list(range(1, 13))
        lp.xValueAxis.labelTextFormat = lambda v: MN[int(v) - 1]
        lo, hi = min(p[1] for p in pts), max(p[1] for p in pts)
        lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = lo * 0.95, hi * 1.03
        lp.yValueAxis.valueStep = max(round((hi - lo) / 4, -3), 1000)
        lp.yValueAxis.labelTextFormat = lambda v: f"{v:,.0f}"
        for ax in (lp.xValueAxis, lp.yValueAxis):
            ax.labels.fontName, ax.labels.fontSize = F_REG, 7
        lp.yValueAxis.visibleGrid, lp.yValueAxis.gridStrokeColor = 1, LINE
        dr.add(lp)
        st += [Paragraph("Month-end net worth", h2), dr]
    timing = ch - d.saved - d.market_gain
    rows = [["Source", "Amount", "Share"], ["Saved from income (income minus net spend)", money(d.saved, 0), f"{pct(d.saved, ch):.0f}%"],
            ["Market gains on investments", money(d.market_gain, 0), f"{pct(d.market_gain, ch):.0f}%"], ["Money owed to you and other timing", money(timing, 0), f"{pct(timing, ch):.0f}%"],
            ["Total growth", money(ch, 0), "100%"]]
    st += [Paragraph("Where the growth came from", h2), table(rows, [100 * mm, 40 * mm, 30 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, 4), (-1, 4), F_BOLD, 8)])]
    rows = [["", "Start", "End"], ["Fixed assets", money(s.fixed, 0), money(e.fixed, 0)], ["Variable assets", money(s.variable, 0), money(e.variable, 0)], ["Net worth", money(s.net_worth, 0), money(e.net_worth, 0)]]
    st += [Paragraph("Fixed and variable assets", h2), table(rows, [60 * mm, 40 * mm, 40 * mm], align_right_cols=(1, 2), extra=[("FONT", (0, 3), (-1, 3), F_BOLD, 8)]), PageBreak()]
    return st


def who(d: YearlyData):
    if not d.people_rank or _hidden(d, "people"):
        return []
    hero = d.people_rank[0]
    hb = Table([[Paragraph(f'<font size="8" color="#6B7B82">NUMBER ONE THIS YEAR</font><br/><font size="18" color="#0F4C5C"><b>{hero.name}</b></font><br/>'
                           f'<font size="9">{money(hero.spent, 0)} spent together over {hero.outings} outings, about {money(hero.average, 0)} each time.</font>',
                           ParagraphStyle("hb", parent=base, leading=20))]], colWidths=[CW])
    hb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL_L), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LINEBEFORE", (0, 0), (0, -1), 4, ORANGE)]))
    friends = d.groups.get("Friends", ZERO) or Decimal(1)
    family = d.groups.get("Family", ZERO) or Decimal(1)
    rows = [["#", "Person", "Relationship", "Outings", "Spent with", "Avg per outing", "Share of group", ""]]
    for i, r in enumerate(d.people_rank, start=1):
        grp = friends if r.relationship == "friend" else family
        rows.append([str(i), r.name, r.relationship.title(), str(r.outings), money(r.spent, 0), money(r.average, 0), f"{pct(r.spent, grp):.0f}% of {r.relationship}",
                     bar(float(r.spent / d.people_rank[0].spent), ORANGE if i == 1 else TEAL, 28 * mm)])
    return [Paragraph("7. Who you spent the most with", h1), Spacer(1, 2), hb, Spacer(1, 8),
            table(rows, [8 * mm, 26 * mm, 24 * mm, 18 * mm, 24 * mm, 26 * mm, 28 * mm, 30 * mm], font=7.6, align_right_cols=(3, 4, 5), extra=[("FONT", (0, 1), (-1, 1), F_BOLD, 7.6)]),
            Spacer(1, 4), Paragraph("Spent with = your own share of every entry the person is on, not what you paid for others and not divided between people. One entry with several people counts your share for each of them, so totals overlap and shares of a group can add up to more than 100%. Outings are distinct days.", note), PageBreak()]


def projection(d: YearlyData):
    if not d.nw_end or "projection" in d.settings.hidden_sections:
        return []

    def years(target, start, annual, r):
        v, y = start, 0
        while v < target and y < 80:
            v, y = v * (1 + r) + annual, y + 1
        return y

    start, annual = float(d.nw_end.net_worth), float(d.saved)
    rows = [["Scenario", "Saved a year", "Real return", "Years to S$1M", "Reached in"]]
    for name, a, r in [("Your pace this year", annual, 0.04), ("Save S$200 more a month", annual + 2400, 0.04), ("Cautious returns", annual, 0.02), ("Cautious returns and S$200 more a month", annual + 2400, 0.02)]:
        y = years(1_000_000, start, a, r)
        rows.append([name, money(Decimal(str(round(a))), 0), f"{r*100:.0f}%", str(y) if y < 80 else "80+", str(d.year + y)])
    return [Paragraph("8. Retirement projection (optional, annual report only)", h1), Paragraph("An illustration from your own numbers, not financial advice. Real returns and savings will vary.", note), Spacer(1, 6),
            table(rows, [70 * mm, 28 * mm, 24 * mm, 30 * mm, 28 * mm], align_right_cols=(1, 2, 3, 4)), Spacer(1, 6),
            Paragraph("It appears in the yearly report only, never in the monthly report. Hide it with /settings reports.", note)]


def build(d: YearlyData, out) -> None:
    story = []
    for sec in (summary, month_table, budgets, category_matrix, trips_and_owed, perks, net_worth, who, projection):
        story += sec(d)
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=14 * mm, bottomMargin=17 * mm, title=f"Yearly Report: {d.year}", author="Finance Bot")
    f = make_footer(f"{d.year} yearly report")
    doc.build(story, onFirstPage=f, onLaterPages=f)


def render(d: YearlyData) -> bytes:
    buf = io.BytesIO()
    build(d, buf)
    return buf.getvalue()
