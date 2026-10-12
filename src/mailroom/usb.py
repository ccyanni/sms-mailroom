"""Talk to A7672G Modems through libusb (see ADR 0001).

macOS creates no serial device for these Modems, so Mailroom claims the
vendor-specific AT interface itself and uses its bulk endpoints directly.
"""

from __future__ import annotations

import errno
import logging
import queue
import threading
import time

import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

from mailroom.at import ATChannel
from mailroom.transport import ATError, LinkLost

VENDOR_ID = 0x1E0E
PRODUCT_ID = 0x9011
# The Modem has two AT-capable interfaces: 4 is its AT port, 5 its MODEM (dial-up)
# port, and by default it sends every unsolicited line to both. Mailroom talks on
# the AT port and must keep reading the other one too: while either is left
# unread, SMS in the GSM 7-bit alphabet silently never arrive (see ADR 0001).
AT_INTERFACE = 4
SECONDARY_AT_INTERFACE = 5

_SET_CONTROL_LINE_STATE = 0x22
_DTR_AND_RTS = 0x03
_MAX_CONSECUTIVE_READ_FAILURES = 5

log = logging.getLogger(__name__)


class UsbModemLink:
    def __init__(self, device: usb.core.Device) -> None:
        self._device = device
        self._incoming: queue.Queue[bytes | LinkLost] = queue.Queue()
        self._closing = False
        self._out, primary_in = self._open(AT_INTERFACE)
        _, secondary_in = self._open(SECONDARY_AT_INTERFACE)
        # Named in the log, so a read error can be traced to one Modem and one interface.
        where = f"{device.bus}:{device.address}"
        for endpoint, deliver, number in (
            (primary_in, self._incoming.put, AT_INTERFACE),
            (secondary_in, _discard, SECONDARY_AT_INTERFACE),
        ):
            threading.Thread(
                target=self._pump, args=(endpoint, deliver, f"{where} interface {number}"), daemon=True
            ).start()
        self._channel = ATChannel(self._read, self._write)
        try:
            while self._channel.wait_indication(0.2) is not None:
                pass  # discard whatever the Modem said before Mailroom was listening
            self._channel.command("ATE0")
        except ATError:
            self.close()
            raise

    def _open(self, number: int):
        """Claim an AT interface and return its bulk (out, in) endpoints."""
        # Interfaces are looked up by number, not position: the Modem has no interface 3.
        interface = usb.util.find_descriptor(self._device.get_active_configuration(), bInterfaceNumber=number)
        usb.util.claim_interface(self._device, number)
        # The Modem expects the host to assert DTR on an AT interface it uses.
        self._device.ctrl_transfer(0x21, _SET_CONTROL_LINE_STATE, _DTR_AND_RTS, number, None)
        return (
            usb.util.find_descriptor(interface, custom_match=_bulk_endpoint(usb.util.ENDPOINT_OUT)),
            usb.util.find_descriptor(interface, custom_match=_bulk_endpoint(usb.util.ENDPOINT_IN)),
        )

    def command(self, text: str) -> list[str]:
        return self._channel.command(text)

    def wait_indication(self, timeout: float) -> str | None:
        return self._channel.wait_indication(timeout)

    def close(self) -> None:
        self._closing = True
        try:
            usb.util.release_interface(self._device, AT_INTERFACE)
            usb.util.release_interface(self._device, SECONDARY_AT_INTERFACE)
            usb.util.dispose_resources(self._device)
        except usb.core.USBError:
            pass

    def _pump(self, endpoint, deliver, name: str) -> None:
        """Read from one of the Modem's endpoints for as long as the link is open.

        One blocking read with no timeout, instead of many short ones: on macOS
        libusb aborts the pipe whenever a read times out, which loses data that
        arrives at that moment and intermittently fails the next read.
        """
        failures = 0
        while not self._closing:
            try:
                data = bytes(endpoint.read(4096, timeout=0))
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as exc:
                if self._closing:
                    return
                failures += 1
                if exc.errno == errno.ENODEV or failures >= _MAX_CONSECUTIVE_READ_FAILURES:
                    self._incoming.put(LinkLost(str(exc)))
                    return
                log.warning("read from Modem at %s failed (%s), retrying", name, exc)
                try:
                    endpoint.clear_halt()
                except usb.core.USBError:
                    pass
                time.sleep(0.2 * failures)
                continue
            failures = 0
            if data:
                deliver(data)

    def _read(self, timeout: float) -> bytes:
        try:
            item = self._incoming.get(timeout=max(timeout, 0.001))
        except queue.Empty:
            return b""
        if isinstance(item, LinkLost):
            self._incoming.put(item)  # the link stays lost for every later read
            raise item
        return item

    def _write(self, data: bytes) -> None:
        try:
            self._out.write(data, timeout=5000)
        except usb.core.USBError as exc:
            raise LinkLost(str(exc)) from exc


class UsbTransport:
    def __init__(self) -> None:
        self._backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        self._devices: dict[str, usb.core.Device] = {}

    def present(self) -> set[str]:
        devices = usb.core.find(
            find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=self._backend
        )
        # The USB address is assigned afresh each time a Modem is plugged in.
        self._devices = {f"{device.bus}:{device.address}": device for device in devices}
        return set(self._devices)

    def open(self, key: str) -> UsbModemLink:
        try:
            return UsbModemLink(self._devices[key])
        except usb.core.USBError as exc:
            raise LinkLost(str(exc)) from exc


def _discard(data: bytes) -> None:
    pass


def _bulk_endpoint(direction: int):
    def match(endpoint) -> bool:
        return (
            usb.util.endpoint_direction(endpoint.bEndpointAddress) == direction
            and usb.util.endpoint_type(endpoint.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
        )
    return match
