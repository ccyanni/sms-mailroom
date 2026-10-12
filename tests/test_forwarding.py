"""Messages are forwarded to the owner's Telegram chat."""

import logging
import re

import pytest
from fastapi.testclient import TestClient

from mailroom.telegram import TelegramSettings
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for

TOKEN = "123456:SECRET-bot-token"
SETTINGS = TelegramSettings(token=TOKEN, chat_id="4242")
PART_TIMEOUT = 0.4


class FakeTelegram:
    """Stands in for the HTTPS call to Telegram and records what was sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.down = False

    def __call__(self, url: str, payload: dict) -> None:
        if self.down:
            raise OSError(f"could not connect to {url}")
        self.calls.append((url, payload))

    @property
    def texts(self) -> list[str]:
        return [payload["text"] for _, payload in self.calls]


@pytest.fixture
def telegram():
    return FakeTelegram()


@pytest.fixture
def modem():
    return FakeModem(number="+886900000001")


@pytest.fixture
def mailroom(modem, telegram, tmp_path):
    def start(settings=SETTINGS, part_timeout=60.0):
        return TestClient(
            create_app(
                FakeTransport(modem),
                tmp_path / "mailroom.db",
                poll_interval=0.3,
                scan_interval=0.05,
                part_timeout=part_timeout,
                telegram=settings,
                http_post=telegram,
                forward_interval=0.05,
            )
        )
    return start


def forwarding_shown(page) -> list[str]:
    return re.findall(r'class="forwarding">(.*?)</span>', page.get("/").text)


def test_message_is_sent_to_the_configured_chat(modem, telegram, mailroom):
    with mailroom():
        modem.deliver(build_pdu("0912345678", "Your code is 123456", encoding="gsm7"))
        wait_for(lambda: telegram.calls)

    url, payload = telegram.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert payload["chat_id"] == "4242"
    assert payload["text"] == "📩 +886900000001 ← 0912345678\n2026-10-11 23:34:07\n\nYour code is 123456"


def test_failed_send_is_retried_until_it_succeeds_and_sent_only_once(modem, telegram, mailroom):
    telegram.down = True
    with mailroom() as page:
        modem.deliver(build_pdu("111", "important"))
        wait_for(lambda: forwarding_shown(page) == ["not forwarded yet"])

        telegram.down = False
        wait_for(lambda: forwarding_shown(page) == ["forwarded"])
        modem.deliver(build_pdu("111", "second"))
        wait_for(lambda: len(telegram.calls) == 2)

    assert [text.splitlines()[-1] for text in telegram.texts] == ["important", "second"]


def test_message_that_could_not_be_sent_is_sent_after_a_restart(modem, telegram, mailroom):
    telegram.down = True
    with mailroom() as page:
        modem.deliver(build_pdu("111", "survives a restart"))
        wait_for(lambda: forwarding_shown(page) == ["not forwarded yet"])

    telegram.down = False
    with mailroom():
        wait_for(lambda: telegram.calls)
    with mailroom():
        pass

    assert len(telegram.calls) == 1


def test_multi_part_message_is_forwarded_once_complete(modem, telegram, mailroom):
    with mailroom():
        modem.deliver(build_pdu("111", "second half", part=(7, 2, 2)))
        modem.deliver(build_pdu("111", "first half, ", part=(7, 2, 1)))
        wait_for(lambda: telegram.calls)

    assert [text.splitlines()[-1] for text in telegram.texts] == ["first half, second half"]


def test_incomplete_message_is_forwarded_after_the_timeout_then_in_full(modem, telegram, mailroom):
    with mailroom(part_timeout=PART_TIMEOUT):
        modem.deliver(build_pdu("111", "first half, ", part=(7, 2, 1)))
        wait_for(lambda: telegram.calls)
        modem.deliver(build_pdu("111", "second half", part=(7, 2, 2)))
        wait_for(lambda: len(telegram.calls) == 2)

    incomplete, complete = telegram.texts
    assert "⚠️ Incomplete" in incomplete and incomplete.endswith("first half, […]")
    assert "✅ Now complete" in complete and complete.endswith("first half, second half")


def test_without_telegram_nothing_is_sent_and_setting_it_up_later_does_not_flood(modem, telegram, mailroom):
    with mailroom(settings=None) as page:
        modem.deliver(build_pdu("111", "before Telegram was set up"))
        wait_for(lambda: forwarding_shown(page) == ["not forwarded"])

    with mailroom() as page:
        modem.deliver(build_pdu("111", "after"))
        wait_for(lambda: telegram.calls)

    assert [text.splitlines()[-1] for text in telegram.texts] == ["after"]


def test_the_bot_token_is_never_logged(modem, telegram, mailroom, caplog):
    telegram.down = True
    with caplog.at_level(logging.DEBUG), mailroom() as page:
        modem.deliver(build_pdu("111", "hello"))
        wait_for(lambda: "could not forward" in caplog.text)

    assert TOKEN not in caplog.text
    assert "<token>" in caplog.text


def test_very_long_text_is_cut_to_what_telegram_accepts(modem, telegram, mailroom):
    with mailroom():
        for sequence in range(1, 81):
            modem.deliver(build_pdu("111", "字" * 60, part=(9, 80, sequence)))
        wait_for(lambda: telegram.calls, timeout=10)

    assert len(telegram.texts[0]) == 4096
