"""Run Mailroom against the Modems attached to this computer."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

import uvicorn

from mailroom import config
from mailroom.access import CloudflareAccess, LockedAccess, OpenAccess
from mailroom.health import network_service_enabled
from mailroom.usb import UsbTransport
from mailroom.web import create_app

DEFAULT_DB = config.DATA_DIR / "mailroom.db"


def main() -> None:
    log_file = os.environ.get("MAILROOM_LOG_FILE")
    handler: logging.Handler = logging.StreamHandler()
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3)
    logging.basicConfig(
        level=os.environ.get("MAILROOM_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )
    db_path = Path(os.environ.get("MAILROOM_DB", DEFAULT_DB))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    settings = config.load()
    if settings.telegram is None:
        logging.getLogger(__name__).warning("Telegram is not set up; Messages will not be forwarded")
    log = logging.getLogger(__name__)
    if settings.access is not None:
        access = CloudflareAccess(settings.access)
    elif settings.allow_unauthenticated:
        log.warning("the web page is open to anyone on this computer: [access] allow_unauthenticated is set")
        access = OpenAccess()
    else:
        log.warning("the web page is locked until [access] team_domain and audience are set in the config")
        access = LockedAccess()
    app = create_app(
        UsbTransport(),
        db_path,
        telegram=settings.telegram,
        alert_after=settings.alert_after_minutes * 60,
        network_service_enabled=network_service_enabled,
        access=access,
    )
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MAILROOM_PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
