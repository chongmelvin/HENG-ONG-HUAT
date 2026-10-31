"""Telegram report messages (PRD 5.5, 6.6): net worth first, traffic lights, personality touch."""
from __future__ import annotations

from decimal import Decimal

from ..core import indicators as ind
from ..core.indicators import Badge
from ..domain.money import ZERO, fmt
from ..messaging.templates import Messenger
from .dataset import MonthlyData, YearlyData


def _tl(badge: Badge, light: str) -> str:
    return badge.pre(light)


def monthly_message(d: MonthlyData, msg: Messenger) -> str:
    st, b = d.settings, Badge.of(d.settings)
    rate = d.savings_rate
    light = ind.savings_light(rate, st.savings_green, st.savings_yellow)
    event = "report_good" if light == ind.GREEN else "report_mid" if light == ind.YELLOW else "report_low"
    lines = [f"📊 {msg.say(event, month=calendar_name(d), rate=f'{rate:.0f}')}"]
    if d.nw:
        nw = d.nw
        ch = nw.change
        rec = ""
        if nw.recon is not None and not nw.recon.first:
            rec = f" {b(nw.recon.icon)} Fixed assets {'reconciled' if nw.recon.gap == 0 else 'have a gap of ' + fmt(nw.recon.gap)}."
        if nw.prev:
            lines.append(f"Net worth: {fmt(nw.snap.net_worth, 0)} {_tl(b, ind.networth_light(ch, nw.prev.net_worth))}{'up' if ch >= 0 else 'down'} {fmt(abs(ch), 0)} "
                         f"({float(ch / nw.prev.net_worth * 100):+.1f}%).{rec}")
        else:
            lines.append(f"Net worth: {fmt(nw.snap.net_worth, 0)}.{rec}")
        if nw.runway is not None:
            lines.append(f"Liquid runway: {nw.runway} months.")
    lines.append(f"Income {fmt(d.income, 0)} | Net spend {fmt(d.net_spend, 0)} | Saved {fmt(d.saved, 0)} ({_tl(b, light)}savings rate {rate:.0f}%)")
    if d.total_limit:
        used = float(d.monthly_net / d.total_limit * 100)
        row = f"{_tl(b, ind.budget_light(used))}Monthly budget: {fmt(d.monthly_net, 0)} of {fmt(d.total_limit, 0)} ({used:.0f}%)."
        worst = max((r for r in d.cats if r.limit and r.bucket.value == 'monthly'), key=lambda r: r.used_pct, default=None)
        if worst and worst.used_pct >= 80:
            row += f" {_tl(b, ind.budget_light(worst.used_pct))}{worst.category.name}: {fmt(worst.net, 0)} of {fmt(worst.limit, 0)} ({worst.used_pct:.0f}%)."
        lines.append(row)
    if d.yearly_limit:
        pace = d.yearly_pace
        label = "under pace" if pace and pace[2] == ind.GREEN else "near pace" if pace and pace[2] == ind.YELLOW else "ahead of pace"
        lines.append(f"{_tl(b, pace[2] if pace else '')}Yearly bucket: {fmt(d.yearly_ytd, 0)} of {fmt(d.yearly_limit, 0)} ({label}).")
    if d.people_rank:
        top = d.people_rank[0]
        lines.append(f"Most time with: {top.name} ({fmt(top.spent, 0)}, {top.outings} outings this month).")
    waits = [f"{_tl(b, ind.owed_light(r['days']))}{r['person']} {fmt(r['owed'], 0)} ({r['days']} days)" for r in sorted(d.owed_rows, key=lambda r: -r["days"])]
    claims = sum((c.outstanding for c in d.claim_rows), ZERO)
    if waits or claims:
        lines.append("Waiting on you: " + ", ".join(waits) + (f". Claim {fmt(claims, 0)}." if claims else "."))
    soon = []
    for v in d.voucher_rows:
        if v["days_left"] <= 60:
            soon.append(f"{_tl(b, v['light'])}{v['voucher'].scheme} {fmt(v['voucher'].remaining, 0)} expires in {v['days_left']} days")
    for p, due in d.policies.get("due_90", [])[:2] if d.policies else []:
        days = (due - d.generated).days
        if days <= 14:
            soon.append(f"{_tl(b, ind.bill_light(days))}{p.insurer} {fmt(p.premium, 0)} on {due:%-d %b}")
    if soon:
        lines.append("Coming up: " + ". ".join(soon) + ".")
    return "\n".join(lines)


def calendar_name(d: MonthlyData) -> str:
    import calendar
    return calendar.month_name[d.month]


def yearly_message(d: YearlyData, msg: Messenger) -> str:
    b = Badge.of(d.settings)
    rate = d.savings_rate
    light = ind.savings_light(rate, d.settings.savings_green, d.settings.savings_yellow)
    head = f"📊 {d.year} report is here. " + ("Wah, saved" if light == ind.GREEN else "Saved") + f" {fmt(d.saved, 0)} this year ({rate:.0f}%)."
    lines = [head, f"Income {fmt(d.income, 0)} | Net spend {fmt(d.net_spend, 0)}"]
    n = max(sum(1 for m in d.months if m["mon"]), 1)
    over = d.over_months()
    lines.append(f"Monthly bucket: {fmt(d.monthly_total, 0)}, about {fmt(d.monthly_total / n, 0)} a month."
                 + (f" Over the total limit {len(over)} time(s)." if over else " Never over the total limit."))
    if d.yearly_limit:
        used = float(d.yearly_total / d.yearly_limit * 100)
        lines.append(f"{_tl(b, ind.budget_light(used))}Yearly bucket: {fmt(d.yearly_total, 0)} of {fmt(d.yearly_limit, 0)} ({used:.0f}%)")
    if d.people_rank:
        r = d.people_rank
        tail = f", ahead of {r[1].name}" + (f" and {r[2].name}" if len(r) > 2 else "") if len(r) > 1 else ""
        lines.append(f"You spent the most with {r[0].name}: {fmt(r[0].spent, 0)} over {r[0].outings} outings{tail}.")
    if d.nw_start and d.nw_end:
        ch = d.nw_end.net_worth - d.nw_start.net_worth
        lines.append(f"Net worth: {fmt(d.nw_start.net_worth, 0)} to {fmt(d.nw_end.net_worth, 0)} {_tl(b, ind.networth_light(ch, d.nw_start.net_worth))}({fmt(ch, 0, sign=True)})")
    cv = sum((c["value"] for c in d.cards_value), ZERO)
    fee = sum((c["fee"] for c in d.cards_value), ZERO)
    if d.cards_value:
        lines.append(f"Rewards about {fmt(cv, 0)} vs {fmt(fee, 0)} card fees.")
    if d.vouchers.get("expired"):
        lines.append(f"Vouchers expired unused: {fmt(d.vouchers['expired'], 0)}.")
    if d.owed.get("outstanding"):
        lines.append(f"Money owed to you: {fmt(d.owed['outstanding'], 0)}.")
    return "\n".join(lines)
