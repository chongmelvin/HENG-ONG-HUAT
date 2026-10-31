"""Report datasets (PRD 9.5). Everything is computed from configuration and data; nothing is hard-coded.

The Telegram message, the PDF and the calendar all read the same dataset object, so their numbers
always match. Sections that have no data are simply absent (`None` or empty), and the renderers
skip them.
"""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from ..core import bills as bills_core
from ..core import budgets, cards as cards_core, claims as claims_core, insurance as ins_core, items as items_core
from ..core import networth, people as people_core, savings, splits, vouchers
from ..core.ledger import NetIndex, active_expenses
from ..domain.enums import ACTIVE, AccountType, Bucket
from ..domain.models import (Account, Bill, Card, Category, Claim, Expense, Holding, Income, Item, Person, Receivable,
                             Refund, Settings, Settlement, Snapshot, Subscription, Trip)
from ..domain.money import ZERO
from ..v2 import investments, rewards, subscriptions as subs_core, trips as trips_core

D0 = Decimal("0")


def _sum(it) -> Decimal:
    return sum(it, ZERO)


def pct(a: Decimal, b: Decimal) -> float:
    return float(a / b * 100) if b else 0.0


# ======================================================================= monthly
@dataclass
class CatRow:
    category: Category
    bucket: Bucket
    net: Decimal
    entries: int
    limit: Optional[Decimal]

    @property
    def used_pct(self) -> float:
        return pct(self.net, self.limit) if self.limit else 0.0


@dataclass
class MonthlyData:
    year: int
    month: int
    generated: date
    settings: Settings
    income: Decimal = ZERO
    net_spend: Decimal = ZERO
    monthly_net: Decimal = ZERO
    yearly_net: Decimal = ZERO
    paid_total: Decimal = ZERO
    prev: dict = field(default_factory=dict)
    cats: list[CatRow] = field(default_factory=list)
    total_limit: Optional[Decimal] = None
    yearly_limit: Optional[Decimal] = None
    yearly_ytd: Decimal = ZERO
    yearly_pace: Optional[tuple] = None
    cumulative: list[tuple[int, Decimal]] = field(default_factory=list)
    yearly_items: list[Expense] = field(default_factory=list)
    day_totals: dict[int, Decimal] = field(default_factory=dict)
    bill_days: dict[int, str] = field(default_factory=dict)
    large_days: set[int] = field(default_factory=set)
    entries: list[Expense] = field(default_factory=list)
    groups: dict[str, Decimal] = field(default_factory=dict)
    people_rank: list = field(default_factory=list)
    accounts_paid: dict[str, Decimal] = field(default_factory=dict)
    locations: dict[str, Decimal] = field(default_factory=dict)
    tags: dict[str, Decimal] = field(default_factory=dict)
    top: list[Expense] = field(default_factory=list)
    unusual: list[str] = field(default_factory=list)
    owed_rows: list[dict] = field(default_factory=list)
    settled_rows: list[dict] = field(default_factory=list)
    claim_rows: list[Claim] = field(default_factory=list)
    card_rows: list = field(default_factory=list)
    policies: dict = field(default_factory=dict)
    subs: list[Subscription] = field(default_factory=list)
    fees: list[Expense] = field(default_factory=list)
    voucher_rows: list = field(default_factory=list)
    voucher_used: Decimal = ZERO
    items_month: list[Item] = field(default_factory=list)
    warranties: list = field(default_factory=list)
    trips_month: list = field(default_factory=list)
    nw: Optional["NetWorthData"] = None
    names: dict = field(default_factory=dict)
    trend6: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)

    @property
    def saved(self) -> Decimal:
        return self.income - self.net_spend

    @property
    def savings_rate(self) -> float:
        return pct(self.saved, self.income)

    @property
    def title(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"


@dataclass
class NetWorthData:
    snap: Snapshot
    prev: Optional[Snapshot]
    asset_types: list[tuple[str, Decimal]]
    liabilities: Decimal
    gross_assets: Decimal
    holdings: list
    trend: list[tuple[str, Decimal, Decimal]]       # (label, fixed, variable)
    bridge: Optional[networth.Bridge]
    runway: Optional[Decimal]
    fixed_rows: list[tuple[str, Decimal, Decimal]]  # (account, prev, cur)
    recon: Optional[networth.Reconciliation]
    liquid: Decimal

    @property
    def change(self) -> Decimal:
        return self.snap.net_worth - self.prev.net_worth if self.prev else ZERO


def _snapshot_for(repo, end: date) -> Optional[Snapshot]:
    s = [x for x in networth.snapshots(repo) if x.date <= end]
    return s[-1] if s else None


def _nw_data(repo, settings: Settings, start: date, end: date, avg_net: Decimal) -> Optional[NetWorthData]:
    snap = _snapshot_for(repo, end)
    if snap is None:
        return None
    prev = networth.previous_snapshot(repo, snap.date)
    accts = {a.id: a for a in repo.all(Account)}
    bal = {b.account_id: b.amount for b in snap.balances}
    bank = sum((v for k, v in bal.items() if accts.get(k) and accts[k].type == AccountType.BANK), ZERO)
    cash = sum((v for k, v in bal.items() if accts.get(k) and accts[k].type in (AccountType.CASH, AccountType.EWALLET)), ZERO)
    other_pos = sum((v for k, v in bal.items() if accts.get(k) and accts[k].type in (AccountType.BROKERAGE,) and v > 0), ZERO)
    liabilities = -sum((v for v in bal.values() if v < 0), ZERO)
    by_type = investments.by_type(repo)
    items = [("Bank deposits", bank), ("Cash and e-wallets", cash), ("Money owed to you", snap.owed)]
    if other_pos:
        items.append(("Other assets", other_pos))
    items += [(k, v) for k, v in by_type.items()]
    items = [(k, v) for k, v in items if v > 0]
    gross = _sum(v for _, v in items)
    trend = []
    snaps = networth.snapshots(repo)
    by_month: dict[tuple[int, int], Snapshot] = {}
    for s in snaps:
        by_month[(s.date.year, s.date.month)] = s
    y, m = end.year, end.month
    keys = []
    for _ in range(10):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    for k in reversed(keys):
        if k in by_month:
            s = by_month[k]
            trend.append((calendar.month_abbr[k[1]], s.fixed, s.variable))
    fixed_rows = []
    pb = {b.account_id: b.amount for b in prev.balances} if prev else {}
    for a in networth.fixed_accounts(repo):
        fixed_rows.append((a.name, pb.get(a.id, ZERO), bal.get(a.id, ZERO)))
    fixed_rows.append(("Money owed to you", prev.owed if prev else ZERO, snap.owed))
    recon = networth.reconcile(repo, settings, bal, snap.date) if not snap.balances == [] else None
    return NetWorthData(
        snap=snap, prev=prev, asset_types=items, liabilities=liabilities, gross_assets=gross,
        holdings=investments.table(repo, snap.date, month_start=prev.date if prev else None), trend=trend,
        bridge=networth.bridge(repo, settings, prev, snap) if prev else None,
        runway=networth.runway_months(repo, snap, avg_net), fixed_rows=fixed_rows, recon=recon,
        liquid=networth.liquid_assets(snap, repo))


def monthly(repo, settings: Settings, year: int, month: int, today: date) -> MonthlyData:
    s, e = budgets.month_bounds(year, month)
    idx = NetIndex(repo)
    exps = [x for x in active_expenses(repo) if s <= x.spend_date <= e]
    all_exps = active_expenses(repo)
    d = MonthlyData(year, month, today, settings, entries=sorted(exps, key=lambda x: (x.spend_date, x.description)))
    cats = {c.id: c for c in repo.all(Category)}
    accts = {a.id: a for a in repo.all(Account)}
    people = {p.id: p for p in repo.all(Person)}
    d.names = {"cats": cats, "accts": accts, "people": people}
    d.income = _sum(i.amount for i in repo.all(Income) if i.status == ACTIVE and s <= i.date <= e)
    d.monthly_net = _sum(idx.net(x) for x in exps if x.bucket == Bucket.MONTHLY)
    d.yearly_net = _sum(idx.net(x) for x in exps if x.bucket == Bucket.YEARLY)
    d.net_spend = d.monthly_net + d.yearly_net
    d.paid_total = _sum(x.amount for x in exps)
    # previous month
    py, pm = (year, month - 1) if month > 1 else (year - 1, 12)
    ps, pe = budgets.month_bounds(py, pm)
    pex = [x for x in all_exps if ps <= x.spend_date <= pe]
    pinc = _sum(i.amount for i in repo.all(Income) if i.status == ACTIVE and ps <= i.date <= pe)
    pnet = _sum(idx.net(x) for x in pex)
    d.prev = {"income": pinc, "net": pnet, "monthly": _sum(idx.net(x) for x in pex if x.bucket == Bucket.MONTHLY),
              "yearly": _sum(idx.net(x) for x in pex if x.bucket == Bucket.YEARLY), "has": bool(pex or pinc)}
    # budgets
    d.total_limit = budgets.limit_in_force(repo, budgets.TOTAL_M, e)
    d.yearly_limit = budgets.limit_in_force(repo, budgets.TOTAL_Y, e)
    grouped: dict[tuple[str, Bucket], list[Expense]] = defaultdict(list)
    for x in exps:
        grouped[(x.category_id, x.bucket)].append(x)
    for (cid, b), xs in grouped.items():
        c = cats.get(cid)
        if c:
            lim = budgets.limit_in_force(repo, f"category:{cid}", e) if b == Bucket.MONTHLY else None
            d.cats.append(CatRow(c, b, _sum(idx.net(x) for x in xs), len(xs), lim))
    for c in cats.values():          # categories with a limit but no spend still show in the budget table
        if c.status == ACTIVE and not any(r.category.id == c.id for r in d.cats):
            lim = budgets.limit_in_force(repo, f"category:{c.id}", e)
            if lim:
                d.cats.append(CatRow(c, Bucket.MONTHLY, ZERO, 0, lim))
    d.cats.sort(key=lambda r: -r.net)
    d.yearly_ytd = budgets.spent(idx, all_exps, date(year, 1, 1), e, bucket=Bucket.YEARLY)
    d.yearly_pace = budgets.yearly_pace(repo, min(e, today)) if d.yearly_limit else None
    by_day_m: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for x in exps:
        d.day_totals[x.spend_date.day] = d.day_totals.get(x.spend_date.day, ZERO) + idx.net(x)
        if x.bucket == Bucket.MONTHLY:
            by_day_m[x.spend_date.day] += idx.net(x)
        if x.amount >= 100:
            d.large_days.add(x.spend_date.day)
    run = ZERO
    for day in range(1, e.day + 1):
        run += by_day_m[day]
        d.cumulative.append((day, run))
    d.yearly_items = [x for x in exps if x.bucket == Bucket.YEARLY]
    for b in repo.find(Bill, status=ACTIVE):
        for dd in bills_core.occurrences(b, s, e):
            d.bill_days[dd.day] = b.name
    # who / where
    d.groups = people_core.group_totals(repo, start=s, end=e, net_of=idx.net)
    d.people_rank = people_core.ranking(repo, start=s, end=e, limit=8)
    for x in exps:
        for p in x.payments:
            n = accts[p.account_id].name if p.account_id in accts else "?"
            d.accounts_paid[n] = d.accounts_paid.get(n, ZERO) + p.amount
        if x.location:
            d.locations[x.location] = d.locations.get(x.location, ZERO) + idx.net(x)
        for t in x.tags:
            d.tags[t] = d.tags.get(t, ZERO) + idx.net(x)
    d.top = sorted(exps, key=lambda x: -x.amount)[:5]
    med: dict[str, float] = {}
    for cid in {x.category_id for x in exps}:
        vals = [float(x.amount) for x in exps if x.category_id == cid]
        med[cid] = statistics.median(vals) if vals else 0
    for x in d.top:
        m = med.get(x.category_id, 0)
        if m and float(x.amount) >= 5 * m and len([1 for y in exps if y.category_id == x.category_id]) >= 5:
            d.unusual.append(f"{x.description or 'An entry'} on {x.spend_date:%-d %b} ({x.amount}) was about {float(x.amount)/m:.0f}x your typical {cats[x.category_id].name} entry ({Decimal(str(m)).quantize(Decimal('0.01'))}).")
    # owed / claims
    for r in splits.open_receivables(repo):
        ex = repo.get(Expense, r.expense_id)
        d.owed_rows.append({"person": people[r.person_id].name if r.person_id in people else "?", "desc": ex.description if ex else "",
                            "date": r.created, "owed": r.outstanding, "days": (e - r.created).days})
    for st in repo.all(Settlement):
        if s <= st.date <= e:
            d.settled_rows.append({"date": st.date, "person": people[st.person_id].name if st.person_id in people else "?",
                                   "amount": st.amount, "account": accts[st.account_id].name if st.account_id in accts else "?"})
    d.claim_rows = claims_core.pending(repo)
    # cards etc (sections vanish when nothing is configured)
    d.card_rows = cards_core.summarise(repo, settings, e)
    d.policies = ins_core.summary(repo, e)
    d.subs = repo.find(Subscription, status=ACTIVE)
    d.fees = [x for x in exps if "Fees" in x.tags]
    d.voucher_rows = vouchers.summary(repo, e)
    d.voucher_used = _sum(u.amount for u in repo.all(vouchers.VoucherUsage) if s <= u.date <= e)
    d.items_month = [i for i in repo.all(Item) if s <= i.purchase_date <= e]
    d.warranties = items_core.expiring_within(repo, e, 60)
    d.trips_month = [trips_core.summary(repo, t.id) for t in repo.all(Trip) if t.start <= e and (t.end is None or t.end >= s)]
    snaps_this_year = [x for x in all_exps if x.spend_date.year == year and x.spend_date <= e]
    months_seen = {(x.spend_date.month) for x in snaps_this_year}
    nets = [_sum(idx.net(x) for x in snaps_this_year if x.spend_date.month == m) for m in sorted(months_seen)]
    avg = (_sum(nets) / len(nets)) if nets else ZERO
    y2, m2 = year, month
    for _ in range(6):
        ms, me = budgets.month_bounds(y2, m2)
        inc = _sum(i.amount for i in repo.all(Income) if i.status == ACTIVE and ms <= i.date <= me)
        net = _sum(idx.net(x) for x in all_exps if ms <= x.spend_date <= me)
        d.trend6.insert(0, (calendar.month_abbr[m2], inc, net))
        m2 -= 1
        if m2 == 0:
            y2, m2 = y2 - 1, 12
    d.nw = _nw_data(repo, settings, s, e, avg)
    return d


# ======================================================================= yearly
@dataclass
class YearlyData:
    year: int
    generated: date
    settings: Settings
    months: list[dict] = field(default_factory=list)       # per month: income, mon, yr, net, saved, nw
    income: Decimal = ZERO
    net_spend: Decimal = ZERO
    monthly_total: Decimal = ZERO
    yearly_total: Decimal = ZERO
    mon_matrix: dict[str, list[Decimal]] = field(default_factory=dict)
    yr_matrix: dict[str, list[Decimal]] = field(default_factory=dict)
    cat_limits: dict[str, list[Optional[Decimal]]] = field(default_factory=dict)
    total_limits: list[Optional[Decimal]] = field(default_factory=list)
    yearly_limit: Optional[Decimal] = None
    groups: dict[str, Decimal] = field(default_factory=dict)
    accounts: dict[str, Decimal] = field(default_factory=dict)
    people_rank: list = field(default_factory=list)
    trips: list = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    owed: dict = field(default_factory=dict)
    cards_value: list[dict] = field(default_factory=list)
    fees: dict[str, Decimal] = field(default_factory=dict)
    subs: tuple = (ZERO, ZERO)
    subs_list: list = field(default_factory=list)
    insurance: dict = field(default_factory=dict)
    vouchers: dict = field(default_factory=dict)
    nw_start: Optional[Snapshot] = None
    nw_end: Optional[Snapshot] = None
    market_gain: Decimal = ZERO
    contributions: Decimal = ZERO
    names: dict = field(default_factory=dict)

    @property
    def saved(self) -> Decimal:
        return self.income - self.net_spend

    @property
    def savings_rate(self) -> float:
        return pct(self.saved, self.income)

    def over_months(self) -> list[int]:
        return [i for i, m in enumerate(self.months) if self.total_limits[i] and m["mon"] > self.total_limits[i]]

    def cat_over(self, cat: str) -> list[int]:
        lims = self.cat_limits.get(cat, [])
        return [i for i, v in enumerate(self.mon_matrix.get(cat, [])) if lims and lims[i] and v > lims[i]]


def yearly(repo, settings: Settings, year: int, today: date) -> YearlyData:
    idx = NetIndex(repo)
    cats = {c.id: c for c in repo.all(Category)}
    accts = {a.id: a for a in repo.all(Account)}
    d = YearlyData(year, today, settings, names={"cats": cats, "accts": accts})
    exps = [x for x in active_expenses(repo) if x.spend_date.year == year]
    incomes = [i for i in repo.all(Income) if i.status == ACTIVE and i.date.year == year]
    snaps = {s.date.month: s for s in networth.snapshots(repo) if s.date.year == year}
    prev_nw = networth.previous_snapshot(repo, date(year, 1, 1))
    mon_cat: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO] * 12)
    yr_cat: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO] * 12)
    lim_cat: dict[str, list[Optional[Decimal]]] = {}
    for x in exps:
        n = idx.net(x)
        name = cats[x.category_id].name if x.category_id in cats else "?"
        (mon_cat if x.bucket == Bucket.MONTHLY else yr_cat)[name][x.spend_date.month - 1] += n
    for c in cats.values():
        if c.name in mon_cat and c.default_bucket == Bucket.MONTHLY:
            lim_cat[c.name] = [budgets.limit_in_force(repo, f"category:{c.id}", date(year, m, budgets.month_bounds(year, m)[1].day)) for m in range(1, 13)]
    d.mon_matrix, d.yr_matrix, d.cat_limits = dict(mon_cat), dict(yr_cat), lim_cat
    d.total_limits = [budgets.limit_in_force(repo, budgets.TOTAL_M, budgets.month_bounds(year, m)[1]) for m in range(1, 13)]
    d.yearly_limit = budgets.limit_in_force(repo, budgets.TOTAL_Y, date(year, 12, 31))
    for m in range(1, 13):
        mon = _sum(v[m - 1] for v in mon_cat.values())
        yrv = _sum(v[m - 1] for v in yr_cat.values())
        inc = _sum(i.amount for i in incomes if i.date.month == m)
        d.months.append({"income": inc, "mon": mon, "yr": yrv, "net": mon + yrv, "saved": inc - mon - yrv,
                         "nw": snaps[m].net_worth if m in snaps else None})
    d.income = _sum(m["income"] for m in d.months)
    d.monthly_total, d.yearly_total = _sum(m["mon"] for m in d.months), _sum(m["yr"] for m in d.months)
    d.net_spend = d.monthly_total + d.yearly_total
    d.groups = people_core.group_totals(repo, start=date(year, 1, 1), end=date(year, 12, 31), net_of=idx.net)
    for x in exps:
        for p in x.payments:
            n = accts[p.account_id].name if p.account_id in accts else "?"
            d.accounts[n] = d.accounts.get(n, ZERO) + p.amount
    d.people_rank = people_core.ranking(repo, start=date(year, 1, 1), end=date(year, 12, 31), limit=10)
    d.trips = [trips_core.summary(repo, t.id) for t in repo.all(Trip) if t.start.year == year]
    d.items = [i for i in repo.all(Item) if i.purchase_date.year == year]
    recs = [r for r in repo.all(Receivable) if r.created.year == year]
    d.owed = {"lent": _sum(r.amount for r in recs), "repaid": _sum(r.settled for r in recs), "outstanding": _sum(r.outstanding for r in repo.all(Receivable)),
              "claims_submitted": _sum(c.amount for c in repo.all(Claim)), "claims_paid": _sum(c.paid_amount for c in repo.all(Claim))}
    for c in repo.find(Card, status=ACTIVE):
        d.cards_value.append({"card": c, "spend": _sum(p.amount for x in exps for p in x.payments if p.account_id == c.account_id),
                              **rewards.annual_value_vs_fee(repo, c, year)})
    d.fees = {"Fees tagged": _sum(idx.net(x) for x in exps if "Fees" in x.tags),
              "Annual card fees": _sum(c["fee"] for c in d.cards_value)}
    d.subs, d.subs_list = subs_core.totals(repo), repo.find(Subscription, status=ACTIVE)
    d.insurance = ins_core.summary(repo, date(year, 12, 31))
    expired = [v for v in repo.all(vouchers.Voucher) if v.status == "expired" and v.expires.year == year]
    d.vouchers = {"received": _sum(v.original for v in repo.all(vouchers.Voucher) if (v.issued or v.expires).year == year),
                  "used": _sum(u.amount for u in repo.all(vouchers.VoucherUsage) if u.date.year == year),
                  "expired": _sum(v.remaining for v in expired)}
    d.nw_start = prev_nw or (snaps[min(snaps)] if snaps else None)
    d.nw_end = snaps[max(snaps)] if snaps else None
    if d.nw_start and d.nw_end and d.nw_start.id != d.nw_end.id:
        d.contributions = networth._contributions(repo, d.nw_start.date, d.nw_end.date)
        d.market_gain = (d.nw_end.variable - d.nw_start.variable) - d.contributions
    return d
