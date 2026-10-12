"""SQLite storage for SIMs, Messages and their Parts."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mailroom.pdu import Delivery, PduError, decode_deliver

_SCHEMA_VERSION = 3
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sims (
    iccid  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    number     TEXT,
    forwarding INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE messages (
    id           INTEGER PRIMARY KEY,
    sim_iccid    TEXT NOT NULL REFERENCES sims(iccid),
    sender       TEXT NOT NULL,
    text         TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    complete     INTEGER NOT NULL,
    concat_ref   INTEGER,
    concat_total INTEGER,
    forward_state TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE parts (
    id          INTEGER PRIMARY KEY,
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    sim_iccid   TEXT NOT NULL,
    sequence    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    pdu         TEXT NOT NULL,
    UNIQUE (sim_iccid, pdu)
);
"""

# Concatenation references are a single byte and get reused, so a Part only
# joins a Message whose other Parts the network stamped around the same time.
_SAME_MESSAGE_WINDOW = timedelta(days=1)
MISSING_PART = "[…]"

# Forwarding states of a Message.
PENDING = "pending"  # not yet delivered to Telegram
SENT_INCOMPLETE = "sent_incomplete"  # delivered while Parts were missing; owed the full text
SENT = "sent"
SKIPPED = "skipped"  # never to be forwarded


@dataclass(frozen=True)
class StoredMessage:
    id: int
    sim_label: str
    sender: str
    text: str
    sent_at: datetime
    complete: bool
    forward_state: str = PENDING
    forwarding: bool = True


@dataclass(frozen=True)
class StoredSim:
    iccid: str
    label: str
    number: str | None
    forwarding: bool
    last_message_at: datetime | None


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._migrate()

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

    def list_sims(self) -> list[StoredSim]:
        with self._lock:
            rows = self._db.execute(
                "SELECT s.iccid, s.label, s.number, s.forwarding, "
                "(SELECT MAX(sent_at) FROM messages m WHERE m.sim_iccid = s.iccid) "
                "FROM sims s ORDER BY s.rowid"
            ).fetchall()
        return [
            StoredSim(iccid, label, number, bool(forwarding), datetime.fromisoformat(last) if last else None)
            for iccid, label, number, forwarding, last in rows
        ]

    def rename_sim(self, iccid: str, label: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE sims SET label = ? WHERE iccid = ?", (label, iccid))

    def set_forwarding(self, iccid: str, enabled: bool) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE sims SET forwarding = ? WHERE iccid = ?", (enabled, iccid))

    def add_message(self, iccid: str, pdu: str, delivery: Delivery) -> bool:
        """Store a delivery durably, as a new Message or as a Part of one already begun.

        Returns False if this exact PDU was already stored.
        """
        with self._lock, self._db:
            return self._add(iccid, pdu, delivery, datetime.now(timezone.utc))

    def list_messages(
        self,
        incomplete_received_before: datetime | None = None,
        sim_iccid: str | None = None,
        search: str | None = None,
    ) -> list[StoredMessage]:
        """Messages, newest first, optionally only one SIM's and only those containing `search`.

        A Message still missing Parts is left out until it has waited since
        `incomplete_received_before`, so that Parts in transit are not shown as a broken Message.
        """
        cutoff = (incomplete_received_before or datetime.max.replace(tzinfo=timezone.utc)).isoformat()
        where, values = ["(m.complete OR m.received_at <= ?)"], [cutoff]
        if sim_iccid:
            where.append("m.sim_iccid = ?")
            values.append(sim_iccid)
        if search:
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(m.text LIKE ? ESCAPE '\\' OR m.sender LIKE ? ESCAPE '\\')")
            values += [pattern, pattern]
        with self._lock:
            rows = self._db.execute(
                _SELECT_MESSAGE + "WHERE " + " AND ".join(where) + " ORDER BY m.sent_at DESC, m.id DESC",
                values,
            ).fetchall()
        return [_stored(row) for row in rows]

    def delete_message(self, message_id: int) -> None:
        """Remove a Message and its Parts for good."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM parts WHERE message_id = ?", (message_id,))
            self._db.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    def awaiting_forwarding(self, incomplete_received_before: datetime) -> list[StoredMessage]:
        """Messages owed to Telegram, oldest first.

        That is Messages never delivered that are complete or have waited long
        enough for their Parts, and Messages delivered incomplete that have since
        been completed.
        """
        with self._lock:
            rows = self._db.execute(
                _SELECT_MESSAGE
                + "WHERE (m.forward_state = ? AND (m.complete OR m.received_at <= ?)) "
                "OR (m.forward_state = ? AND m.complete) ORDER BY m.id",
                (PENDING, incomplete_received_before.isoformat(), SENT_INCOMPLETE),
            ).fetchall()
        return [_stored(row) for row in rows]

    def set_forward_state(self, message_id: int, state: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE messages SET forward_state = ? WHERE id = ?", (state, message_id))

    def _add(self, iccid: str, pdu: str, delivery: Delivery, received_at: datetime) -> bool:
        pdu = pdu.upper()
        concat = delivery.concatenation
        sequence = concat.sequence if concat else 1
        # Compared by content rather than by PDU: a network can deliver the same SMS
        # twice through different service centres, which changes only the PDU's prefix.
        if self._db.execute(
            "SELECT 1 FROM parts p JOIN messages m ON m.id = p.message_id "
            "WHERE p.sim_iccid = ? AND m.sender = ? AND p.sent_at = ? AND p.text = ? AND p.sequence = ? "
            "AND m.concat_ref IS ? AND m.concat_total IS ?",
            (
                iccid,
                delivery.sender,
                _utc(delivery.sent_at),
                delivery.text,
                sequence,
                concat.reference if concat else None,
                concat.total if concat else None,
            ),
        ).fetchone():
            return False
        message_id = self._message_awaiting(iccid, delivery) if concat else None
        if message_id is None:
            message_id = self._db.execute(
                "INSERT INTO messages (sim_iccid, sender, text, sent_at, received_at, complete, "
                "concat_ref, concat_total) VALUES (?, ?, '', ?, ?, 0, ?, ?)",
                (
                    iccid,
                    delivery.sender,
                    _utc(delivery.sent_at),
                    _utc(received_at),
                    concat.reference if concat else None,
                    concat.total if concat else None,
                ),
            ).lastrowid
        self._db.execute(
            "INSERT INTO parts (message_id, sim_iccid, sequence, text, sent_at, pdu) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, iccid, sequence, delivery.text, _utc(delivery.sent_at), pdu),
        )
        self._assemble(message_id)
        return True

    def _message_awaiting(self, iccid: str, delivery: Delivery) -> int | None:
        """The Message this Part belongs to, if its other Parts have started to arrive."""
        concat = delivery.concatenation
        candidates = self._db.execute(
            "SELECT id, sent_at FROM messages "
            "WHERE sim_iccid = ? AND sender = ? AND concat_ref = ? AND concat_total = ? "
            "AND id NOT IN (SELECT message_id FROM parts WHERE sequence = ?) "
            "ORDER BY id DESC",
            (iccid, delivery.sender, concat.reference, concat.total, concat.sequence),
        ).fetchall()
        for message_id, sent_at in candidates:
            if abs(datetime.fromisoformat(sent_at) - delivery.sent_at) <= _SAME_MESSAGE_WINDOW:
                return message_id
        return None

    def _assemble(self, message_id: int) -> None:
        """Rebuild a Message's text from the Parts that have arrived, in sequence order."""
        (total,) = self._db.execute(
            "SELECT COALESCE(concat_total, 1) FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        parts = dict(
            self._db.execute("SELECT sequence, text FROM parts WHERE message_id = ?", (message_id,))
        )
        pieces: list[str] = []
        for sequence in range(1, total + 1):
            piece = parts.get(sequence, MISSING_PART)
            if piece != MISSING_PART or pieces[-1:] != [MISSING_PART]:
                pieces.append(piece)
        self._db.execute(
            "UPDATE messages SET text = ?, complete = ?, "
            "sent_at = (SELECT MIN(sent_at) FROM parts WHERE message_id = ?) WHERE id = ?",
            ("".join(pieces), len(parts) >= total, message_id, message_id),
        )

    def _migrate(self) -> None:
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
        if version == _SCHEMA_VERSION:
            return
        tables = {name for (name,) in self._db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "messages" not in tables:
            self._db.executescript(_SCHEMA)
        else:
            if version < 2:
                # Version 1 kept one row per PDU; replay them so split Messages are joined.
                earlier = self._db.execute(
                    "SELECT sim_iccid, pdu, received_at FROM messages ORDER BY id"
                ).fetchall()
                self._db.execute("DROP TABLE messages")
                self._db.execute("ALTER TABLE sims ADD COLUMN forwarding INTEGER NOT NULL DEFAULT 1")
                self._db.executescript(_SCHEMA)
                for iccid, pdu, received_at in earlier:
                    try:
                        self._add(iccid, pdu, decode_deliver(pdu), datetime.fromisoformat(received_at))
                    except PduError:
                        continue
            else:
                self._db.execute("ALTER TABLE sims ADD COLUMN forwarding INTEGER NOT NULL DEFAULT 1")
                self._db.execute(
                    "ALTER TABLE messages ADD COLUMN forward_state TEXT NOT NULL DEFAULT 'pending'"
                )
            # Messages from before Forwarding existed are history, not news.
            self._db.execute("UPDATE messages SET forward_state = ?", (SKIPPED,))
        self._db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


_SELECT_MESSAGE = (
    "SELECT m.id, s.label, m.sender, m.text, m.sent_at, m.complete, m.forward_state, s.forwarding "
    "FROM messages m JOIN sims s ON s.iccid = m.sim_iccid "
)


def _stored(row: tuple) -> StoredMessage:
    id_, label, sender, text, sent_at, complete, forward_state, forwarding = row
    return StoredMessage(
        id_, label, sender, text, datetime.fromisoformat(sent_at), bool(complete), forward_state, bool(forwarding)
    )


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()
