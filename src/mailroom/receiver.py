"""Receive Messages from one Modem and hand them to the store."""

from __future__ import annotations

import logging
import re
import threading
import time

from mailroom.pdu import PduError, decode_deliver
from mailroom.store import Store
from mailroom.transport import ATError, LinkLost, ModemLink

log = logging.getLogger(__name__)

_CMGL = re.compile(r"\+CMGL:\s*(\d+),")
_CNUM = re.compile(r'\+CNUM:\s*"[^"]*","([^"]*)"')
_ICCID = re.compile(r"\+ICCID:\s*(\w+)")
_IMEI = re.compile(r"^(\d{14,16})$")

RECEIVING = "receiving"


class Receiver:
    def __init__(self, link: ModemLink, store: Store, poll_interval: float = 30.0) -> None:
        self._link = link
        self._store = store
        self._poll_interval = poll_interval
        self._imei: str | None = None
        self._iccid: str | None = None
        self.state = "starting"

    def run(self, stop: threading.Event) -> None:
        """Collect Messages until `stop` is set: on every indication, and on a timer as a safety net."""
        last_collect = float("-inf")
        while not stop.is_set():
            try:
                indication = self._link.wait_indication(timeout=0.2)
                new_message = indication is not None and indication.startswith("+CMTI")
                if new_message or time.monotonic() - last_collect >= self._poll_interval:
                    last_collect = time.monotonic()
                    self.collect()
                    self._report(RECEIVING)
            except LinkLost as exc:
                self._report(f"lost: {exc}")
                return
            except ATError as exc:
                self._iccid = None  # identify the SIM afresh once it is readable again
                self._report(f"cannot receive: {exc}")

    def collect(self) -> None:
        """Move every Message on the SIM into the store, deleting each only once it is stored."""
        iccid = self._prepare()
        lines = self._link.command("AT+CMGL=4")
        for header, pdu in zip(lines, lines[1:]):
            match = _CMGL.match(header)
            if not match:
                continue
            try:
                delivery = decode_deliver(pdu)
            except PduError:
                log.exception("leaving undecodable PDU on SIM %s: %s", iccid, pdu)
                continue
            self._store.add_message(iccid, pdu, delivery)
            self._link.command(f"AT+CMGD={match.group(1)}")

    def _prepare(self) -> str:
        """Identify the Modem and its SIM and put the Modem in the mode Mailroom reads in."""
        if self._imei is None:
            self._imei = _first_match(_IMEI, self._link.command("AT+CGSN"))
        if self._iccid is None:
            iccid = _first_match(_ICCID, self._link.command("AT+CICCID"))
            if iccid is None:
                raise ATError("Modem did not report an ICCID")
            self._link.command("AT+CMGF=0")  # PDU mode
            self._link.command('AT+CPMS="SM","SM","SM"')  # keep Messages on the SIM
            self._link.command("AT+CNMI=2,1,0,0,0")  # store new Messages and indicate with +CMTI
            try:
                self._link.command("AT+CATR=3")  # send indications to the AT port only
            except ATError:
                log.warning("Modem %s does not accept AT+CATR=3", self._imei)
            try:
                number = _first_match(_CNUM, self._link.command("AT+CNUM")) or None
            except ATError:
                number = None
            self._store.register_sim(iccid, number)
            self._iccid = iccid
        return self._iccid

    def _report(self, state: str) -> None:
        if state != self.state:
            self.state = state
            level = logging.INFO if state == RECEIVING else logging.WARNING
            log.log(level, "Modem %s (SIM %s): %s", self._imei or "unknown", self._iccid or "none", state)


def _first_match(pattern: re.Pattern[str], lines: list[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None
