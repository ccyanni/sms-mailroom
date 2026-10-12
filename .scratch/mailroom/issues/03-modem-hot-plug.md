# 03: Plug and unplug Modems while SMS Mailroom is running

**What to build:** The owner can add, remove or re-seat a Modem without restarting SMS Mailroom. A newly attached Modem is detected, identified and starts receiving, including collecting Messages already on its SIM. A removed Modem is noticed and released cleanly, and the other Modems keep working throughout.

**Blocked by:** 02

**Status:** ready-for-agent

- [x] A Modem plugged in after startup begins receiving without a restart
- [x] Messages waiting on a newly attached Modem's SIM are collected
- [x] Unplugging a Modem does not crash SMS Mailroom or interrupt other Modems
- [x] A Modem that is unplugged and plugged back in resumes receiving
- [x] SMS Mailroom exposes which Modems are currently present, so later tickets can show and alert on it
- [ ] Covered by automated tests using the fake Modem, and verified by hand with a real Modem (automated tests done; hand verification pending)
