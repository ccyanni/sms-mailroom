"""Alerts: tell the owner when Mailroom can no longer be trusted to receive, and when it can again."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from mailroom import i18n
from mailroom.forwarder import Forwarder
from mailroom.receiver import HOME, NOT_REGISTERED, RECEIVING, ROAMING
from mailroom.service import Service
from mailroom.store import Store, StoredAlert

log = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
NETWORK_SERVICE = "A76XX Series LTE Module"
_STORAGE_NEARLY_FULL = 0.8
_UNSTABLE_WINDOW = timedelta(minutes=30)
_UNSTABLE_DISCONNECTS = 3
_NETWORK_SERVICE_CHECK_EVERY = timedelta(minutes=10)
_NOW = timedelta(0)


def network_service_enabled() -> bool | None:
    """Whether macOS would route traffic through the Modems; None if it has no such network service."""
    try:
        result = subprocess.run(
            ["networksetup", "-getnetworkserviceenabled", NETWORK_SERVICE],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() == "Enabled"


def booted_recently(within: float = 600.0) -> bool:
    """Whether the Mac started up in the last `within` seconds, as opposed to only the service restarting."""
    try:
        result = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=10)
        booted = int(re.search(r"sec = (\d+)", result.stdout).group(1))
    except (OSError, subprocess.TimeoutExpired, AttributeError):
        return False
    return datetime.now(timezone.utc).timestamp() - booted < within


class HealthMonitor:
    def __init__(
        self,
        store: Store,
        service: Service,
        forwarder: Forwarder,
        send: Callable[[str], None] | None,
        alert_after: float = 180.0,
        interval: float = 5.0,
        network_service_enabled: Callable[[], bool | None] | None = None,
        language: str = i18n.DEFAULT_LANGUAGE,
        start_notice: str | None = None,
        start_notice_after: float = 15.0,
    ) -> None:
        """A problem is reported once it has lasted `alert_after` seconds, so brief blips stay quiet.

        `start_notice` is "boot" or "restart" to tell the owner that Mailroom has started, once the
        Modems have had `start_notice_after` seconds to be found; None sends nothing.
        """
        self._store = store
        self._service = service
        self._forwarder = forwarder
        self._send = send
        self._alert_after = timedelta(seconds=alert_after)
        self._interval = interval
        self._network_service_enabled = network_service_enabled
        self._network_service_checked: datetime | None = None
        self._language = language
        self.network_service_state: bool | None = None  # as last probed; None when unknown
        self._outage_since: datetime | None = None
        self._start_notice = start_notice
        self._start_notice_at = datetime.now(timezone.utc) + timedelta(seconds=start_notice_after)
        self._outage_notices: list[dict] = []

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            try:
                self.check()
            except Exception:
                log.exception("health check failed")

    def active_alerts(self, language: str) -> list[tuple[str, datetime]]:
        """What is wrong right now and since when, in words, for the web page."""
        alerts = [
            (i18n.alert_text(language, alert.kind, alert.values), alert.since)
            for alert in self._store.list_alerts()
            if alert.raised
        ]
        since = self._forwarder.failing_since
        if since is not None:
            alerts.append((i18n.alert_text(language, "telegram_down", {"time": _clock(since)}), since))
        return alerts

    def check(self) -> None:
        now = datetime.now(timezone.utc)
        known = {alert.key: alert for alert in self._store.list_alerts()}
        problems: dict[str, tuple[str, dict, timedelta]] = {}

        attached = self._service.modems()
        by_iccid = {modem.iccid: modem for modem in attached if modem.iccid}
        for sim in self._store.list_sims():
            modem = by_iccid.get(sim.iccid)
            if modem is None:
                problems[f"sim:{sim.iccid}"] = ("sim_absent", {"label": sim.label}, self._alert_after)
            elif modem.state == RECEIVING and modem.network.registration == NOT_REGISTERED:
                problems[f"sim:{sim.iccid}"] = ("sim_unregistered", {"label": sim.label}, self._alert_after)
            network = modem.network if modem else None
            if network and network.storage_total and network.storage_used is not None:
                if network.storage_used >= _STORAGE_NEARLY_FULL * network.storage_total:
                    problems[f"storage:{sim.iccid}"] = (
                        "storage",
                        {"label": sim.label, "used": network.storage_used, "total": network.storage_total},
                        self._alert_after,
                    )

        for modem in attached:
            if modem.imei and not modem.iccid and modem.state.startswith("cannot receive"):
                problems[f"modem:{modem.imei}"] = (
                    "modem", {"imei": modem.imei, "state": modem.state}, self._alert_after
                )

        drops = self._service.disconnects_since(now - _UNSTABLE_WINDOW)
        for imei in set(drops):
            key = f"unstable:{imei}"
            if drops.count(imei) >= _UNSTABLE_DISCONNECTS or key in known:
                problems[key] = ("unstable", {"imei": imei, "count": drops.count(imei)}, _NOW)

        if self._network_service_enabled is not None:
            due = self._network_service_checked is None or now - self._network_service_checked >= _NETWORK_SERVICE_CHECK_EVERY
            if due:
                self._network_service_checked = now
                self.network_service_state = self._network_service_enabled()
            if self.network_service_state:
                problems["data:network-service"] = ("network_service", {}, _NOW)

        for key, (kind, values, grace) in problems.items():
            self._raise(known.get(key) or StoredAlert(key, kind, values, now, raised=False, delivered=False), now, grace)
        for key, alert in known.items():
            if key not in problems:
                self._resolve(alert)
        self._watch_telegram(now)
        self._announce_start(now, attached)

    def _announce_start(self, now: datetime, attached: list) -> None:
        if self._start_notice is None or now < self._start_notice_at:
            return
        receiving = sum(modem.network.registration in (HOME, ROAMING) for modem in attached if modem.iccid)
        summary = i18n.text(
            self._language,
            "started_summary",
            modems=len(attached),
            sims=len(self._store.list_sims()),
            good=receiving,
        )
        if self._send_text(i18n.text(self._language, f"started_{self._start_notice}") + "\n" + summary):
            self._start_notice = None

    def _raise(self, alert: StoredAlert, now: datetime, grace: timedelta) -> None:
        raised = alert.raised or now - alert.since >= grace
        if raised and not alert.raised:
            log.warning("alert: %s", i18n.alert_text("en", alert.kind, alert.values))
        delivered = alert.delivered or (raised and self._deliver("alert_header", alert.kind, alert.values))
        self._store.save_alert(StoredAlert(alert.key, alert.kind, alert.values, alert.since, raised, delivered))

    def _resolve(self, alert: StoredAlert) -> None:
        if alert.raised:
            log.info("resolved: %s", i18n.alert_text("en", alert.kind, alert.values))
        if alert.delivered and not self._deliver("resolved_header", alert.kind, alert.values):
            return  # tell the owner it is over before forgetting it
        self._store.delete_alert(alert.key)

    def _watch_telegram(self, now: datetime) -> None:
        """Telegram cannot carry news of its own outage, so say it once it is back."""
        since = self._forwarder.failing_since
        if since is not None:
            self._outage_since = since
        elif self._outage_since is not None:
            if now - self._outage_since >= self._alert_after:
                self._outage_notices.append({"start": _clock(self._outage_since), "end": _clock(now)})
            self._outage_since = None
        self._outage_notices = [
            notice
            for notice in self._outage_notices
            if not self._deliver("alert_header", "telegram_outage", notice)
        ]

    def _deliver(self, header: str, kind: str, values: dict) -> bool:
        return self._send_text(
            i18n.text(self._language, header) + "\n" + i18n.alert_text(self._language, kind, values)
        )

    def _send_text(self, text: str) -> bool:
        if self._send is None:
            return False
        try:
            self._send(text)
        except Exception:
            return False
        return True


def _clock(moment: datetime) -> str:
    return moment.astimezone(TAIPEI).strftime("%H:%M")
