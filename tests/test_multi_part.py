"""A long SMS the network split into Parts reaches the owner as one Message."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_pdu import PART_1_OF_2, PART_2_OF_2

CAPTURED_TEXT = (
    "(验证密码)504126，尊敬的用户，您的号码正在一个新设备上登录中国移动 APP，"
    "该验证码5分钟内有效。请勿泄露或转发他人，谨防被骗。【中国移动】"
)
PART_TIMEOUT = 0.4


@pytest.fixture
def modem():
    return FakeModem()


@pytest.fixture
def mailroom(modem, tmp_path):
    def start(*modems, part_timeout=60.0):
        return TestClient(
            create_app(
                FakeTransport(*(modems or (modem,))),
                tmp_path / "mailroom.db",
                poll_interval=0.3,
                scan_interval=0.05,
                part_timeout=part_timeout,
            )
        )
    return start


def shown(page) -> list[tuple[str, bool]]:
    """(text, is marked incomplete) for each Message on the page."""
    items = re.findall(r'<li class="message">(.*?)</li>', page.get("/").text, flags=re.S)
    return [
        (re.search(r'<span class="text">(.*?)</span>', item, flags=re.S).group(1), "incomplete" in item)
        for item in items
    ]


def part(text: str, sequence: int, total: int, reference: int = 7, sender: str = "12345") -> str:
    return build_pdu(sender, text, part=(reference, total, sequence))


def test_captured_parts_stored_in_reverse_order_become_one_message(modem, mailroom):
    with mailroom() as page:
        modem.deliver(PART_2_OF_2)
        modem.deliver(PART_1_OF_2)

        assert wait_for(lambda: shown(page)) == [(CAPTURED_TEXT, False)]


def test_parts_are_joined_in_sequence_order_whatever_order_they_arrive_in(modem, mailroom):
    with mailroom() as page:
        for sequence, text in [(3, "three"), (1, "one "), (2, "two ")]:
            modem.deliver(part(text, sequence, total=3))

        assert wait_for(lambda: shown(page)) == [("one two three", False)]


def test_message_is_not_shown_while_its_parts_are_still_arriving(modem, mailroom):
    with mailroom() as page:
        modem.deliver(part("first half, ", 1, total=2))
        wait_for(lambda: not modem.stored)

        assert shown(page) == []


def test_message_missing_a_part_is_shown_as_incomplete_after_the_timeout(modem, mailroom):
    with mailroom(part_timeout=PART_TIMEOUT) as page:
        modem.deliver(part("start ", 1, total=3))
        modem.deliver(part(" end", 3, total=3))

        assert wait_for(lambda: shown(page)) == [("start […] end", True)]


def test_late_part_completes_the_existing_message(modem, mailroom):
    with mailroom(part_timeout=PART_TIMEOUT) as page:
        modem.deliver(part("first half, ", 1, total=2))
        wait_for(lambda: shown(page) == [("first half, […]", True)])

        modem.deliver(part("second half", 2, total=2))

        assert wait_for(lambda: shown(page) == [("first half, second half", False)])


def test_duplicate_part_changes_nothing(modem, mailroom):
    with mailroom() as page:
        modem.deliver(part("a", 1, total=2))
        modem.deliver(part("a", 1, total=2))
        modem.deliver(part("b", 2, total=2))
        wait_for(lambda: not modem.stored)

        assert shown(page) == [("ab", False)]


def test_parts_from_different_senders_are_not_mixed(modem, mailroom):
    with mailroom() as page:
        modem.deliver(part("A1 ", 1, total=2, sender="111"))
        modem.deliver(part("B1 ", 1, total=2, sender="222"))
        modem.deliver(part("B2", 2, total=2, sender="222"))
        modem.deliver(part("A2", 2, total=2, sender="111"))

        assert sorted(wait_for(lambda: len(shown(page)) == 2 and shown(page))) == [
            ("A1 A2", False),
            ("B1 B2", False),
        ]


def test_parts_on_different_sims_are_not_mixed(mailroom):
    one = FakeModem(iccid="89886000000000000001", imei="860000000000001")
    two = FakeModem(iccid="89860000000000000002", imei="860000000000002")
    with mailroom(one, two, part_timeout=PART_TIMEOUT) as page:
        one.deliver(part("for one ", 1, total=2))
        two.deliver(part("for two", 2, total=2))

        assert sorted(wait_for(lambda: len(shown(page)) == 2 and shown(page))) == [
            ("[…]for two", True),
            ("for one […]", True),
        ]


def test_reused_reference_starts_a_new_message(modem, mailroom):
    with mailroom() as page:
        for text in ("first ", "second "):
            modem.deliver(part(text + "1/2 ", 1, total=2))
            modem.deliver(part(text + "2/2", 2, total=2))

        assert sorted(wait_for(lambda: len(shown(page)) == 2 and shown(page))) == [
            ("first 1/2 first 2/2", False),
            ("second 1/2 second 2/2", False),
        ]


def test_messages_stored_by_the_first_schema_are_joined_on_upgrade(modem, mailroom, tmp_path):
    db = sqlite3.connect(tmp_path / "mailroom.db")
    db.executescript(
        """
        CREATE TABLE sims (iccid TEXT PRIMARY KEY, label TEXT NOT NULL, number TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, sim_iccid TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL,
            sent_at TEXT NOT NULL, received_at TEXT NOT NULL, pdu TEXT NOT NULL, UNIQUE (sim_iccid, pdu));
        INSERT INTO sims VALUES ('89860000000000004832', 'China Mobile', '+8613800000000');
        """
    )
    single = build_pdu("12345", "on its own")
    for pdu in (PART_2_OF_2, PART_1_OF_2, single):
        db.execute(
            "INSERT INTO messages (sim_iccid, sender, text, sent_at, received_at, pdu) "
            "VALUES ('89860000000000004832', '?', '?', '2026-10-11T15:58:44+00:00', '2026-10-11T17:29:54+00:00', ?)",
            (pdu,),
        )
    db.commit()
    db.close()

    with mailroom() as page:
        assert sorted(shown(page)) == sorted([(CAPTURED_TEXT, False), ("on its own", False)])
        assert "China Mobile" in page.get("/").text
