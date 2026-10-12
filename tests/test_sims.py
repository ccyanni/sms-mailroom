"""The owner sees every SIM Mailroom knows and can manage it."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_forwarding import FakeTelegram

ICCID = "89886000000000000001"


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def page(transport, telegram, tmp_path):
    app = create_app(
        transport,
        tmp_path / "mailroom.db",
        poll_interval=0.2,
        scan_interval=0.05,
        telegram=TelegramSettings("123:token", "4242"),
        http_post=telegram,
        forward_interval=0.05,
    )
    with TestClient(app) as client:
        yield client


def sims(page) -> list[dict[str, str]]:
    """What the page shows for each SIM."""
    found = []
    for item in re.findall(r'<li class="sim card">(.*?)</li>', page.get("/status").text, flags=re.S):
        details = dict(re.findall(r'class="(number|operator|signal|registration|last)">(.*?)</span>', item))
        details["label"] = re.search(r'name="label" value="(.*?)"', item).group(1)
        details["forwarding"] = re.search(r"Forwarding (on|off)", item).group(1)
        found.append(details)
    return found


def message_labels(page) -> list[tuple[str, str]]:
    return re.findall(r'class="sim-label">(.*?)</span>.*?class="text">(.*?)</span>', page.get("/").text, flags=re.S)


def plug(transport, page, **modem_options) -> FakeModem:
    modem = FakeModem(**{"iccid": ICCID, "number": "+886900000001", **modem_options})
    transport.plug(modem)
    wait_for(lambda: any(s["registration"] != "not in a Modem" for s in sims(page)))
    return modem


def test_new_sim_is_registered_by_itself_with_forwarding_on(transport, page):
    assert sims(page) == []

    plug(transport, page)

    (sim,) = sims(page)
    assert sim["label"] == sim["number"] == "+886900000001"
    assert sim["forwarding"] == "on"
    assert sim["last"] == "never"


def test_sim_without_a_readable_number_is_labelled_by_its_iccid(transport, page):
    plug(transport, page, iccid="89860000000000004832", number=None)

    (sim,) = sims(page)
    assert sim["label"] == "SIM …4832"
    assert sim["number"] == "number unknown"


def test_page_shows_how_each_sim_is_doing_on_the_network(transport, page):
    modem = plug(transport, page)
    modem.operator, modem.signal, modem.registration = "Far EasTone", 17, 5

    wait_for(lambda: sims(page)[0]["registration"] == "roaming")
    (sim,) = sims(page)
    assert (sim["operator"], sim["signal"]) == ("Far EasTone", "17/31")

    modem.registration, modem.signal = 0, 99
    wait_for(lambda: sims(page)[0]["registration"] == "not registered")
    (sim,) = sims(page)
    assert (sim["operator"], sim["signal"]) == ("–", "–")


def test_page_shows_when_a_sim_last_received_a_message(transport, page):
    modem = plug(transport, page)

    modem.deliver(build_pdu("111", "hi"))

    wait_for(lambda: sims(page)[0]["last"] == "2026-10-11 23:34:07")


def test_renaming_a_sim_relabels_its_messages(transport, telegram, page):
    modem = plug(transport, page)
    modem.deliver(build_pdu("111", "before the rename"))
    wait_for(lambda: message_labels(page))

    response = page.post(f"/sims/{ICCID}/label", data={"label": "  Bank OTP  "})
    modem.deliver(build_pdu("222", "after the rename"))
    wait_for(lambda: len(telegram.calls) == 2)

    assert response.url.path == "/"
    assert sims(page)[0]["label"] == "Bank OTP"
    assert {label for label, _ in message_labels(page)} == {"Bank OTP"}
    assert telegram.texts[1].startswith("📩 Bank OTP ← 222")


def test_blank_label_is_ignored(transport, page):
    plug(transport, page)

    page.post(f"/sims/{ICCID}/label", data={"label": "   "})

    assert sims(page)[0]["label"] == "+886900000001"


def test_label_cannot_inject_markup(transport, page):
    plug(transport, page)

    page.post(f"/sims/{ICCID}/label", data={"label": '"><script>alert(1)</script>'})

    assert "<script>alert(1)</script>" not in page.get("/").text


def test_messages_are_not_forwarded_while_forwarding_is_off(transport, telegram, page):
    modem = plug(transport, page)

    page.post(f"/sims/{ICCID}/forwarding", data={"enabled": "0"})
    assert sims(page)[0]["forwarding"] == "off"
    modem.deliver(build_pdu("111", "while off"))
    wait_for(lambda: "not forwarded<" in page.get("/").text)

    page.post(f"/sims/{ICCID}/forwarding", data={"enabled": "1"})
    assert sims(page)[0]["forwarding"] == "on"
    modem.deliver(build_pdu("111", "while on"))
    wait_for(lambda: telegram.calls)

    assert [text.splitlines()[-1] for text in telegram.texts] == ["while on"]


def test_forwarding_is_switched_per_sim(transport, telegram, page):
    quiet = plug(transport, page)
    loud = FakeModem(iccid="89860000000000000002", number="+8613800000000", imei="860000000000002")
    transport.plug(loud)
    wait_for(lambda: len(sims(page)) == 2)

    page.post(f"/sims/{ICCID}/forwarding", data={"enabled": "0"})
    quiet.deliver(build_pdu("111", "quiet"))
    loud.deliver(build_pdu("222", "loud"))
    wait_for(lambda: telegram.calls and len(message_labels(page)) == 2)

    assert [text.splitlines()[-1] for text in telegram.texts] == ["loud"]


def test_sim_moved_to_another_modem_keeps_its_label_settings_and_messages(transport, page):
    first = plug(transport, page, imei="860000000000001")
    first.deliver(build_pdu("111", "in the first Modem"))
    wait_for(lambda: message_labels(page))
    page.post(f"/sims/{ICCID}/label", data={"label": "Travel SIM"})
    page.post(f"/sims/{ICCID}/forwarding", data={"enabled": "0"})

    transport.unplug(first)
    wait_for(lambda: sims(page)[0]["registration"] == "not in a Modem")
    second = plug(transport, page, imei="860000000000002")
    second.deliver(build_pdu("111", "in the second Modem"))
    wait_for(lambda: len(message_labels(page)) == 2)

    (sim,) = sims(page)
    assert (sim["label"], sim["forwarding"]) == ("Travel SIM", "off")
    assert sorted(message_labels(page)) == [
        ("Travel SIM", "in the first Modem"),
        ("Travel SIM", "in the second Modem"),
    ]
