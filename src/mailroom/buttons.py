"""Buttons under each Message's Telegram copy, so the owner can archive or delete it from Telegram.

Presses are fetched from Telegram by long polling: nothing reaches this computer from the internet.
A press is trusted only from the owner's private chat with the bot, and finds its Message through
the copy it was pressed on, never through an id carried in the button.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from mailroom import i18n
from mailroom.forwarder import TAIPEI, format_message
from mailroom.store import Store, StoredMessage
from mailroom.telegram import TelegramBot, TelegramError

log = logging.getLogger(__name__)

ARCHIVE, UNARCHIVE, TRASH, RESTORE = "archive", "unarchive", "trash", "restore"
_LABELS = {ARCHIVE: "archive", UNARCHIVE: "unarchive", TRASH: "delete", RESTORE: "restore"}
_DONE = {ARCHIVE: "tg_archived", UNARCHIVE: "tg_unarchived", TRASH: "tg_trashed", RESTORE: "tg_restored"}
_MAX_RETRY_DELAY = 60.0


def keyboard(language: str, message: StoredMessage) -> dict:
    """The buttons that fit where a Message is now."""
    if message.deleted_at is not None:
        actions = [RESTORE]
    else:
        actions = [UNARCHIVE if message.archived else ARCHIVE, TRASH]
    row = [{"text": i18n.text(language, _LABELS[action]), "callback_data": action} for action in actions]
    return {"inline_keyboard": [row]}


def copy_text(language: str, message: StoredMessage, trash_days: int) -> str:
    """What a Message's Telegram copy says now: the Message, or only who sent it once it is in the Trash."""
    if message.deleted_at is None:
        return format_message(message, language=language)
    time = message.sent_at.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    notice = i18n.text(language, "tg_in_trash", days=trash_days)
    return f"🗑 {message.sim_label} ← {message.sender}\n{time}\n\n{notice}"


class Buttons:
    def __init__(
        self,
        store: Store,
        bot: TelegramBot,
        language: str,
        trash_keep: timedelta,
        poll_timeout: int = 25,
        first_retry: float = 1.0,
    ) -> None:
        self._store = store
        self._bot = bot
        self._language = language
        self._trash_days = trash_keep.days
        self._poll_timeout = poll_timeout
        self._first_retry = first_retry
        self.failing_since: datetime | None = None  # when fetching presses from Telegram stopped working

    def keyboard(self, message: StoredMessage) -> dict:
        return keyboard(self._language, message)

    def run(self, stop: threading.Event) -> None:
        offset: int | None = None
        delay, failures = self._first_retry, 0
        while not stop.is_set():
            try:
                presses = self._bot.button_presses(offset, self._poll_timeout)
            except TelegramError as exc:
                failures += 1
                self.failing_since = self.failing_since or datetime.now(timezone.utc)
                if failures == 1:
                    continue  # a long poll that Telegram leaves unanswered now and then: just ask again
                if failures == 2:
                    log.warning("could not fetch button presses from Telegram, will keep trying: %s", exc)
                if stop.wait(delay):
                    return
                delay = min(delay * 2, _MAX_RETRY_DELAY)
                continue
            if failures > 1:
                log.info("fetching button presses from Telegram works again")
            self.failing_since = None
            delay, failures = self._first_retry, 0
            for update in presses:
                if isinstance(update.get("update_id"), int):
                    offset = update["update_id"] + 1  # Telegram forgets everything before the offset
                try:
                    self.handle(update)
                except Exception:
                    log.exception("could not handle a button press")

    def handle(self, update: dict) -> None:
        press = update.get("callback_query")
        if not isinstance(press, dict):
            return
        copy = press.get("message") or {}
        chat = (copy.get("chat") or {}).get("id")
        presser = (press.get("from") or {}).get("id")
        if str(chat) != self._bot.chat_id or str(presser) != self._bot.chat_id:
            log.warning("ignored a button press from outside the owner's chat")
            return  # no answer: nothing is said to anyone else
        action = press.get("data")
        message = self._store.message_for_telegram_copy(copy.get("message_id"))
        if message is None:
            self._quietly(self._bot.edit, copy.get("message_id"), i18n.text(self._language, "tg_gone"), None)
            self._quietly(self._bot.answer, press["id"], i18n.text(self._language, "tg_gone"))
            return
        if action not in _DONE:
            self._quietly(self._bot.answer, press["id"], i18n.text(self._language, "tg_unknown"))
            return
        done = self._apply(action, message)
        message = self._store.message_for_telegram_copy(copy["message_id"]) or message
        for telegram_message_id in self._store.telegram_copies(message.id):
            text = copy_text(self._language, message, self._trash_days)
            self._quietly(self._bot.edit, telegram_message_id, text, self.keyboard(message))
        said = _DONE[action] if done else "tg_restore_first"
        self._quietly(self._bot.answer, press["id"], i18n.text(self._language, said))

    def _apply(self, action: str, message: StoredMessage) -> bool:
        """Do what the button says, to the Message as it is now: an old button may be out of date.

        Returns False when it could not be done: a Message in the Trash is not archived or moved to the inbox.
        """
        if action == TRASH:
            self._store.move_to_trash([message.id])
        elif action == RESTORE:
            self._store.restore([message.id])
        elif message.deleted_at is None:
            self._store.set_archived(message.id, action == ARCHIVE)
        else:
            return False
        return True

    @staticmethod
    def _quietly(call, *args) -> None:
        """Telegram refuses an edit that changes nothing, or of a copy the owner removed; neither matters."""
        try:
            call(*args)
        except TelegramError as exc:
            log.info("Telegram did not take a button update: %s", exc)
