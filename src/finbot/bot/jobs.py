"""Scheduled work (runs daily at the report hour, Asia/Singapore). Idempotent per day (PRD 9.1)."""
from __future__ import annotations

import logging
from datetime import date, datetime

from ..core import bills as bills_core, claims as claims_core, indicators as ind, items as items_core, splits, vouchers
from ..core.ledger import create_income
from ..domain.enums import ACTIVE
from ..domain.models import Bill, Card, Processed, Trip
from ..domain.money import fmt
from ..v2 import annual, rewards, subscriptions, trips
from .types import Button, Reply

log = logging.getLogger(__name__)


def run_daily(engine, now: datetime | None = None) -> list[Reply]:
    now = now or engine.now()
    today = now.date()
    key = f"job:{today.isoformat()}"
    if engine.repo.get(Processed, key):                       # a restart at 9:00 must not send everything twice
        return []
    engine.repo.add(Processed(id=key, at=now))
    repo, s, b = engine.repo, engine.settings(), engine.badge()
    out: list[Reply] = []

    # bills and premiums (3 days before, on the day, overdue)
    for bill, due, delta, light in bills_core.due_today(repo, today):
        if bill.kind == "income":
            continue
        when = "today" if delta == 0 else f"in {delta} days" if delta > 0 else f"{-delta} days ago (overdue)"
        last = f" Last amount: {fmt(bill.last_amount or bill.amount)}." if (bill.last_amount or bill.amount) else ""
        out.append(Reply(f"{b.pre(light)}{engine.msg.say('bill')} {bill.name} is due {due:%a %-d %b} ({when}).{last}",
                         [[Button("Paid", f"x:billpaid:{bill.id}"), Button("Snooze", f"x:billsnooze:{bill.id}"), Button("Skip", f"x:billskip:{bill.id}")]]))
    # recurring income: confirm, never post silently
    for bill in repo.find(Bill, status=ACTIVE, kind="income"):
        if bills_core.next_due(bill, today) == today:
            out.append(Reply(f"{bill.name.replace(' (income)', '')} {fmt(bill.amount)} is expected today into {engine.acct_name(bill.account_id)}.",
                             [[Button("Confirm", f"x:incconfirm:{bill.id}"), Button("Different amount", f"x:incdiff:{bill.id}"), Button("Skip", f"x:incskip:{bill.id}")]]))
    # expiries
    for v, days in vouchers.expiry_alerts(repo, today):
        out.append(Reply(f"{b.pre(ind.expiry_light(days))}" + engine.msg.say("voucher", scheme=v.scheme, amt=fmt(v.remaining), days=days),
                         [[Button("Used", "x:noop"), Button("Snooze", "x:noop"), Button("Extended", f"x:voucher:{v.id}:expired")]]))
    for v in vouchers.expire_overdue(repo, now):
        out.append(Reply(f"{b.pre(ind.RED)}{v.scheme} voucher {fmt(v.remaining)} expired on {v.expires:%-d %b}. Mark it as expired unused?",
                         [[Button("Confirm", f"x:voucher:{v.id}:expired"), Button("It was extended", "x:noop")]]))
    for it, days, light in items_core.warranty_alerts(repo, today):
        out.append(Reply(f"{b.pre(light)}{it.name} warranty ends {it.warranty_end:%-d %b %Y} ({days} days)." + (f" Receipt: {it.receipt_link}" if it.receipt_link else "")))
    for prog, bal, days in rewards.expiry_alerts(repo, today):
        out.append(Reply(f"{b.pre(ind.expiry_light(days))}{prog.name}: {bal.balance:,.0f} {prog.kind.value} {'expire in ' + str(days) + ' days' if days > 0 else 'have expired'}."))
    for sub, kind, days in subscriptions.reminders(repo, today):
        out.append(Reply(f"{b.pre(ind.YELLOW)}{sub.name} {'renews' if kind == 'renewal' else 'free trial ends'} in {days} days ({fmt(sub.amount)})."))
    # money owed: chase after chase_days, then weekly (never drafted, never sent to friends)
    for pid, owed, days in splits.chase_due(repo, today, s.chase_days):
        if (days - s.chase_days) % 7 == 0:
            out.append(Reply(f"{b.pre(ind.owed_light(days))}" + engine.msg.say("chase", name=engine.person_name(pid), amt=fmt(owed), days=days)))
    for c in claims_core.chase_due(repo, today, 14):
        if (today - c.submitted).days % 14 == 0:
            out.append(Reply(f"{c.claimant} claim {fmt(c.outstanding)} hasn't been paid in {(today - c.submitted).days} days."))
    # trips
    for t in repo.find(Trip, active=True):
        if not t.paused:
            state = trips.check_state(repo, t, today)
            if state == "still_on":
                trips.mark_checked(repo, t, today)
                out.append(Reply(f"Still on the {t.name} trip?", [[Button("Yes", "x:noop"), Button("End trip", "x:tripend")]]))
    # card annual fees
    for card in repo.find(Card, status=ACTIVE):
        if card.annual_fee > 0 and card.fee_month == today.month and today.day == 1:
            out.append(Reply(f"Annual fee for {card.bank} {card.name} ({fmt(card.annual_fee)}) falls this month."))
    # month start
    if today.day == 1:
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        out += engine.monthly_report(y, m)
        out.append(Reply("Monthly review. About 5 minutes.", [[Button("Start", "x:review:1"), Button("Later", "x:noop")]]))
        for it, amt in annual.run_sinking_funds(repo, today):
            log.info("sinking fund %s %s", it.name, amt)
        for card in repo.find(Card, status=ACTIVE):
            rewards.record_estimate(repo, now, card, y, m)
        if today.month == 1:
            out += engine.yearly_report(today.year - 1)
    # weekly nudge for unfinished setup
    if not s.setup_complete and today.weekday() == 0:
        out.append(Reply("Setup isn't finished yet. Send /setup to pick up where you left off."))
    return out
