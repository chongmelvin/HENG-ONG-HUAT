"""End-to-end flows, mirroring the sample chats and test cases (no Telegram involved)."""
from datetime import date, datetime
from decimal import Decimal as Dc
from types import SimpleNamespace as NS

import pytest

from finbot.bot.engine import Engine
from finbot.core import networth, pin
from finbot.domain.models import Category, Expense, Person, Settings
from finbot.v2 import fx as fxm, investments


@pytest.fixture
def eng(world):
    world.settings.places = ["Orchard", "Tampines"]
    world.repo.update(world.settings)
    e = Engine(world.repo, world.clock, seed=1)
    e.w = world
    return e


def texts(replies):
    return "\n".join(r.text for r in replies)


def press(eng, replies, label):
    for r in replies:
        for row in r.buttons:
            for b in row:
                if b.label == label:
                    return eng.handle_callback(b.data)
    raise AssertionError(f"no button {label!r} in {[b.label for r in replies for row in r.buttons for b in row]}")


def test_unknown_word_asks_category_then_remembers(eng):
    r = eng.handle_text("bubble tea 6.20 paylah")
    assert "Which category" in texts(r)
    r2 = press(eng, r, "Food")
    out = texts(r2)
    assert "S$6.20" in out and "Food" in out and "🟢 Monthly budget left" in out
    again = eng.handle_text("bubble tea 6.20 paylah")                 # now remembered (and not a duplicate: wait for window)
    assert "Which category" not in texts(again)


def test_budget_lines_and_people(eng):
    out = texts(eng.handle_text("grab 12 cc with bob orchard"))
    assert "Transport" in out and "Bob" in out and "🟢 Monthly budget left: S$1,988 of S$2,000" in out
    assert "🟢 Transport left: S$188 of S$200." in out
    out2 = texts(eng.handle_text("grab 170 cc"))                      # 182 of 200 = 91% used -> yellow
    assert "🟡 Transport left: S$18 of S$200 (91% used)" in out2


def test_missing_amount_then_answer(eng):
    r = eng.handle_text("lunch paylah")
    assert "cannot catch the amount" in texts(r)
    out = texts(eng.handle_text("5.5"))
    assert "S$5.50" in out and "Food" in out


def test_unknown_account_offers_add(eng):
    r = eng.handle_text("lunch 8 grabpay")
    assert 'I don\'t know an account called "grabpay"' in texts(r)
    out = texts(press(eng, r, 'Add "Grabpay"'))
    assert "Grabpay" in out and "S$8.00" in out


def test_two_amounts_zero_and_future_date(eng):
    r = eng.handle_text("dinner 45 55 cc")
    assert "two amounts" in texts(r)
    assert "S$45" in texts(press(eng, r, "S$45"))
    r = eng.handle_text("25 dec lunch 6 cash")
    assert "future" in texts(r) and "25 Dec 2025" in texts(r)
    assert "Cancelled" in texts(press(eng, r, "Cancel"))


def test_zero_or_negative_amount_is_refused(eng):
    out = texts(eng.handle_text("lunch -5 cash"))
    assert "S$" not in out or "more than 0" in out or "cannot catch the amount" in out


def test_duplicate_warning_and_large_confirm(eng):
    eng.handle_text("lunch 4 cash")
    again = eng.handle_text("lunch 4 cash")
    assert "looks the same" in texts(again)
    big = press(eng, eng.handle_text("laptop 25000 cc"), "Shopping")
    big = press(eng, big, "Yearly")
    assert "above S$5,000" in texts(big)
    assert "S$25,000.00" in texts(press(eng, big, "Confirm"))


def test_equal_split_of_80_between_three(eng):
    out = texts(eng.handle_text("dinner 80 cc split alice bob"))
    assert "your share S$26.68" in out and "Alice owes S$26.66" in out and "Bob owes S$26.66" in out
    assert "🟢 Monthly budget left: S$1,920 of S$2,000" in out           # full amount counts until repaid
    owed = texts(eng.handle_text("/owed"))
    assert "Bob" in owed and "Total owed to you: S$53.32" in owed


def test_settle_partial_overpay_and_late_repayment(eng):
    eng.handle_text("dinner 80 cc split alice bob")
    out = texts(eng.handle_text("/settle bob 26.66 paynow"))
    assert "Recorded S$26.66 from Bob" in out and "Bob owes nothing" in out
    r = eng.handle_text("/settle alice 100 paynow")
    assert "only owes S$26.66" in texts(r)
    done = texts(press(eng, r, "Yes"))
    assert "Alice" in done and "owe Alice S$73.34" in done


def test_with_ranking_uses_your_share(eng):
    eng.handle_text("dinner 80 cc split alice bob")
    eng.handle_text("/settle bob 26.66 paynow")
    out = texts(eng.handle_text("/with bob"))
    assert "S$26.68" in out and "1 outings" in out
    assert "1 Bob" in texts(eng.handle_text("/with")) or "1 Alice" in texts(eng.handle_text("/with"))


def test_first_breach_scolds_once(eng):
    eng.handle_text("lunch 590 cash")
    first = texts(eng.handle_text("lunch 20 cash"))
    assert "🔴" in first and "over by S$10" in first and ("Aiyo" in first or "Wah" in first)
    second = texts(eng.handle_text("lunch 5 cash"))
    assert "still over by S$15" in second and "Aiyo" not in second


def test_persona_off_is_plain(eng):
    eng.handle_callback("x:persona:off")
    eng.handle_text("lunch 590 cash")
    out = texts(eng.handle_text("lunch 20 cash"))
    assert "over its limit by S$10" in out and "Aiyo" not in out and "lah" not in out


def test_indicators_off_removes_lights_but_keeps_numbers(eng):
    eng.handle_callback("x:indicators:off")
    out = texts(eng.handle_text("lunch 8 cash"))
    assert "Monthly budget left: S$1,992 of S$2,000" in out and not any(c in out for c in "🟢🟡🔴")


def test_undo_restore_and_delete_with_links(eng):
    eng.handle_text("lunch 8 cash")
    r = eng.handle_text("/undo")
    assert "Removed your last entry" in texts(r)
    press(eng, r, "Restore")
    assert len([e for e in eng.repo.all(Expense) if e.status == "active"]) == 1


def test_update_id_is_processed_once(eng):
    first = eng.handle_text("lunch 8 cash", update_id=77)
    second = eng.handle_text("lunch 8 cash", update_id=77)
    assert first and second == []
    assert len(eng.repo.all(Expense)) == 1


def test_pin_flow_wrong_right_lockout(eng):
    pin.set_pin(eng.w.settings, "482913")
    eng.repo.update(eng.w.settings)
    r = eng.handle_text("/networth")
    assert "needs your PIN" in texts(r) and "🟢" not in texts(r) and r[0].sensitive
    bad = eng.handle_text("111111")
    assert "2 tries left" in texts(bad) and bad[0].delete_user_message
    ok = eng.handle_text("/networth")
    good = eng.handle_text("482913")
    assert good[0].delete_user_message and "Unlocked for 15 minutes" in texts(good)
    # locked after three wrong tries (fresh engine = fresh gate)
    e2 = Engine(eng.repo, eng.clock, seed=1)
    e2.handle_text("/networth")
    e2.handle_text("000000"); e2.handle_text("/networth"); e2.handle_text("000001"); e2.handle_text("/networth")
    last = e2.handle_text("000002")
    assert "locked for 15 minutes" in texts(last)
    assert "locked" in texts(e2.handle_text("/networth"))
    assert "S$" in texts(e2.handle_text("lunch 8 cash"))               # normal logging still works


def test_help_and_unknown_command(eng):
    eng.guide_url = "https://example.test/guide"
    r = eng.handle_text("/help")
    assert r[0].buttons[0][0].label == "Open guide (PDF)" and "Need help ah?" in r[0].text
    assert "/settle <person> <amount> <account>" in texts(eng.handle_text("/help settle"))
    assert "Did you mean /help?" in texts(eng.handle_text("/hepl"))


def test_voucher_quick_add_and_split_payment(eng):
    out = texts(eng.handle_text("+CDC 100 exp 31 dec"))
    assert "Added CDC voucher" in out and "S$100.00" in out
    r = eng.handle_text("lunch 12 voucher cdc 8 paynow 4")
    out = texts(r)
    assert "CDC S$8.00" in out and "PayNow S$4.00" in out
    assert "S$92.00" in texts(eng.handle_text("/vouchers"))
    over = texts(eng.handle_text("groceries 200 voucher cdc"))
    assert "has only S$92.00 left" in over


def test_bill_reminder_paid_flow(eng):
    from finbot.core import bills
    b = bills.create_bill(eng.repo, eng.now(), name="Phone bill", due_day=21, amount=Dc("38"), category_id=eng.w.cats["Bills"].id, account_id=eng.w.accts["DBS Card"].id)
    r = eng.handle_callback(f"x:billpaid:{b.id}")
    assert "How much did you pay?" in texts(r)
    out = texts(eng.handle_text("around 40"))
    assert "I need a number" in out
    out = texts(eng.handle_text("40"))
    assert "Phone bill S$40.00" in out


def test_trip_flow_with_both_amounts(eng):
    out = texts(eng.handle_text("/trip start Japan 18 Oct to 27 Oct jpy budget 3000"))
    assert "Trip mode on" in out and "Yearly bucket" in out
    saved = texts(eng.handle_text("lunch 1200 yen sgd 11.40 cash"))
    assert "[Japan]" in saved and "1,200 JPY = S$11.40" in saved and "Yearly bucket left" in saved
    assert "Monthly budget left" not in saved
    assert "Japan" in texts(eng.handle_text("/trip summary"))
    conflict = texts(eng.handle_text("/trip start Bali 1 Dec jpy"))
    assert "End it or pause it first" in conflict


def test_snapshot_first_then_networth(eng):
    pin.set_pin(eng.w.settings, "482913")
    eng.repo.update(eng.w.settings)
    r = eng.handle_text("/snapshot")
    assert "Needs your PIN" not in texts(r)                           # snapshot is gated: asks for the PIN
    assert "PIN" in texts(r)
    eng.handle_text("482913")
    r = eng.handle_text("/snapshot")
    steps = 0
    while "balance of" in texts(r) and steps < 10:
        r = eng.handle_text("100")
        steps += 1
    assert "Starting balances saved" in texts(r)
    assert eng.w.settings.first_snapshot_date is not None or eng.settings().first_snapshot_date is not None
    assert "Net worth" in texts(eng.handle_text("/networth"))


def test_report_command_returns_message_and_pdf(eng):
    eng.handle_text("lunch 8 cash")
    r = eng.handle_text("/report 2026-10")
    assert r[0].files and r[0].files[0][1][:4] == b"%PDF"
    assert "report is here" in r[0].text


def test_questions_route_to_llm_when_available(eng):
    eng.llm = NS(answer=lambda q: "You spent S$120 on Seoul in 2023.")
    assert texts(eng.handle_text("how much did I spend in Seoul 3 years ago?")) == "You spent S$120 on Seoul in 2023."
    assert "S$" in texts(eng.handle_text("lunch 8 cash"))


def test_edit_amount_and_category_via_buttons(eng):
    r = eng.handle_text("lunch 8 cash")
    saved = r[0]
    eid = saved.buttons[0][0].data.split(":")[1]
    menu = eng.handle_callback(f"e:{eid}:f:amount")
    assert "Send the new amount" in texts(menu)
    out = texts(eng.handle_text("12"))
    assert "Updated amount" in out and eng.repo.get(Expense, eid).amount == Dc("12.00")


def test_big_ticket_prompt_and_receipt_attach(eng):
    r = eng.handle_text("standing desk 399 cc")
    cat = press(eng, r, "Shopping") if "Which category" in texts(r) else r
    if "Count this toward" in texts(cat):
        cat = press(eng, cat, "Yearly")
    assert any("big-ticket" in x.text for x in cat)
    yes = press(eng, cat, "Yes")
    w = press(eng, yes, "2 yrs")
    assert "Warranty ends" in texts(w) or "warranty ends" in texts(w)
    out = texts(eng.handle_file(file_id="F1", link="https://t.me/c/1/2"))
    assert "Saved the receipt" in out
    assert "t.me/c/1/2" in texts(eng.handle_text("/item desk"))


def test_guided_add_walks_through_buttons(eng):
    r = eng.handle_text("/add")
    assert "How much?" in texts(r)
    r = eng.handle_text("24.80")
    assert "Which category" in texts(r)
    r = press(eng, r, "Groceries")
    assert "Which account?" in texts(r)
    r = press(eng, r, "PayNow")
    assert "With whom?" in texts(r)
    r = press(eng, r, "Bob")
    assert "So far: Bob" in texts(r)
    r = press(eng, r, "Done")
    assert "Location?" in texts(r)
    out = texts(press(eng, r, "Orchard"))
    assert "S$24.80" in out and "Groceries" in out and "PayNow" in out and "Bob" in out


def test_v2_admin_commands_end_to_end(eng):
    from finbot.domain.models import Card
    from finbot.domain.enums import RewardType
    from finbot.core.ids import new_id
    w = eng.w
    eng.repo.add(Card(id="cd1", account_id=w.accts["DBS Card"].id, bank="DBS", name="Altitude", last4="4444", statement_day=15, due_day=22, reward_type=RewardType.MILES, value_per_unit=Dc("0.015")))
    assert "Saved the online rule" in texts(eng.handle_text("/rewards rule dbs online 4 cap 1000 fallback 1.2"))
    assert "Saved the general rule" in texts(eng.handle_text("/rewards rule dbs general 1.2"))
    assert "now counts as online" in texts(eng.handle_text("/bestcard map grab online"))
    out = texts(eng.handle_text("/bestcard grab 20"))
    assert "DBS Altitude" in out and "about S$1.20" in out
    assert "Tracking Netflix" in texts(eng.handle_text("/subs add Netflix 17.98"))
    assert "Netflix" in texts(eng.handle_text("/subs"))
    assert "loan" in texts(eng.handle_text("/loans add Bank 12000 3.6% 1000"))
    assert "Payoff" in texts(eng.handle_text("/loans"))
    assert "planned for Nov" in texts(eng.handle_text("/yearplan add Insurance 1800 nov"))
    assert "left unplanned" in texts(eng.handle_text("/yearplan"))
