"""Messages delivered by a Modem are stored and shown on the web page."""

import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for


@pytest.fixture
def modem():
    return FakeModem(iccid="89886000000000000001", number="+886900000001")


@pytest.fixture
def mailroom(modem, tmp_path):
    return lambda *modems: TestClient(
        create_app(
            FakeTransport(*(modems or (modem,))),
            tmp_path / "mailroom.db",
            poll_interval=0.3,
            scan_interval=0.05,
        )
    )


def shown_messages(page) -> list[str]:
    return re.findall(r'<span class="text">(.*?)</span>', page.get("/").text, flags=re.S)


def test_message_delivered_to_a_modem_appears_on_the_page(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("0912345678", "Your code is 123456", encoding="gsm7"))

        wait_for(lambda: shown_messages(page))
        html = page.get("/").text

    assert "Your code is 123456" in html
    assert "0912345678" in html
    assert "+886900000001" in html  # the SIM that received it
    assert "2026-10-11 23:34:07" in html


def test_page_says_so_when_there_are_no_messages(mailroom):
    with mailroom() as page:
        assert "No Messages yet." in page.get("/").text


@pytest.mark.parametrize("text", ["測試 test 123", "验证码 504126，请勿泄露", "繁體與简体 mixed 內容"])
def test_chinese_text_is_displayed_correctly(modem, mailroom, text):
    with mailroom() as page:
        modem.deliver(build_pdu("10086", text))

        assert wait_for(lambda: shown_messages(page)) == [text]


def test_times_are_shown_in_taipei_time(modem, mailroom):
    tokyo = timezone(timedelta(hours=9))
    with mailroom() as page:
        modem.deliver(build_pdu("12345", "hi", sent_at=datetime(2026, 3, 1, 0, 30, 0, tzinfo=tokyo)))

        wait_for(lambda: shown_messages(page))
        assert "2026-02-28 23:30:00" in page.get("/").text


def test_messages_are_listed_newest_first(modem, mailroom):
    taipei = timezone(timedelta(hours=8))
    with mailroom() as page:
        for hour, text in [(10, "middle"), (9, "oldest"), (11, "newest")]:
            modem.deliver(build_pdu("12345", text, sent_at=datetime(2026, 5, 1, hour, tzinfo=taipei)))

        wait_for(lambda: len(shown_messages(page)) == 3)
        assert shown_messages(page) == ["newest", "middle", "oldest"]


def test_message_is_stored_once_and_removed_from_the_sim(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("12345", "only once"))
        wait_for(lambda: not modem.stored)
        modem.deliver(build_pdu("12345", "only once"))  # the same PDU turns up again
        wait_for(lambda: not modem.stored)

        assert shown_messages(page) == ["only once"]


def test_messages_already_on_the_sim_at_startup_are_collected(modem, mailroom):
    modem.deliver(build_pdu("12345", "arrived while down"), announce=False)

    with mailroom() as page:
        assert wait_for(lambda: shown_messages(page)) == ["arrived while down"]


def test_missed_indication_only_delays_a_message(modem, mailroom):
    with mailroom() as page:
        wait_for(lambda: page.get("/").status_code == 200)
        modem.deliver(build_pdu("12345", "no indication"), announce=False)

        assert wait_for(lambda: shown_messages(page)) == ["no indication"]


def test_messages_survive_a_restart(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("12345", "kept"))
        wait_for(lambda: shown_messages(page))

    with mailroom() as page:
        assert shown_messages(page) == ["kept"]


def test_each_message_is_shown_with_the_sim_that_received_it(mailroom):
    taiwan = FakeModem(iccid="89886000000000000001", number="+886900000001")
    unnamed = FakeModem(iccid="89860000000000004832", number=None)
    with mailroom(taiwan, unnamed) as page:
        taiwan.deliver(build_pdu("111", "to taiwan"))
        unnamed.deliver(build_pdu("222", "to unnamed"))
        wait_for(lambda: len(shown_messages(page)) == 2)
        html = page.get("/").text

    by_text = {text: sim for sim, text in re.findall(r'class="sim-label">(.*?)</span>.*?class="text">(.*?)</span>', html, flags=re.S)}
    assert by_text == {"to taiwan": "+886900000001", "to unnamed": "SIM …4832"}


def test_message_text_cannot_inject_markup(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("12345", "<script>alert(1)</script>"))
        wait_for(lambda: shown_messages(page))

        assert "<script>alert(1)</script>" not in page.get("/").text


def test_modem_without_a_readable_sim_does_not_disturb_other_modems(mailroom):
    working = FakeModem(iccid="89886000000000000001")
    empty = FakeModem(iccid="89860000000000000002")
    empty.sim_present = False
    with mailroom(empty, working) as page:
        working.deliver(build_pdu("111", "still works"))

        assert wait_for(lambda: shown_messages(page)) == ["still works"]


def test_modem_starts_receiving_once_its_sim_becomes_readable(modem, mailroom):
    modem.sim_present = False
    with mailroom() as page:
        assert page.get("/").status_code == 200
        modem.deliver(build_pdu("111", "after the SIM was seated"), announce=False)
        modem.sim_present = True

        assert wait_for(lambda: shown_messages(page)) == ["after the SIM was seated"]


def test_freshly_attached_modem_waits_quietly_for_its_sim(modem, mailroom, caplog):
    modem.sim_present = False
    with caplog.at_level(logging.INFO), mailroom() as page:
        wait_for(lambda: "waiting for its SIM" in caplog.text)
        assert "(starting)" in page.get("/status").text
        modem.deliver(build_pdu("111", "once the SIM was ready"), announce=False)
        modem.sim_present = True

        assert wait_for(lambda: shown_messages(page)) == ["once the SIM was ready"]
    assert "cannot receive" not in caplog.text


def test_sim_that_never_answers_is_reported(modem, mailroom, monkeypatch):
    monkeypatch.setattr("mailroom.receiver._SIM_READY_WITHIN", 0.5)
    modem.sim_present = False
    with mailroom() as page:
        assert wait_for(lambda: "cannot receive: AT+CICCID: +CME ERROR: SIM not inserted" in page.get("/status").text)


def test_same_sms_delivered_twice_through_different_service_centres_is_stored_once(modem, mailroom):
    # Captured from China Mobile: two deliveries eleven bytes apart only in the service centre address.
    first = build_pdu("10086910", "验证码 662022")
    second = first.replace("0791889623844906", "0791889623844916", 1)
    assert first != second
    with mailroom() as page:
        modem.deliver(first)
        wait_for(lambda: not modem.stored)
        modem.deliver(second)
        wait_for(lambda: not modem.stored)

        assert shown_messages(page) == ["验证码 662022"]


def test_same_text_sent_again_later_is_a_new_message(modem, mailroom):
    taipei = timezone(timedelta(hours=8))
    with mailroom() as page:
        for minute in (1, 2):
            modem.deliver(build_pdu("12345", "ok", sent_at=datetime(2026, 5, 1, 9, minute, tzinfo=taipei)))

        wait_for(lambda: len(shown_messages(page)) == 2)


def test_what_a_modem_reports_about_the_network_is_logged(modem, mailroom, caplog):
    with caplog.at_level(logging.INFO), mailroom():
        wait_for(lambda: "AT+CEREG=2" in modem.settings and "AT+CGEREP=2,0" in modem.settings)
        modem.report("+CGEV: NW PDN DEACT 2")

        wait_for(lambda: "Modem 860000000000001 reported +CGEV: NW PDN DEACT 2" in caplog.text)


def test_new_message_indication_is_not_logged_as_a_report(modem, mailroom, caplog):
    with caplog.at_level(logging.INFO), mailroom() as page:
        modem.deliver(build_pdu("0912345678", "hello"))
        wait_for(lambda: shown_messages(page))

    assert "reported" not in caplog.text
