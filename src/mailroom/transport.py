"""The seam between Mailroom and its Modems.

Everything above this module talks to a Modem only through `ModemLink`, so the
real libusb transport (ADR 0001) and the scripted fake used in tests are
interchangeable.
"""

from __future__ import annotations

from typing import Protocol


class ATError(Exception):
    """The Modem answered a command with ERROR, +CME ERROR or +CMS ERROR, or not at all."""


class LinkLost(ATError):
    """The Modem can no longer be reached, typically because it was unplugged."""


class ModemLink(Protocol):
    """An AT command channel to one Modem."""

    def command(self, text: str) -> list[str]:
        """Send one AT command and return its information lines, without the final OK.

        Raises ATError if the Modem reports an error.
        """
        ...

    def wait_indication(self, timeout: float) -> str | None:
        """Return the next unsolicited line from the Modem, or None after `timeout` seconds."""
        ...

    def close(self) -> None:
        ...


class Transport(Protocol):
    """Finds the Modems that are attached, which can change at any time."""

    def present(self) -> set[str]:
        """Keys of the Modems attached right now.

        A key stays the same for as long as its Modem stays attached; a Modem
        that is unplugged and plugged back in comes back under a new key.
        """
        ...

    def open(self, key: str) -> ModemLink:
        ...
