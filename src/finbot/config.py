"""Environment configuration (Railway variables). See .env.example."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Optional


class ConfigError(RuntimeError):
    pass


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ConfigError(f"Missing environment variable {name}")
    return v


@dataclass
class Config:
    bot_token: str
    owner_user_id: int
    group_chat_id: int
    storage: str = "sheets"                      # sheets | memory (local dev)
    sheet_id: str = ""
    google_credentials: dict = field(default_factory=dict)
    public_url: str = ""
    webhook_secret: str = ""                     # sent by Telegram in X-Telegram-Bot-Api-Secret-Token
    webhook_path: str = ""                       # unguessable path segment
    guide_token: str = ""                        # unguessable path segment for the help PDF
    mode: str = "webhook"                        # webhook | polling
    port: int = 8080
    timezone: str = "Asia/Singapore"
    allow_private_chat: bool = False
    anthropic_key: Optional[str] = None
    llm_model: str = "claude-sonnet-5-5"

    @classmethod
    def from_env(cls) -> "Config":
        storage = os.environ.get("STORAGE", "sheets")
        creds: dict = {}
        if storage == "sheets":
            raw = _req("GOOGLE_CREDENTIALS_JSON")
            try:
                creds = json.loads(raw if raw.lstrip().startswith("{") else base64.b64decode(raw).decode())
            except Exception as e:
                raise ConfigError("GOOGLE_CREDENTIALS_JSON must be the service account JSON (or its base64)") from e
        mode = os.environ.get("MODE", "webhook")
        cfg = cls(
            bot_token=_req("BOT_TOKEN"), owner_user_id=int(_req("OWNER_USER_ID")), group_chat_id=int(_req("GROUP_CHAT_ID")),
            storage=storage, sheet_id=_req("SHEET_ID") if storage == "sheets" else "", google_credentials=creds,
            public_url=os.environ.get("PUBLIC_URL", "").rstrip("/"), webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
            webhook_path=os.environ.get("WEBHOOK_PATH", ""), guide_token=os.environ.get("GUIDE_TOKEN", ""), mode=mode,
            port=int(os.environ.get("PORT", "8080")), timezone=os.environ.get("TZ", "Asia/Singapore"),
            allow_private_chat=os.environ.get("ALLOW_PRIVATE_CHAT", "").lower() in ("1", "true", "yes"),
            anthropic_key=os.environ.get("ANTHROPIC_API_KEY") or None, llm_model=os.environ.get("LLM_MODEL", "claude-sonnet-5-5"))
        if mode == "webhook":
            for name in ("public_url", "webhook_secret", "webhook_path"):
                if not getattr(cfg, name):
                    raise ConfigError(f"MODE=webhook needs {name.upper()}")
            if len(cfg.webhook_secret) < 16 or len(cfg.webhook_path) < 16:
                raise ConfigError("WEBHOOK_SECRET and WEBHOOK_PATH must be at least 16 characters (use a long random string)")
        return cfg

    @property
    def guide_url(self) -> str:
        return f"{self.public_url}/guide/{self.guide_token}.pdf" if self.public_url and self.guide_token else ""
