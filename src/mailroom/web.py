"""The web page the owner reads Messages on."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mailroom.service import Service
from mailroom.store import Store
from mailroom.transport import Transport

TAIPEI = ZoneInfo("Asia/Taipei")
_templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def create_app(
    transport: Transport,
    db_path: Path | str,
    poll_interval: float = 30.0,
    scan_interval: float = 2.0,
    part_timeout: float = 60.0,
) -> FastAPI:
    store = Store(db_path)
    service = Service(transport, store, poll_interval, scan_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        try:
            yield
        finally:
            service.stop()
            store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def messages(request: Request):
        rows = [
            {
                "sim": m.sim_label,
                "sender": m.sender,
                "text": m.text,
                "time": m.sent_at.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S"),
                "complete": m.complete,
            }
            for m in store.list_messages(
                incomplete_received_before=datetime.now(timezone.utc) - timedelta(seconds=part_timeout)
            )
        ]
        modems = [
            {"imei": m.imei or "unidentified", "state": m.state} for m in service.modems()
        ]
        return _templates.TemplateResponse(
            request, "messages.html", {"messages": rows, "modems": modems}
        )

    return app
