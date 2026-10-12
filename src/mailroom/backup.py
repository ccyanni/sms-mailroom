"""Daily copies of the database, so a damaged or emptied one can be put back."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from mailroom.store import Store

log = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
_PREFIX, _SUFFIX = "mailroom-", ".db"


def _today() -> date:
    return datetime.now(TAIPEI).date()


class Backups:
    def __init__(
        self,
        store: Store,
        directory: Path | str,
        keep: int = 14,
        check_every: float = 300.0,
        today: Callable[[], date] = _today,
    ) -> None:
        self._store = store
        self._directory = Path(directory)
        self._keep = max(keep, 1)
        self._check_every = check_every
        self._today = today
        self.failing = False

    def run(self, stop: threading.Event) -> None:
        self.ensure()
        while not stop.wait(self._check_every):
            self.ensure()

    def ensure(self) -> None:
        """Make today's backup if there is none yet, then drop the ones beyond `keep`."""
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            target = self._directory / f"{_PREFIX}{self._today():%Y-%m-%d}{_SUFFIX}"
            if not target.exists():
                partial = target.with_suffix(".partial")
                partial.unlink(missing_ok=True)
                # Created owner-only before anything is written: the database holds verification codes.
                os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                self._store.backup_to(partial)
                partial.rename(target)
                log.info("backed up the database to %s", target)
            for old in self.existing()[self._keep:]:
                old.unlink()
            self.failing = False
        except Exception:
            if not self.failing:
                log.exception("could not back up the database")
            self.failing = True

    def existing(self) -> list[Path]:
        """Backups on disk, newest first."""
        return sorted(self._directory.glob(f"{_PREFIX}????-??-??{_SUFFIX}"), reverse=True)

    def latest(self) -> date | None:
        backups = self.existing()
        return date.fromisoformat(backups[0].name[len(_PREFIX):-len(_SUFFIX)]) if backups else None
