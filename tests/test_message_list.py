"""The owner can find, delete and follow Messages on the web page."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for

TAIWAN, CHINA = "89886000000000000001", "89860000000000000002"


@pytest.fixture
def modems():
    return (
        FakeModem(iccid=TAIWAN, number="+886900000001", imei="860000000000001"),
        FakeModem(iccid=CHINA, number="+8613800000000", imei="860000000000002"),
    )


@pytest.fixture
def mailroom(modems, tmp_path):
    return lambda: TestClient(
        create_app(FakeTransport(*modems), tmp_path / "mailroom.db", poll_interval=0.2, scan_interval=0.05)
    )


@pytest.fixture
def page(modems, mailroom):
    taiwan, china = modems
    with mailroom() as client:
        taiwan.deliver(build_pdu("Bank", "Your code is 123456", encoding="gsm7"))
        taiwan.deliver(build_pdu("0912345678", "晚餐吃什麼"))
        china.deliver(build_pdu("10086", "验证码 504126，请勿泄露"))
        china.deliver(build_pdu("10086", "100% 完成_了"))
        wait_for(lambda: len(shown(client)) == 4)
        yield client


def shown(page, **params) -> list[str]:
    return re.findall(r'<span class="text">(.*?)</span>', page.get("/", params=params).text, flags=re.S)


def delete_path(page, text: str) -> str:
    for item in re.findall(r'<li class="message">(.*?)</li>', page.get("/").text, flags=re.S):
        if text in item:
            return re.search(r'action="(/messages/\d+/delete)"', item).group(1)
    raise AssertionError(f"{text!r} is not on the page")


def test_list_can_be_limited_to_one_sim(page):
    assert sorted(shown(page, sim=TAIWAN)) == ["Your code is 123456", "晚餐吃什麼"]
    assert sorted(shown(page, sim=CHINA)) == ["100% 完成_了", "验证码 504126，请勿泄露"]


def test_chosen_sim_stays_selected_in_the_filter(page):
    html = page.get("/", params={"sim": CHINA}).text

    assert f'data-sim="{CHINA}" aria-current="true"' in html
    assert f'data-sim="{TAIWAN}" aria-current="false"' in html


@pytest.mark.parametrize(
    "search, expected",
    [
        ("code", ["Your code is 123456"]),
        ("CODE", ["Your code is 123456"]),
        ("验证码", ["验证码 504126，请勿泄露"]),
        ("晚餐", ["晚餐吃什麼"]),
        ("10086", ["100% 完成_了", "验证码 504126，请勿泄露"]),  # the sender
        ("100%", ["100% 完成_了"]),
        ("成_了", ["100% 完成_了"]),
        ("nothing like this", []),
    ],
)
def test_messages_can_be_searched(page, search, expected):
    assert sorted(shown(page, q=search)) == expected


def test_search_and_sim_filter_combine(page):
    assert shown(page, sim=TAIWAN, q="10086") == []
    assert shown(page, sim=CHINA, q="504126") == ["验证码 504126，请勿泄露"]


def test_page_says_when_nothing_matches(page):
    assert "No Messages match." in page.get("/", params={"q": "nothing like this"}).text


def test_search_text_cannot_inject_markup(page):
    assert "<script>alert(1)" not in page.get("/", params={"q": '"><script>alert(1)</script>'}).text


def test_deleting_a_message_removes_only_that_message(page):
    page.post(delete_path(page, "晚餐吃什麼"))

    assert sorted(shown(page)) == ["100% 完成_了", "Your code is 123456", "验证码 504126，请勿泄露"]


def test_deletion_is_permanent(modems, mailroom, page):
    page.post(delete_path(page, "Your code is 123456"))
    page.__exit__(None, None, None)

    with mailroom() as restarted:
        assert "Your code is 123456" not in shown(restarted)
        assert len(shown(restarted)) == 3


def test_deleting_keeps_the_filter_and_search(page):
    response = page.post(
        delete_path(page, "验证码 504126，请勿泄露"),
        headers={"referer": f"http://testserver/?sim={CHINA}&q=%E5%AE%8C%E6%88%90"},
    )

    assert response.url.path == "/"
    assert response.url.query.decode() == f"sim={CHINA}&q=%E5%AE%8C%E6%88%90"
    assert shown(page) == [] or "验证码 504126，请勿泄露" not in shown(page)


def test_a_form_cannot_redirect_to_another_site(page):
    response = page.post(
        delete_path(page, "晚餐吃什麼"),
        headers={"referer": "https://evil.example/steal?x=1"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/"


def test_page_refreshes_itself_from_its_own_address(page):
    html = page.get("/", params={"sim": CHINA}).text

    assert "fetch(location.href" in html
    assert 'id="refresh"' in html


def test_page_is_laid_out_for_a_phone(page):
    html = page.get("/").text

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "overflow-wrap: anywhere" in html
