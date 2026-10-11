# 08: Alert the owner when a Modem or SIM stops working

**What to build:** Mailroom tells the owner in Telegram when it can no longer be trusted to receive, instead of failing silently. An Alert is sent when a SIM has been off the network for several minutes, when a Modem disappears, when a SIM's storage is nearly full, and when Telegram sends keep failing; a follow-up Alert is sent on recovery. Alerts look clearly different from forwarded Messages and ignore per-SIM Forwarding settings. This ticket also implements the mobile data safeguard: the global "mobile data" setting defaults to off, and while it is off Mailroom keeps each Modem's USB network sharing disabled and raises an Alert at startup if the macOS network service for the Modems is enabled. See "Mobile data" in `../spec.md` for what off does and does not mean.

**Blocked by:** 03, 05, 06

**Status:** ready-for-agent

- [ ] An Alert is sent when a SIM stays unregistered beyond a configurable number of minutes, and another when it registers again
- [ ] An Alert is sent when a Modem disappears, and another when it returns
- [ ] An Alert is sent when a SIM's storage is nearly full
- [ ] An Alert about repeated Telegram failures is delivered once Telegram is reachable again, and the failure is visible on the web page meanwhile
- [ ] A condition that persists produces one Alert, not a stream of them
- [ ] Alerts are visually distinct from Messages and are sent even for SIMs with Forwarding off
- [ ] With mobile data off, each Modem's USB network sharing is kept disabled
- [ ] An Alert is raised at startup if the macOS network service "A76XX Series LTE Module" is enabled
