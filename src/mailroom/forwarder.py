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
        send: Callable[..., object] | None,
        part_timeout: float = 60.0,
        interval: float = 2.0,
        language: str = i18n.DEFAULT_LANGUAGE,
        keyboard: Callable[[StoredMessage], dict] | None = None,
    ) -> None:
        """`send(text, keyboard)` delivers one text to Telegram, returns its Telegram message id if known,
        and raises if it could not; None means Telegram is not set up.

        `keyboard` gives the buttons to put under a Message's copy; None sends it without buttons.
        """
        self._store = store
        self._send = send
        self._keyboard = keyboard
        self._part_timeout = timedelta(seconds=part_timeout)
        self._interval = interval
        self._language = language
        self._failing = False
        self.configured = send is not None
        self.last_sent_at: datetime | None = None  # the last Message Telegram accepted since startup
        self.failing_since: datetime | None = None  # when Telegram stopped accepting Messages

    def run(self, stop: threading.Event) -> None:
        delay = self._interval
        store_failing = False
        while not stop.wait(delay):
            try:
                delivered = self.flush()
            except Exception:  # the Store, not Telegram: a full disk, say. Keep trying, as for Telegram.
                if not store_failing:
                    log.exception("could not forward, will keep trying")
                store_failing, delivered = True, False
            else:
                store_failing = False
            delay = self._interval if delivered else min(delay * 2, _MAX_RETRY_DELAY)

    def flush(self) -> bool:
        """Forward everything owed, oldest first. Returns False if Telegram could not be reached."""
        cutoff = datetime.now(timezone.utc) - self._part_timeout
        message = self._store.next_to_forward(cutoff)
        while message is not None:
            if self._send is None or not message.forwarding:
                self._store.record_forwarding(message, SKIPPED)
            elif not self._forward(message):
                return False
            message = self._store.next_to_forward(cutoff, after_id=message.id)
        return True

    def _forward(self, message: StoredMessage) -> bool:
        """Send one Message; False if Telegram could not be reached."""
        follow_up = message.forward_state == SENT_INCOMPLETE
        text = format_message(message, follow_up, self._language)
        try:
            if self._keyboard is None:
                copy = self._send(text)
            else:
                copy = self._send(text, self._keyboard(message))
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
        state = SENT if message.complete else SENT_INCOMPLETE
        self._store.record_forwarding(message, state, copy if isinstance(copy, int) else None)
        return True


def format_message(message: StoredMessage, follow_up: bool = False, language: str = "en") -> str:
    time = message.sent_at.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"📩 {message.sim_label} ← {message.sender}", time]
    if not message.complete:
        lines.append(i18n.text(language, "message_incomplete"))
    elif follow_up:
        lines.append(i18n.text(language, "message_completed"))
    return "\n".join(lines) + "\n\n" + i18n.message_text(language, message.kind, message.text)
