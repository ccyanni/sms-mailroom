"""An MMS notice or a data SMS is shown and forwarded as a notice, never as its payload read as letters."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mailroom.pdu import decode_deliver
from mailroom.store import Store
from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_data_pdu, build_pdu, mms_notice, wait_for

ICCID = "89886000000000000001"
MMS_TEXT = "A multimedia message (MMS) arrived."
DATA_TEXT = "A data message meant for an app on a phone arrived."


@pytest.fixture
def modem():
    return FakeModem(iccid=ICCID)


class Telegram(list):
    """Stands in for the HTTPS call to Telegram and keeps the texts sent."""

    def post(self, url: str, payload: dict) -> None:
        self.append(payload["text"])


@pytest.fixture
def telegram():
    return Telegram()


@pytest.fixture
def mailroom(modem, telegram, tmp_path):
    return lambda: TestClient(
        create_app(
            FakeTransport(modem),
            tmp_path / "mailroom.db",
            poll_interval=0.3,
            scan_interval=0.05,
            telegram=TelegramSettings("1:token", "1"),
            http_post=telegram.post,
            forward_interval=0.05,
        )
    )


def shown(page, query: str = "") -> list[str]:
    return re.findall(r'<span class="text(?: notice)?">(.*?)</span>', page.get("/" + query).text, flags=re.S)


def test_mms_notice_is_shown_as_a_notice(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_data_pdu("106570000000", mms_notice(), port=2948))

        (text,) = wait_for(lambda: shown(page))
        html = page.get("/").text

    assert text.startswith(MMS_TEXT)
    assert "106570000000" in html
    assert "mms.example.com" not in html  # its address is fetched over mobile data, which is never used
    assert '<span class="text notice">' in html


def test_mms_notice_is_forwarded_as_a_notice(modem, telegram, mailroom):
    with mailroom():
        modem.deliver(build_data_pdu("106570000000", mms_notice(), port=2948))

        wait_for(lambda: telegram)

    (message,) = telegram
    assert "106570000000" in message
    assert MMS_TEXT in message
    assert "mms.example.com" not in message and "\x00" not in message


def test_data_sms_for_another_application_is_shown_as_a_notice(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_data_pdu("0912345678", bytes(range(0, 40)), port=16000))

        (text,) = wait_for(lambda: shown(page))

    assert text.startswith(DATA_TEXT)


def test_mms_notice_in_two_parts_is_one_notice_whichever_part_arrives_first(modem, mailroom):
    payload = mms_notice("http://mms.example.com/m/" + "x" * 150)
    first, second = payload[:100], payload[100:]
    with mailroom() as page:
        modem.deliver(build_data_pdu("106570000000", second, port=2948, part=(9, 2, 2)))
        modem.deliver(build_data_pdu("106570000000", first, port=2948, part=(9, 2, 1)))

        wait_for(lambda: len(page.get("/").text.split(MMS_TEXT)) == 2)
        texts = shown(page)

    assert len(texts) == 1 and texts[0].startswith(MMS_TEXT)


def test_searching_text_does_not_match_an_mms_payload(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_data_pdu("106570000000", mms_notice(), port=2948))
        wait_for(lambda: shown(page))

        assert shown(page, "?q=example") == []
        assert len(shown(page, "?q=106570000000")) == 1


def test_mms_notice_stored_before_it_was_recognised_is_shown_as_a_notice(tmp_path):
    pdu = build_data_pdu("106570000000", mms_notice(), port=2948)
    store = Store(tmp_path / "mailroom.db")
    store.register_sim(ICCID, "+886900000001")
    text_pdu = build_pdu("0912345678", "hello")
    for each in (pdu, text_pdu):
        store.add_message(ICCID, each, decode_deliver(each))
    garbled = mms_notice().decode("latin-1")  # how earlier versions read it
    db = sqlite3.connect(tmp_path / "mailroom.db")
    db.execute("UPDATE parts SET text = ? WHERE pdu = ?", (garbled, pdu.upper()))
    db.execute("UPDATE messages SET text = ? WHERE sender = '106570000000'", (garbled,))
    db.execute("ALTER TABLE messages DROP COLUMN kind")
    db.execute("PRAGMA user_version = 6")
    db.commit()
    db.close()

    messages = {m.sender: m for m in Store(tmp_path / "mailroom.db").list_messages()}

    assert (messages["106570000000"].kind, messages["106570000000"].text) == ("mms", "")
    assert (messages["0912345678"].kind, messages["0912345678"].text) == ("text", "hello")
