"""Runs one Receiver per attached Modem for as long as Mailroom is up."""

from __future__ import annotations

import threading

from mailroom.receiver import Receiver
from mailroom.store import Store
from mailroom.transport import ModemLink, Transport


class Service:
    def __init__(self, transport: Transport, store: Store, poll_interval: float = 30.0) -> None:
        self._transport = transport
        self._store = store
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._links: list[ModemLink] = []

    def start(self) -> None:
        self._links = self._transport.links()
        for link in self._links:
            receiver = Receiver(link, self._store, self._poll_interval)
            thread = threading.Thread(target=receiver.run, args=(self._stop,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join()
        self._threads.clear()
        for link in self._links:
            link.close()
        self._links.clear()
