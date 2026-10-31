from datetime import date, datetime
from decimal import Decimal

from finbot.domain.enums import Bucket
from finbot.domain.models import Expense, Payment, Receivable, Snapshot, Balance, Settings, Persona
from finbot.storage.base import MemoryRepo
from finbot.storage.codec import columns, from_row, to_row


def test_expense_roundtrip():
    e = Expense(id="e1", amount=Decimal("80.00"), category_id="c1", bucket=Bucket.MONTHLY,
                payments=[Payment("a1", Decimal("80.00"))], spend_date=date(2026, 10, 18),
                entry_date=date(2026, 10, 18), my_share=Decimal("26.68"), people=["p1", "p2"],
                tags=["Social"], created_at=datetime(2026, 10, 18, 12, 0))
    row = to_row(e)
    assert len(row) == len(columns(Expense))
    back = from_row(Expense, row)
    assert back == e


def test_optional_and_empty_cells():
    s = from_row(Snapshot, ["s1", "2026-10-31", "[]", "", "", "", "", "", ""])
    assert s.balances == [] and s.net_worth == Decimal("0.00")


def test_settings_enum_roundtrip():
    st = Settings(persona=Persona.SCOLD_OFF, hidden_sections=["fees"])
    assert from_row(Settings, to_row(st)).persona == Persona.SCOLD_OFF


def test_memory_repo_crud():
    r = MemoryRepo()
    rec = Receivable(id="r1", expense_id="e", person_id="p", amount=Decimal("26.66"), created=date(2026, 10, 18))
    r.add(rec)
    assert r.get(Receivable, "r1").amount == Decimal("26.66")
    rec.settled = Decimal("10.00")
    r.update(rec)
    assert r.find(Receivable, person_id="p")[0].outstanding == Decimal("16.66")
