"""Generate a realistic year of demo data (used by tests, README screenshots and `python -m finbot.demo`)."""
from __future__ import annotations

import random
from datetime import date, datetime
from decimal import Decimal as Dc

from .clock import FixedClock
from .core import bills, claims, networth, savings, vouchers
from .core.ledger import ExpenseInput, create_expense, create_income, create_transfer
from .domain.enums import AccountType, Bucket, HoldingType, RewardType
from .domain.models import Card, CardRule, Payment, Subscription
from .core.ids import new_id
from .seed import demo_world
from .storage.base import MemoryRepo
from .v2 import investments, rewards


def build_demo(year: int = 2026, upto_month: int = 10, seed: int = 7):
    rnd = random.Random(seed)
    repo = MemoryRepo()
    clock = FixedClock(datetime(year, 1, 1, 9, 0))
    settings, cats, accts, people = demo_world(repo, clock.now())
    settings.places = ["Orchard", "Tampines", "Ang Mo Kio"]
    repo.update(settings)
    # opening snapshot on 1 Jan
    first = {a.id: Dc("0") for a in networth.fixed_accounts(repo)}
    first[accts["DBS Bank"].id], first[accts["Cash"].id], first[accts["PayLah"].id] = Dc("20000"), Dc("300"), Dc("100")
    investments.add_holding(repo, clock.now(), name="Global equity ETF", symbol="VWRA", type=HoldingType.ETF, units=Dc("100"), cost_basis=Dc("8000"))
    investments.add_holding(repo, clock.now(), name="Bitcoin", symbol="bitcoin", type=HoldingType.CRYPTO, units=Dc("0.1"), cost_basis=Dc("5000"))
    prices = investments.StaticPrices({"VWRA": Dc("85"), "bitcoin": Dc("60000")})
    investments.refresh_prices(repo, prices, date(year, 1, 1))
    networth.take_snapshot(repo, settings, clock.now(), first, on=date(year, 1, 1))
    card = Card(id=new_id("cd"), account_id=accts["DBS Card"].id, bank="DBS", name="Altitude", last4="4444", statement_day=15, due_day=22,
                limit=Dc("5000"), annual_fee=Dc("192"), fee_month=3, reward_type=RewardType.MILES, value_per_unit=Dc("0.015"))
    repo.add(card)
    repo.add(CardRule(id=new_id("cr"), card_id=card.id, category="general", rate=Dc("1.2"), fallback_rate=Dc("1.2"), last_verified=date(year, 1, 1)))
    subs = [("Video streaming", "17.98"), ("Music streaming", "9.90")]
    for n, a in subs:
        repo.add(Subscription(id=new_id("su"), name=n, amount=Dc(a), next_renewal=date(year, upto_month, 14)))
    ppl = list(people.values())
    for m in range(1, upto_month + 1):
        clock.set(datetime(year, m, 25, 9, 0))
        create_income(repo, clock.now(), amount=Dc("3620"), source="Salary", account_id=accts["DBS Bank"].id, on=date(year, m, 25), recurring=True)
        for day in range(1, 28):
            if rnd.random() < 0.55:
                cat = rnd.choices(["Food", "Groceries", "Transport", "Shopping", "Fun"], [50, 12, 25, 6, 7])[0]
                amt = Dc(str(round(rnd.uniform(3, 25 if cat in ("Food", "Transport") else 80), 2)))
                who = rnd.choice([[], [], [], [ppl[0]], [ppl[1]], [ppl[2]]])
                create_expense(repo, settings, ExpenseInput(
                    amount=amt, category_id=cats[cat].id, bucket=cats[cat].default_bucket, payments=[Payment(rnd.choice([accts["DBS Card"], accts["PayLah"], accts["Cash"]]).id, amt)],
                    spend_date=date(year, m, day), description=cat.lower(), people=[p.id for p in who], location=rnd.choice(settings.places)), clock.now())
        create_expense(repo, settings, ExpenseInput(amount=Dc("38"), category_id=cats["Bills"].id, bucket=Bucket.MONTHLY, payments=[Payment(accts["DBS Card"].id, Dc("38"))],
                                                    spend_date=date(year, m, 23), description="Phone bill", tags=["Recurring"]), clock.now())
        if m in (3, 10):
            create_expense(repo, settings, ExpenseInput(amount=Dc("560"), category_id=cats["Travel"].id, bucket=Bucket.YEARLY, payments=[Payment(accts["DBS Card"].id, Dc("560"))],
                                                        spend_date=date(year, m, 5), description="Flights deposit"), clock.now())
        create_transfer(repo, clock.now(), from_account=accts["DBS Bank"].id, to_account=accts["Cash"].id, amount=Dc("100"), on=date(year, m, 3))
        if m == upto_month:   # a few extras so every report section has something
            vouchers.add_voucher(repo, clock.now(), "CDC", Dc("92"), date(year, 12, 31))
            claims_exp = create_expense(repo, settings, ExpenseInput(amount=Dc("25"), category_id=cats["Transport"].id, bucket=Bucket.MONTHLY, payments=[Payment(accts["DBS Card"].id, Dc("25"))],
                                                                     spend_date=date(year, upto_month, 19), description="Taxi", claimable=True, claimant="Acme"), clock.now())
            create_expense(repo, settings, ExpenseInput(amount=Dc("120"), category_id=cats["Food"].id, bucket=Bucket.MONTHLY, payments=[Payment(accts["DBS Card"].id, Dc("120"))],
                                                        spend_date=date(year, upto_month, 11), description="Dinner", people=[ppl[0].id, ppl[1].id], split_mode="equal"), clock.now())

        # month-end snapshot with exactly the computed balances so the demo reconciles
        end = date(year, m, 28)
        bal = networth.computed_balances(repo, settings, end)
        entered = {a.id: bal[a.id] for a in networth.fixed_accounts(repo)}
        if m > 1:
            investments.refresh_prices(repo, investments.StaticPrices({"VWRA": Dc(str(85 + m)), "bitcoin": Dc(str(60000 + m * 1500))}), end)
        networth.take_snapshot(repo, settings, clock.now(), entered, on=end)
    return type("Demo", (), dict(repo=repo, settings=settings, cats=cats, accts=accts, people=people, clock=clock))


if __name__ == "__main__":
    from .reports import dataset, monthly_pdf, yearly_pdf
    demo = build_demo()
    today = date(2026, 10, 31)
    open("demo-monthly.pdf", "wb").write(monthly_pdf.render(dataset.monthly(demo.repo, demo.settings, 2026, 10, today)))
    open("demo-yearly.pdf", "wb").write(yearly_pdf.render(dataset.yearly(demo.repo, demo.settings, 2026, today)))
    print("wrote demo-monthly.pdf and demo-yearly.pdf")
