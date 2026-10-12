"""Only the owner, signed in through Cloudflare Access, can reach the web page."""

import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from mailroom.access import AccessSettings, CloudflareAccess, LockedAccess
from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for

SETTINGS = AccessSettings(team_domain="myteam.cloudflareaccess.com", audience="aud-tag-of-mailroom")
SECRET_TEXT = "Your code is 123456"


class Cloudflare:
    """Stands in for Cloudflare: signs tokens and serves the public keys Mailroom fetches."""

    def __init__(self) -> None:
        self.keys = {"key-1": rsa.generate_private_key(public_exponent=65537, key_size=2048)}
        self.fetches = 0
        self.down = False

    def certs(self, settings: AccessSettings) -> list[dict]:
        self.fetches += 1
        if self.down:
            raise OSError("certs endpoint unreachable")
        return [
            {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": kid}
            for kid, key in self.keys.items()
        ]

    def token(self, kid="key-1", signing_key=None, **claims) -> str:
        payload = {
            "aud": [SETTINGS.audience],
            "iss": SETTINGS.issuer,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "email": "owner@example.com",
            **claims,
        }
        return jwt.encode(payload, signing_key or self.keys[kid], algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def cloudflare():
    return Cloudflare()


@pytest.fixture
def page(cloudflare, tmp_path):
    modem = FakeModem()
    app = create_app(
        FakeTransport(modem),
        tmp_path / "mailroom.db",
        poll_interval=0.2,
        scan_interval=0.05,
        access=CloudflareAccess(SETTINGS, fetch=cloudflare.certs),
    )
    with TestClient(app) as client:
        modem.deliver(build_pdu("Bank", SECRET_TEXT, encoding="gsm7"))
        wait_for(lambda: SECRET_TEXT in client.get("/", headers=signed(cloudflare.token())).text)
        yield client


def signed(token: str) -> dict[str, str]:
    return {"Cf-Access-Jwt-Assertion": token}


def assert_rejected(response) -> None:
    assert response.status_code == 403
    assert SECRET_TEXT not in response.text
    assert response.text == "Forbidden"


def test_request_with_a_valid_token_is_served(cloudflare, page):
    response = page.get("/", headers=signed(cloudflare.token()))

    assert response.status_code == 200
    assert SECRET_TEXT in response.text


def test_token_in_the_cloudflare_cookie_is_accepted(cloudflare, page):
    page.cookies.set("CF_Authorization", cloudflare.token())

    assert page.get("/").status_code == 200


def test_request_without_a_token_is_rejected(page):
    assert_rejected(page.get("/"))


def test_token_for_another_application_is_rejected(cloudflare, page):
    assert_rejected(page.get("/", headers=signed(cloudflare.token(aud=["some-other-app"]))))


def test_token_from_another_team_is_rejected(cloudflare, page):
    assert_rejected(page.get("/", headers=signed(cloudflare.token(iss="https://evil.cloudflareaccess.com"))))


def test_expired_token_is_rejected(cloudflare, page):
    expired = cloudflare.token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))

    assert_rejected(page.get("/", headers=signed(expired)))


def test_token_without_an_expiry_is_rejected(cloudflare, page):
    payload = {"aud": [SETTINGS.audience], "iss": SETTINGS.issuer}
    token = jwt.encode(payload, cloudflare.keys["key-1"], algorithm="RS256", headers={"kid": "key-1"})

    assert_rejected(page.get("/", headers=signed(token)))


def test_token_signed_by_someone_else_is_rejected(cloudflare, page):
    forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert_rejected(page.get("/", headers=signed(cloudflare.token(signing_key=forger))))


def test_unsigned_token_is_rejected(page):
    payload = {"aud": [SETTINGS.audience], "iss": SETTINGS.issuer, "exp": 9999999999}
    unsigned = jwt.encode(payload, key=None, algorithm="none", headers={"kid": "key-1"})

    assert_rejected(page.get("/", headers=signed(unsigned)))


@pytest.mark.parametrize("garbage", ["not-a-token", "a.b.c", ""])
def test_malformed_token_is_rejected(page, garbage):
    assert_rejected(page.get("/", headers=signed(garbage)))


def test_changing_things_also_needs_a_valid_token(cloudflare, page):
    assert_rejected(page.post("/messages/1/delete"))
    assert SECRET_TEXT in page.get("/", headers=signed(cloudflare.token())).text


def test_form_posted_from_another_site_is_rejected_even_with_a_valid_token(cloudflare, page):
    headers = {**signed(cloudflare.token()), "Origin": "https://evil.example"}

    assert_rejected(page.post("/messages/1/delete", headers=headers))
    assert SECRET_TEXT in page.get("/", headers=signed(cloudflare.token())).text


def test_form_posted_from_the_page_itself_is_accepted(cloudflare, page):
    headers = {**signed(cloudflare.token()), "Origin": "http://testserver"}

    page.post("/messages/1/delete", headers=headers)

    assert SECRET_TEXT not in page.get("/", headers=signed(cloudflare.token())).text


def test_token_signed_with_a_rotated_key_is_accepted_after_refetching(cloudflare, page, monkeypatch):
    monkeypatch.setattr("mailroom.access._REFETCH_AT_MOST_EVERY", 0.0)
    cloudflare.keys = {"key-2": rsa.generate_private_key(public_exponent=65537, key_size=2048)}

    assert page.get("/", headers=signed(cloudflare.token(kid="key-2"))).status_code == 200


def test_unknown_key_ids_do_not_flood_cloudflare(cloudflare, page):
    before = cloudflare.fetches

    for _ in range(20):
        assert_rejected(page.get("/", headers=signed(cloudflare.token(kid="key-1") .replace("a", "b", 1))))
        page.get("/", headers=signed(jwt.encode({"x": 1}, "s" * 32, algorithm="HS256", headers={"kid": "nope"})))

    assert cloudflare.fetches - before <= 1


def test_nobody_gets_in_when_cloudflare_keys_cannot_be_fetched(tmp_path):
    cloudflare = Cloudflare()
    cloudflare.down = True
    app = create_app(
        FakeTransport(), tmp_path / "mailroom.db", access=CloudflareAccess(SETTINGS, fetch=cloudflare.certs)
    )
    with TestClient(app) as client:
        assert client.get("/", headers=signed(cloudflare.token())).status_code == 403


def test_locked_page_rejects_everyone(tmp_path):
    app = create_app(FakeTransport(), tmp_path / "mailroom.db", access=LockedAccess())
    with TestClient(app) as client:
        assert_rejected(client.get("/"))
