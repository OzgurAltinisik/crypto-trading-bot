"""Telegram notifications. Without a token/chat id it only logs."""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: Optional[str], chat_id: Optional[str]):
        self.token = token
        self.chat_id = chat_id
        if not token:
            log.warning("TELEGRAM_TOKEN not set: Telegram is off, messages only go to the log")
        elif not chat_id:
            log.info("TELEGRAM_CHAT_ID not set: no broadcast channel (subscribers still get alerts)")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, chat_id: Optional[str] = None) -> bool:
        """Send an HTML message (to the default chat unless `chat_id` is given).
        Callers must html.escape() any dynamic text."""
        if not self.token or not (chat_id or self.chat_id):
            log.info("[notify] %s", text.strip())
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": chat_id or self.chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=10,
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if not r.ok or not body.get("ok", False):
                log.error("Telegram error %s: %s", r.status_code, body.get("description", r.text[:200]))
                return False
            return True
        except requests.RequestException as e:
            log.error("Telegram request failed: %s", e)
            return False
