"""HTTP server (Starlette) for Railway: Telegram webhook, the help guide PDF and a health check.

One public port serves all three:
  POST /tg/<WEBHOOK_PATH>       Telegram updates (also requires the secret-token header)
  GET  /guide/<GUIDE_TOKEN>.pdf the help guide (no personal data; unguessable URL)
  GET  /healthz                 liveness
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Callable, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .config import Config

log = logging.getLogger(__name__)


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def create_server(cfg: Config, application, guide_pdf: Callable[[], bytes]) -> Starlette:
    from telegram import Update

    async def webhook(request: Request) -> Response:
        if not _eq(request.path_params["path"], cfg.webhook_path) or not _eq(request.headers.get("x-telegram-bot-api-secret-token", ""), cfg.webhook_secret):
            return PlainTextResponse("forbidden", status_code=403)
        data = await request.json()
        await application.update_queue.put(Update.de_json(data, application.bot))
        return PlainTextResponse("ok")

    async def guide(request: Request) -> Response:
        if not cfg.guide_token or not _eq(request.path_params["token"], cfg.guide_token):
            return PlainTextResponse("not found", status_code=404)
        return Response(guide_pdf(), media_type="application/pdf", headers={"Cache-Control": "private, max-age=3600"})

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok")

    @asynccontextmanager
    async def lifespan(app):
        await application.initialize()
        await application.start()
        if cfg.mode == "webhook":
            await application.bot.set_webhook(f"{cfg.public_url}/tg/{cfg.webhook_path}", secret_token=cfg.webhook_secret,
                                              allowed_updates=["message", "callback_query"], drop_pending_updates=False)
        yield
        await application.stop()
        await application.shutdown()

    return Starlette(routes=[Route("/tg/{path}", webhook, methods=["POST"]), Route("/guide/{token}.pdf", guide), Route("/healthz", health)], lifespan=lifespan)
