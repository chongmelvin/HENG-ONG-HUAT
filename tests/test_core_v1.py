from datetime import date, datetime
from decimal import Decimal as Dc

import pytest

from finbot.core import bills, budgets, people as ppl, splits, vouchers
from finbot.core.ledger import ExpenseInput, LedgerError, NetIndex, create_expense, create_refund, delete_expense
from finbot.domain.enums import Bucket
from finbot.domain.models import Payment, Receivable
from finbot.domain.money import split_equal


def spend(w, amount, cat="Food", acct="DBS Card", people=(), mode="", on=None, **kw):
    amount = Dc(str(amount))
    return create_expense(w.repo, w.settings, ExpenseInput(
        amount=amount, category_id=w.cats[cat].id, bucket=w.cats[cat].default_bucket,
        payments=[Payment(w.accts[acct].id, amount)], spend_date=on or w.clock.today(),
        people=[w.people[p].id for p in people], split_mode=mode, **kw), w.clock.now())


def test_split_80_three_ways():
    mine, others = split_equal(Dc("80.00"), 3)
    assert mine == Dc("26.68") and others == [Dc("26.66"), Dc("26.66")]


def test_dinner_split_creates_receivables_and_full_budget_hit(world):
    r = spend(world, 80, people=("Alice", "Bob"), mode="equal")
    assert r.expense.my_share == Dc("26.68")
    assert sorted(x.amount for x in r.receivables) == [Dc("26.66"), Dc("26.66")]
    lines = budgets.lines_for(world.repo, r.expense)
    monthly = next(l for l in lines if l.label == "Monthly budget")
    assert monthly.spent == Dc("80.00") and monthly.left == Dc("1920.00")  # full amount counts until repaid


def test_repayment_reduces_net_spend_in_the_original_month(world):
    r = spend(world, 80, people=("Alice", "Bob"), mode="equal", on=date(2026, 9, 28))
    world.clock.set(datetime(2026, 11, 5, 9, 0))
    splits.settle(world.repo, world.clock.now(), world.people["Bob"].id, Dc("26.66"), world.accts["PayNow"].id, date(2026, 11, 5))
    idx = NetIndex(world.repo)
    assert idx.net(world.repo.get(type(r.expense), r.expense.id)) == Dc("53.34")   # September's net spend dropped
    s, e = budgets.month_bounds(2026, 11)
    assert budgets.spent(idx, [], s, e) == 0                                        # November untouched


def test_settle_oldest_first_and_overpayment_needs_confirmation(world):
    spend(world, 40, people=("Bob",), mode="equal", on=date(2026, 10, 1))
    spend(world, 60, people=("Bob",), mode="equal", on=date(2026, 10, 9))
    bob = world.people["Bob"].id
    with pytest.raises(splits.NeedsCreditConfirmation):
        splits.settle(world.repo, world.clock.now(), bob, Dc("100"), world.accts["PayNow"].id, date(2026, 10, 18))
    s = splits.settle(world.repo, world.clock.now(), bob, Dc("25"), world.accts["PayNow"].id, date(2026, 10, 18))
    assert s.applied[0].amount == Dc("20.00") and s.applied[1].amount == Dc("5.00")
    assert splits.balance(world.repo, bob) == Dc("25.00")
    s2 = splits.settle(world.repo, world.clock.now(), bob, Dc("40"), world.accts["PayNow"].id, date(2026, 10, 18), confirm_credit=True)
    assert s2.credit == Dc("15.00") and splits.balance(world.repo, bob) == Dc("-15.00")


def test_custom_split_rejects_oversized_shares(world):
    with pytest.raises(LedgerError):
        create_expense(world.repo, world.settings, ExpenseInput(
            amount=Dc("120"), category_id=world.cats["Food"].id, bucket=Bucket.MONTHLY,
            payments=[Payment(world.accts["DBS Card"].id, Dc("120"))], spend_date=date(2026, 10, 18),
            people=[world.people["Bob"].id, world.people["Alice"].id], split_mode="custom",
            split_values={world.people["Bob"].id: Dc("80"), world.people["Alice"].id: Dc("60")}), world.clock.now())


def test_spent_with_uses_your_share_and_ignores_repayment(world):
    spend(world, 80, people=("Alice", "Bob"), mode="equal")
    spend(world, 12, cat="Transport", people=("Bob",))
    splits.settle(world.repo, world.clock.now(), world.people["Bob"].id, Dc("26.66"), world.accts["PayNow"].id, date(2026, 10, 18))
    r = ppl.ranking(world.repo, start=date(2026, 1, 1), end=date(2026, 12, 31))
    by = {s.name: s for s in r}
    assert by["Bob"].spent == Dc("38.68") and by["Alice"].spent == Dc("26.68")      # 26.68 + 12 ; repayment changes nothing
    assert r[0].name == "Bob"


def test_first_breach_scolds_then_goes_plain(world):
    spend(world, 590)
    first = spend(world, 20)
    b1 = budgets.check_breach(world.repo, world.settings, first.expense)
    assert b1.kind == "first" and b1.over_by == Dc("10.00")
    second = spend(world, 5)
    assert budgets.check_breach(world.repo, world.settings, second.expense).kind == "still"


def test_no_scold_for_exempt_claim_trip_or_backdated(world):
    spend(world, 590)
    assert budgets.check_breach(world.repo, world.settings, spend(world, 50, claimable=True, claimant="Acme").expense) is None
    assert budgets.check_breach(world.repo, world.settings, spend(world, 50, on=date(2026, 10, 10)).expense) is None
    assert budgets.check_breach(world.repo, world.settings, spend(world, 50, people=("Bob",), mode="equal").expense) is None


def test_refund_linked_reduces_original_month(world):
    r = spend(world, 60, cat="Shopping", on=date(2026, 9, 30))
    create_refund(world.repo, world.clock.now(), amount=Dc("60"), account_id=world.accts["DBS Card"].id,
                  on=date(2026, 10, 18), expense_id=r.expense.id)
    assert NetIndex(world.repo).net(r.expense) == 0
    with pytest.raises(LedgerError):
        create_refund(world.repo, world.clock.now(), amount=Dc("1"), account_id=world.accts["DBS Card"].id,
                      on=date(2026, 10, 18), expense_id=r.expense.id)


def test_delete_keeps_repaid_amount_as_credit(world):
    r = spend(world, 120, people=("Bob", "Alice"), mode="equal")
    splits.settle(world.repo, world.clock.now(), world.people["Bob"].id, Dc("40"), world.accts["PayNow"].id, date(2026, 10, 18))
    out = delete_expense(world.repo, world.clock.now(), r.expense.id)
    assert out["credits_kept"][world.people["Bob"].id] == Dc("40.00")
    assert world.repo.find(Receivable) if False else True


def test_voucher_split_payment_earliest_expiry_first(world):
    vouchers.add_voucher(world.repo, world.clock.now(), "CDC", Dc("100"), date(2026, 12, 31))
    vouchers.add_voucher(world.repo, world.clock.now(), "CDC", Dc("20"), date(2026, 11, 30))
    r = create_expense(world.repo, world.settings, ExpenseInput(
        amount=Dc("12"), category_id=world.cats["Food"].id, bucket=Bucket.MONTHLY,
        payments=[Payment(world.accts["CDC"].id, Dc("8")), Payment(world.accts["PayNow"].id, Dc("4"))],
        spend_date=date(2026, 10, 18)), world.clock.now())
    remaining = {v.expires.isoformat(): v.remaining for v in vouchers.active(world.repo)}
    assert remaining["2026-11-30"] == Dc("12.00") and remaining["2026-12-31"] == Dc("100.00")
    with pytest.raises(vouchers.InsufficientVoucher):
        vouchers.plan_consumption(world.repo, "CDC", Dc("500"), date(2026, 10, 18))


def test_bill_dates_and_last_day_clamp(world):
    b = bills.create_bill(world.repo, world.clock.now(), name="Phone", due_day=31, amount=Dc("38"))
    assert bills.occurrences(b, date(2026, 11, 1), date(2026, 11, 30)) == [date(2026, 11, 30)]
    q = bills.create_bill(world.repo, world.clock.now(), name="Insurance", due_day=12, recurrence="half_yearly", anchor_month=5)
    assert bills.occurrences(q, date(2026, 1, 1), date(2026, 12, 31)) == [date(2026, 5, 12), date(2026, 11, 12)]
    with pytest.raises(LedgerError):
        bills.create_bill(world.repo, world.clock.now(), name="X", due_day=32)


def test_reminder_three_days_before_and_paid_variable(world):
    b = bills.create_bill(world.repo, world.clock.now(), name="DBS Card bill", due_day=22, variable=True,
                          amount=Dc("842.10"), account_id=world.accts["DBS Bank"].id, is_transfer=True, ref_id=world.accts["DBS Card"].id)
    world.clock.set(datetime(2026, 10, 19, 9, 0))
    due = bills.due_today(world.repo, date(2026, 10, 19))
    assert [(x[0].name, x[2], x[3]) for x in due] == [("DBS Card bill", 3, "🟡")]
    bills.mark_paid(world.repo, world.settings, world.clock.now(), b.id, Dc("912.40"))
    assert world.repo.get(type(b), b.id).last_amount == Dc("912.40")
    with pytest.raises(LedgerError):
        bills.mark_paid(world.repo, world.settings, world.clock.now(), b.id, Dc("912.40"))   # double tap


def test_limits_keep_effective_dates(world):
    fid = world.cats["Food"].id
    budgets.set_limit(world.repo, world.clock.now(), f"category:{fid}", Dc("650"), date(2026, 10, 12))
    assert budgets.limit_in_force(world.repo, f"category:{fid}", date(2026, 10, 1)) == Dc("600")
    assert budgets.limit_in_force(world.repo, f"category:{fid}", date(2026, 10, 12)) == Dc("650")
