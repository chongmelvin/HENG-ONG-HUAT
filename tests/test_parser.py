from datetime import date
from decimal import Decimal as Dc

from finbot.parsing.expense import parse_expense

TODAY = date(2026, 10, 18)


def parse(w, text, **kw):
    w.settings.places = ["Orchard", "Ang Mo Kio", "Tampines"]
    return parse_expense(w.repo, w.settings, text, TODAY, **kw)


def test_basic(world):
    p = parse(world, "chicken rice 5.50 paylah")
    assert p.amount == Dc("5.50") and p.account.name == "PayLah" and p.description == "chicken rice"
    assert "category" in p.needs            # "chicken rice" is unknown until the user teaches it


def test_alias_category_and_people_and_place(world):
    p = parse(world, "grab 12 cc with bob orchard")
    assert p.category.name == "Transport" and p.account.name == "DBS Card"
    assert [x.name for x in p.people] == ["Bob"] and p.location == "Orchard"
    assert p.needs == []


def test_equal_split_and_custom_split(world):
    p = parse(world, "dinner 120 cc split bob alice")
    assert p.split_mode == "equal" and [x.name for x in p.people] == ["Bob", "Alice"]
    q = parse(world, "dinner 120 cc bob 30 alice 40")
    assert q.split_mode == "custom" and sorted(q.split_values.values()) == [Dc("30"), Dc("40")]
    r = parse(world, "dinner 120 cc treat bob alice")
    assert r.split_mode == "treat"


def test_dates(world):
    assert parse(world, "y lunch 8 cash").spend_date == date(2026, 10, 17)
    assert parse(world, "-2d grab 12 cc").spend_date == date(2026, 10, 16)
    assert parse(world, "12 oct dinner 45 cc").spend_date == date(2026, 10, 12)
    f = parse(world, "25 dec lunch 6 cash")
    assert f.date_error and f.date_suggestion == date(2025, 12, 25)
    assert parse(world, "31 feb lunch 6 cash").date_error


def test_missing_ambiguous_unknown(world):
    assert "amount" in parse(world, "chicken rice paylah").needs
    assert parse(world, "dinner 45 55 cc").ambiguous_amounts == [Dc("45"), Dc("55")]
    p = parse(world, "lunch 8 grabpay")
    assert p.unknown_account == "grabpay"
    q = parse(world, "dinner 90 cc with sam")
    assert q.unknown_people == ["sam"]


def test_unnamed_group_and_typo_suggestion(world):
    p = parse(world, "lunch 12 cash with friends")
    assert p.unnamed and not p.unknown_people
    t = parse(world, "dinner 45 cc with bbo")
    assert t.person_suggestion.name == "Bob"


def test_claim_and_big_tags(world):
    p = parse(world, "taxi 25 cc #claim acme")
    assert p.claimable and p.claimant == "Acme" and p.category.name == "Transport"
    assert parse(world, "headphones 59 cc #big").big


def test_voucher_split_payment(world):
    p = parse(world, "lunch 12 voucher cdc 8 paynow 4")
    assert [(a.name, v) for a, v in p.payments] == [("CDC", Dc("8")), ("PayNow", Dc("4"))]


def test_foreign_currency_and_trip_mode(world):
    p = parse(world, "ramen 1200 yen sgd 11.40 cash")
    assert p.currency == "JPY" and p.foreign_amount == Dc("1200") and p.home_amount == Dc("11.40")
    q = parse(world, "ramen 1200 cash", trip_currency="JPY")
    assert q.currency == "JPY" and q.foreign_amount == Dc("1200") and q.home_amount is None


def test_name_in_description_is_not_tagged_without_with(world):
    p = parse(world, "dinner at bob's place 40 cc")
    assert p.people == []
