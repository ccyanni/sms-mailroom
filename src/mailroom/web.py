"""The web page the owner reads Messages on."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mailroom.access import COOKIE, HEADER, AccessPolicy, OpenAccess
from mailroom.forwarder import Forwarder
from mailroom.health import HealthMonitor
from mailroom.service import Service
from mailroom.store import PENDING, SENT, SENT_INCOMPLETE, SKIPPED, Store
from mailroom.telegram import HttpPost, TelegramSettings, http_post, telegram_sender
from mailroom.transport import Transport

TAIPEI = ZoneInfo("Asia/Taipei")
_FORWARD_LABELS = {
    PENDING: "not forwarded yet",
    SENT_INCOMPLETE: "forwarded",
    SENT: "forwarded",
    SKIPPED: "not forwarded",
}
_templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def create_app(
    transport: Transport,
    db_path: Path | str,
    poll_interval: float = 30.0,
    scan_interval: float = 2.0,
    part_timeout: float = 60.0,
    telegram: TelegramSettings | None = None,
    http_post: HttpPost = http_post,
    forward_interval: float = 2.0,
    alert_after: float = 180.0,
    health_interval: float = 5.0,
    network_service_enabled: Callable[[], bool | None] | None = None,
    access: AccessPolicy | None = None,
) -> FastAPI:
    access = access or OpenAccess()
    store = Store(db_path)
    send = telegram_sender(telegram, http_post) if telegram else None
    forwarder = Forwarder(store, send, part_timeout, forward_interval)
    service = Service(transport, store, forwarder, poll_interval, scan_interval)
    monitor = HealthMonitor(
        store, service, forwarder, send, alert_after, health_interval, network_service_enabled
    )
    service.add_background(monitor.run)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        try:
            yield
        finally:
            service.stop()
            store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def owner_only(request: Request, call_next):
        token = request.headers.get(HEADER) or request.cookies.get(COOKIE)
        if not access.allows(token) or _from_another_site(request):
            return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def messages(request: Request, sim: str = "", q: str = ""):
        search = q.strip()
        rows = [
            {
                "id": m.id,
                "sim": m.sim_label,
                "sender": m.sender,
                "text": m.text,
                "time": _taipei(m.sent_at),
                "complete": m.complete,
                "forwarding": _FORWARD_LABELS[m.forward_state],
            }
            for m in store.list_messages(
                incomplete_received_before=datetime.now(timezone.utc) - timedelta(seconds=part_timeout),
                sim_iccid=sim or None,
                search=search or None,
            )
        ]
        attached = service.modems()
        in_modem = {m.iccid: m for m in attached if m.iccid}
        sims = []
        for stored in store.list_sims():
            modem = in_modem.get(stored.iccid)
            network = modem.network if modem else None
            sims.append(
                {
                    "iccid": stored.iccid,
                    "label": stored.label,
                    "number": stored.number or "number unknown",
                    "forwarding": stored.forwarding,
                    "operator": (network and network.operator) or "–",
                    "signal": f"{network.signal}/31" if network and network.signal is not None else "–",
                    "registration": network.registration if network else "not in a Modem",
                    "last": _taipei(stored.last_message_at) if stored.last_message_at else "never",
                }
            )
        modems = [{"imei": m.imei or "unidentified", "state": m.state} for m in attached]
        return _templates.TemplateResponse(
            request,
            "messages.html",
            {
                "messages": rows,
                "modems": modems,
                "sims": sims,
                "sim": sim,
                "search": search,
                "alerts": monitor.active_alerts(),
            },
        )

    @app.post("/messages/{message_id}/delete")
    def delete_message(message_id: int, request: Request):
        store.delete_message(message_id)
        return _back(request)

    @app.post("/sims/{iccid}/label")
    async def rename_sim(iccid: str, request: Request):
        label = (await _form(request)).get("label", "").strip()
        if label:
            store.rename_sim(iccid, label[:60])
        return _back(request)

    @app.post("/sims/{iccid}/forwarding")
    async def set_forwarding(iccid: str, request: Request):
        store.set_forwarding(iccid, (await _form(request)).get("enabled") == "1")
        return _back(request)

    return app


def _taipei(moment: datetime) -> str:
    return moment.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


async def _form(request: Request) -> dict[str, str]:
    fields = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {name: values[-1] for name, values in fields.items()}


def _back(request: Request) -> RedirectResponse:
    """Return to the page the form was on, keeping its filter and search."""
    referer = urlsplit(request.headers.get("referer", ""))
    target = "/" + (f"?{referer.query}" if referer.path == "/" and referer.query else "")
    return RedirectResponse(target, status_code=303)


def _from_another_site(request: Request) -> bool:
    """A form posted by some other website, riding on the owner's signed-in browser."""
    origin = request.headers.get("origin")
    if request.method in ("GET", "HEAD") or not origin:
        return False
    return urlsplit(origin).netloc != request.headers.get("host")
