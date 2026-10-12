"""Mailroom tells the owner when it can no longer be trusted to receive."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for
from test_forwarding import FakeTelegram

ICCID = "89886000000000000001"
GRACE = 0.4


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def modem(transport):
    modem = FakeModem(iccid=ICCID, number="+886900000001", imei="860000000000001")
    transport.plug(modem)
    return modem


@pytest.fixture
def mailroom(transport, telegram, tmp_path):
    def start(network_service_enabled=None, alert_after=GRACE):
        return TestClient(
            create_app(
                transport,
                tmp_path / "mailroom.db",
                poll_interval=0.1,
                scan_interval=0.05,
                telegram=TelegramSettings("123:token", "4242"),
                http_post=telegram,
                forward_interval=0.05,
                alert_after=alert_after,
                health_interval=0.05,
                network_service_enabled=network_service_enabled,
            )
        )
    return start


def alerts(telegram) -> list[str]:
    return [text for text in telegram.texts if not text.startswith("📩")]


def receiving(page) -> bool:
    return "(receiving)" in page.get("/status").text and "home" in page.get("/status").text


def settle(seconds: float = 3 * GRACE) -> None:
    import time
    time.sleep(seconds)


def test_sim_off_the_network_raises_one_alert_and_another_when_it_recovers(modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))

        modem.registration = 0
        wait_for(lambda: alerts(telegram))
        settle()
        assert alerts(telegram) == [
            "⚠️ SMS Mailroom alert\nSIM +886900000001 is not receiving: it is not registered on a mobile network."
        ]
        assert "is not receiving" in page.get("/status").text

        modem.registration = 1
        wait_for(lambda: len(alerts(telegram)) == 2)
        assert alerts(telegram)[1].startswith("✅ SMS Mailroom: resolved\nSIM +886900000001 is not receiving")
        assert "is not receiving" not in page.get("/status").text


def test_brief_loss_of_registration_stays_quiet(modem, telegram, mailroom):
    with mailroom(alert_after=5.0) as page:
        wait_for(lambda: receiving(page))

        modem.registration = 0
        wait_for(lambda: "not registered" in page.get("/status").text)
        modem.registration = 1
        wait_for(lambda: receiving(page))
        settle(0.5)

    assert alerts(telegram) == []


def test_modem_that_disappears_raises_an_alert_and_another_when_it_returns(transport, modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))

        transport.unplug(modem)
        wait_for(lambda: alerts(telegram))
        assert alerts(telegram) == [
            "⚠️ SMS Mailroom alert\nSIM +886900000001 is not receiving: its Modem is no longer attached."
        ]

        transport.plug(modem)
        wait_for(lambda: len(alerts(telegram)) == 2)
        assert alerts(telegram)[1].startswith("✅ SMS Mailroom: resolved")


def test_modem_that_drops_off_for_a_moment_stays_quiet(transport, modem, telegram, mailroom):
    with mailroom(alert_after=5.0) as page:
        wait_for(lambda: receiving(page))

        transport.unplug(modem)
        wait_for(lambda: "No Modems attached." in page.get("/status").text)
        transport.plug(modem)
        wait_for(lambda: receiving(page))
        settle(0.5)

    assert alerts(telegram) == []


def test_modem_that_keeps_disconnecting_raises_one_alert(transport, modem, telegram, mailroom):
    with mailroom(alert_after=5.0) as page:
        for _ in range(3):
            wait_for(lambda: receiving(page))
            transport.unplug(modem)
            wait_for(lambda: "No Modems attached." in page.get("/status").text)
            transport.plug(modem)
        wait_for(lambda: alerts(telegram))
        settle(0.5)

    (alert,) = alerts(telegram)
    assert "Modem 860000000000001 keeps disconnecting (3 times in the last 30 minutes)" in alert
    assert "USB hub" in alert


def test_alert_is_not_repeated_after_a_restart_while_the_problem_persists(modem, telegram, mailroom):
    modem.registration = 0
    with mailroom():
        wait_for(lambda: alerts(telegram))
    with mailroom():
        settle()

    assert len(alerts(telegram)) == 1


def test_sim_storage_filling_up_raises_an_alert(modem, telegram, mailroom):
    modem.capacity = 5
    with mailroom() as page:
        wait_for(lambda: receiving(page))
        for _ in range(4):
            modem.deliver("00", announce=False)  # undecodable, so it stays on the SIM

        wait_for(lambda: alerts(telegram))

    assert "has 4 of 5 storage slots in use" in alerts(telegram)[0]


def test_telegram_outage_is_shown_on_the_page_and_reported_once_it_is_over(modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))
        telegram.down = True
        modem.deliver(build_pdu("111", "sent during the outage"))
        wait_for(lambda: "Telegram has not been reachable since" in page.get("/status").text)
        settle()

        telegram.down = False
        wait_for(lambda: alerts(telegram))
        settle(0.5)

        assert "Telegram has not been reachable" not in page.get("/status").text
    (alert,) = alerts(telegram)
    assert re.fullmatch(
        r"⚠️ SMS Mailroom alert\nTelegram could not be reached from \d\d:\d\d to \d\d:\d\d\. "
        r"Messages received meanwhile were forwarded late\.",
        alert,
    )
    assert [text.splitlines()[-1] for text in telegram.texts if text.startswith("📩")] == ["sent during the outage"]


def test_alerts_ignore_a_sims_forwarding_setting(modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))
        page.post(f"/sims/{ICCID}/forwarding", data={"enabled": "0"})

        modem.registration = 0

        wait_for(lambda: alerts(telegram))


def test_enabled_network_service_raises_an_alert_at_startup(modem, telegram, mailroom):
    with mailroom(network_service_enabled=lambda: True, alert_after=5.0) as page:
        wait_for(lambda: alerts(telegram))

        assert "the Mac could send traffic over a SIM" in alerts(telegram)[0]
        assert "A76XX Series LTE Module" in page.get("/status").text


@pytest.mark.parametrize("state", [False, None])
def test_disabled_or_absent_network_service_is_fine(modem, telegram, mailroom, state):
    with mailroom(network_service_enabled=lambda: state) as page:
        wait_for(lambda: receiving(page))
        settle(0.3)

    assert alerts(telegram) == []


def test_usb_network_sharing_is_kept_disabled_on_every_modem(modem, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))

    assert "AT+DIALMODE=1" in modem.settings


def test_healthy_mailroom_sends_no_alerts(modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))
        modem.deliver(build_pdu("111", "all good"))
        wait_for(lambda: telegram.calls)
        settle()

    assert alerts(telegram) == []


# --- The notice that Mailroom has started --------------------------------------------------------


@pytest.fixture
def announcing(transport, telegram, tmp_path):
    def start(kind="restart", language=None):
        return TestClient(
            create_app(
                transport,
                tmp_path / "mailroom.db",
                poll_interval=0.1,
                scan_interval=0.05,
                telegram=TelegramSettings("123:token", "4242"),
                http_post=telegram,
                forward_interval=0.05,
                alert_after=60,
                health_interval=0.05,
                language=language,
                start_notice=kind,
                start_notice_after=0.5,
            )
        )
    return start


def test_owner_is_told_once_when_the_service_restarts(modem, telegram, announcing):
    with announcing("restart"):
        wait_for(lambda: alerts(telegram))
        settle(1.0)

    assert alerts(telegram) == ["🟢 SMS Mailroom started (the service restarted)\n1 Modems attached, 1 of 1 SIMs receiving"]


def test_start_notice_says_when_the_mac_has_just_booted(modem, telegram, announcing):
    with announcing("boot"):
        wait_for(lambda: alerts(telegram))

    assert alerts(telegram)[0].startswith("🟢 SMS Mailroom started (the Mac has just booted)\n")


def test_start_notice_counts_sims_that_are_not_receiving(transport, modem, telegram, announcing):
    with announcing():
        wait_for(lambda: alerts(telegram))  # the SIM is now known
    telegram.calls.clear()
    transport.unplug(modem)

    with announcing():
        wait_for(lambda: alerts(telegram))

    assert alerts(telegram) == ["🟢 SMS Mailroom started (the service restarted)\n0 Modems attached, 0 of 1 SIMs receiving"]


def test_start_notice_uses_the_configured_language(modem, telegram, announcing):
    with announcing("boot", language="zh"):
        wait_for(lambda: alerts(telegram))

    assert alerts(telegram) == ["🟢 SMS Mailroom 已啟動（電腦剛重新開機）\n接上 1 片模組，1 張 SIM 中有 1 張正常收訊"]


def test_start_notice_is_delivered_once_telegram_becomes_reachable(modem, telegram, announcing):
    telegram.down = True
    with announcing():
        settle(1.0)
        assert alerts(telegram) == []

        telegram.down = False
        wait_for(lambda: alerts(telegram))
        settle(0.5)

    assert len(alerts(telegram)) == 1


def test_no_start_notice_unless_asked_for(modem, telegram, mailroom):
    with mailroom() as page:
        wait_for(lambda: receiving(page))
        settle(1.0)

    assert alerts(telegram) == []


def test_boot_is_told_apart_from_a_service_restart():
    from mailroom.health import booted_recently

    assert booted_recently(within=10 * 365 * 86400) is True  # this Mac booted less than ten years ago
    assert booted_recently(within=0) is False
