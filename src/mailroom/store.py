"""SQLite storage for SIMs and Messages."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mailroom.pdu import Delivery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sims (
    iccid  TEXT PRIMARY KEY,
    label  TEXT NOT NULL,
    number TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    sim_iccid   TEXT NOT NULL REFERENCES sims(iccid),
    sender      TEXT NOT NULL,
    text        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    received_at TEXT NOT NULL,
    pdu         TEXT NOT NULL,
    UNIQUE (sim_iccid, pdu)
);
"""


@dataclass(frozen=True)
class StoredMessage:
    id: int
    sim_label: str
    sender: str
    text: str
    sent_at: datetime


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def register_sim(self, iccid: str, number: str | None) -> None:
        """Record a SIM the first time it is seen; a known SIM keeps its label."""
        label = number or f"SIM …{iccid[-4:]}"
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sims (iccid, label, number) VALUES (?, ?, ?) "
                "ON CONFLICT (iccid) DO UPDATE SET number = COALESCE(excluded.number, number)",
                (iccid, label, number),
            )

    def add_message(self, iccid: str, pdu: str, delivery: Delivery) -> bool:
        """Store a Message durably. Returns False if this exact PDU was already stored."""
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO messages "
                "(sim_iccid, sender, text, sent_at, received_at, pdu) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    iccid,
                    delivery.sender,
                    delivery.text,
                    delivery.sent_at.astimezone(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    pdu.upper(),
                ),
            )
            return cursor.rowcount == 1

    def list_messages(self) -> list[StoredMessage]:
        """All Messages, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT m.id, s.label, m.sender, m.text, m.sent_at "
                "FROM messages m JOIN sims s ON s.iccid = m.sim_iccid "
                "ORDER BY m.sent_at DESC, m.id DESC"
            ).fetchall()
        return [
            StoredMessage(id_, label, sender, text, datetime.fromisoformat(sent_at))
            for id_, label, sender, text, sent_at in rows
        ]
