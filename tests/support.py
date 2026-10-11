"""Test doubles and helpers: a scripted fake Modem and a PDU builder."""

from __future__ import annotations

import queue
import time
from datetime import datetime, timedelta, timezone

from mailroom.pdu import _GSM_BASIC
from mailroom.transport import ATError

TAIPEI_TIME = timezone(timedelta(hours=8))


class FakeModem:
    """Answers the AT commands Mailroom uses and emits new-message indications."""

    def __init__(self, iccid: str = "89886000000000000001", number: str | None = "+886900000001") -> None:
        self.iccid = iccid
        self.number = number
        self.stored: dict[int, str] = {}
        self._indications: queue.Queue[str] = queue.Queue()

    def deliver(self, pdu: str, announce: bool = True) -> None:
        """Simulate the network delivering an SMS: it lands in SIM storage and is indicated."""
        index = max(self.stored, default=0) + 1
        self.stored[index] = pdu
        if announce:
            self._indications.put(f'+CMTI: "SM",{index}')

    def command(self, text: str) -> list[str]:
        if text == "AT+CICCID":
            return [f"+ICCID: {self.iccid}"]
        if text == "AT+CNUM":
            return [f'+CNUM: "","{self.number}",145'] if self.number else []
        if text == "AT+CMGL=4":
            lines = []
            for index, pdu in sorted(self.stored.items()):
                lines += [f"+CMGL: {index},0,,{len(pdu) // 2}", pdu]
            return lines
        if text.startswith("AT+CMGD="):
            self.stored.pop(int(text.split("=")[1]), None)
            return []
        raise ATError(f"unsupported command: {text}")

    def wait_indication(self, timeout: float) -> str | None:
        try:
            return self._indications.get(timeout=timeout)
        except queue.Empty:
            return None


class FakeTransport:
    def __init__(self, *modems: FakeModem) -> None:
        self._modems = list(modems)

    def links(self) -> list[FakeModem]:
        return self._modems


def wait_for(condition, timeout: float = 3.0):
    """Poll until `condition()` is truthy and return its value."""
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value or time.monotonic() > deadline:
            assert value, "condition not met in time"
            return value
        time.sleep(0.02)


def build_pdu(
    sender: str,
    text: str,
    sent_at: datetime = datetime(2026, 10, 11, 23, 34, 7, tzinfo=TAIPEI_TIME),
    encoding: str = "ucs2",
) -> str:
    """Build a single-Part SMS-DELIVER PDU."""
    smsc = "0791889623844906"
    if sender.lstrip("+").isdigit():
        digits = sender.lstrip("+")
        toa = "91" if sender.startswith("+") else "81"
        address = f"{len(digits):02X}{toa}{_swap(digits + 'F' * (len(digits) % 2))}"
    else:
        packed = _pack_septets(sender)
        address = f"{len(packed) * 2:02X}D0{packed.hex().upper()}"
    if encoding == "ucs2":
        body = text.encode("utf-16-be")
        dcs, length = "08", len(body)
    else:
        body = _pack_septets(text)
        dcs, length = "00", len(text)
    return f"{smsc}04{address}00{dcs}{_timestamp(sent_at)}{length:02X}{body.hex().upper()}"


def _swap(digits: str) -> str:
    return "".join(digits[i + 1] + digits[i] for i in range(0, len(digits), 2))


def _timestamp(moment: datetime) -> str:
    quarters = int(moment.utcoffset().total_seconds() // 900)
    zone = _swap(f"{abs(quarters):02d}")
    if quarters < 0:
        zone = f"{int(zone, 16) | 0x08:02X}"
    return _swap(moment.strftime("%y%m%d%H%M%S")) + zone


def _pack_septets(text: str) -> bytes:
    bits = 0
    for i, char in enumerate(text):
        bits |= _GSM_BASIC.index(char) << (7 * i)
    return bits.to_bytes((7 * len(text) + 7) // 8, "little")
