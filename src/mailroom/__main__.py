"""Run Mailroom against the Modems attached to this computer."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

from mailroom.usb import UsbTransport
from mailroom.web import create_app

DEFAULT_DB = Path.home() / "Library" / "Application Support" / "Mailroom" / "mailroom.db"


def main() -> None:
    logging.basicConfig(level=os.environ.get("MAILROOM_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db_path = Path(os.environ.get("MAILROOM_DB", DEFAULT_DB))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(UsbTransport(), db_path)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MAILROOM_PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
