"""The owner keeps the inbox clean: useful Messages go to the Archive, junk is deleted, several at once if need be."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_forwarding import FakeTelegram

TAIWAN, CHINA = "89886000000000000001", "89860000000000000002"
TEXTS = ["bank code 123456", "spam one", "spam two", "electricity bill"]


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
    return lambda: TestClient(
        create_app(
            FakeTransport(*modems),
            tmp_path / "mailroom.db",
            poll_interval=0.2,
            scan_interval=0.05,
            telegram=TelegramSettings("123:token", "4242"),
            http_post=telegram,
            forward_interval=0.05,
        )
    )


@pytest.fixture
def page(modems, mailroom):
    taiwan, china = modems
    with mailroom() as client:
        for index, text in enumerate(TEXTS):
            (china if "spam" in text else taiwan).deliver(build_pdu(f"sender{index}", text))
        wait_for(lambda: len(shown(client)) == 4)
        yield client


def shown(page, **params) -> list[str]:
    return re.findall(r'class="text">(.*?)</span>', page.get("/", params=params).text, flags=re.S)


def message_id(page, text: str, **params) -> int:
    for item in re.findall(r'<li class="message">(.*?)</li>', page.get("/", params=params).text, flags=re.S):
        if text in item:
            return int(re.search(r"/messages/(\d+)/", item).group(1))
    raise AssertionError(f"{text!r} is not on the page")


def archive(page, text: str) -> None:
    page.post(f"/messages/{message_id(page, text)}/archive", data={"archived": "1"})


def test_archived_message_leaves_the_inbox_for_the_archive(page):
    archive(page, "electricity bill")

    assert sorted(shown(page)) == ["bank code 123456", "spam one", "spam two"]
    assert shown(page, box="archived") == ["electricity bill"]


def test_archived_message_can_be_moved_back(page):
    archive(page, "electricity bill")

    target = message_id(page, "electricity bill", box="archived")
    page.post(f"/messages/{target}/archive", data={"archived": "0"})

    assert len(shown(page)) == 4
    assert shown(page, box="archived") == []


def test_page_shows_how_many_messages_each_box_holds(page):
    archive(page, "electricity bill")
    html = page.get("/").text

    assert "Inbox 3" in html
    assert "Archived 1" in html


def test_box_counts_follow_the_sim_filter_and_the_search(page):
    archive(page, "spam one")

    china, taiwan = page.get("/", params={"sim": CHINA}).text, page.get("/", params={"sim": TAIWAN}).text
    assert "Inbox 1" in china and "Archived 1" in china
    assert "Inbox 2" in taiwan and "Archived 0" in taiwan
    searched = page.get("/", params={"q": "spam two"}).text
    assert "Inbox 1" in searched and "Archived 0" in searched


def test_box_counts_match_what_each_box_lists(page):
    archive(page, "spam one")

    for params in ({}, {"sim": CHINA}, {"q": "spam"}, {"sim": TAIWAN, "q": "bill"}):
        html = page.get("/", params=params).text
        inbox, archived = re.search(r"Inbox (\d+)", html).group(1), re.search(r"Archived (\d+)", html).group(1)
        assert (int(inbox), int(archived)) == (len(shown(page, **params)), len(shown(page, box="archived", **params)))


def test_search_and_sim_filter_work_in_the_archive(page):
    archive(page, "electricity bill")
    archive(page, "spam one")

    assert shown(page, box="archived", q="bill") == ["electricity bill"]
    assert shown(page, box="archived", sim=CHINA) == ["spam one"]
    assert shown(page, q="bill") == []


def test_archiving_keeps_the_filter_the_owner_was_looking_at(page):
    response = page.post(
        f"/messages/{message_id(page, 'spam one')}/archive",
        data={"archived": "1"},
        headers={"referer": f"http://testserver/?sim={CHINA}&q=spam"},
    )

    assert response.url.query.decode() == f"sim={CHINA}&q=spam"


def test_archiving_does_not_forward_the_message_again(page, telegram):
    wait_for(lambda: len(telegram.calls) == 4)

    archive(page, "electricity bill")
    page.post(f"/messages/{message_id(page, 'electricity bill', box='archived')}/archive", data={"archived": "0"})
    import time
    time.sleep(0.3)

    assert len(telegram.calls) == 4


def test_several_selected_messages_are_deleted_in_one_action(page):
    chosen = [message_id(page, "spam one"), message_id(page, "spam two")]

    response = page.post(
        "/messages/delete",
        content="&".join(f"id={value}" for value in chosen),
        headers={"content-type": "application/x-www-form-urlencoded", "referer": "http://testserver/?select=1&q=spam"},
    )

    assert sorted(shown(page)) == ["bank code 123456", "electricity bill"]
    assert response.url.query.decode() == "q=spam"  # selection is over, the search stays


def test_deleting_nothing_changes_nothing(page):
    page.post("/messages/delete", content="", headers={"content-type": "application/x-www-form-urlencoded"})
    page.post("/messages/delete", content="id=abc&id=", headers={"content-type": "application/x-www-form-urlencoded"})

    assert len(shown(page)) == 4


def test_selection_lists_only_what_the_filter_shows(page):
    html = page.get("/", params={"select": "1", "q": "spam"}).text

    picked = re.findall(r'type="checkbox" name="id" value="(\d+)" form="bulk"', html)
    assert sorted(map(int, picked)) == sorted([message_id(page, "spam one"), message_id(page, "spam two")])
    assert 'action="/messages/delete"' in html
    assert "Select all" in html


def test_selection_is_offered_only_when_asked_for(page):
    html = page.get("/").text

    assert 'type="checkbox"' not in html
    assert 'action="/messages/delete"' not in html


def test_bulk_delete_also_needs_a_valid_origin(page):
    target = message_id(page, "spam one")

    response = page.post(
        "/messages/delete",
        content=f"id={target}",
        headers={"content-type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert len(shown(page)) == 4


def test_existing_database_is_upgraded_with_every_message_in_the_inbox(modems, mailroom, tmp_path):
    with mailroom() as client:
        modems[0].deliver(build_pdu("111", "from before the Archive existed"))
        wait_for(lambda: shown(client))
    db = sqlite3.connect(tmp_path / "mailroom.db")
    db.execute("ALTER TABLE messages DROP COLUMN archived")
    db.execute("PRAGMA user_version = 3")
    db.commit()
    db.close()

    with mailroom() as client:
        assert shown(client) == ["from before the Archive existed"]
        assert shown(client, box="archived") == []
