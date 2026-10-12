"""Deliver text to the owner's Telegram chat."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Callable

HttpPost = Callable[[str, dict], None]
_LIMIT = 4096  # Telegram's maximum message length


@dataclass(frozen=True)
class TelegramSettings:
    token: str
    chat_id: str


class TelegramError(Exception):
    """Telegram could not be reached or refused the message. Never contains the bot token."""


def http_post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if not json.load(response).get("ok"):
            raise TelegramError("Telegram answered without ok")


def telegram_sender(settings: TelegramSettings, post: HttpPost = http_post) -> Callable[[str], None]:
    url = f"https://api.telegram.org/bot{settings.token}/sendMessage"

    def send(text: str) -> None:
        if len(text) > _LIMIT:
            text = text[: _LIMIT - 1] + "…"
        try:
            post(url, {"chat_id": settings.chat_id, "text": text})
        except Exception as exc:
            # The token is part of the URL, which some errors quote.
            reason = f"{type(exc).__name__}: {exc}".replace(settings.token, "<token>")
            raise TelegramError(reason) from None

    return send
