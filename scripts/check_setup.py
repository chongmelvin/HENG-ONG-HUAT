"""Pre-flight check for your environment: python scripts/check_setup.py

Verifies the env vars, the Google Sheet (tabs and headers) and the Telegram group (admin, privacy mode,
supergroup). It changes nothing except creating missing Sheet tabs.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from finbot.config import Config, ConfigError  # noqa: E402


async def main() -> int:
    try:
        cfg = Config.from_env()
    except ConfigError as e:
        print("CONFIG:", e)
        return 1
    print("config ok")
    if cfg.storage == "sheets":
        from finbot.storage.sheets import SheetsRepo, SchemaError
        repo = SheetsRepo.from_service_account(cfg.google_credentials, cfg.sheet_id)
        repo.ensure_tabs()
        try:
            repo.verify_schema()
            print("sheet ok: all tabs and headers match")
        except SchemaError as e:
            print("SHEET:", e)
            return 1
    from telegram import Bot
    bot = Bot(cfg.bot_token)
    me = await bot.get_me()
    chat = await bot.get_chat(cfg.group_chat_id)
    member = await bot.get_chat_member(cfg.group_chat_id, me.id)
    problems = []
    if member.status not in ("administrator", "creator"):
        problems.append("bot is not an admin")
    elif getattr(member, "can_delete_messages", True) is False:
        problems.append("bot cannot delete messages (needed for PIN messages)")
    if not me.can_read_all_group_messages and member.status not in ("administrator", "creator"):
        problems.append("privacy mode is on")
    if chat.type != "supergroup":
        problems.append("group is not a supergroup (receipt links need one)")
    print("telegram:", "ok" if not problems else "; ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
