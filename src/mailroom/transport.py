"""The seam between Mailroom and its Modems.

Everything above this module talks to a Modem only through `ModemLink`, so the
real libusb transport (ADR 0001) and the scripted fake used in tests are
interchangeable.
"""

from __future__ import annotations

from typing import Protocol


class ATError(Exception):
    """The Modem answered a command with ERROR, +CME ERROR or +CMS ERROR."""


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


class Transport(Protocol):
    """Finds the Modems that are attached."""

    def links(self) -> list[ModemLink]:
        ...
