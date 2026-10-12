"""A web address in a Message can be opened, but only past a warning about scams."""

import re

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for


@pytest.fixture
def modem():
    return FakeModem(iccid="89886000000000000001", number="+886900000001", imei="860000000000001")


@pytest.fixture
def page(modem, tmp_path):
    app = create_app(FakeTransport(modem), tmp_path / "mailroom.db", poll_interval=0.2, scan_interval=0.05)
    with TestClient(app) as client:
        yield client


def receive(modem, page, text: str, **params) -> str:
    """Deliver one Message and return its item on the page."""
    modem.deliver(build_pdu("Sender", text))
    wait_for(lambda: '<li class="message">' in page.get("/").text)
    return re.search(r'<li class="message">(.*?)</li>', page.get("/", params=params).text, flags=re.S).group(1)


def warnings(item: str) -> list[tuple[str, str]]:
    """The (host, address) of every link the owner may open, each read from inside its warning."""
    found = []
    for box in re.findall(r'<details class="golink".*?</details>', item, flags=re.S):
        assert "Watch out for scams" in box
        (opening,) = re.findall(r'<a class="btn" href="(.*?)" target="_blank" rel="noopener noreferrer">', box)
        found.append((re.search(r'class="host">(.*?)</span>', box).group(1), opening))
    return found


def test_link_in_a_message_opens_in_a_new_window_past_a_warning(modem, page):
    item = receive(modem, page, "Pay at https://pay.example/bill?id=7 today")

    assert warnings(item) == [("pay.example", "https://pay.example/bill?id=7")]


def test_link_in_the_text_leads_to_its_warning_not_to_the_site(modem, page):
    item = receive(modem, page, "Pay at https://pay.example/bill today")

    (target, shown) = re.search(r'<a class="url" href="(.*?)">(.*?)</a>', item).groups()
    assert shown == "https://pay.example/bill"
    assert f'<details class="golink" id="{target.lstrip("#")}">' in item
    assert item.count('href="https://pay.example/bill"') == 1  # only the one inside the warning


def test_link_ends_where_the_sentence_around_it_goes_on(modem, page):
    item = receive(modem, page, "繳費記錄請至 https://fetnet.example/TAX00b。謝謝（詳見 https://a.example/x）")

    assert [address for _, address in warnings(item)] == ["https://fetnet.example/TAX00b", "https://a.example/x"]


def test_address_without_a_scheme_is_a_link(modem, page):
    item = receive(modem, page, "Track it: reurl.example/abc or www.post.example")

    assert warnings(item) == [
        ("reurl.example", "https://reurl.example/abc"),
        ("www.post.example", "https://www.post.example"),
    ]


def test_warning_names_the_host_a_disguised_link_really_goes_to(modem, page):
    item = receive(modem, page, "Verify now https://bank.example@evil.example/login")

    assert warnings(item) == [("evil.example", "https://bank.example@evil.example/login")]


def test_link_repeated_in_a_message_has_one_warning(modem, page):
    item = receive(modem, page, "https://a.example/x and again https://a.example/x")

    assert len(warnings(item)) == 1
    assert item.count('<a class="url"') == 2


def test_text_that_only_looks_like_an_address_is_left_alone(modem, page):
    item = receive(modem, page, "Fee 10.25, rate 3.5/10, mail a@b.example/x, javascript:alert(1), ver 2.0")

    assert warnings(item) == []
    assert '<a class="url"' not in item


def test_link_cannot_inject_markup(modem, page):
    item = receive(modem, page, 'https://a.example/\'onmouseover=\'x "><script>alert(1)</script>')

    assert "<script>" not in item
    assert "'onmouseover" not in item


def test_links_are_plain_text_while_selecting(modem, page):
    item = receive(modem, page, "Pay at https://pay.example/bill", select="1")

    assert "https://pay.example/bill" in item
    assert "href=" not in item
