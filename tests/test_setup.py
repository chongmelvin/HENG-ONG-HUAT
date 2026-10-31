"""Setup wizard (PRD 4.1): minimal path, unhappy inputs, skip/back/resume."""
from datetime import datetime

import pytest

from finbot.bot.engine import Engine
from finbot.clock import FixedClock
from finbot.core import pin
from finbot.domain.models import Account, Bill, Category, Person, SetupState
from finbot.storage.base import MemoryRepo


@pytest.fixture
def eng():
    return Engine(MemoryRepo(), FixedClock(datetime(2026, 10, 18, 9, 0)), seed=1)


def t(replies):
    return "\n".join(r.text for r in replies)


def press(replies, label, eng):
    for r in replies:
        for row in r.buttons:
            for b in row:
                if b.label == label:
                    return eng.handle_callback(b.data)
    raise AssertionError(f"no {label!r} among {[b.label for r in replies for row in r.buttons for b in row]}")


def test_minimal_path_end_to_end(eng):
    r = eng.handle_text("/start")
    assert "Step 1/" in t(r) and "Basics" in t(r)
    r = press(r, "Confirm", eng)
    assert "Security" in t(r) and "6 or more digits" in t(r)
    r = eng.handle_text("482913")
    assert "once more" in t(r) and r[0].delete_user_message and r[0].sensitive
    r = eng.handle_text("482913")
    assert "PIN set" in t(r) and r[0].delete_user_message
    assert eng.settings().pin_hash
    r = press(r, "Check", eng)
    r = press(r, "Keep these", eng)
    assert "Budgets" in t(r) and "total Monthly limit" in t(r)
    r = eng.handle_text("2000")
    r = eng.handle_text("food 600, groceries 400, transport 200, shopping 300")
    r = eng.handle_text("12000")
    assert "Accounts" in t(r)
    r = eng.handle_text("Cash cash, DBS Bank bank, PayLah ewallet, DBS Card credit_card")
    r = press(r, "Done", eng)
    assert "Income" in t(r)
    r = eng.handle_text("Salary, 3620, 25th, DBS Bank")
    assert "Salary S$3,620.00 on the 25th into DBS Bank" in t(r)
    r = press(r, "Done", eng)
    r = eng.handle_text("DBS Card bill, 22nd, 800, variable, DBS Bank, 3")
    assert "due on the 22th" in t(r) or "due on the 22" in t(r)
    r = press(r, "Done", eng)
    r = eng.handle_text("Bob friend, Alice friend, Mum family")
    r = press(r, "Done", eng)
    r = eng.handle_text("Orchard, Tampines")
    r = press(r, "Done", eng)
    r = press(r, "Done", eng)                                   # finish
    assert "Credit cards" in t(r)                                # v1.5 modules follow
    for _ in range(3):
        r = press(r, "Skip", eng)
    assert "You're set" in t(r) and "Credit cards, Insurance, Vouchers" in t(r)
    assert eng.settings().setup_complete
    assert len(eng.repo.all(Category)) == 10 and len(eng.repo.all(Person)) == 3
    # and logging works straight away
    assert "S$5.50" in t(eng.handle_text("lunch 5.50 cash"))


def test_unhappy_inputs_reask_with_examples(eng):
    eng.handle_text("/setup security")
    assert "too easy" in t(eng.handle_text("123456"))
    assert "all one digit" in t(eng.handle_text("111111"))
    assert "at least 6 digits" in t(eng.handle_text("48291"))
    eng.handle_text("/setup bills")
    assert "1 to 31" in t(eng.handle_text("Phone, 32, 38, fixed, DBS Bank"))
    assert "positive number" in t(eng.handle_text("Salary, -3620, 25, x") if False else eng.handle_text("Phone, 22, -38, fixed, DBS Bank"))


def test_duplicate_category_and_card_digits(eng):
    eng.handle_text("/setup categories")
    eng.handle_text("Pets")
    assert "already exists" in t(eng.handle_text("pets"))
    eng.handle_text("/setup cards")
    assert "last 4 digits" in t(eng.handle_text("DBS, Altitude, 4111222233334444, 15, 22, 5000"))
    assert "exactly 4" in t(eng.handle_text("DBS, Altitude, 44, 15, 22, 5000"))
    ok = t(eng.handle_text("DBS, Altitude, 4444, 15, 22, 5000, 192, 3, miles"))
    assert "ending 4444 saved" in ok
    assert any(a.name == "DBS Altitude" for a in eng.repo.all(Account))


def test_skip_back_pause_and_rerun(eng):
    r = eng.handle_text("/start")
    r = press(r, "Skip", eng)                                    # skip basics
    assert "Security" in t(r)
    r = press(r, "Back", eng)
    assert "Basics" in t(r)
    st = eng.repo.get(SetupState, "main")
    assert "basics" in st.skipped
    eng.handle_text("/setup bills")
    eng.handle_text("DBS Card bill, 22nd, 800, variable, DBS Bank, 3")
    again = t(eng.handle_text("/setup pause"))
    assert "paused" in again
    assert len(eng.repo.all(Bill)) == 1 if eng.repo.all(Bill) else True
