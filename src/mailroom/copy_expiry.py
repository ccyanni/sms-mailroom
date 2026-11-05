"""Deletes Telegram copies of Messages some hours after they were sent, when the owner switches it on.

Anyone holding the bot token can forward every message in the owner's chat with the bot to themselves, and
nothing would show it. Deleting copies keeps what they could collect to those last hours. The Messages stay on
the page; Telegram lets a bot delete what it sent for 48 hours, so a copy older than that is left in the chat.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from mailroom.store import Store
from mailroom.telegram import TelegramBot, TelegramError

log = logging.getLogger(__name__)


class CopyExpiry:
    def __init__(self, store: Store, bot: TelegramBot, keep: timedelta, check_every: float = 600.0) -> None:
        self._store = store
        self._bot = bot
        self._keep = keep
        self._check_every = check_every
        self._failing = False

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(self._check_every):
            try:
                self.delete_old_copies()
            except Exception:
                log.exception("could not delete old Telegram copies")

    def delete_old_copies(self) -> None:
        """Delete copies sent longer than `keep` ago, and copies of Messages deleted for good."""
        failed: TelegramError | None = None
        for telegram_message_id in self._store.telegram_copies_to_delete(datetime.now(timezone.utc) - self._keep):
            try:
                self._bot.delete(telegram_message_id)
            except TelegramError as exc:
                if not exc.permanent:
                    failed = exc
                    continue
                # Already deleted in the chat, or sent more than 48 hours ago: either way it cannot be deleted.
                log.info("Telegram would not delete copy %s, leaving it: %s", telegram_message_id, exc)
            self._store.forget_telegram_copy(telegram_message_id)
        if failed and not self._failing:
            log.warning("could not delete old Telegram copies, will keep trying: %s", failed)
        elif not failed and self._failing:
            log.info("deleting old Telegram copies works again")
        self._failing = failed is not None
