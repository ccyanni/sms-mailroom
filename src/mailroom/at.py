"""AT command framing over a raw byte stream.

Separates a command's own response from unsolicited lines, which a Modem may
emit at any moment, including in the middle of a response.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable

from mailroom.transport import ATError

log = logging.getLogger(__name__)

_UNSOLICITED = {
    "+CMTI", "+CMT", "+CDS", "+CGEV", "+CEREG", "+CREG", "+CGREG", "+CPIN", "+SIMCARD",
    "+CTZV", "+CIEV", "+CLIP", "+CRING", "+CUSD",
    "RING", "NO CARRIER", "*ATREADY", "SMS DONE", "PB DONE", "RDY",
}


class ATChannel:
    def __init__(self, read: Callable[[float], bytes], write: Callable[[bytes], None]) -> None:
        """`read(timeout)` returns whatever bytes arrive within `timeout` seconds, possibly none."""
        self._read = read
        self._write = write
        self._buffer = b""
        self._indications: deque[str] = deque()

    def command(self, text: str, timeout: float = 10.0) -> list[str]:
        log.debug("> %s", text)
        self._write(text.encode("ascii") + b"\r")
        info: list[str] = []
        deadline = time.monotonic() + timeout
        while True:
            for line in self._lines(max(deadline - time.monotonic(), 0.0)):
                if line == "OK":
                    return info
                if line == "ERROR" or line.startswith(("+CME ERROR", "+CMS ERROR")):
                    raise ATError(f"{text}: {line}")
                if line == text:
                    continue  # command echo
                if _is_unsolicited(line, text):
                    self._indications.append(line)
                else:
                    info.append(line)
            if time.monotonic() >= deadline:
                raise ATError(f"{text}: no response within {timeout:g}s")

    def wait_indication(self, timeout: float) -> str | None:
        if not self._indications:
            self._indications.extend(self._lines(timeout))
        return self._indications.popleft() if self._indications else None

    def _lines(self, timeout: float) -> list[str]:
        """Complete lines available after one read; a partial line is kept for the next call."""
        self._buffer += self._read(timeout)
        *complete, self._buffer = self._buffer.replace(b"\r", b"\n").split(b"\n")
        lines = [line.decode("ascii", errors="replace").strip() for line in complete if line.strip()]
        for line in lines:
            log.debug("< %s", line)
        return lines


def _is_unsolicited(line: str, command: str) -> bool:
    prefix = line.split(":", 1)[0]
    if prefix.startswith("+") and prefix[1:] in command:
        return False  # the answer to the command just sent
    return prefix in _UNSOLICITED
