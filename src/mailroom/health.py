"""Alerts: tell the owner when Mailroom can no longer be trusted to receive, and when it can again."""

from __future__ import annotations

import logging
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from mailroom.forwarder import Forwarder
from mailroom.receiver import NOT_REGISTERED, RECEIVING
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
    ) -> None:
        """A problem is reported once it has lasted `alert_after` seconds, so brief blips stay quiet."""
        self._store = store
        self._service = service
        self._forwarder = forwarder
        self._send = send
        self._alert_after = timedelta(seconds=alert_after)
        self._interval = interval
        self._network_service_enabled = network_service_enabled
        self._network_service_checked: datetime | None = None
        self._outage_since: datetime | None = None
        self._outage_notices: list[str] = []

    def run(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            try:
                self.check()
            except Exception:
                log.exception("health check failed")

    def active_alerts(self) -> list[str]:
        """What is wrong right now, for the web page."""
        alerts = [alert.text for alert in self._store.list_alerts() if alert.raised]
        since = self._forwarder.failing_since
        if since is not None:
            alerts.append(f"Telegram has not been reachable since {_clock(since)}; Messages are waiting to be forwarded.")
        return alerts

    def check(self) -> None:
        now = datetime.now(timezone.utc)
        known = {alert.key: alert for alert in self._store.list_alerts()}
        problems: dict[str, tuple[str, timedelta]] = {}

        attached = self._service.modems()
        by_iccid = {modem.iccid: modem for modem in attached if modem.iccid}
        for sim in self._store.list_sims():
            modem = by_iccid.get(sim.iccid)
            if modem is None:
                reason = "its Modem is no longer attached"
            elif modem.state == RECEIVING and modem.network.registration == NOT_REGISTERED:
                reason = "it is not registered on a mobile network"
            else:
                reason = None
            if reason:
                problems[f"sim:{sim.iccid}"] = (f"SIM {sim.label} is not receiving: {reason}.", self._alert_after)
            network = modem.network if modem else None
            if network and network.storage_total and network.storage_used is not None:
                if network.storage_used >= _STORAGE_NEARLY_FULL * network.storage_total:
                    problems[f"storage:{sim.iccid}"] = (
                        f"SIM {sim.label} has {network.storage_used} of {network.storage_total} storage slots "
                        "in use. When it is full, new Messages are lost.",
                        self._alert_after,
                    )

        for modem in attached:
            if modem.imei and not modem.iccid and modem.state.startswith("cannot receive"):
                problems[f"modem:{modem.imei}"] = (f"Modem {modem.imei}: {modem.state}.", self._alert_after)

        drops = self._service.disconnects_since(now - _UNSTABLE_WINDOW)
        for imei in set(drops):
            key = f"unstable:{imei}"
            if drops.count(imei) >= _UNSTABLE_DISCONNECTS or key in known:
                problems[key] = (
                    f"Modem {imei} keeps disconnecting ({drops.count(imei)} times in the last 30 minutes). "
                    "Check the USB hub, its power supply and the cable.",
                    _NOW,
                )

        if self._network_service_enabled is not None:
            key = "data:network-service"
            due = self._network_service_checked is None or now - self._network_service_checked >= _NETWORK_SERVICE_CHECK_EVERY
            if due:
                self._network_service_checked = now
                enabled = self._network_service_enabled()
            else:
                enabled = key in known
            if enabled:
                problems[key] = (
                    f'The macOS network service "{NETWORK_SERVICE}" is enabled, so the Mac could send traffic '
                    "over a SIM. Disable it in System Settings → Network.",
                    _NOW,
                )

        for key, (text, grace) in problems.items():
            self._raise(known.get(key) or StoredAlert(key, text, now, raised=False, delivered=False), now, grace)
        for key, alert in known.items():
            if key not in problems:
                self._resolve(alert)
        self._watch_telegram(now)

    def _raise(self, alert: StoredAlert, now: datetime, grace: timedelta) -> None:
        raised = alert.raised or now - alert.since >= grace
        if raised and not alert.raised:
            log.warning("alert: %s", alert.text)
        delivered = alert.delivered or (raised and self._deliver(f"⚠️ Mailroom alert\n{alert.text}"))
        self._store.save_alert(StoredAlert(alert.key, alert.text, alert.since, raised, delivered))

    def _resolve(self, alert: StoredAlert) -> None:
        if alert.raised:
            log.info("resolved: %s", alert.text)
        if alert.delivered and not self._deliver(f"✅ Mailroom: resolved\n{alert.text}"):
            return  # tell the owner it is over before forgetting it
        self._store.delete_alert(alert.key)

    def _watch_telegram(self, now: datetime) -> None:
        """Telegram cannot carry news of its own outage, so say it once it is back."""
        since = self._forwarder.failing_since
        if since is not None:
            self._outage_since = since
        elif self._outage_since is not None:
            if now - self._outage_since >= self._alert_after:
                self._outage_notices.append(
                    f"⚠️ Mailroom alert\nTelegram could not be reached from {_clock(self._outage_since)} "
                    f"to {_clock(now)}. Messages received meanwhile were forwarded late."
                )
            self._outage_since = None
        self._outage_notices = [notice for notice in self._outage_notices if not self._deliver(notice)]

    def _deliver(self, text: str) -> bool:
        if self._send is None:
            return False
        try:
            self._send(text)
        except Exception:
            return False
        return True


def _clock(moment: datetime) -> str:
    return moment.astimezone(TAIPEI).strftime("%H:%M")
