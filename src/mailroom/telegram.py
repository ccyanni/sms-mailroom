"""Talk to the owner's Telegram chat through the Bot API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

HttpPost = Callable[[str, dict], object]  # calls one Bot API method, returns its result
_LIMIT = 4096  # Telegram's maximum message length


@dataclass(frozen=True)
class TelegramSettings:
    token: str
    chat_id: str


class TelegramError(Exception):
    """Telegram could not be reached or refused the call. Never contains the bot token.

    `permanent` is True when Telegram refused the call itself (a bad request), so asking again will not help.
    """

    def __init__(self, reason: str, permanent: bool = False) -> None:
        super().__init__(reason)
        self.permanent = permanent


def http_post(url: str, payload: dict) -> object:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    # A long poll waits on Telegram's side for up to `timeout` seconds before it answers.
    with urllib.request.urlopen(request, timeout=15 + int(payload.get("timeout", 0))) as response:
        answer = json.load(response)
    if not answer.get("ok"):
        raise TelegramError("Telegram answered without ok")
    return answer.get("result")


class TelegramBot:
    def __init__(self, settings: TelegramSettings, post: HttpPost = http_post) -> None:
        self.chat_id = settings.chat_id
        self._token = settings.token
        self._post = post

    def send(self, text: str, keyboard: dict | None = None) -> int | None:
        """Send a text to the owner's chat; returns the Telegram message id when Telegram says it."""
        payload: dict = {"chat_id": self.chat_id, "text": _fit(text)}
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        result = self._call("sendMessage", payload)
        return result.get("message_id") if isinstance(result, dict) else None

    def edit(self, message_id: int, text: str, keyboard: dict | None) -> None:
        payload: dict = {"chat_id": self.chat_id, "message_id": message_id, "text": _fit(text)}
        payload["reply_markup"] = keyboard or {"inline_keyboard": []}
        self._call("editMessageText", payload)

    def delete(self, message_id: int) -> None:
        """Delete a message the bot sent; Telegram allows it for 48 hours after sending."""
        self._call("deleteMessage", {"chat_id": self.chat_id, "message_id": message_id})

    def answer(self, callback_query_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def button_presses(self, offset: int | None, timeout: int) -> list[dict]:
        """Wait up to `timeout` seconds for updates after `offset`; only button presses are asked for."""
        payload: dict = {"timeout": timeout, "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        return result if isinstance(result, list) else []

    def _call(self, method: str, payload: dict) -> object:
        try:
            return self._post(f"https://api.telegram.org/bot{self._token}/{method}", payload)
        except Exception as exc:
            # The token is part of the URL, which some errors quote.
            reason = f"{type(exc).__name__}: {exc}".replace(self._token, "<token>")
            refused = isinstance(exc, urllib.error.HTTPError) and exc.code == 400
            raise TelegramError(reason, permanent=refused) from None


def telegram_sender(settings: TelegramSettings, post: HttpPost = http_post) -> Callable[[str], object]:
    return TelegramBot(settings, post).send


def _fit(text: str) -> str:
    return text if len(text) <= _LIMIT else text[: _LIMIT - 1] + "…"
