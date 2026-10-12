"""Keeps one Receiver running for every Modem that is attached, as Modems come and go."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from mailroom.forwarder import Forwarder
from mailroom.receiver import Receiver
from mailroom.store import Store
from mailroom.transport import ATError, ModemLink, Transport

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModemStatus:
    """A Modem that is attached right now."""

    imei: str | None
    iccid: str | None
    state: str


@dataclass
class _Running:
    link: ModemLink
    receiver: Receiver
    thread: threading.Thread
    stop: threading.Event


class Service:
    def __init__(
        self,
        transport: Transport,
        store: Store,
        forwarder: Forwarder,
        poll_interval: float = 30.0,
        scan_interval: float = 2.0,
    ) -> None:
        self._transport = transport
        self._store = store
        self._forwarder = forwarder
        self._poll_interval = poll_interval
        self._scan_interval = scan_interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running: dict[str, _Running] = {}
        self._unopenable: set[str] = set()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._scan()
        self._threads = [
            threading.Thread(target=self._supervise, daemon=True),
            threading.Thread(target=self._forwarder.run, args=(self._stop,), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join()
        for key in list(self._running):
            self._retire(key)

    def modems(self) -> list[ModemStatus]:
        with self._lock:
            receivers = [running.receiver for running in self._running.values()]
        return [ModemStatus(r.imei, r.iccid, r.state) for r in receivers]

    def _supervise(self) -> None:
        while not self._stop.wait(self._scan_interval):
            self._scan()

    def _scan(self) -> None:
        """Bring the running Receivers in line with the Modems attached right now.

        Presence comes from asking the transport, not from waiting for a read to
        fail: a link to a Modem that has gone can stay silent indefinitely.
        """
        try:
            present = self._transport.present()
        except Exception:
            log.exception("could not look for Modems")
            return
        for key, running in list(self._running.items()):
            if key not in present or not running.thread.is_alive():
                self._retire(key)
        self._unopenable &= present
        for key in present - self._running.keys():
            self._adopt(key)

    def _adopt(self, key: str) -> None:
        try:
            link = self._transport.open(key)
        except ATError as exc:
            if key not in self._unopenable:
                self._unopenable.add(key)
                log.warning("could not open Modem at %s, will keep trying: %s", key, exc)
            return
        self._unopenable.discard(key)
        receiver = Receiver(link, self._store, self._poll_interval)
        stop = threading.Event()
        thread = threading.Thread(target=receiver.run, args=(stop,), daemon=True)
        with self._lock:
            self._running[key] = _Running(link, receiver, thread, stop)
        thread.start()
        log.info("Modem attached at %s", key)

    def _retire(self, key: str) -> None:
        with self._lock:
            running = self._running.pop(key)
        running.stop.set()
        running.thread.join()
        running.link.close()
        log.info("Modem %s at %s is gone", running.receiver.imei or "unknown", key)
