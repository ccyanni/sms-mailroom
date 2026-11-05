"""When switched on, Telegram copies are deleted some hours after they were sent, so a leaked bot token cannot collect the history."""

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from mailroom import config
from mailroom.pdu import decode_deliver
from mailroom.store import Store
from support import build_pdu, wait_for
from test_archive import message_id, shown
from test_telegram_buttons import FakeBot, receive

# The FakeBot, modem and mailroom fixtures come from test_telegram_buttons.
from test_telegram_buttons import bot, mailroom, modem  # noqa: F401


def kept(**options):
    return {"telegram_keep": timedelta(seconds=0.3), "telegram_keep_check_every": 0.05, **options}


def test_copy_is_deleted_from_telegram_once_it_is_old_enough_and_the_message_stays(modem, bot, mailroom):
    with mailroom(**kept()) as page:
        copy = receive(modem, bot, page, "code 123456")
        wait_for(lambda: copy in bot.deleted)

        assert shown(page) == ["code 123456"]


def test_copy_is_kept_until_then(modem, bot, mailroom):
    with mailroom(**kept(telegram_keep=timedelta(hours=1))) as page:
        receive(modem, bot, page, "fresh")
        time.sleep(0.3)

    assert bot.delete_attempts == []


def test_copy_of_a_message_deleted_for_good_is_deleted_from_telegram_at_once(modem, bot, mailroom):
    with mailroom(**kept(telegram_keep=timedelta(hours=1))) as page:
        copy = receive(modem, bot, page, "gone from the page")
        page.post(f"/messages/{message_id(page, 'gone from the page')}/delete")
        page.post("/trash/empty")
        wait_for(lambda: copy in bot.deleted)


def test_copy_telegram_no_longer_lets_the_bot_delete_is_given_up(modem, bot, mailroom):
    with mailroom(**kept()) as page:
        bot.too_old_to_delete.add(101)
        receive(modem, bot, page, "sent while Mailroom was down for days")
        wait_for(lambda: bot.delete_attempts)
        time.sleep(0.3)

    assert bot.delete_attempts == [101]


def test_copy_that_could_not_be_deleted_for_now_is_deleted_later(modem, bot, mailroom):
    bot.deleting_fails_with = OSError("could not connect")
    with mailroom(**kept()) as page:
        copy = receive(modem, bot, page, "try again")
        wait_for(lambda: len(bot.delete_attempts) >= 2)
        bot.deleting_fails_with = None
        wait_for(lambda: copy in bot.deleted)


def test_without_a_keep_time_copies_are_never_deleted(modem, bot, mailroom):
    with mailroom() as page:
        receive(modem, bot, page, "kept forever")
        time.sleep(0.3)

    assert bot.delete_attempts == []


def write_config(tmp_path, lines: str):
    path = tmp_path / "config.toml"
    path.write_text('[telegram]\ntoken = "1:a"\nchat_id = 1\n' + lines)
    return path


def test_copies_are_kept_unless_deleting_them_is_switched_on(tmp_path):
    assert config.load(write_config(tmp_path, "")).telegram_keep is None
    assert config.load(write_config(tmp_path, "delete_copies = false\ndelete_after_hours = 6\n")).telegram_keep is None


def test_switched_on_copies_are_deleted_after_24_hours_unless_the_config_says_otherwise(tmp_path):
    assert config.load(write_config(tmp_path, "delete_copies = true\n")).telegram_keep == timedelta(hours=24)
    assert config.load(write_config(tmp_path, "delete_copies = true\ndelete_after_hours = 1\n")).telegram_keep == timedelta(hours=1)
    assert config.load(write_config(tmp_path, "delete_copies = true\ndelete_after_hours = 47\n")).telegram_keep == timedelta(hours=47)


@pytest.mark.parametrize("hours", ["0", "48", "100", "-1", "1.5", '"6"', "true"])
def test_keep_time_telegram_would_not_honour_is_refused(tmp_path, hours):
    with pytest.raises(ValueError, match="delete_after_hours"):
        config.load(write_config(tmp_path, f"delete_copies = true\ndelete_after_hours = {hours}\n"))


def test_switch_must_be_true_or_false(tmp_path):
    with pytest.raises(ValueError, match="delete_copies"):
        config.load(write_config(tmp_path, 'delete_copies = "yes"\n'))


def test_copies_recorded_before_they_had_a_sent_time_are_dated_by_their_message(tmp_path):
    path = tmp_path / "mailroom.db"
    store = Store(path)
    store.register_sim("8988600", None)
    pdu = build_pdu("111", "old copy")
    store.add_message("8988600", pdu, decode_deliver(pdu))
    store.close()
    db = sqlite3.connect(path)
    with db:  # the table as it was before copies had a sent time
        db.execute("DROP TABLE telegram_copies")
        db.execute("CREATE TABLE telegram_copies (telegram_message_id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL)")
        db.execute("INSERT INTO telegram_copies VALUES (101, 1)")
        db.execute("UPDATE messages SET received_at = '2026-11-01T00:00:00+00:00'")
    db.close()

    store = Store(path)
    assert store.telegram_copies(1) == [101]
    assert store.telegram_copies_to_delete(sent_before=datetime(2026, 11, 2, tzinfo=timezone.utc)) == [101]
    assert store.telegram_copies_to_delete(sent_before=datetime(2026, 10, 31, tzinfo=timezone.utc)) == []
    store.close()
