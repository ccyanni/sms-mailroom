"""SQLite storage for SIMs, Messages and their Parts."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mailroom.pdu import MMS, TEXT, Delivery, PduError, decode_deliver

_SCHEMA_VERSION = 8
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sims (
    iccid  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    number     TEXT,
    forwarding INTEGER NOT NULL DEFAULT 1,
    number_override TEXT,
    forgotten  INTEGER NOT NULL DEFAULT 0
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
    forward_state TEXT NOT NULL DEFAULT 'pending',
    archived      INTEGER NOT NULL DEFAULT 0,
    kind          TEXT NOT NULL DEFAULT 'text',
    deleted_at    TEXT
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

# Which Telegram message is a copy of which Message, so a button pressed under a copy finds its Message,
# and when it was sent, so it can be deleted from Telegram in time. Message ids are reused once the newest
# Message is deleted for good, so a button never carries one, and a copy of a Message deleted for good keeps
# no message_id, only what is needed to delete it from Telegram.
_COPIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_copies (
    telegram_message_id INTEGER PRIMARY KEY,
    message_id          INTEGER,
    sent_at             TEXT NOT NULL
)
"""

_ALERTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    key       TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    params    TEXT NOT NULL,
    since     TEXT NOT NULL,
    raised    INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0
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

# Where a Message is kept.
INBOX, ARCHIVE, TRASH = "inbox", "archived", "trash"
_IN_BOX = {
    INBOX: "m.deleted_at IS NULL AND NOT m.archived",
    ARCHIVE: "m.deleted_at IS NULL AND m.archived",
    TRASH: "m.deleted_at IS NOT NULL",
}


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
    archived: bool = False
    kind: str = TEXT  # TEXT, or an MMS or DATA Message whose text is not for reading
    deleted_at: datetime | None = None  # when it was moved to the Trash
    received_at: datetime | None = None  # when its first Part was stored; with the id, tells it from a later Message given the same id


@dataclass(frozen=True)
class StoredSim:
    iccid: str
    label: str
    number: str | None
    forwarding: bool
    last_message_at: datetime | None


@dataclass(frozen=True)
class StoredAlert:
    """A problem Mailroom has noticed and is tracking until it goes away."""

    key: str
    kind: str  # which problem; i18n turns it into words
    values: dict  # the particulars: which SIM, which Modem, how many
    since: datetime
    raised: bool  # it has lasted long enough to be worth telling the owner
    delivered: bool  # the owner has been told on Telegram


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.create_function("same_number", 2, _same_number, deterministic=True)
        os.chmod(path, 0o600)  # Messages are stored in plain text
        # Deleted rows are overwritten, not just marked free, so deleted text cannot be read back from the file.
        self._db.execute("PRAGMA secure_delete = ON")
        self._lock = threading.Lock()
        with self._lock, self._db:
            left_in_freed_space = self._migrate()
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(alerts)")}
            if columns and "kind" not in columns:
                self._db.execute("DROP TABLE alerts")  # an earlier layout; alerts are rebuilt as problems recur
            self._db.executescript(_ALERTS_SCHEMA)
            self._migrate_copies()
            self._db.execute(_COPIES_SCHEMA)
        if left_in_freed_space:
            with self._lock:
                self._db.execute("VACUUM")  # rewrites the file without the space earlier versions freed

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def backup_to(self, path: Path | str) -> None:
        """Write a consistent copy of the whole database to `path`."""
        with self._lock:
            copy = sqlite3.connect(path)
            try:
                self._db.backup(copy)
            finally:
                copy.close()

    def register_sim(self, iccid: str, number: str | None) -> None:
        """Record a SIM the first time it is seen; a known SIM keeps its label, and a forgotten one is remembered again."""
        label = number or f"SIM …{iccid[-4:]}"
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sims (iccid, label, number) VALUES (?, ?, ?) "
                "ON CONFLICT (iccid) DO UPDATE SET number = COALESCE(excluded.number, number), forgotten = 0",
                (iccid, label, number),
            )

    def list_sims(self) -> list[StoredSim]:
        """The SIMs the owner has not forgotten."""
        with self._lock:
            rows = self._db.execute(
                "SELECT s.iccid, s.label, COALESCE(s.number_override, s.number), s.forwarding, "
                "(SELECT MAX(sent_at) FROM messages m WHERE m.sim_iccid = s.iccid) "
                "FROM sims s WHERE NOT s.forgotten ORDER BY s.rowid"
            ).fetchall()
        return [
            StoredSim(iccid, label, number, bool(forwarding), datetime.fromisoformat(last) if last else None)
            for iccid, label, number, forwarding, last in rows
        ]

    def forget_sim(self, iccid: str) -> None:
        """Stop showing a SIM that is no longer used; its Messages are kept."""
        with self._lock, self._db:
            self._db.execute("UPDATE sims SET forgotten = 1 WHERE iccid = ?", (iccid,))

    def rename_sim(self, iccid: str, label: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE sims SET label = ? WHERE iccid = ?", (label, iccid))

    def correct_sim_number(self, iccid: str, number: str | None) -> None:
        """Show the owner's number for a SIM instead of the one it reports; None goes back to the SIM's own."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE sims SET number_override = NULLIF(?, number) WHERE iccid = ?", (number, iccid)
            )

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
        box: str = INBOX,
    ) -> list[StoredMessage]:
        """The Messages in one box, newest first; optionally one SIM's and only Messages containing `search`.

        A Message still missing Parts is left out until it has waited since
        `incomplete_received_before`, so that Parts in transit are not shown as a broken Message.
        """
        where, values = _filter(incomplete_received_before, sim_iccid, search)
        with self._lock:
            rows = self._db.execute(
                _SELECT_MESSAGE + f"WHERE {where} AND {_IN_BOX[box]} ORDER BY m.sent_at DESC, m.id DESC", values
            ).fetchall()
        return [_stored(row) for row in rows]

    def count_messages(
        self,
        incomplete_received_before: datetime | None = None,
        sim_iccid: str | None = None,
        search: str | None = None,
    ) -> dict[str, int]:
        """How many Messages the same filter finds in each box."""
        where, values = _filter(incomplete_received_before, sim_iccid, search)
        counted = ", ".join(f"COALESCE(SUM({condition}), 0)" for condition in _IN_BOX.values())
        with self._lock:
            row = self._db.execute(f"SELECT {counted} FROM messages m WHERE {where}", values).fetchone()
        return dict(zip(_IN_BOX, row))

    def set_archived(self, message_id: int, archived: bool) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE messages SET archived = ? WHERE id = ?", (archived, message_id))

    def move_to_trash(self, message_ids: list[int]) -> None:
        moment = _utc(datetime.now(timezone.utc))
        with self._lock, self._db:
            self._db.executemany(
                "UPDATE messages SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                [(moment, message_id) for message_id in message_ids],
            )

    def restore(self, message_ids: list[int]) -> None:
        """Take Messages out of the Trash, back to the inbox or the Archive, wherever they were."""
        with self._lock, self._db:
            self._db.executemany(
                "UPDATE messages SET deleted_at = NULL WHERE id = ?", [(message_id,) for message_id in message_ids]
            )

    def delete_for_good(self, message_ids: list[int]) -> None:
        """Remove Messages that are in the Trash, and their Parts. Messages elsewhere are left alone."""
        with self._lock, self._db:
            for message_id in message_ids:
                self._purge("id = ?", (message_id,))

    def empty_trash(self, deleted_before: datetime | None = None) -> None:
        """Delete for good everything in the Trash, or only what was moved there before `deleted_before`."""
        with self._lock, self._db:
            if deleted_before is None:
                self._purge("1", ())
            else:
                self._purge("deleted_at <= ?", (_utc(deleted_before),))

    def _purge(self, condition: str, values: tuple) -> None:
        chosen = f"SELECT id FROM messages WHERE deleted_at IS NOT NULL AND {condition}"
        self._db.execute(f"DELETE FROM parts WHERE message_id IN ({chosen})", values)
        self._db.execute(f"UPDATE telegram_copies SET message_id = NULL WHERE message_id IN ({chosen})", values)
        self._db.execute(f"DELETE FROM messages WHERE id IN ({chosen})", values)

    def next_to_forward(self, incomplete_received_before: datetime, after_id: int = 0) -> StoredMessage | None:
        """The oldest Message owed to Telegram with an id above `after_id`, as it is right now.

        That is a Message never delivered that is complete or has waited long
        enough for its Parts, or one delivered incomplete that has since been
        completed. Asked for one at a time, so a Message moved to the Trash, or
        whose SIM's Forwarding was switched off, while others were being sent is
        seen as it is now.
        """
        with self._lock:
            row = self._db.execute(
                _SELECT_MESSAGE
                + "WHERE m.id > ? AND m.deleted_at IS NULL "
                "AND ((m.forward_state = ? AND (m.complete OR m.received_at <= ?)) OR (m.forward_state = ? AND m.complete)) "
                "ORDER BY m.id LIMIT 1",
                (after_id, PENDING, incomplete_received_before.isoformat(), SENT_INCOMPLETE),
            ).fetchone()
        return _stored(row) if row else None

    def record_forwarding(self, message: StoredMessage, state: str, telegram_message_id: int | None = None) -> None:
        """Set what became of forwarding `message`, and the Telegram copy it was sent as, in one write.

        Only `message` itself is changed: if it was deleted for good while it was being sent, and a newer
        Message was given its id, nothing is.
        """
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE messages SET forward_state = ? WHERE id = ? AND received_at = ?",
                (state, message.id, _utc(message.received_at)),
            ).rowcount
            if changed and telegram_message_id is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO telegram_copies (telegram_message_id, message_id, sent_at) VALUES (?, ?, ?)",
                    (telegram_message_id, message.id, _utc(datetime.now(timezone.utc))),
                )

    def telegram_copies_to_delete(self, sent_before: datetime) -> list[int]:
        """Telegram copies sent before `sent_before`, and copies of Messages deleted for good."""
        with self._lock:
            rows = self._db.execute(
                "SELECT telegram_message_id FROM telegram_copies WHERE sent_at <= ? OR message_id IS NULL "
                "ORDER BY telegram_message_id",
                (_utc(sent_before),),
            ).fetchall()
        return [telegram_message_id for (telegram_message_id,) in rows]

    def forget_telegram_copy(self, telegram_message_id: int) -> None:
        """The copy is no longer on Telegram, or can no longer be deleted from it."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM telegram_copies WHERE telegram_message_id = ?", (telegram_message_id,))

    def message_for_telegram_copy(self, telegram_message_id: int) -> StoredMessage | None:
        """The Message a Telegram message is a copy of; None once that Message is deleted for good."""
        with self._lock:
            row = self._db.execute(
                _SELECT_MESSAGE + "JOIN telegram_copies c ON c.message_id = m.id WHERE c.telegram_message_id = ?",
                (telegram_message_id,),
            ).fetchone()
        return _stored(row) if row else None

    def telegram_copies(self, message_id: int) -> list[int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT telegram_message_id FROM telegram_copies WHERE message_id = ? ORDER BY telegram_message_id",
                (message_id,),
            ).fetchall()
        return [telegram_message_id for (telegram_message_id,) in rows]

    def list_alerts(self) -> list[StoredAlert]:
        with self._lock:
            rows = self._db.execute(
                "SELECT key, kind, params, since, raised, delivered FROM alerts ORDER BY since, key"
            ).fetchall()
        return [
            StoredAlert(key, kind, json.loads(params), datetime.fromisoformat(since), bool(raised), bool(delivered))
            for key, kind, params, since, raised, delivered in rows
        ]

    def save_alert(self, alert: StoredAlert) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO alerts (key, kind, params, since, raised, delivered) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    alert.key,
                    alert.kind,
                    json.dumps(alert.values, ensure_ascii=False),
                    _utc(alert.since),
                    alert.raised,
                    alert.delivered,
                ),
            )

    def delete_alert(self, key: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM alerts WHERE key = ?", (key,))

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
                "concat_ref, concat_total, kind) VALUES (?, ?, '', ?, ?, 0, ?, ?, ?)",
                (
                    iccid,
                    delivery.sender,
                    _utc(delivery.sent_at),
                    _utc(received_at),
                    concat.reference if concat else None,
                    concat.total if concat else None,
                    delivery.kind,
                ),
            ).lastrowid
        elif delivery.kind == MMS:  # only the first Part of a data Message shows it is an MMS notice
            self._db.execute("UPDATE messages SET kind = ? WHERE id = ?", (MMS, message_id))
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
            "UPDATE messages SET text = CASE kind WHEN 'text' THEN ? ELSE '' END, complete = ?, "
            "sent_at = (SELECT MIN(sent_at) FROM parts WHERE message_id = ?) WHERE id = ?",
            ("".join(pieces), len(parts) >= total, message_id, message_id),
        )

    def _migrate_copies(self) -> None:
        """Give copies recorded before they had a sent time one, and let them outlive their Message."""
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(telegram_copies)")}
        if not columns or "sent_at" in columns:
            return
        if not self._db.in_transaction:
            self._db.execute("BEGIN")  # so the table is never left half rebuilt
        self._db.execute("ALTER TABLE telegram_copies RENAME TO telegram_copies_before")
        self._db.execute(_COPIES_SCHEMA)
        self._db.execute(
            "INSERT INTO telegram_copies (telegram_message_id, message_id, sent_at) "
            "SELECT c.telegram_message_id, m.id, COALESCE(m.received_at, ?) "
            "FROM telegram_copies_before c LEFT JOIN messages m ON m.id = c.message_id",
            (_utc(datetime.now(timezone.utc)),),
        )
        self._db.execute("DROP TABLE telegram_copies_before")

    def _migrate(self) -> bool:
        """Bring the database up to date. Returns True if earlier versions may have left deleted text in freed space."""
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
        if version == _SCHEMA_VERSION:
            return False
        tables = {name for (name,) in self._db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "messages" not in tables:
            self._db.executescript(_SCHEMA)
        elif version < 2:
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
            # Messages from before Forwarding existed are history, not news.
            self._db.execute("UPDATE messages SET forward_state = ?", (SKIPPED,))
        else:
            if version < 3:
                self._db.execute("ALTER TABLE sims ADD COLUMN forwarding INTEGER NOT NULL DEFAULT 1")
                self._db.execute(
                    "ALTER TABLE messages ADD COLUMN forward_state TEXT NOT NULL DEFAULT 'pending'"
                )
                self._db.execute("UPDATE messages SET forward_state = ?", (SKIPPED,))
            if version < 4:
                self._db.execute("ALTER TABLE messages ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        sim_columns = {row[1] for row in self._db.execute("PRAGMA table_info(sims)")}
        if "number_override" not in sim_columns:
            self._db.execute("ALTER TABLE sims ADD COLUMN number_override TEXT")
        if "forgotten" not in sim_columns:
            self._db.execute("ALTER TABLE sims ADD COLUMN forgotten INTEGER NOT NULL DEFAULT 0")
        if "kind" not in {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}:
            self._db.execute("ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'")
            self._recognise_data_messages()
        left_in_freed_space = False
        if "deleted_at" not in {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}:
            self._db.execute("ALTER TABLE messages ADD COLUMN deleted_at TEXT")
            left_in_freed_space = True  # versions before the Trash deleted without overwriting
        self._db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        return left_in_freed_space

    def _recognise_data_messages(self) -> None:
        """Mark MMS notices and data SMS stored before they were told apart, whose text was their payload as letters."""
        recognised: dict[int, str] = {}
        for part_id, message_id, pdu in self._db.execute("SELECT id, message_id, pdu FROM parts").fetchall():
            try:
                delivery = decode_deliver(pdu)
            except PduError:
                continue
            if delivery.kind != TEXT:
                self._db.execute("UPDATE parts SET text = ? WHERE id = ?", (delivery.text, part_id))
                if recognised.get(message_id) != MMS:
                    recognised[message_id] = delivery.kind
        for message_id, kind in recognised.items():
            self._db.execute("UPDATE messages SET kind = ? WHERE id = ?", (kind, message_id))
            self._assemble(message_id)


def _filter(
    incomplete_received_before: datetime | None, sim_iccid: str | None, search: str | None
) -> tuple[str, list]:
    """The WHERE clause shared by listing and counting, so the two can never disagree."""
    cutoff = (incomplete_received_before or datetime.max.replace(tzinfo=timezone.utc)).isoformat()
    where, values = ["(m.complete OR m.received_at <= ?)"], [cutoff]
    if sim_iccid:
        where.append("m.sim_iccid = ?")
        values.append(sim_iccid)
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(m.text LIKE ? ESCAPE '\\' OR m.sender LIKE ? ESCAPE '\\' OR same_number(m.sender, ?))")
        values += [pattern, pattern, search]
    return " AND ".join(where), values


_PHONE_NUMBER = re.compile(r"\+?[\d\s().-]+")
_SHORTEST_NUMBER = 7  # digits; anything shorter is a short code, matched as plain text only


def _same_number(sender: str, search: str) -> bool:
    """Whether a search names the sender's line however either is written: 0933…, +886933… and 00886933… all do.

    The digits are compared from the end, so a leading 0, a + or 00 and the country code make no difference.
    """
    if not (_PHONE_NUMBER.fullmatch(sender) and _PHONE_NUMBER.fullmatch(search)):
        return False
    sender_digits, search_digits = (re.sub(r"\D", "", n).lstrip("0") for n in (sender, search))
    shorter, longer = sorted((sender_digits, search_digits), key=len)
    return len(shorter) >= _SHORTEST_NUMBER and longer.endswith(shorter)


_SELECT_MESSAGE = (
    "SELECT m.id, s.label, m.sender, m.text, m.sent_at, m.complete, m.forward_state, s.forwarding, m.archived, "
    "m.kind, m.deleted_at, m.received_at "
    "FROM messages m JOIN sims s ON s.iccid = m.sim_iccid "
)


def _stored(row: tuple) -> StoredMessage:
    id_, label, sender, text, sent_at, complete, forward_state, forwarding, archived, kind, deleted_at, received_at = row
    return StoredMessage(
        id_,
        label,
        sender,
        text,
        datetime.fromisoformat(sent_at),
        bool(complete),
        forward_state,
        bool(forwarding),
        bool(archived),
        kind,
        datetime.fromisoformat(deleted_at) if deleted_at else None,
        datetime.fromisoformat(received_at),
    )


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()
