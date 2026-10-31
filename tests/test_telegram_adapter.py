import asyncio
from datetime import datetime
from types import SimpleNamespace as NS

from finbot.bot.engine import Engine
from finbot.bot.telegram_app import TelegramBot
from finbot.bot.types import Button, Reply
from finbot.clock import FixedClock
from finbot.config import Config
from finbot.storage.base import MemoryRepo


def make():
    cfg = Config(bot_token="123456:ABC-DEF", owner_user_id=7, group_chat_id=-1001234567890, storage="memory", mode="polling")
    eng = Engine(MemoryRepo(), FixedClock(datetime(2026, 10, 18, 9, 0)), seed=1)
    return TelegramBot(cfg, eng), cfg


def update(user, chat, chat_type="supergroup"):
    return NS(effective_user=NS(id=user), effective_chat=NS(id=chat, type=chat_type))


def test_two_part_allowlist():
    bot, cfg = make()
    assert bot.authorised(update(7, -1001234567890))
    assert not bot.authorised(update(8, -1001234567890))                 # someone else in your group
    assert not bot.authorised(update(7, -1009999999999))                 # you, in another group
    assert not bot.authorised(update(7, 7, "private"))                   # DMs are off unless enabled
    cfg.allow_private_chat = True
    assert bot.authorised(update(7, 7, "private"))
    assert not bot.authorised(NS(effective_user=None, effective_chat=None))


def test_ignored_updates_never_reach_the_engine():
    bot, _ = make()
    seen = []
    bot.engine.handle_text = lambda *a, **k: seen.append(a) or []
    msg = NS(text="lunch 8 cash")
    asyncio.run(bot.on_text(NS(effective_user=NS(id=99), effective_chat=NS(id=-1001234567890, type="supergroup"), message=msg, update_id=1), None))
    assert seen == []


def test_send_builds_inline_keyboard_url_buttons_and_files():
    bot, _ = make()
    sent = []

    class B:
        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            sent.append(("msg", text, reply_markup, parse_mode))
            return NS(delete=lambda: None)

        async def send_document(self, chat_id, doc):
            sent.append(("doc", doc))

    bot.app = NS(bot=B(), job_queue=None)
    asyncio.run(bot._send(1, [Reply("hello", [[Button("Open guide (PDF)", "url:https://x.test/g.pdf"), Button("Yes", "p:abc:ok")]], files=[("r.pdf", b"%PDF")]),
                                 Reply("<pre>cal</pre>")]))
    kinds = [s[0] for s in sent]
    assert kinds[:2] == ["msg", "doc"]
    kb = sent[0][2].inline_keyboard[0]
    assert kb[0].url == "https://x.test/g.pdf" and kb[1].callback_data == "p:abc:ok"
    assert sent[2][3] == "HTML"
