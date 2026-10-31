from datetime import date, datetime
from decimal import Decimal as Dc

import pytest

from finbot.core import cards, claims, insurance, items, networth, pin, savings
from finbot.core.ledger import ExpenseInput, LedgerError, NetIndex, create_expense, create_income, create_transfer
from finbot.domain.enums import AssetGroup, Bucket, ClaimStatus, RewardType
from finbot.domain.models import Account, Card, Payment, Snapshot
from finbot.domain.enums import AccountType
from finbot.core.ids import new_id


def snap_balances(w, **by_name):
    out = {}
    for a in networth.fixed_accounts(w.repo):
        out[a.id] = Dc(str(by_name.get(a.name.replace(" ", "_"), 0)))
    return out


def test_first_snapshot_sets_opening_and_then_reconciles(world):
    w = world
    w.clock.set(datetime(2026, 10, 1, 9, 0))
    first = {a.id: Dc("1000") for a in networth.fixed_accounts(w.repo)}
    first[w.accts["DBS Card"].id] = Dc("-200")
    s1, r1 = networth.take_snapshot(w.repo, w.settings, w.clock.now(), first)
    assert r1.first and w.settings.first_snapshot_date == date(2026, 10, 1)
    # a month of activity
    w.clock.set(datetime(2026, 10, 25, 9, 0))
    create_income(w.repo, w.clock.now(), amount=Dc("3620"), source="Salary", account_id=w.accts["DBS Bank"].id, on=date(2026, 10, 25))
    create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("45"), category_id=w.cats["Food"].id, bucket=Bucket.MONTHLY,
                   payments=[Payment(w.accts["DBS Card"].id, Dc("45"))], spend_date=date(2026, 10, 20)), w.clock.now())
    create_transfer(w.repo, w.clock.now(), from_account=w.accts["DBS Bank"].id, to_account=w.accts["Cash"].id, amount=Dc("200"), on=date(2026, 10, 21))
    entered = dict(first)
    entered[w.accts["DBS Bank"].id] = Dc("1000") + Dc("3620") - Dc("200")
    entered[w.accts["Cash"].id] = Dc("1200")
    entered[w.accts["DBS Card"].id] = Dc("-245")
    s2, r2 = networth.take_snapshot(w.repo, w.settings, w.clock.now(), entered)
    assert r2.gap == 0 and r2.icon == "✅"


def test_gap_is_found_per_account_and_written_off_after_review(world):
    w = world
    first = {a.id: Dc("500") for a in networth.fixed_accounts(w.repo)}
    networth.take_snapshot(w.repo, w.settings, w.clock.now(), first, on=date(2026, 10, 1))
    entered = dict(first)
    entered[w.accts["Cash"].id] = Dc("470")
    entered[w.accts["PayLah"].id] = Dc("492.60")
    s, r = networth.take_snapshot(w.repo, w.settings, w.clock.now(), entered, on=date(2026, 10, 31))
    assert r.gap == Dc("-37.40") and r.icon == "🔴"
    assert [m.account.name for m in r.movers] == ["Cash", "PayLah"]
    entered2 = dict(first)
    entered2[w.accts["Cash"].id] = Dc("470")
    s2, r2 = networth.take_snapshot(w.repo, w.settings, w.clock.now(), entered2, write_off=True, on=date(2026, 10, 31))
    # after the write-off the books agree with what you typed
    assert networth.reconcile(w.repo, w.settings, entered2, date(2026, 10, 31)).gap == 0


def test_missing_balance_is_refused(world):
    with pytest.raises(LedgerError):
        networth.take_snapshot(world.repo, world.settings, world.clock.now(), {})


def test_money_owed_counts_as_fixed_asset(world):
    w = world
    create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("80"), category_id=w.cats["Food"].id, bucket=Bucket.MONTHLY,
                   payments=[Payment(w.accts["DBS Card"].id, Dc("80"))], spend_date=date(2026, 10, 18),
                   people=[w.people["Alice"].id, w.people["Bob"].id], split_mode="equal"), w.clock.now())
    assert networth.owed_total(w.repo) == Dc("53.32")


def test_claim_lifecycle(world):
    w = world
    r = create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("25"), category_id=w.cats["Transport"].id, bucket=Bucket.MONTHLY,
                       payments=[Payment(w.accts["DBS Card"].id, Dc("25"))], spend_date=date(2026, 10, 19), claimable=True, claimant="Acme"), w.clock.now())
    batch, todo = claims.submit(w.repo, w.clock.now(), "acme")
    assert todo[0].status == ClaimStatus.SUBMITTED
    with pytest.raises(claims.ExcessPayout):
        claims.pay(w.repo, w.clock.now(), "acme", Dc("40"), w.accts["DBS Bank"].id)
    claims.pay(w.repo, w.clock.now(), "acme", Dc("25"), w.accts["DBS Bank"].id)
    assert NetIndex(w.repo).net(r.expense) == 0                     # payout lowers net spend, and is not income


def test_rejected_claim_stays_personal_spending(world):
    w = world
    r = create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("25"), category_id=w.cats["Transport"].id, bucket=Bucket.MONTHLY,
                       payments=[Payment(w.accts["DBS Card"].id, Dc("25"))], spend_date=date(2026, 10, 19), claimable=True, claimant="Acme"), w.clock.now())
    claims.reject(w.repo, w.clock.now(), r.claim.id)
    assert NetIndex(w.repo).net(r.expense) == Dc("25") and not claims.pending(w.repo)


def test_big_ticket_prompt_rules_and_warranty(world):
    w = world
    r = create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("399"), category_id=w.cats["Shopping"].id, bucket=Bucket.YEARLY,
                       payments=[Payment(w.accts["DBS Card"].id, Dc("399"))], spend_date=date(2026, 10, 18)), w.clock.now())
    assert items.should_prompt(w.settings, r.expense, False) and not items.should_prompt(w.settings, r.expense.__class__(**{**r.expense.__dict__, "amount": Dc("59")}), False)
    assert items.should_prompt(w.settings, r.expense.__class__(**{**r.expense.__dict__, "amount": Dc("59")}), True)
    it = items.create_item(w.repo, w.clock.now(), r.expense, "Standing desk", 24)
    assert it.warranty_end == date(2028, 10, 18)
    assert items.find_item(w.repo, "desk").id == it.id


def test_insurance_summary_and_policy_number_truncated(world):
    w = world
    insurance.add_policy(w.repo, w.clock.now(), policy_number="P1234567890", insurer="Prudential", product="Life", type="Life",
                         premium=Dc("900"), frequency="half_yearly", next_due=date(2026, 11, 12))
    insurance.add_policy(w.repo, w.clock.now(), insurer="Shield", product="Plan", type="Hospitalisation", premium=Dc("1200"),
                         frequency="yearly", next_due=date(2027, 1, 5))
    s = insurance.summary(w.repo, date(2026, 10, 19))
    assert s["annual"] == Dc("3000") and s["monthly"] == Dc("250.00")
    assert [p.insurer for p, _ in s["due_90"]] == ["Prudential", "Shield"]
    assert w.repo.all(type(s["policies"][0]))[0].policy_last4 == "7890"


def test_card_cycle_and_statement_gap(world):
    w = world
    card = Card(id=new_id("cd"), account_id=w.accts["DBS Card"].id, bank="DBS", name="Altitude", last4="4444",
                statement_day=15, due_day=22, limit=Dc("5000"), reward_type=RewardType.MILES)
    w.repo.add(card)
    assert cards.cycle_bounds(card, date(2026, 10, 18)) == (date(2026, 10, 16), date(2026, 11, 15))
    create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("842.10"), category_id=w.cats["Shopping"].id, bucket=Bucket.MONTHLY,
                   payments=[Payment(card.account_id, Dc("842.10"))], spend_date=date(2026, 10, 17)), w.clock.now())
    assert cards.statement_gap(w.repo, card, Dc("1042.10"), date(2026, 10, 18)) == Dc("200.00")


def test_pin_rules_lockout_and_unlock(world):
    s = world.settings
    for bad in ("123456", "111111", "48291"):
        with pytest.raises(pin.PinError):
            pin.set_pin(s, bad)
    pin.set_pin(s, "482913")
    g = pin.PinGate()
    now = datetime(2026, 10, 18, 12, 0)
    assert g.try_pin(s, "000000", now) == (False, "2")
    assert g.try_pin(s, "000001", now) == (False, "1")
    assert g.try_pin(s, "000002", now) == (False, "locked")
    assert g.try_pin(s, "482913", now) == (False, "locked")           # even the right PIN is refused while locked
    from datetime import timedelta
    later = now + timedelta(minutes=16)
    assert g.try_pin(s, "482913", later)[0] and g.is_unlocked(later) and not g.is_unlocked(later + timedelta(minutes=16))


def test_savings_buckets_float_and_warn(world):
    w = world
    b = savings.create_bucket(w.repo, "House", Dc("50000"))
    savings.allocate(w.repo, b.id, Dc("2000"), date(2026, 10, 1))
    assert savings.balance(w.repo, b.id) == Dc("2000.00")
    assert savings.check_total(w.repo, Dc("1500")) == Dc("500.00")
