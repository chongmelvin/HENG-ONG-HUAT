"""Telegram adapter: authorisation, sending replies, receipts, scheduled jobs, startup access check.

All behaviour lives in Engine. This file only translates between Telegram objects and Reply objects.
"""
from __future__ import annotations

import asyncio
import hmac
import io
import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from ..config import Config
from .engine import Engine
from .types import Reply

log = logging.getLogger(__name__)
SERVER_ERROR = "Something went wrong on my side. Nothing was lost; please try again."


class TelegramBot:
    def __init__(self, cfg: Config, engine: Engine) -> None:
        self.cfg, self.engine = cfg, engine
        self._lock = asyncio.Lock()                  # one user, one conversation: serialise engine access
        self.app: Application = Application.builder().token(cfg.bot_token).post_init(self._post_init).build()
        self.app.add_handler(MessageHandler(filters.TEXT, self.on_text))                    # commands arrive as text too
        self.app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, self.on_file))
        self.app.add_handler(CallbackQueryHandler(self.on_callback))
        self.app.job_queue.run_daily(self.on_daily, time(cfg_hour(engine), 0, tzinfo=ZoneInfo(cfg.timezone)), name="daily")

    # ------------------------------------------------------------------ security (PRD 9.4)
    def authorised(self, update: Update) -> bool:
        """Two-part allowlist: your user ID AND your private group. Everything else is ignored silently."""
        u, c = update.effective_user, update.effective_chat
        if not u or not c or u.id != self.cfg.owner_user_id:
            return False
        return c.id == self.cfg.group_chat_id or (self.cfg.allow_private_chat and c.type == "private")

    # ------------------------------------------------------------------ handlers
    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.authorised(update) or not update.message or not update.message.text:
            return
        await self._run(update, lambda: self.engine.handle_text(update.message.text, update_id=update.update_id))

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not self.authorised(update) or not q:
            return
        await q.answer()
        await self._run(update, lambda: self.engine.handle_callback(q.data or ""))

    async def on_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        m = update.message
        if not self.authorised(update) or not m:
            return
        file_id = m.photo[-1].file_id if m.photo else (m.document.file_id if m.document else "")
        chat = update.effective_chat
        link = f"https://t.me/c/{str(chat.id)[4:]}/{m.message_id}" if chat.type == "supergroup" and str(chat.id).startswith("-100") else ""
        await self._run(update, lambda: self.engine.handle_file(file_id=file_id, link=link, caption=m.caption or ""))

    async def on_daily(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        async with self._lock:
            try:
                replies = await asyncio.to_thread(self.engine.run_jobs)
            except Exception:
                log.exception("daily jobs failed")
                return
        await self._send(self.cfg.group_chat_id, replies)

    async def _run(self, update: Update, fn) -> None:
        async with self._lock:
            try:
                replies = await asyncio.to_thread(fn)
            except Exception:
                log.exception("engine error")
                replies = [Reply(SERVER_ERROR)]
        chat_id = update.effective_chat.id
        if any(r.delete_user_message for r in replies) and update.message:
            try:
                await update.message.delete()                  # PIN messages are removed the moment they are read
            except Exception:
                log.warning("could not delete the user's message (is the bot an admin with delete rights?)")
        await self._send(chat_id, replies)

    # ------------------------------------------------------------------ sending
    async def _send(self, chat_id: int, replies: list[Reply]) -> None:
        bot = self.app.bot
        for r in replies:
            markup = None
            if r.buttons:
                markup = InlineKeyboardMarkup([[InlineKeyboardButton(b.label, url=b.data[4:]) if b.data.startswith("url:")
                                                else InlineKeyboardButton(b.label, callback_data=b.data[:64]) for b in row] for row in r.buttons])
            if r.text:
                msg = await bot.send_message(chat_id, r.text, reply_markup=markup, parse_mode="HTML" if r.text.startswith("<pre>") else None)
                if r.auto_delete_s:
                    self.app.job_queue.run_once(lambda c, m=msg: m.delete(), r.auto_delete_s)
            for name, data in r.files:
                await bot.send_document(chat_id, InputFile(io.BytesIO(data), filename=name))
            for fid in r.file_ids:
                await bot.send_document(chat_id, fid)

    # ------------------------------------------------------------------ startup checks
    async def _post_init(self, app: Application) -> None:
        warnings = await self.access_check()
        if warnings:
            await self._send(self.cfg.group_chat_id, [Reply("⚠️ Setup check:\n" + "\n".join(f"- {w}" for w in warnings))])

    async def access_check(self) -> list[str]:
        out: list[str] = []
        try:
            me = await self.app.bot.get_me()
            chat = await self.app.bot.get_chat(self.cfg.group_chat_id)
            member = await self.app.bot.get_chat_member(self.cfg.group_chat_id, me.id)
        except Exception as e:
            return [f"I can't reach the group ({type(e).__name__}). Check GROUP_CHAT_ID and that I am in the group."]
        is_admin = member.status in ("administrator", "creator")
        if not is_admin:
            out.append("I'm not an admin. Make me admin with permission to delete messages, so I can remove PIN messages.")
        elif getattr(member, "can_delete_messages", True) is False:
            out.append("I'm an admin but can't delete messages. Turn on 'Delete messages'. Without it I refuse to take a PIN.")
        if not me.can_read_all_group_messages and not is_admin:
            out.append("Privacy mode is on, so I can only see commands. Turn it off in BotFather, then remove me and add me again.")
        if chat.type != "supergroup":
            out.append("This group is not a supergroup, so I can't create receipt links. I'll send files instead.")
        return out


def cfg_hour(engine: Engine) -> int:
    return engine.settings().report_hour
