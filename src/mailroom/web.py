"""The web page the owner reads and tidies Messages on, and checks the system's state."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mailroom import i18n
from mailroom.backup import Backups
from mailroom.access import COOKIE, HEADER, AccessPolicy, OpenAccess
from mailroom.forwarder import Forwarder
from mailroom.health import HealthMonitor
from mailroom.receiver import HOME, RECEIVING, ROAMING
from mailroom.service import Service
from mailroom.store import PENDING, SENT, SENT_INCOMPLETE, SKIPPED, Store
from mailroom.telegram import HttpPost, TelegramSettings, http_post, telegram_sender
from mailroom.transport import Transport

TAIPEI = ZoneInfo("Asia/Taipei")
LANGUAGE_COOKIE = "lang"
_FORWARD_LABELS = {
    PENDING: "forward_pending",
    SENT_INCOMPLETE: "forward_sent",
    SENT: "forward_sent",
    SKIPPED: "forward_skipped",
}
# A Message that talks about a code, and the first run of 4 to 8 digits in it that is not a date, a time or an amount.
_MENTIONS_CODE = re.compile(r"驗證|验证|校驗|校验|動態密碼|动态密码|密碼|密码|code|otp|passcode|\bpin\b", re.IGNORECASE)
_CODE = re.compile(
    r"(?<![\d:/$¥-])(?<!\d\.)(?<![A-Za-z])\d{4,8}(?!\d)(?![.:/]\d)(?![年月日元])"
    r"|(?<=[A-Za-z]-)\d{4,8}(?!\d)(?![.:/]\d)"
)
_UNSTABLE_WINDOW = timedelta(minutes=30)
_UNSTABLE_DROPS = 3
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
    language: str | None = None,
    start_notice: str | None = None,
    start_notice_after: float = 15.0,
    backup_dir: Path | str | None = None,
    backup_keep: int = 14,
    backup_check_every: float = 300.0,
    backup_today: Callable[[], date] | None = None,
) -> FastAPI:
    """`language` is used for Telegram texts and for the page until the owner picks another."""
    access = access or OpenAccess()
    language = i18n.language(language)
    store = Store(db_path)
    send = telegram_sender(telegram, http_post) if telegram else None
    forwarder = Forwarder(store, send, part_timeout, forward_interval, language)
    service = Service(transport, store, forwarder, poll_interval, scan_interval)
    monitor = HealthMonitor(
        store,
        service,
        forwarder,
        send,
        alert_after,
        health_interval,
        network_service_enabled,
        language,
        start_notice,
        start_notice_after,
    )
    service.add_background(monitor.run)
    backups = None
    if backup_dir is not None:
        clock = {"today": backup_today} if backup_today else {}
        backups = Backups(store, backup_dir, backup_keep, backup_check_every, **clock)
        service.add_background(backups.run)
    started_at = datetime.now(timezone.utc)

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

    def page(request: Request, template: str, lang: str, **context) -> HTMLResponse:
        return _templates.TemplateResponse(
            request,
            template,
            {
                "t": i18n.strings(lang),
                "lang": lang,
                "languages": [("zh", "中文"), ("en", "English")],
                "has_alerts": bool(monitor.active_alerts(lang)),
                **context,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def messages(request: Request, sim: str = "", q: str = "", box: str = "inbox", select: str = ""):
        lang = _language(request, language)
        now = datetime.now(timezone.utc)
        search, archived, selecting = q.strip(), box == "archived", select == "1"
        rows = []
        found = {
            "incomplete_received_before": now - timedelta(seconds=part_timeout),
            "sim_iccid": sim or None,
            "search": search or None,
        }
        for m in store.list_messages(**found, archived=archived):
            code = _CODE.search(m.text) if _MENTIONS_CODE.search(m.text) else None
            rows.append(
                {
                    "id": m.id,
                    "sim": m.sim_label,
                    "sender": m.sender,
                    "text": m.text,
                    "time": _taipei(m.sent_at),
                    "ago": i18n.relative_time(lang, m.sent_at.astimezone(TAIPEI), now),
                    "complete": m.complete,
                    "forwarding": i18n.text(lang, _FORWARD_LABELS[m.forward_state]),
                    "code": code.group() if code else None,
                }
            )
        inbox_count, archived_count = store.count_messages(**found)

        def link(**changes: str) -> str:
            """This list with something changed, keeping the rest of the filter."""
            query = {"sim": sim, "q": search, "box": "archived" if archived else "", "select": "1" if selecting else ""}
            query.update(changes)
            return "/?" + urlencode({key: value for key, value in query.items() if value})

        return page(
            request,
            "messages.html",
            lang,
            view="messages",
            messages=rows,
            sims=[(s.iccid, s.label) for s in store.list_sims()],
            sim=sim,
            search=search,
            archived=archived,
            selecting=selecting,
            filtered=bool(sim or search),
            inbox_count=inbox_count,
            archived_count=archived_count,
            link=link,
        )

    @app.get("/status", response_class=HTMLResponse)
    def status(request: Request):
        lang = _language(request, language)
        t = i18n.strings(lang)
        now = datetime.now(timezone.utc)
        attached = service.modems()
        in_modem = {m.iccid: m for m in attached if m.iccid}
        sims = []
        for stored in store.list_sims():
            modem = in_modem.get(stored.iccid)
            network = modem.network if modem else None
            registration = network.registration if network else None
            sims.append(
                {
                    "iccid": stored.iccid,
                    "label": stored.label,
                    "number": stored.number or t["number_unknown"],
                    "forwarding": stored.forwarding,
                    "good": registration in (HOME, ROAMING),
                    "operator": (network and network.operator) or "–",
                    "signal": f"{network.signal}/31" if network and network.signal is not None else "–",
                    "bars": -(-network.signal * 4 // 31) if network and network.signal else 0,
                    "registration": t[registration] if registration else t["not_in_modem"],
                    "last": _taipei(stored.last_message_at) if stored.last_message_at else t["never"],
                    "modem": modem.imei if modem else None,
                }
            )
        modems = [
            {
                "imei": m.imei or t["unidentified"],
                "state": t.get(f"state_{m.state}", m.state),
                "good": m.state == RECEIVING,
            }
            for m in attached
        ]
        return page(
            request,
            "status.html",
            lang,
            view="status",
            sims=sims,
            good_sims=sum(sim["good"] for sim in sims),
            modems=modems,
            alerts=[(text, _taipei(since)) for text, since in monitor.active_alerts(lang)],
            system=_system_status(lang, now),
        )

    def _system_status(lang: str, now: datetime) -> list[dict]:
        """One row per thing outside the SIMs that the owner may need to act on."""
        t = i18n.strings(lang)

        def row(name: str, state: str, note: str, level: str = "ok") -> dict:
            return {"name": t[name], "state": t[state], "note": note, "level": level}

        rows = [
            row(
                "sys_service",
                "sys_running",
                i18n.text(lang, "sys_uptime", duration=i18n.duration(lang, (now - started_at).total_seconds())),
            )
        ]
        if not forwarder.configured:
            rows.append(row("sys_telegram", "sys_telegram_off", t["sys_telegram_off_note"], "warn"))
        elif forwarder.failing_since is not None:
            note = i18n.text(lang, "sys_telegram_down_note", time=_taipei(forwarder.failing_since)[11:16])
            rows.append(row("sys_telegram", "sys_telegram_down", note, "warn"))
        elif forwarder.last_sent_at is not None:
            when = i18n.relative_time(lang, forwarder.last_sent_at, now)
            rows.append(row("sys_telegram", "sys_telegram_ok", i18n.text(lang, "sys_telegram_last", when=when)))
        else:
            rows.append(row("sys_telegram", "sys_telegram_ok", t["sys_telegram_none"]))

        enabled = monitor.network_service_state
        if enabled is None:
            rows.append(row("sys_data", "sys_data_unknown", t["sys_data_unknown_note"], "unknown"))
        elif enabled:
            rows.append(row("sys_data", "sys_data_on", t["sys_data_on_note"], "warn"))
        else:
            rows.append(row("sys_data", "sys_data_off", t["sys_data_off_note"]))

        drops = service.disconnects_since(now - _UNSTABLE_WINDOW)
        counts = {imei: drops.count(imei) for imei in sorted(set(drops))}
        if not counts:
            rows.append(row("sys_usb", "sys_usb_ok", t["sys_usb_ok_note"]))
        else:
            unstable = max(counts.values()) >= _UNSTABLE_DROPS
            note = "；".join(i18n.text(lang, "sys_usb_drops", imei=imei, count=count) for imei, count in counts.items())
            rows.append(row("sys_usb", "sys_usb_bad" if unstable else "sys_usb_some", note, "warn" if unstable else "ok"))

        if backups is not None:
            latest = backups.latest()
            when = latest.isoformat() if latest else t["sys_backup_none"]
            if backups.failing or latest is None:
                note = i18n.text(lang, "sys_backup_failing_note", date=when)
                rows.append(row("sys_backup", "sys_backup_failing", note, "warn"))
            else:
                note = i18n.text(lang, "sys_backup_ok_note", date=when, count=len(backups.existing()))
                rows.append(row("sys_backup", "sys_backup_ok", note))

        if isinstance(access, OpenAccess):
            rows.append(row("sys_access", "sys_access_off", t["sys_access_off_note"], "warn"))
        else:
            rows.append(row("sys_access", "sys_access_on", t["sys_access_on_note"]))
        return rows

    @app.post("/messages/delete")
    async def delete_messages(request: Request):
        chosen = parse_qs((await request.body()).decode()).get("id", [])
        store.delete_messages([int(value) for value in chosen if value.isdigit()])
        return _back(request, drop=("select",))

    @app.post("/messages/{message_id}/delete")
    def delete_message(message_id: int, request: Request):
        store.delete_messages([message_id])
        return _back(request)

    @app.post("/messages/{message_id}/archive")
    async def archive_message(message_id: int, request: Request):
        store.set_archived(message_id, (await _form(request)).get("archived") == "1")
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

    @app.post("/settings/language")
    async def set_language(request: Request):
        chosen = i18n.language((await _form(request)).get("lang"))
        response = _back(request)
        response.set_cookie(LANGUAGE_COOKIE, chosen, max_age=10 * 365 * 86400, samesite="lax", httponly=True)
        return response

    return app


def _language(request: Request, default: str) -> str:
    chosen = request.cookies.get(LANGUAGE_COOKIE)
    return chosen if chosen in i18n.LANGUAGES else default


def _taipei(moment: datetime) -> str:
    return moment.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


async def _form(request: Request) -> dict[str, str]:
    fields = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {name: values[-1] for name, values in fields.items()}


def _back(request: Request, drop: tuple[str, ...] = ()) -> RedirectResponse:
    """Return to the page the form was on, keeping its filter and search."""
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.path not in ("/", "/status") or referer.netloc != request.headers.get("host"):
        return RedirectResponse("/", status_code=303)
    path = referer.path
    query = [(key, value) for key, values in parse_qs(referer.query).items() if key not in drop for value in values]
    return RedirectResponse(path + (f"?{urlencode(query)}" if query else ""), status_code=303)


def _from_another_site(request: Request) -> bool:
    """A form posted by some other website, riding on the owner's signed-in browser."""
    origin = request.headers.get("origin")
    if request.method in ("GET", "HEAD") or not origin:
        return False
    return urlsplit(origin).netloc != request.headers.get("host")
