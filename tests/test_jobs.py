from datetime import date, datetime
from decimal import Decimal as Dc

import pytest

from finbot.bot.engine import Engine
from finbot.core import bills, vouchers
from finbot.core.ledger import ExpenseInput, create_expense
from finbot.domain.enums import Bucket
from finbot.domain.models import Bill, Payment
from finbot.v2 import trips


@pytest.fixture
def eng(world):
    return Engine(world.repo, world.clock, seed=1), world


def t(rs):
    return "\n".join(r.text for r in rs)


def test_bill_reminder_three_days_before_and_only_once_per_day(eng):
    e, w = eng
    bills.create_bill(w.repo, w.clock.now(), name="DBS Card bill", due_day=22, amount=Dc("842.10"), variable=True)
    w.clock.set(datetime(2026, 10, 19, 9, 0))
    first = e.run_jobs()
    assert "🟡" in t(first) and "DBS Card bill is due Thu 22 Oct (in 3 days)" in t(first) and "Reminder ah:" in t(first)
    assert [b.label for b in first[0].buttons[0]] == ["Paid", "Snooze", "Skip"]
    assert e.run_jobs() == []                                     # restart at 9:00 must not resend


def test_bill_due_today_is_red_and_overdue_stays_red(eng):
    e, w = eng
    bills.create_bill(w.repo, w.clock.now(), name="Phone", due_day=18, amount=Dc("38"))
    out = t(e.run_jobs())
    assert "🔴" in out and "due Sun 18 Oct (today)" in out
    w.clock.set(datetime(2026, 10, 20, 9, 0))
    assert "overdue" in t(e.run_jobs())


def test_voucher_alerts_at_60_30_7(eng):
    e, w = eng
    vouchers.add_voucher(w.repo, w.clock.now(), "CDC", Dc("92"), date(2026, 12, 17))       # 60 days from 18 Oct
    out = t(e.run_jobs())
    assert "CDC voucher S$92.00 expiring in 60 days" in out and "🟡" in out


def test_chase_after_seven_days_then_weekly(eng):
    e, w = eng
    create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("80"), category_id=w.cats["Food"].id, bucket=Bucket.MONTHLY,
                   payments=[Payment(w.accts["DBS Card"].id, Dc("80"))], spend_date=date(2026, 10, 11),
                   people=[w.people["Bob"].id], split_mode="equal"), w.clock.now())
    out = t(e.run_jobs())                                         # 7 days after 11 Oct
    assert "Bob still never pay S$40.00 leh. 7 days already." in out and "🟡" in out
    w.clock.set(datetime(2026, 10, 19, 9, 0))
    assert "never pay" not in t(e.run_jobs())                    # not every day
    w.clock.set(datetime(2026, 10, 25, 9, 0))
    assert "14 days" in t(e.run_jobs())                          # weekly after that


def test_recurring_income_asks_before_posting(eng):
    e, w = eng
    w.clock.set(datetime(2026, 10, 25, 9, 0))
    w.repo.add(Bill(id="bi_inc", name="Salary (income)", due_day=25, amount=Dc("3620"), account_id=w.accts["DBS Bank"].id, kind="income", lead_days=0, created=date(2026, 10, 1)))
    r = e.run_jobs()
    assert "Salary S$3,620.00 is expected today into DBS Bank" in t(r)
    assert not w.repo.all(type(w.repo.all(Bill)[0])) is None
    from finbot.domain.models import Income
    assert w.repo.all(Income) == []                              # nothing posted silently
    out = t(e.handle_callback("x:incconfirm:bi_inc"))
    assert "Saved income: S$3,620.00" in out and len(w.repo.all(Income)) == 1


def test_first_of_month_sends_report_and_review_prompt(eng):
    e, w = eng
    w.clock.set(datetime(2026, 11, 1, 9, 0))
    create_expense(w.repo, w.settings, ExpenseInput(amount=Dc("8"), category_id=w.cats["Food"].id, bucket=Bucket.MONTHLY,
                   payments=[Payment(w.accts["Cash"].id, Dc("8"))], spend_date=date(2026, 10, 5)), w.clock.now())
    out = e.run_jobs()
    assert any(r.files and r.files[0][1][:4] == b"%PDF" for r in out)
    assert any("Monthly review" in r.text for r in out)


def test_open_ended_trip_asks_still_on(eng):
    e, w = eng
    trips.start_trip(w.repo, w.settings, w.clock.now(), name="Japan", start=date(2026, 10, 11), currency="JPY")
    assert "Still on the Japan trip?" in t(e.run_jobs())
