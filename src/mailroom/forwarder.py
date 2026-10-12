"""Forwarding: deliver each Message to the owner's Telegram chat, retrying until it gets there."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from mailroom import i18n
from mailroom.store import SENT, SENT_INCOMPLETE, SKIPPED, Store, StoredMessage

log = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
_MAX_RETRY_DELAY = 60.0


class Forwarder:
    def __init__(
        self,
        store: Store,
        send: Callable[[str], None] | None,
        part_timeout: float = 60.0,
        interval: float = 2.0,
        language: str = i18n.DEFAULT_LANGUAGE,
    ) -> None:
        """`send` delivers one text to Telegram and raises if it could not; None means Telegram is not set up."""
        self._store = store
        self._send = send
        self._part_timeout = timedelta(seconds=part_timeout)
        self._interval = interval
        self._language = language
        self._failing = False
        self.configured = send is not None
        self.last_sent_at: datetime | None = None  # the last Message Telegram accepted since startup
        self.failing_since: datetime | None = None  # when Telegram stopped accepting Messages

    def run(self, stop: threading.Event) -> None:
        delay = self._interval
        while not stop.wait(delay):
            delivered = self.flush()
            delay = self._interval if delivered else min(delay * 2, _MAX_RETRY_DELAY)

    def flush(self) -> bool:
        """Forward everything owed, oldest first. Returns False if Telegram could not be reached."""
        cutoff = datetime.now(timezone.utc) - self._part_timeout
        for message in self._store.awaiting_forwarding(cutoff):
            if self._send is None or not message.forwarding:
                self._store.set_forward_state(message.id, SKIPPED)
                continue
            follow_up = message.forward_state == SENT_INCOMPLETE
            try:
                self._send(format_message(message, follow_up, self._language))
            except Exception as exc:
                if not self._failing:
                    log.warning("could not forward to Telegram, will keep trying: %s", exc)
                self._failing = True
                self.failing_since = self.failing_since or datetime.now(timezone.utc)
                return False
            if self._failing:
                log.info("forwarding to Telegram works again")
            self._failing = False
            self.failing_since = None
            self.last_sent_at = datetime.now(timezone.utc)
            self._store.set_forward_state(message.id, SENT if message.complete else SENT_INCOMPLETE)
        return True


def format_message(message: StoredMessage, follow_up: bool = False, language: str = "en") -> str:
    time = message.sent_at.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"📩 {message.sim_label} ← {message.sender}", time]
    if not message.complete:
        lines.append(i18n.text(language, "message_incomplete"))
    elif follow_up:
        lines.append(i18n.text(language, "message_completed"))
    return "\n".join(lines) + "\n\n" + message.text
