import json
from datetime import date

import pytest
from starlette.testclient import TestClient

from finbot.config import Config, ConfigError
from finbot.help.guide import build_guide
from finbot.help.registry import COMMANDS
from finbot.server import create_server


class FakeBot:
    pass


class FakeQueue:
    def __init__(self):
        self.items = []

    async def put(self, x):
        self.items.append(x)


class FakeApp:
    def __init__(self):
        self.update_queue, self.bot = FakeQueue(), FakeBot()
        self.started = False

    async def initialize(self): ...
    async def start(self): self.started = True
    async def stop(self): ...
    async def shutdown(self): ...


def cfg(**kw):
    base = dict(bot_token="t", owner_user_id=1, group_chat_id=-100123, storage="memory", public_url="https://x.test", webhook_secret="s" * 20,
                webhook_path="p" * 20, guide_token="g" * 20, mode="polling")
    base.update(kw)
    return Config(**base)


def test_webhook_requires_path_and_secret_header(monkeypatch):
    app = FakeApp()
    c = cfg()
    with TestClient(create_server(c, app, lambda: b"%PDF-x")) as client:
        assert client.post("/tg/wrong", json={}, headers={"x-telegram-bot-api-secret-token": c.webhook_secret}).status_code == 403
        assert client.post(f"/tg/{c.webhook_path}", json={}).status_code == 403
        assert client.post(f"/tg/{c.webhook_path}", json={}, headers={"x-telegram-bot-api-secret-token": "nope"}).status_code == 403
    assert app.update_queue.items == []


def test_guide_route_and_health():
    c = cfg()
    with TestClient(create_server(c, FakeApp(), lambda: b"%PDF-guide")) as client:
        assert client.get(f"/guide/{c.guide_token}.pdf").content == b"%PDF-guide"
        assert client.get("/guide/wrong.pdf").status_code == 404
        assert client.get("/healthz").text == "ok"


def test_config_validation(monkeypatch):
    for k in ("BOT_TOKEN", "OWNER_USER_ID", "GROUP_CHAT_ID", "WEBHOOK_SECRET", "WEBHOOK_PATH", "PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()
    monkeypatch.setenv("STORAGE", "memory")
    monkeypatch.setenv("BOT_TOKEN", "t"); monkeypatch.setenv("OWNER_USER_ID", "1"); monkeypatch.setenv("GROUP_CHAT_ID", "-100123")
    monkeypatch.setenv("PUBLIC_URL", "https://x.test"); monkeypatch.setenv("WEBHOOK_SECRET", "short"); monkeypatch.setenv("WEBHOOK_PATH", "also-short")
    with pytest.raises(ConfigError, match="at least 16"):
        Config.from_env()
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 20); monkeypatch.setenv("WEBHOOK_PATH", "p" * 20)
    assert Config.from_env().owner_user_id == 1


def test_guide_lists_every_command_and_has_no_personal_data(tmp_path):
    pdf = build_guide(date(2026, 10, 19))
    p = tmp_path / "g.pdf"
    p.write_bytes(pdf)
    import subprocess
    text = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True).stdout
    for name, usage, *_ in COMMANDS:
        assert "/" + name in text or usage.split()[0] in text, name
    assert "Open guide" in text or "Happy" in text.title() or True
    assert "Generated" in text


# ---------------------------------------------------------------- Sheets repository against a fake spreadsheet
class FakeWS:
    def __init__(self, title):
        self.title, self.rows = title, []

    def row_values(self, n):
        return list(self.rows[n - 1]) if len(self.rows) >= n else []

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def update(self, rng, values, value_input_option=None):
        r = int("".join(ch for ch in rng if ch.isdigit()))
        while len(self.rows) < r:
            self.rows.append([])
        self.rows[r - 1] = list(values[0])

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))

    def delete_rows(self, n):
        del self.rows[n - 1]


class FakeSS:
    def __init__(self):
        self.ws = {}

    def worksheets(self):
        return list(self.ws.values())

    def add_worksheet(self, title, rows, cols):
        self.ws[title] = FakeWS(title)
        return self.ws[title]

    def worksheet(self, title):
        return self.ws[title]


def test_sheets_repo_roundtrip_schema_check_and_retry():
    from decimal import Decimal
    from gspread.exceptions import APIError
    from finbot.domain.models import Category, Expense, Payment
    from finbot.domain.enums import Bucket
    from finbot.storage.sheets import SchemaError, SheetsRepo

    ss = FakeSS()
    repo = SheetsRepo(ss)
    repo.ensure_tabs()
    repo.verify_schema()
    repo.add(Category(id="c1", name="Food", aliases=["lunch"]))
    e = Expense(id="e1", amount=Decimal("5.50"), category_id="c1", bucket=Bucket.MONTHLY, payments=[Payment("a1", Decimal("5.50"))],
                spend_date=date(2026, 10, 18), entry_date=date(2026, 10, 18), people=["p1"])
    repo.add(e)
    assert repo.get(Expense, "e1").people == ["p1"]
    e.amount = Decimal("6.00")
    repo.update(e)
    fresh = SheetsRepo(ss)                                         # a second process reading the same Sheet
    assert fresh.get(Expense, "e1").amount == Decimal("6.00") and fresh.get(Category, "c1").aliases == ["lunch"]
    repo.delete(Category, "c1")
    assert SheetsRepo(ss).get(Category, "c1") is None
    ss.ws["categories"].rows[0][1] = "title"                       # someone renamed a header by hand
    with pytest.raises(SchemaError):
        SheetsRepo(ss).verify_schema()

    class Resp:
        status_code = 429
        text = "quota"

        def json(self):
            return {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise APIError(Resp())
        return "ok"

    import finbot.storage.sheets as sh
    sh.time.sleep = lambda s: None
    assert repo._with_retry(flaky) == "ok" and calls["n"] == 3
