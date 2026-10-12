"""What the page shows and says: codes, language, appearance, and the state of the system."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.access import AccessSettings, CloudflareAccess
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
def modem(transport):
    modem = FakeModem(iccid=ICCID, number="+886900000001", imei="860000000000001")
    transport.plug(modem)
    return modem


@pytest.fixture
def mailroom(transport, telegram, tmp_path):
    def start(**options):
        options.setdefault("telegram", TelegramSettings("123:token", "4242"))
        return TestClient(
            create_app(
                transport,
                tmp_path / "mailroom.db",
                poll_interval=0.1,
                scan_interval=0.05,
                http_post=telegram,
                forward_interval=0.05,
                health_interval=0.05,
                **{"alert_after": 0.3, **options},
            )
        )
    return start


def texts(page) -> list[str]:
    return re.findall(r'class="text">(.*?)</span>', page.get("/").text, flags=re.S)


def system(page) -> dict[str, tuple[str, str]]:
    """Each row of the system card: name → (state, level)."""
    rows = re.findall(
        r'<li class="sys-row" data-level="(\w+)">.*?<b>(.*?)</b>.*?class="sys-state">(.*?)</span>',
        page.get("/status").text,
        flags=re.S,
    )
    return {name: (state, level) for level, name, state in rows}


def note(page, name: str) -> str:
    row = re.search(rf"<b>{re.escape(name)}</b>.*?<small>(.*?)</small>", page.get("/status").text, flags=re.S)
    return row.group(1)


# --- Messages ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, code",
    [
        ("Your code is 482913, valid for 5 minutes", "482913"),
        ("G-731840 is your Google verification code.", "731840"),
        ("驗證碼 4821，請勿提供給他人", "4821"),
        ("(验证密码)662022，尊敬的用户，您正在登录中国移动 APP，该验证码5分钟内有效。", "662022"),
        ("您于2026年10月12日申请的动态密码为 905512", "905512"),
        ("Use OTP 55021 before 12:30 on 2026-10-12", "55021"),
    ],
)
def test_a_code_in_a_message_is_shown_on_its_own_with_a_copy_button(modem, mailroom, text, code):
    with mailroom() as page:
        modem.deliver(build_pdu("Bank", text))
        wait_for(lambda: texts(page))

        assert f'data-copy="{code}"' in page.get("/").text


@pytest.mark.parametrize(
    "text",
    [
        "See you at 8",
        "Paid 268.00 on 10/11",
        "Call 0912345678 back",
        "Order 123456789012",
        "Balance 268.00, card ending 4471",
        "交费/充值提醒：您于2026年10月12日01:02成功缴费100.00元。",
        "測試 0821",
        "您的密碼已於 2026/10/12 變更",
    ],
)
def test_text_without_a_code_gets_no_copy_button(modem, mailroom, text):
    with mailroom() as page:
        modem.deliver(build_pdu("Friend", text))
        wait_for(lambda: texts(page))

        assert "data-copy=" not in page.get("/").text


def test_message_says_how_long_ago_it_arrived_and_exactly_when(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("Bank", "hello"))
        wait_for(lambda: texts(page))
        html = page.get("/").text

    assert re.search(r'class="ago">(yesterday|\d+ h ago|\d+/\d+)</span>', html)
    assert "<time>2026-10-11 23:34:07</time>" in html


def test_deleting_takes_a_second_explicit_step(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("Bank", "hello"))
        wait_for(lambda: texts(page))
        html = page.get("/").text

    confirm = re.search(r'<details class="confirm">(.*?)</details>', html, flags=re.S).group(1)
    assert "<summary" in confirm and "Delete" in confirm
    assert "This cannot be undone." in confirm
    assert re.search(r'action="/messages/\d+/delete"', confirm)


# --- Language ---------------------------------------------------------------------------------------


def test_page_is_in_traditional_chinese_unless_told_otherwise(modem, mailroom, monkeypatch):
    monkeypatch.undo()  # drop the tests' English default
    with mailroom() as page:
        html = page.get("/").text
        status = page.get("/status").text

    assert '<html lang="zh-Hant">' in html
    assert "收件匣" in html and "還沒有簡訊。" in html
    assert "系統" in status and "SMS Mailroom 服務" in status


def test_owner_can_switch_to_english_and_the_choice_is_remembered(modem, mailroom, monkeypatch):
    monkeypatch.undo()
    with mailroom() as page:
        response = page.post("/settings/language", data={"lang": "en"}, headers={"referer": "http://testserver/status"})

        assert response.url.path == "/status"
        assert '<html lang="en">' in page.get("/").text
        assert "Inbox" in page.get("/").text

        page.post("/settings/language", data={"lang": "zh"})
        assert "收件匣" in page.get("/").text


def test_unknown_language_falls_back_to_the_default(modem, mailroom):
    with mailroom() as page:
        page.post("/settings/language", data={"lang": "tlh"})

        assert '<html lang="en">' in page.get("/").text


def test_telegram_texts_use_the_configured_language(modem, telegram, mailroom):
    with mailroom(language="zh") as page:
        wait_for(lambda: "(receiving)" in page.get("/status").text or "收訊中" in page.get("/status").text)
        modem.deliver(build_pdu("111", "前半，", part=(7, 2, 1)))
        modem.registration = 0
        wait_for(lambda: any(text.startswith("⚠️ SMS Mailroom 異常通知") for text in telegram.texts))

    alert = next(text for text in telegram.texts if text.startswith("⚠️ SMS Mailroom 異常通知"))
    assert alert == "⚠️ SMS Mailroom 異常通知\nSIM「+886900000001」未在收訊：沒有註冊到電信網路。"


def test_alerts_on_the_page_follow_the_page_language(modem, mailroom):
    with mailroom() as page:
        wait_for(lambda: "(receiving)" in page.get("/status").text)
        modem.registration = 0
        wait_for(lambda: "is not receiving" in page.get("/status").text)

        page.post("/settings/language", data={"lang": "zh"})
        assert "未在收訊：沒有註冊到電信網路。" in page.get("/status").text


def test_every_string_exists_in_both_languages():
    from mailroom import i18n

    assert set(i18n.strings("zh")) == set(i18n.strings("en"))


# --- Navigation and appearance -----------------------------------------------------------------------


def test_status_tab_is_marked_while_an_alert_is_active(modem, mailroom):
    with mailroom() as page:
        wait_for(lambda: "(receiving)" in page.get("/status").text)
        assert '<span class="mark">' not in page.get("/").text

        modem.registration = 0
        wait_for(lambda: '<span class="mark">' in page.get("/").text)


def test_appearance_can_follow_the_system_or_be_chosen(modem, mailroom):
    with mailroom() as page:
        html = page.get("/").text

    for choice in ("system", "light", "dark"):
        assert f'data-theme-choice="{choice}"' in html
    assert "prefers-color-scheme: dark" in html
    assert ':root[data-theme="dark"]' in html
    assert 'localStorage.getItem("theme")' in html


def test_both_sections_are_one_tap_apart(modem, mailroom):
    with mailroom() as page:
        messages, status = page.get("/").text, page.get("/status").text

    assert 'href="/" aria-current="page"' in messages and 'href="/status" aria-current="page"' not in messages
    assert 'href="/status" aria-current="page"' in status


# --- System status -----------------------------------------------------------------------------------


def test_system_card_reports_a_healthy_installation(modem, telegram, mailroom):
    access = CloudflareAccess(AccessSettings("team.cloudflareaccess.com", "aud"), fetch=lambda settings: [])
    with mailroom(network_service_enabled=lambda: False) as page:
        wait_for(lambda: "(receiving)" in page.get("/status").text)
        modem.deliver(build_pdu("111", "hello"))
        wait_for(lambda: telegram.calls)
        wait_for(lambda: system(page)["macOS network service"][0] == "Disabled")

        assert system(page) == {
            "SMS Mailroom service": ("Running", "ok"),
            "Telegram forwarding": ("Working", "ok"),
            "macOS network service": ("Disabled", "ok"),
            "USB connection": ("Stable", "ok"),
            "Page protection": ("Off", "warn"),  # this test page is open; see the next test
        }
        assert note(page, "SMS Mailroom service") == "Up for 0 min"
        assert note(page, "Telegram forwarding") == "Last forwarded just now"
    assert access.allows(None) is False


def test_system_card_says_when_cloudflare_access_protects_the_page(transport, tmp_path):
    from test_access import SETTINGS, Cloudflare, signed

    cloudflare = Cloudflare()
    app = create_app(transport, tmp_path / "mailroom.db", access=CloudflareAccess(SETTINGS, fetch=cloudflare.certs))
    with TestClient(app) as page:
        html = page.get("/status", headers=signed(cloudflare.token())).text

    assert re.search(r"<b>Page protection</b>.*?class=\"sys-state\">On</span>", html, flags=re.S)


def test_system_card_flags_telegram_not_set_up(modem, mailroom):
    with mailroom(telegram=None) as page:
        assert system(page)["Telegram forwarding"] == ("Not set up", "warn")


def test_system_card_flags_telegram_unreachable(modem, telegram, mailroom):
    telegram.down = True
    with mailroom() as page:
        modem.deliver(build_pdu("111", "hello"))

        wait_for(lambda: system(page)["Telegram forwarding"] == ("Unreachable", "warn"))


@pytest.mark.parametrize("probe, expected", [(True, ("Enabled", "warn")), (None, ("Unknown", "unknown"))])
def test_system_card_shows_the_macos_network_service(modem, mailroom, probe, expected):
    with mailroom(network_service_enabled=lambda: probe) as page:
        wait_for(lambda: system(page)["macOS network service"] == expected)


def test_system_card_counts_modem_drops_and_calls_three_unstable(transport, modem, mailroom):
    with mailroom(alert_after=60) as page:
        for drops in (1, 2, 3):
            wait_for(lambda: "(receiving)" in page.get("/status").text)
            transport.unplug(modem)
            wait_for(lambda: "No Modems attached." in page.get("/status").text)
            transport.plug(modem)
            wait_for(lambda: f"dropped off {drops} times" in note(page, "USB connection"))
            assert system(page)["USB connection"] == (("Unstable", "warn") if drops == 3 else ("Stable", "ok"))


@pytest.mark.parametrize(
    "minutes, english, chinese",
    [(0, "just now", "剛剛"), (5, "5 min ago", "5 分鐘前"), (125, "2 h ago", "2 小時前"), (1500, "yesterday", "昨天")],
)
def test_time_since_a_message_is_said_plainly(minutes, english, chinese):
    from datetime import datetime, timedelta, timezone

    from mailroom import i18n

    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    assert i18n.relative_time("en", now - timedelta(minutes=minutes), now) == english
    assert i18n.relative_time("zh", now - timedelta(minutes=minutes), now) == chinese
    assert i18n.relative_time("zh", now - timedelta(days=5), now) == "10/7"


def test_no_string_is_named_like_something_a_template_would_find_on_the_table_itself():
    # In a template, `t.copy` finds dict.copy before the string called "copy".
    from mailroom import i18n

    assert [key for key in i18n.strings("en") if hasattr(dict, key)] == []


def test_copy_button_is_labelled(modem, mailroom):
    with mailroom() as page:
        modem.deliver(build_pdu("Bank", "Your code is 482913"))
        wait_for(lambda: texts(page))
        html, status = page.get("/").text, page.get("/status").text

    assert re.search(r'data-copy="482913">.*?</svg>Copy</button>', html, flags=re.S)
    assert "built-in method" not in html and "built-in method" not in status
