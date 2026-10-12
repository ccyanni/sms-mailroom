"""Test doubles and helpers: a scripted fake Modem and a PDU builder."""

from __future__ import annotations

import queue
import time
from datetime import datetime, timedelta, timezone

from mailroom.pdu import _GSM_BASIC
from mailroom.transport import ATError, LinkLost

TAIPEI_TIME = timezone(timedelta(hours=8))


class FakeModem:
    """Answers the AT commands Mailroom uses and emits new-message indications."""

    def __init__(
        self,
        iccid: str = "89886000000000000001",
        number: str | None = "+886900000001",
        imei: str = "860000000000001",
    ) -> None:
        self.iccid = iccid
        self.number = number
        self.imei = imei
        self.attached = True
        self.link_failures = 0
        self.times_closed = 0
        self.sim_present = True
        self.stored: dict[int, str] = {}
        self._indications: queue.Queue[str] = queue.Queue()

    def deliver(self, pdu: str, announce: bool = True) -> None:
        """Simulate the network delivering an SMS: it lands in SIM storage and is indicated."""
        index = max(self.stored, default=0) + 1
        self.stored[index] = pdu
        if announce:
            self._indications.put(f'+CMTI: "SM",{index}')

    def command(self, text: str) -> list[str]:
        if not self.attached:
            raise LinkLost("Modem is unplugged")
        if text == "AT+CGSN":
            return [self.imei]
        if not self.sim_present:
            raise ATError(f"{text}: +CME ERROR: SIM not inserted")
        if text in ("AT+CMGF=0", "AT+CNMI=2,1,0,0,0", "AT+CATR=3"):
            return []
        if text == 'AT+CPMS="SM","SM","SM"':
            return [f"+CPMS: {len(self.stored)},40,{len(self.stored)},40,{len(self.stored)},40"]
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
        if self.link_failures:
            self.link_failures -= 1
            raise LinkLost("simulated link failure")
        try:
            return self._indications.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.times_closed += 1


class FakeTransport:
    """Modems can be plugged in and unplugged while Mailroom runs."""

    def __init__(self, *modems: FakeModem) -> None:
        self._attached: dict[str, FakeModem] = {}
        self._plugs = 0
        self.refuse_to_open = False
        for modem in modems:
            self.plug(modem)

    def plug(self, modem: FakeModem) -> None:
        self._plugs += 1
        modem.attached = True
        self._attached[f"port-{self._plugs}"] = modem

    def unplug(self, modem: FakeModem) -> None:
        modem.attached = False
        self._attached = {key: m for key, m in self._attached.items() if m is not modem}

    def present(self) -> set[str]:
        return set(self._attached)

    def open(self, key: str) -> FakeModem:
        if self.refuse_to_open:
            raise LinkLost("simulated failure to open")
        return self._attached[key]


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
    part: tuple[int, int, int] | None = None,
) -> str:
    """Build an SMS-DELIVER PDU; `part` is (reference, total, sequence) for one Part of a long SMS."""
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
    first_octet = "04"
    if part is not None:
        assert encoding == "ucs2", "the builder only splits UCS2 text"
        body = bytes([0x05, 0x00, 0x03, *part]) + body
        first_octet, length = "44", len(body)
    return f"{smsc}{first_octet}{address}00{dcs}{_timestamp(sent_at)}{length:02X}{body.hex().upper()}"


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
