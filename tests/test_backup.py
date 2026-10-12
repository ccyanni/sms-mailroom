"""Mailroom keeps a daily copy of its database."""

import re
import sqlite3
import stat
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from mailroom.web import create_app
from support import FakeModem, FakeTransport, build_pdu, wait_for


class Calendar:
    def __init__(self) -> None:
        self.day = date(2026, 10, 12)

    def __call__(self) -> date:
        return self.day


@pytest.fixture
def calendar():
    return Calendar()


@pytest.fixture
def modem():
    return FakeModem()


@pytest.fixture
def backups(tmp_path):
    return tmp_path / "backups"


@pytest.fixture
def mailroom(modem, calendar, backups, tmp_path):
    def start(keep=14, directory=None):
        return TestClient(
            create_app(
                FakeTransport(modem),
                tmp_path / "mailroom.db",
                poll_interval=0.1,
                scan_interval=0.05,
                backup_dir=directory or backups,
                backup_keep=keep,
                backup_check_every=0.05,
                backup_today=calendar,
            )
        )
    return start


def names(directory) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def messages_in(path) -> list[str]:
    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return [text for (text,) in db.execute("SELECT text FROM messages ORDER BY id")]
    finally:
        db.close()


def backup_row(page) -> tuple[str, str, str]:
    row = re.search(
        r'data-level="(\w+)">(?:(?!</li>).)*?<b>Database backup</b>.*?class="sys-state">(.*?)</span>.*?<small>(.*?)</small>',
        page.get("/status").text,
        flags=re.S,
    )
    return row.group(2), row.group(1), row.group(3)


def test_database_is_backed_up_when_the_service_starts(modem, mailroom, backups):
    with mailroom() as page:
        modem.deliver(build_pdu("111", "stored before the restart"))
        wait_for(lambda: "stored before the restart" in page.get("/").text)
    (backups / "mailroom-2026-10-12.db").unlink()

    with mailroom():
        wait_for(lambda: backups.exists() and names(backups) == ["mailroom-2026-10-12.db"])

    assert messages_in(backups / "mailroom-2026-10-12.db") == ["stored before the restart"]


def test_only_one_backup_is_made_per_day(mailroom, backups):
    with mailroom():
        wait_for(lambda: (backups / "mailroom-2026-10-12.db").exists())
        first = (backups / "mailroom-2026-10-12.db").stat().st_mtime_ns
        import time
        time.sleep(0.4)

        assert names(backups) == ["mailroom-2026-10-12.db"]
        assert (backups / "mailroom-2026-10-12.db").stat().st_mtime_ns == first


def test_a_new_backup_is_made_when_the_day_changes(modem, calendar, mailroom, backups):
    with mailroom() as page:
        wait_for(lambda: (backups / "mailroom-2026-10-12.db").exists())
        modem.deliver(build_pdu("111", "arrived on the first day"))
        wait_for(lambda: "arrived on the first day" in page.get("/").text)

        calendar.day += timedelta(days=1)
        wait_for(lambda: len(names(backups)) == 2)

    assert names(backups) == ["mailroom-2026-10-12.db", "mailroom-2026-10-13.db"]
    assert messages_in(backups / "mailroom-2026-10-12.db") == []
    assert messages_in(backups / "mailroom-2026-10-13.db") == ["arrived on the first day"]


def test_only_the_newest_backups_are_kept(calendar, mailroom, backups):
    with mailroom(keep=3):
        for _ in range(5):
            wait_for(lambda: backups.exists() and f"mailroom-{calendar.day}.db" in names(backups))
            calendar.day += timedelta(days=1)
        wait_for(lambda: f"mailroom-{calendar.day}.db" in names(backups))

    assert names(backups) == ["mailroom-2026-10-15.db", "mailroom-2026-10-16.db", "mailroom-2026-10-17.db"]


def test_other_files_in_the_backup_directory_are_left_alone(calendar, mailroom, backups):
    backups.mkdir()
    (backups / "notes.txt").write_text("mine")
    (backups / "mailroom-old.db").write_text("not one of ours")

    with mailroom(keep=1):
        wait_for(lambda: "mailroom-2026-10-12.db" in names(backups))
        calendar.day += timedelta(days=1)
        wait_for(lambda: "mailroom-2026-10-13.db" in names(backups))

    assert names(backups) == ["mailroom-2026-10-13.db", "mailroom-old.db", "notes.txt"]


def test_backups_can_be_read_only_by_the_owner(mailroom, backups):
    with mailroom():
        wait_for(lambda: (backups / "mailroom-2026-10-12.db").exists())

    assert stat.S_IMODE((backups / "mailroom-2026-10-12.db").stat().st_mode) == 0o600


def test_database_can_be_read_only_by_the_owner(mailroom, tmp_path):
    with mailroom():
        pass

    assert stat.S_IMODE((tmp_path / "mailroom.db").stat().st_mode) == 0o600


def test_status_shows_the_last_backup(mailroom, backups):
    with mailroom() as page:
        wait_for(lambda: (backups / "mailroom-2026-10-12.db").exists())

        assert backup_row(page) == ("Up to date", "ok", "Last one 2026-10-12; 1 kept")


def test_status_flags_a_backup_that_fails(mailroom, tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("in the way")

    with mailroom(directory=blocked) as page:
        wait_for(lambda: backup_row(page)[0] == "Failing")

        assert backup_row(page) == ("Failing", "warn", "The last attempt failed; see the log. Last good one: none")


def test_no_backup_row_when_backups_are_not_set_up(modem, tmp_path):
    with TestClient(create_app(FakeTransport(modem), tmp_path / "mailroom.db")) as page:
        assert "Database backup" not in page.get("/status").text
