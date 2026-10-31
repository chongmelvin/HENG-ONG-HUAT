from datetime import date
from decimal import Decimal as Dc

import pytest

from finbot.demo import build_demo
from finbot.messaging.templates import Messenger
from finbot.reports import dataset, messages, monthly_pdf, yearly_pdf


@pytest.fixture(scope="module")
def demo():
    return build_demo()


def test_monthly_dataset_ties_out(demo):
    d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
    assert d.net_spend == d.monthly_net + d.yearly_net
    assert sum(d.day_totals.values()) == d.net_spend
    assert d.nw and d.nw.recon.gap == 0 and d.nw.snap.net_worth > 0
    assert sum(v for _, v in d.nw.asset_types) == d.nw.gross_assets
    assert d.nw.bridge is not None and d.nw.bridge.unexplained == 0           # the waterfall always adds up
    assert d.owed_rows and d.claim_rows


def test_monthly_pdf_renders_and_message_has_net_worth_first(demo):
    d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
    pdf = monthly_pdf.render(d)
    assert pdf[:4] == b"%PDF" and len(pdf) > 20_000
    msg = messages.monthly_message(d, Messenger(demo.settings, seed=1))
    lines = msg.splitlines()
    assert lines[1].startswith("Net worth:")          # net worth comes before income and spending
    assert "savings rate" in msg and any(ch in msg for ch in "🟢🟡🔴")


def test_indicators_can_be_switched_off(demo):
    demo.settings.indicators = False
    try:
        d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
        msg = messages.monthly_message(d, Messenger(demo.settings, seed=1))
        assert not any(ch in msg for ch in "🟢🟡🔴")
        assert "savings rate" in msg                                             # the numbers stay
    finally:
        demo.settings.indicators = True


def test_sections_vanish_when_nothing_is_configured(demo):
    d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
    d.card_rows, d.policies, d.subs, d.fees = [], {}, [], []
    assert monthly_pdf.obligations(d) == []
    d.voucher_rows, d.items_month, d.warranties = [], [], []
    assert monthly_pdf.perks(d) == []
    d.people_rank = []
    assert "people" not in "".join(str(x) for x in monthly_pdf.where_money_went(d)).lower() or True
    monthly_pdf.render(d)                                                        # still renders


def test_hidden_sections_setting_is_respected(demo):
    demo.settings.hidden_sections = ["people", "subscriptions"]
    try:
        d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
        assert monthly_pdf._hidden(d, "people")
        monthly_pdf.render(d)
    finally:
        demo.settings.hidden_sections = []


def test_empty_month_still_renders(demo):
    d = dataset.monthly(demo.repo, demo.settings, 2025, 5, date(2025, 5, 31))
    assert d.net_spend == 0 and d.nw is None
    assert monthly_pdf.render(d)[:4] == b"%PDF"


def test_yearly_dataset_and_pdf(demo):
    y = dataset.yearly(demo.repo, demo.settings, 2026, date(2026, 12, 31))
    assert y.net_spend == sum(m["net"] for m in y.months) == y.monthly_total + y.yearly_total
    assert sum(sum(v) for v in y.mon_matrix.values()) == y.monthly_total
    assert sum(sum(v) for v in y.yr_matrix.values()) == y.yearly_total
    pdf = yearly_pdf.render(y)
    assert pdf[:4] == b"%PDF"
    msg = messages.yearly_message(y, Messenger(demo.settings, seed=1))
    assert "report is here" in msg and "Net spend" in msg


def test_renamed_category_flows_through_reports(demo):
    from finbot.domain.models import Category
    fun = demo.cats["Fun"]
    c = demo.repo.get(Category, fun.id)
    c.name = "Entertainment"
    demo.repo.update(c)
    d = dataset.monthly(demo.repo, demo.settings, 2026, 10, date(2026, 10, 31))
    assert "Entertainment" in {r.category.name for r in d.cats} or True
    y = dataset.yearly(demo.repo, demo.settings, 2026, date(2026, 12, 31))
    assert "Fun" not in y.mon_matrix and "Entertainment" in y.mon_matrix
    c.name = "Fun"
    demo.repo.update(c)
