"""v2 commands: trips, investments, rewards, best card, subscriptions, loans, yearly plan, fees (PRD 6)."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..core import budgets, indicators as ind, savings
from ..core.ledger import LedgerError, NetIndex, active_expenses
from ..core.lookup import norm
from ..domain.enums import ACTIVE, HoldingType
from ..domain.models import Card, Holding, Loan, RewardBalance, RewardProgram, Trip
from ..domain.money import D, ZERO, fmt
from ..parsing.dates import MONTHS
from ..parsing.expense import CURRENCIES
from ..v2 import annual, bestcard, investments, loans, rewards, subscriptions, trips
from .types import Button, Reply


class CommandsV2:
    # ------------------------------------------------------------------ /trip
    def cmd_trip(self, args: str) -> list[Reply]:
        toks = args.split()
        s = self.settings()
        sub = toks[0].lower() if toks else ""
        if sub == "start":
            m = re.match(r"start\s+(.+?)\s+(\d{1,2})\s+([a-z]{3,4})(?:\s+to\s+(\d{1,2})\s+([a-z]{3,4}))?(?:\s+([a-z]{3}))?(?:\s+budget\s+(\d+))?\s*$", args, re.I)
            if not m:
                return [Reply("Usage: /trip start Japan 20 Nov to 27 Nov jpy [budget 3000]")]
            name, d1, m1, d2, m2, cur, bud = m.groups()
            y = self.today().year
            start = date(y, MONTHS[m1.lower()[:3]], int(d1))
            end = date(y, MONTHS[m2.lower()[:3]], int(d2)) if d2 else None
            currency = (cur or "").upper() or "SGD"
            if cur and cur.lower() not in CURRENCIES:
                return [Reply(f'I don\'t know the currency "{cur}". Try jpy, usd, krw, thb...')]
            try:
                t = trips.start_trip(self.repo, s, self.now(), name=name.title(), start=start, end=end, currency=currency, budget=D(bud) if bud else None)
            except trips.TripConflict as e:
                p = self.pend("confirm", {"do": "noop", "args": {}})
                return [Reply(f"{e.active.name} is still on. End it or pause it first.", [[Button("End it", "x:tripend"), Button("Pause it", "x:trippause")]])]
            tail = f" Optional trip limit {fmt(t.budget, 0)} (inside the Yearly bucket)." if t.budget else ""
            return [Reply(f"✅ {self.msg.say('trip_on')} {t.name}, {currency}. Trip spend counts under your Yearly bucket.{tail}")]
        if sub in ("pause", "end", "resume", "summary"):
            if sub == "summary":
                t = self.repo.get(Trip, s.active_trip_id) or max(self.repo.all(Trip), key=lambda x: x.start, default=None)
                if not t:
                    return [Reply("No trips yet.")]
                sm = trips.summary(self.repo, t.id)
                top = ", ".join(f"{k} {fmt(v, 0)}" for k, v in sorted(sm.by_category.items(), key=lambda kv: -kv[1])[:4])
                lim = f", {self.badge().pre(ind.budget_light(sm.budget_used_pct))}{sm.budget_used_pct:.0f}% of the trip limit" if sm.budget_used_pct is not None else ""
                return [Reply(f"{t.name}: {fmt(sm.total)} in SGD, {fmt(sm.per_day)} a day{lim}.\nBy category: {top}.")]
            if sub == "resume":
                paused = [t for t in self.repo.all(Trip) if t.paused]
                if not paused:
                    return [Reply("No paused trip.")]
                trips.resume_trip(self.repo, s, paused[-1].id)
                return [Reply(f"✅ Back on the {paused[-1].name} trip.")]
            if not s.active_trip_id:
                return [Reply("No trip is on.")]
            t = trips.pause_trip(self.repo, s) if sub == "pause" else trips.end_trip(self.repo, s, self.now())
            return [Reply(f"✅ {t.name} {'paused' if sub == 'pause' else 'ended'}. Normal mode is back.")]
        return [Reply("Usage: /trip start Japan 20 Nov to 27 Nov jpy | pause | resume | end | summary")]

    # ------------------------------------------------------------------ /invest
    def cmd_invest(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "add":
            if len(toks) < 6:
                return [Reply("Usage: /invest add <symbol> <stock|etf|crypto> <units> <cost basis> <name...>")]
            try:
                typ = HoldingType(toks[2].lower())
            except ValueError:
                return [Reply("Type must be stock, etf or crypto.")]
            h = investments.add_holding(self.repo, self.now(), name=" ".join(toks[5:]), symbol=toks[1], type=typ, units=D(toks[3]), cost_basis=D(toks[4]))
            return [Reply(f"✅ Added {h.name}. Prices are fetched automatically.")]
        out = []
        if (not toks or toks[0] == "refresh") and self.prices:
            res = investments.refresh_prices(self.repo, self.prices, self.today(), self.fx)
            if res.stale:
                out.append(Reply("⚠️ I couldn't fetch " + ", ".join(h.name for h in res.stale) + ". Using the last known price, marked stale."))
        rows = investments.table(self.repo, self.today())
        if not rows:
            return out + [Reply("No holdings yet. /invest add VWRA etf 100 8000 Global equity ETF")]
        tot = sum((r.value for r in rows), ZERO)
        lines = [f"Investments {fmt(tot, 0)}:"] + [f"{r.holding.name}{' *' if r.stale else ''}: {fmt(r.value, 0)} ({r.return_pct:+.1f}%, {r.share_pct:.0f}% of total)" for r in rows]
        big = [r for r in rows if r.share_pct > 30]
        if big:
            lines.append(f"⚠️ {big[0].holding.name} is {big[0].share_pct:.0f}% of your investments (flag above 30%).")
        return out + [Reply("\n".join(lines), sensitive=True)]

    # ------------------------------------------------------------------ /rewards, /bestcard
    def cmd_rewards(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "confirm" and len(toks) >= 3:
            card = next((c for c in self.repo.all(Card) if norm(toks[1]) in norm(c.bank + " " + c.name)), None)
            if not card:
                return [Reply("I couldn't find that card.")]
            prog = rewards.ensure_program(self.repo, card)
            exp = None
            if "exp" in toks:
                exp = date.fromisoformat(toks[toks.index("exp") + 1])
            diff = rewards.confirm_balance(self.repo, self.now(), prog.id, D(toks[2]), exp)
            return [Reply(f"✅ Balance confirmed at {D(toks[2]):,.0f}." + (f" Adjusted by {diff:+,.0f} from my estimate." if diff else ""))]
        if toks and toks[0] == "rule" and len(toks) >= 4:
            from ..domain.models import CardRule
            from ..core.ids import new_id
            card = next((c for c in self.repo.all(Card) if norm(toks[1]) in norm(c.bank + " " + c.name)), None)
            if not card:
                return [Reply("I couldn't find that card.")]
            kv = {toks[i].lower(): toks[i + 1] for i in range(4, len(toks) - 1, 2)}
            rule = CardRule(id=new_id("cr"), card_id=card.id, category=toks[2].lower(), rate=Decimal(toks[3]), last_verified=self.today(),
                            cap=D(kv["cap"]) if "cap" in kv else None, min_spend=D(kv["min"]) if "min" in kv else None,
                            channel=kv.get("channel", ""), fallback_rate=Decimal(kv.get("fallback", "0.4")))
            self.repo.add(rule)
            return [Reply(f"✅ Saved the {toks[2].lower()} rule for {card.bank} {card.name}, verified today. Banks change these often, so I'll nudge you to re-check in 6 months.")]
        bals = self.repo.all(RewardBalance)
        if not bals:
            return [Reply("No rewards tracked yet. /rewards confirm <card> <balance> exp 2026-12-31")]
        b, today = self.badge(), self.today()
        lines = []
        for rb in bals:
            p = self.repo.get(RewardProgram, rb.program_id)
            tail = ""
            if rb.expires:
                days = (rb.expires - today).days
                tail = f", expires {rb.expires:%-d %b} ({b.pre(ind.expiry_light(days))}{days} days)"
            lines.append(f"{p.name}: {rb.balance:,.0f} {p.kind.value} (about {fmt(rewards.value_of(p, rb.balance), 0)}){tail}")
        return [Reply("\n".join(lines))]

    def cmd_bestcard(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "map" and len(toks) == 3:
            from ..domain.models import MerchantMap
            from ..core.ids import new_id
            self.repo.add(MerchantMap(id=new_id("mm"), keyword=toks[1].lower(), card_category=toks[2].lower()))
            return [Reply(f"✅ {toks[1]} now counts as {toks[2].lower()} for card rules.")]
        m = re.match(r"^(.*?)\s*\$?(\d+(?:\.\d+)?)\s*$", args.strip())
        if not m or not m.group(1):
            return [Reply("Usage: /bestcard grab 20")]
        merchant, amount = m.group(1), D(m.group(2))
        cat, opts = bestcard.recommend(self.repo, merchant, amount, self.today())
        if not opts:
            return [Reply(f"None of your cards has a rule for {cat}. Add earn rules in /setup earn.")]
        lines = []
        for i, o in enumerate(opts, 1):
            lines.append(f"{i}) {o.card.bank} {o.card.name}: {o.reason} (about {fmt(o.value)} on this).")
        if any(o.stale for o in opts):
            lines.append("⚠️ Some earn rules were last verified over 6 months ago. Banks change them often, so re-check.")
        return [Reply("\n".join(lines))]

    # ------------------------------------------------------------------ extras
    def cmd_subs(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "add" and len(toks) >= 3:
            try:
                amt = D(toks[-1] if re.match(r"^\d", toks[-1]) else toks[-2])
            except ValueError:
                return [Reply("Usage: /subs add Netflix 17.98")]
            name = " ".join(t for t in toks[1:] if t not in (str(amt), toks[-1]) or t == toks[1]) if False else " ".join(toks[1:-1])
            sub = subscriptions.add(self.repo, self.now(), name.title(), amt, self.today().replace(day=min(self.today().day, 28)))
            return [Reply(f"✅ Tracking {sub.name} at {fmt(amt)} a month. I'll remind you 3 days before each renewal.")]
        subs = self.repo.find(subscriptions.Subscription, status=ACTIVE)
        sug = subscriptions.detect(self.repo, self.today())
        if not subs and not sug:
            return [Reply("No subscriptions tracked.")]
        m, y = subscriptions.totals(self.repo)
        lines = [f"{s.name}: {fmt(s.amount)} {s.cycle}, renews {s.next_renewal:%-d %b}" if s.next_renewal else f"{s.name}: {fmt(s.amount)} {s.cycle}" for s in sorted(subs, key=lambda s: s.next_renewal or date.max)]
        lines.append(f"Total {fmt(m)} a month, {fmt(y)} a year.")
        for name, amt in sug[:3]:
            lines.append(f"Looks like a subscription: {name} {fmt(amt)} repeating monthly. Track it? /subs add {name} {amt}")
        return [Reply("\n".join(lines))]

    def cmd_loans(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "add" and len(toks) >= 5:
            rate = D(toks[-2].rstrip("%")) / 100
            l = loans.add(self.repo, self.now(), lender=" ".join(toks[1:-3]).title(), original=D(toks[-3]), balance=D(toks[-3]), rate=rate, instalment=D(toks[-1]))
            return [Reply(f"✅ Added the {l.lender} loan: {fmt(l.balance, 0)} at {l.rate * 100:.1f}%, instalment {fmt(l.instalment)}. Interest counts as spending; principal is a transfer.")]
        ls = loans.active(self.repo)
        if not ls:
            return [Reply("No loans tracked.")]
        out = []
        for l in ls:
            base_ = loans.payoff(l, self.today())
            fast = loans.payoff(l, self.today(), Decimal("200"))
            t = f"{l.lender}: balance {fmt(l.balance, 0)} at {l.rate * 100:.1f}%, instalment {fmt(l.instalment)}."
            if base_:
                t += f" Payoff {base_.payoff:%b %Y}, interest {fmt(base_.total_interest, 0)}."
            if fast and base_:
                t += f" Paying {fmt(Decimal('200'), 0)} more a month: payoff {fast.payoff:%b %Y}, saves {fmt(base_.total_interest - fast.total_interest, 0)} interest."
            out.append(t)
        return [Reply("\n".join(out))]

    def cmd_yearplan(self, args: str) -> list[Reply]:
        toks = args.split()
        if toks and toks[0] == "add" and len(toks) >= 4:
            month = MONTHS.get(toks[-1].lower()[:3]) or (int(toks[-1]) if toks[-1].isdigit() else 0)
            if not 1 <= month <= 12:
                return [Reply("Usage: /yearplan add Insurance 1800 nov")]
            it = annual.add(self.repo, " ".join(toks[1:-2]).title(), D(toks[-2]), month)
            return [Reply(f"✅ {it.name} {fmt(it.amount, 0)} planned for {calendar_month(month)}. Set aside {fmt(annual.monthly_set_aside(it), 0)} a month (virtual; your Monthly budget is untouched).")]
        t = self.today()
        idx, exps = NetIndex(self.repo), active_expenses(self.repo)
        ys, ye = budgets.year_bounds(t.year)
        f = annual.forecast(self.repo, t.year, budgets.spent(idx, exps, ys, ye, bucket=budgets.Bucket.YEARLY))
        lines = [f"{calendar_month(it.month)}: {it.name} {fmt(it.amount, 0)} (set aside {fmt(annual.monthly_set_aside(it), 0)} a month)" for it in f["calendar"]]
        lines.append(f"Known yearly costs {fmt(f['known'], 0)}, spent so far {fmt(f['spent'], 0)}, left unplanned {fmt(f['unplanned'], 0)} of {fmt(f['limit'], 0)}.")
        return [Reply("\n".join(lines))]

    def cmd_fees(self, args: str) -> list[Reply]:
        t = self.today()
        fees = [e for e in active_expenses(self.repo) if "Fees" in e.tags and e.spend_date.year == t.year]
        total = sum((e.amount for e in fees), ZERO)
        annual_fees = sum((c.annual_fee for c in self.repo.all(Card) if c.status == ACTIVE), ZERO)
        return [Reply(f"Fees this year: {fmt(total)} tagged, plus annual card fees {fmt(annual_fees)}.\n" + "\n".join(f"{e.spend_date:%-d %b} {e.description} {fmt(e.amount)}" for e in fees[-8:]))]


def calendar_month(m: int) -> str:
    import calendar
    return calendar.month_abbr[m]
