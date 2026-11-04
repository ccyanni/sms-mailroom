"""Deleting moves a Message to the Trash, where it can be restored for 30 days before it is deleted for good."""

import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_archive import CHINA, TAIWAN, TEXTS, archive, message_id, shown
from test_forwarding import FakeTelegram

FORM = {"content-type": "application/x-www-form-urlencoded"}


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def modems():
    return (
        FakeModem(iccid=TAIWAN, number="+886900000001", imei="860000000000001"),
        FakeModem(iccid=CHINA, number="+8613800000000", imei="860000000000002"),
    )


@pytest.fixture
def mailroom(modems, telegram, tmp_path):
    return lambda **options: TestClient(
        create_app(
            FakeTransport(*modems),
            tmp_path / "mailroom.db",
            poll_interval=0.2,
            scan_interval=0.05,
            part_timeout=0.3,
            telegram=TelegramSettings("123:token", "4242"),
            http_post=telegram,
            forward_interval=0.05,
            **options,
        )
    )


@pytest.fixture
def page(modems, mailroom):
    taiwan, china = modems
    with mailroom(trash_check_every=0.05) as client:
        for index, text in enumerate(TEXTS):
            (china if "spam" in text else taiwan).deliver(build_pdu(f"sender{index}", text))
        wait_for(lambda: len(shown(client)) == 4)
        yield client


def delete(page, text: str, **params) -> None:
    page.post(f"/messages/{message_id(page, text, **params)}/delete")


def in_trash(page, **params) -> list[str]:
    return shown(page, box="trash", **params)


def bulk(page, action: str, ids: list[int]):
    return page.post(action, content="&".join(f"id={value}" for value in ids), headers=FORM)


def age_trash(db_path, days: float) -> None:
    """Pretend everything in the Trash was deleted `days` ago."""
    db = sqlite3.connect(db_path)
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    db.execute("UPDATE messages SET deleted_at = ? WHERE deleted_at IS NOT NULL", (moment.isoformat(),))
    db.commit()
    db.close()


def test_deleted_message_moves_from_the_inbox_to_the_trash(page):
    delete(page, "spam one")

    assert sorted(shown(page)) == ["bank code 123456", "electricity bill", "spam two"]
    assert in_trash(page) == ["spam one"]


def test_deleted_message_leaves_the_archive_for_the_trash(page):
    archive(page, "electricity bill")
    delete(page, "electricity bill", box="archived")

    assert shown(page, box="archived") == []
    assert in_trash(page) == ["electricity bill"]


def test_deleting_needs_no_confirmation_but_deleting_for_good_does(page):
    assert "This cannot be undone." not in page.get("/").text

    delete(page, "spam one")
    trash = page.get("/", params={"box": "trash"}).text

    assert re.search(r'<details class="confirm">.*?This cannot be undone\..*?/purge', trash, flags=re.S)


def test_several_selected_messages_move_to_the_trash_together(page):
    bulk(page, "/messages/delete", [message_id(page, "spam one"), message_id(page, "spam two")])

    assert sorted(in_trash(page)) == ["spam one", "spam two"]


def test_trash_shows_its_count_beside_the_other_boxes(page):
    archive(page, "electricity bill")
    delete(page, "spam one")
    html = page.get("/").text

    assert "Inbox 2" in html and "Archived 1" in html and "Trash 1" in html


def test_search_and_sim_filter_work_in_the_trash(page):
    delete(page, "spam one")
    delete(page, "bank code 123456")

    assert in_trash(page, q="spam") == ["spam one"]
    assert in_trash(page, sim=TAIWAN) == ["bank code 123456"]
    assert shown(page, q="spam") == ["spam two"]
    assert "Trash 1" in page.get("/", params={"q": "spam"}).text


def test_trash_says_how_many_days_each_message_has_left(page, tmp_path):
    delete(page, "spam one")
    assert "Deleted for good in 30 days" in page.get("/", params={"box": "trash"}).text

    age_trash(tmp_path / "mailroom.db", 27.5)
    assert "Deleted for good in 3 days" in page.get("/", params={"box": "trash"}).text


def test_restored_message_goes_back_where_it_was(page):
    archive(page, "electricity bill")
    delete(page, "electricity bill", box="archived")
    delete(page, "spam one")

    page.post(f"/messages/{message_id(page, 'electricity bill', box='trash')}/restore")
    bulk(page, "/messages/restore", [message_id(page, "spam one", box="trash")])

    assert shown(page, box="archived") == ["electricity bill"]
    assert "spam one" in shown(page)
    assert in_trash(page) == []


def test_message_in_the_trash_can_be_deleted_for_good(page):
    delete(page, "spam one")
    delete(page, "spam two")

    page.post(f"/messages/{message_id(page, 'spam one', box='trash')}/purge")
    assert in_trash(page) == ["spam two"]

    bulk(page, "/messages/purge", [message_id(page, "spam two", box="trash")])
    assert in_trash(page) == []
    assert len(shown(page)) == 2


def test_emptying_the_trash_deletes_everything_in_it_and_nothing_else(page):
    delete(page, "spam one")
    delete(page, "spam two")

    page.post("/trash/empty")

    assert in_trash(page) == []
    assert sorted(shown(page)) == ["bank code 123456", "electricity bill"]


def test_only_a_message_in_the_trash_can_be_deleted_for_good(page):
    target = message_id(page, "bank code 123456")

    page.post(f"/messages/{target}/purge")
    bulk(page, "/messages/purge", [target])

    assert "bank code 123456" in shown(page)


def test_deleting_for_good_also_needs_a_valid_origin(page):
    delete(page, "spam one")
    target = message_id(page, "spam one", box="trash")
    evil = {"Origin": "https://evil.example"}

    assert page.post(f"/messages/{target}/purge", headers=evil).status_code == 403
    assert page.post("/trash/empty", headers=evil).status_code == 403
    assert in_trash(page) == ["spam one"]


def test_message_is_deleted_for_good_after_30_days_in_the_trash(page, tmp_path):
    delete(page, "spam one")
    delete(page, "spam two")
    age_trash(tmp_path / "mailroom.db", 29.9)
    time.sleep(0.2)
    assert len(in_trash(page)) == 2

    age_trash(tmp_path / "mailroom.db", 30.1)
    wait_for(lambda: in_trash(page) == [])
    assert len(shown(page)) == 2


def test_old_trash_is_emptied_when_the_service_starts(modems, mailroom, tmp_path):
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "junk from a month ago"))
        wait_for(lambda: shown(client))
        delete(client, "junk from a month ago")
    age_trash(tmp_path / "mailroom.db", 45)

    with mailroom() as client:
        assert in_trash(client) == []


def test_message_in_the_trash_is_not_forwarded_until_restored(modems, mailroom, telegram):
    telegram.down = True
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "waiting for Telegram"))
        wait_for(lambda: shown(client))
        delete(client, "waiting for Telegram")
        telegram.down = False
        time.sleep(0.3)
        assert telegram.texts == []

        client.post(f"/messages/{message_id(client, 'waiting for Telegram', box='trash')}/restore")
        wait_for(lambda: telegram.texts)
        assert "waiting for Telegram" in telegram.texts[0]


def test_late_part_joins_its_message_in_the_trash(modems, mailroom):
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "first half, ", part=(7, 2, 1)))
        wait_for(lambda: shown(client))
        delete(client, "first half")

        modems[0].deliver(build_pdu("111", "second half", part=(7, 2, 2)))
        wait_for(lambda: in_trash(client) == ["first half, second half"])
        assert shown(client) == []


def test_repeat_of_a_message_in_the_trash_is_not_stored_again(modems, mailroom):
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "sent twice"))
        wait_for(lambda: shown(client))
        delete(client, "sent twice")

        modems[0].deliver(build_pdu("111", "sent twice"))
        wait_for(lambda: not modems[0].stored)
        time.sleep(0.2)
        assert shown(client) == []
        assert in_trash(client) == ["sent twice"]


def test_text_deleted_for_good_is_not_left_in_the_database_file(page, tmp_path):
    delete(page, "spam one")
    page.post("/trash/empty")

    assert b"spam one" not in (tmp_path / "mailroom.db").read_bytes()


def test_existing_database_is_upgraded_with_nothing_in_the_trash(modems, mailroom, tmp_path):
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "from before the Trash existed"))
        wait_for(lambda: shown(client))
    db = sqlite3.connect(tmp_path / "mailroom.db")
    db.execute("ALTER TABLE messages DROP COLUMN deleted_at")
    db.execute("PRAGMA user_version = 7")
    db.commit()
    db.close()

    with mailroom() as client:
        assert shown(client) == ["from before the Trash existed"]
        assert in_trash(client) == []


def test_upgrade_clears_text_an_earlier_version_left_in_freed_space(modems, mailroom, tmp_path):
    db_path = tmp_path / "mailroom.db"
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "kept"))
        modems[0].deliver(build_pdu("222", "deleted long ago"))
        wait_for(lambda: len(shown(client)) == 2)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA secure_delete = OFF")  # how earlier versions deleted
    db.execute("DELETE FROM parts WHERE message_id IN (SELECT id FROM messages WHERE sender = '222')")
    db.execute("DELETE FROM messages WHERE sender = '222'")
    db.execute("ALTER TABLE messages DROP COLUMN deleted_at")
    db.execute("PRAGMA user_version = 7")
    db.commit()
    db.close()
    assert b"deleted long ago" in db_path.read_bytes()  # otherwise this test proves nothing

    with mailroom() as client:
        assert shown(client) == ["kept"]
    assert b"deleted long ago" not in db_path.read_bytes()
