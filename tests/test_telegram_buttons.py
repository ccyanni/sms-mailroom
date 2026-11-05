"""The owner archives or deletes a Message with the buttons under its Telegram copy."""

import logging
import queue
import re
import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

from mailroom import config
from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_archive import message_id, shown

TOKEN, OWNER, STRANGER = "123:secret-token", 4242, 9999


class FakeBot:
    """Telegram's Bot API as Mailroom uses it: sends, edits, answers, and button presses to hand out."""

    def __init__(self) -> None:
        self.sent: list[dict] = []  # sendMessage payloads, each given a Telegram message id
        self.edits: dict[int, dict] = {}  # the latest editMessageText payload for each Telegram message
        self.answers: list[dict] = []
        self.polls = 0
        self.polling_fails_with: Exception | None = None
        self.polling_failures_left: int | None = None  # None: keeps failing for as long as polling_fails_with is set
        self._presses: queue.Queue[dict] = queue.Queue()
        self._next_update = 1
        self.while_sending = None  # called once, in the middle of the next sendMessage
        self.deleted: list[int] = []
        self.delete_attempts: list[int] = []
        self.too_old_to_delete: set[int] = set()  # Telegram lets a bot delete only what it sent in the last 48 hours
        self.deleting_fails_with: Exception | None = None

    def __call__(self, url: str, payload: dict):
        assert url.startswith(f"https://api.telegram.org/bot{TOKEN}/")
        method = url.rsplit("/", 1)[1]
        if method == "sendMessage":
            if self.while_sending:
                meanwhile, self.while_sending = self.while_sending, None
                meanwhile()
            self.sent.append(payload)
            return {"message_id": 100 + len(self.sent)}
        if method == "editMessageText":
            self.edits[payload["message_id"]] = payload
            return {"message_id": payload["message_id"]}
        if method == "deleteMessage":
            self.delete_attempts.append(payload["message_id"])
            if self.deleting_fails_with:
                raise self.deleting_fails_with
            if payload["message_id"] in self.too_old_to_delete:
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
            self.deleted.append(payload["message_id"])
            return True
        if method == "answerCallbackQuery":
            self.answers.append(payload)
            return True
        if method == "getUpdates":
            self.polls += 1
            assert payload["allowed_updates"] == ["callback_query"]
            if self.polling_fails_with and self.polling_failures_left != 0:
                if self.polling_failures_left is not None:
                    self.polling_failures_left -= 1
                raise self.polling_fails_with
            try:
                return [self._presses.get(timeout=0.05)]
            except queue.Empty:
                return []
        raise AssertionError(f"unexpected Telegram call {method}")

    def press(self, telegram_message_id: int, action: str, sender: int = OWNER, chat: int = OWNER) -> None:
        self._presses.put(
            {
                "update_id": self._next_update,
                "callback_query": {
                    "id": f"press-{self._next_update}",
                    "from": {"id": sender},
                    "message": {"message_id": telegram_message_id, "chat": {"id": chat, "type": "private"}},
                    "data": action,
                },
            }
        )
        self._next_update += 1

    def forwarded(self, text: str) -> int:
        """The Telegram message id of the last copy that carried `text`."""
        return [100 + i + 1 for i, payload in enumerate(self.sent) if text in payload["text"]][-1]

    def buttons(self, telegram_message_id: int) -> list[str]:
        payload = self.edits.get(telegram_message_id) or self.sent[telegram_message_id - 101]
        markup = payload.get("reply_markup", {"inline_keyboard": []})
        return [button["callback_data"] for row in markup["inline_keyboard"] for button in row]

    def text(self, telegram_message_id: int) -> str:
        return (self.edits.get(telegram_message_id) or self.sent[telegram_message_id - 101])["text"]


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def modem():
    return FakeModem(number="+886900000001")


@pytest.fixture
def mailroom(modem, bot, tmp_path):
    def start(**options):
        options.setdefault("telegram_buttons", True)
        return TestClient(
            create_app(
                FakeTransport(modem),
                tmp_path / "mailroom.db",
                poll_interval=0.2,
                scan_interval=0.05,
                part_timeout=0.3,
                telegram=TelegramSettings(TOKEN, str(OWNER)),
                http_post=bot,
                forward_interval=0.05,
                health_interval=0.05,
                **options,
            )
        )
    return start


def in_trash(page) -> list[str]:
    return shown(page, box="trash")


def receive(modem, bot, page, text: str, sender: str = "111") -> int:
    modem.deliver(build_pdu(sender, text))
    wait_for(lambda: any(text in payload["text"] for payload in bot.sent))
    return bot.forwarded(text)


def test_forwarded_message_carries_archive_and_delete_buttons(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "your parcel")

    assert bot.buttons(copy) == ["archive", "trash"]


def test_delete_moves_the_message_to_the_trash_and_takes_the_text_off_telegram(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "spam offer")
        bot.press(copy, "trash")
        wait_for(lambda: in_trash(page) == ["spam offer"])
        wait_for(lambda: copy in bot.edits)
        assert shown(page) == []

    assert "spam offer" not in bot.text(copy)
    assert "Trash" in bot.text(copy) and "111" in bot.text(copy)
    assert bot.buttons(copy) == ["restore"]


def test_restore_brings_the_text_and_buttons_back(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "deleted by mistake")
        bot.press(copy, "trash")
        wait_for(lambda: in_trash(page))
        bot.press(copy, "restore")
        wait_for(lambda: shown(page) == ["deleted by mistake"])
        wait_for(lambda: bot.buttons(copy) == ["archive", "trash"])

    assert "deleted by mistake" in bot.text(copy)


def test_archive_moves_the_message_to_the_archive(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "electricity bill")
        bot.press(copy, "archive")
        wait_for(lambda: shown(page, box="archived") == ["electricity bill"])
        wait_for(lambda: bot.buttons(copy) == ["unarchive", "trash"])

        bot.press(copy, "unarchive")
        wait_for(lambda: shown(page) == ["electricity bill"])


def test_every_press_is_answered(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "anything")
        bot.press(copy, "archive")
        bot.press(copy, "trash")
        wait_for(lambda: len(bot.answers) == 2)

    assert [answer["callback_query_id"] for answer in bot.answers] == ["press-1", "press-2"]
    assert [answer["text"] for answer in bot.answers] == ["Archived", "Moved to the Trash"]


def test_press_acts_on_the_message_as_it_is_now(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "deleted on the page")
        page.post(f"/messages/{message_id(page, 'deleted on the page')}/delete")
        bot.press(copy, "archive")  # an old button, from before it was deleted
        wait_for(lambda: bot.answers)
        wait_for(lambda: copy in bot.edits)
        assert in_trash(page) == ["deleted on the page"]

    assert bot.buttons(copy) == ["restore"]
    assert bot.answers[0]["text"] == "This Message is in the Trash; restore it first"


def test_copy_of_a_message_deleted_for_good_changes_nothing(modem, bot, mailroom):
    with mailroom() as page:
        old = receive(modem, bot, page, "old junk")
        bot.press(old, "trash")
        wait_for(lambda: in_trash(page))
        old_id = message_id(page, "old junk", box="trash")
        page.post("/trash/empty")
        new = receive(modem, bot, page, "new and wanted")
        assert message_id(page, "new and wanted") == old_id  # SQLite reused the id; otherwise this proves nothing

        bot.press(old, "restore")
        bot.press(old, "trash")
        wait_for(lambda: len(bot.answers) == 3)
        assert shown(page) == ["new and wanted"]
        assert in_trash(page) == []

    assert "old junk" not in bot.text(old) and "deleted for good" in bot.text(old)
    assert bot.buttons(old) == []
    assert new not in bot.edits


def test_full_text_sent_after_an_incomplete_copy_also_has_buttons_and_both_are_cleared(modem, bot, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("111", "first half, ", part=(7, 2, 1)))
        wait_for(lambda: bot.sent)
        modem.deliver(build_pdu("111", "second half", part=(7, 2, 2)))
        wait_for(lambda: len(bot.sent) == 2)
        first, full = 101, 102
        assert bot.buttons(full) == ["archive", "trash"]

        bot.press(full, "trash")
        wait_for(lambda: first in bot.edits and full in bot.edits)

    assert "first half" not in bot.text(first) and "first half" not in bot.text(full)


def test_alerts_and_the_start_notice_carry_no_buttons(modem, bot, mailroom):
    with mailroom(start_notice="restart", start_notice_after=0.1):
        wait_for(lambda: bot.sent)

    assert "reply_markup" not in bot.sent[0]


@pytest.mark.parametrize("sender, chat", [(STRANGER, OWNER), (OWNER, STRANGER), (STRANGER, STRANGER)])
def test_press_from_anyone_else_or_anywhere_else_is_ignored(modem, bot, mailroom, sender, chat):
    with mailroom() as page:
        copy = receive(modem, bot, page, "mine alone")
        bot.press(copy, "trash", sender=sender, chat=chat)
        polls = bot.polls
        wait_for(lambda: bot.polls > polls + 2)  # the press has been fetched and dealt with
        time.sleep(0.1)

        assert shown(page) == ["mine alone"]
    assert bot.answers == []
    assert bot.edits == {}


def test_unknown_button_changes_nothing(modem, bot, mailroom):
    with mailroom() as page:
        copy = receive(modem, bot, page, "still here")
        bot.press(copy, "purge")
        wait_for(lambda: bot.answers)

        assert shown(page) == ["still here"]


def test_buttons_can_be_switched_off(modem, bot, mailroom):
    with mailroom(telegram_buttons=False) as page:
        copy = receive(modem, bot, page, "no buttons")
        time.sleep(0.2)

    assert bot.buttons(copy) == []
    assert bot.polls == 0


def test_buttons_are_on_unless_the_config_says_otherwise(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\ntoken = "1:a"\nchat_id = 1\n')
    assert config.load(path).telegram_buttons is True

    path.write_text('[telegram]\ntoken = "1:a"\nchat_id = 1\nbuttons = false\n')
    assert config.load(path).telegram_buttons is False


def test_presses_that_cannot_be_fetched_raise_an_alert_until_they_can(modem, bot, mailroom):
    bot.polling_fails_with = OSError("HTTP Error 409: Conflict")
    with mailroom(alert_after=0.2) as page:
        wait_for(lambda: any("buttons" in payload["text"] for payload in bot.sent))
        alert = [payload["text"] for payload in bot.sent if "buttons" in payload["text"]][0]
        assert "token" in alert
        assert "buttons" in page.get("/status").text

        bot.polling_fails_with = None
        wait_for(lambda: any("work again" in payload["text"] for payload in bot.sent))


def test_token_is_kept_out_of_the_log(modem, bot, mailroom, caplog):
    bot.polling_fails_with = OSError(f"could not reach https://api.telegram.org/bot{TOKEN}/getUpdates")
    with caplog.at_level(logging.WARNING), mailroom():
        wait_for(lambda: bot.polls >= 1)
        wait_for(lambda: "<token>" in caplog.text)

    assert TOKEN not in caplog.text
    assert re.search(r"button presses", caplog.text)


def test_message_deleted_for_good_while_being_sent_does_not_pass_its_copy_to_a_newer_message(modem, bot, mailroom):
    with mailroom() as page:
        def meanwhile():
            old_id = message_id(page, "being sent")
            page.post(f"/messages/{old_id}/delete")
            page.post("/trash/empty")
            modem.deliver(build_pdu("111", "arrived meanwhile"))
            wait_for(lambda: shown(page) == ["arrived meanwhile"])
            assert message_id(page, "arrived meanwhile") == old_id  # SQLite reused the id; otherwise this proves nothing

        bot.while_sending = meanwhile
        old = receive(modem, bot, page, "being sent")
        new = receive(modem, bot, page, "arrived meanwhile")  # forwarded on its own, not taken as already sent
        assert new != old

        bot.press(old, "trash")
        wait_for(lambda: bot.answers)
        assert shown(page) == ["arrived meanwhile"]


def test_a_single_fetch_that_times_out_is_retried_without_a_warning(modem, bot, mailroom, caplog):
    bot.polling_fails_with, bot.polling_failures_left = TimeoutError("The read operation timed out"), 1
    with caplog.at_level(logging.INFO), mailroom():
        wait_for(lambda: bot.polls >= 3)

    assert "button presses" not in caplog.text


def test_fetching_that_keeps_failing_is_warned_about_once(modem, bot, mailroom, caplog):
    bot.polling_fails_with = TimeoutError("The read operation timed out")
    with caplog.at_level(logging.INFO), mailroom(telegram_poll_retry=0.01):
        wait_for(lambda: bot.polls >= 4)
        bot.polling_fails_with = None
        wait_for(lambda: "works again" in caplog.text)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "button presses" in r.getMessage()]
    assert len(warnings) == 1
