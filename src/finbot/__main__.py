"""Entry point: `python -m finbot`."""
from __future__ import annotations

import logging
import os

from .bot.engine import Engine
from .bot.telegram_app import TelegramBot
from .clock import Clock
from .config import Config
from .help.guide import build_guide
from .server import create_server
from .storage.base import MemoryRepo
from .v2.fx import FrankfurterProvider
from .v2.investments import CoinGeckoProvider, RoutingProvider, YahooProvider
from .v2.llm import LLMService


def build(cfg: Config):
    if cfg.storage == "sheets":
        from .storage.sheets import SheetsRepo
        repo = SheetsRepo.from_service_account(cfg.google_credentials, cfg.sheet_id)
        repo.ensure_tabs()
        repo.verify_schema()                      # refuses to run if a header was edited by hand
    else:
        repo = MemoryRepo()
    clock = Clock(cfg.timezone)
    engine = Engine(repo, clock, fx=FrankfurterProvider(), prices=RoutingProvider(YahooProvider(), CoinGeckoProvider()),
                    guide_url=cfg.guide_url, guide_pdf=lambda: build_guide(clock.today()))
    if cfg.anthropic_key:
        engine.llm = LLMService(repo, engine.settings(), clock.today, model=cfg.llm_model)
    return engine


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    engine = build(cfg)
    bot = TelegramBot(cfg, engine)
    if cfg.mode == "polling":                     # local development
        bot.app.run_polling(allowed_updates=["message", "callback_query"])
        return
    import uvicorn
    uvicorn.run(create_server(cfg, bot.app, lambda: build_guide(engine.today())), host="0.0.0.0", port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
