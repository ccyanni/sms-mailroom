"""Who may reach the web page.

In production every request must carry a Cloudflare Access token, so that a
misconfigured tunnel cannot expose the owner's Messages.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

import jwt

log = logging.getLogger(__name__)

HEADER = "cf-access-jwt-assertion"
COOKIE = "CF_Authorization"
_REFETCH_AT_MOST_EVERY = 60.0  # seconds; an unknown key id must not turn into a request flood


@dataclass(frozen=True)
class AccessSettings:
    team_domain: str  # e.g. "example.cloudflareaccess.com"
    audience: str  # the Access application's AUD tag

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"


class AccessPolicy(Protocol):
    def allows(self, token: str | None) -> bool:
        ...


class OpenAccess:
    """No check at all. Only for local development, where the page is reachable from this computer alone."""

    def allows(self, token: str | None) -> bool:
        return True


class LockedAccess:
    """Nobody gets in. Used until Cloudflare Access has been configured."""

    def allows(self, token: str | None) -> bool:
        return False


def fetch_keys(settings: AccessSettings) -> list[dict]:
    """Cloudflare's current signing keys for the team, as JWKs."""
    with urllib.request.urlopen(f"{settings.issuer}/cdn-cgi/access/certs", timeout=10) as response:
        return json.load(response)["keys"]


class CloudflareAccess:
    def __init__(
        self,
        settings: AccessSettings,
        fetch: Callable[[AccessSettings], list[dict]] = fetch_keys,
    ) -> None:
        self._settings = settings
        self._fetch = fetch
        self._keys: dict[str, object] = {}
        self._fetched_at = float("-inf")

    def allows(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            key = self._key(jwt.get_unverified_header(token).get("kid"))
            if key is None:
                return False
            jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            return False
        return True

    def _key(self, key_id: str | None):
        if key_id not in self._keys and time.monotonic() - self._fetched_at >= _REFETCH_AT_MOST_EVERY:
            self._fetched_at = time.monotonic()
            try:
                self._keys = {
                    jwk["kid"]: jwt.PyJWK.from_dict(jwk).key for jwk in self._fetch(self._settings)
                }
            except Exception as exc:
                log.warning("could not fetch Cloudflare Access keys: %s", exc)
        return self._keys.get(key_id)
