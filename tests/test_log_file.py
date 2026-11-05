"""The log names the Modems and SIMs, so only the owner can read it."""

import logging
import stat

from mailroom.__main__ import log_handler


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_new_log_file_is_readable_only_by_the_owner(tmp_path):
    handler = log_handler(str(tmp_path / "logs" / "mailroom.log"))
    handler.emit(logging.makeLogRecord({"msg": "hello"}))
    handler.close()

    assert mode(tmp_path / "logs" / "mailroom.log") == 0o600


def test_log_file_left_readable_by_others_is_closed_off(tmp_path):
    log = tmp_path / "mailroom.log"
    log.write_text("old lines\n")
    log.chmod(0o644)
    old = tmp_path / "mailroom.log.1"
    old.write_text("older lines\n")
    old.chmod(0o644)

    log_handler(str(log)).close()

    assert mode(log) == 0o600 and mode(old) == 0o600


def test_rotated_log_files_are_readable_only_by_the_owner(tmp_path):
    handler = log_handler(str(tmp_path / "mailroom.log"), max_bytes=10)
    for _ in range(3):
        handler.emit(logging.makeLogRecord({"msg": "a line longer than ten bytes"}))
    handler.close()

    assert [mode(path) for path in sorted(tmp_path.iterdir())] == [0o600] * len(list(tmp_path.iterdir()))
    assert (tmp_path / "mailroom.log.1").exists()
