"""Modems can be plugged in, unplugged and re-seated while Mailroom is running."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def page(transport, tmp_path):
    app = create_app(transport, tmp_path / "mailroom.db", poll_interval=0.3, scan_interval=0.05)
    with TestClient(app) as client:
        yield client


def shown_messages(page) -> list[str]:
    return re.findall(r'<span class="text">(.*?)</span>', page.get("/").text, flags=re.S)


def shown_modems(page) -> list[str]:
    return re.findall(r'class="modem">(\d+) ', page.get("/status").text)


def first_modem() -> FakeModem:
    return FakeModem(iccid="89886000000000000001", imei="860000000000001")


def second_modem() -> FakeModem:
    return FakeModem(iccid="89860000000000000002", imei="860000000000002")


def test_modem_plugged_in_after_startup_starts_receiving(transport, page):
    assert "No Modems attached." in page.get("/status").text
    modem = first_modem()

    transport.plug(modem)
    wait_for(lambda: shown_modems(page) == [modem.imei])
    modem.deliver(build_pdu("111", "hello"))

    assert wait_for(lambda: shown_messages(page)) == ["hello"]


def test_messages_waiting_on_a_newly_plugged_modem_are_collected(transport, page):
    modem = first_modem()
    modem.deliver(build_pdu("111", "was waiting"), announce=False)

    transport.plug(modem)

    assert wait_for(lambda: shown_messages(page)) == ["was waiting"]


def test_unplugging_a_modem_leaves_the_others_receiving(transport, page):
    staying, leaving = first_modem(), second_modem()
    transport.plug(staying)
    transport.plug(leaving)
    wait_for(lambda: len(shown_modems(page)) == 2)

    transport.unplug(leaving)
    wait_for(lambda: shown_modems(page) == [staying.imei])
    staying.deliver(build_pdu("111", "still here"))

    assert wait_for(lambda: shown_messages(page)) == ["still here"]
    wait_for(lambda: leaving.times_closed == 1)


def test_modem_that_is_unplugged_and_plugged_back_in_resumes(transport, page):
    modem = first_modem()
    transport.plug(modem)
    wait_for(lambda: shown_modems(page))
    transport.unplug(modem)
    wait_for(lambda: not shown_modems(page))

    modem.deliver(build_pdu("111", "arrived while unplugged"), announce=False)
    transport.plug(modem)

    assert wait_for(lambda: shown_messages(page)) == ["arrived while unplugged"]


def test_link_that_fails_while_the_modem_stays_attached_is_reopened(transport, page):
    modem = first_modem()
    transport.plug(modem)
    wait_for(lambda: shown_modems(page))

    modem.link_failures = 1
    wait_for(lambda: modem.times_closed == 1)
    modem.deliver(build_pdu("111", "after the link came back"))

    assert wait_for(lambda: shown_messages(page)) == ["after the link came back"]


def test_modem_that_cannot_be_opened_is_retried(transport, page):
    modem = first_modem()
    transport.refuse_to_open = True
    transport.plug(modem)
    modem.deliver(build_pdu("111", "eventually"), announce=False)
    assert page.get("/").status_code == 200

    transport.refuse_to_open = False

    assert wait_for(lambda: shown_messages(page)) == ["eventually"]
