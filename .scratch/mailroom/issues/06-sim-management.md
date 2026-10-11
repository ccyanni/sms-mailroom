# 06: Manage and monitor SIMs from the web page

**What to build:** The owner sees every SIM Mailroom knows and can manage it. A SIM seen for the first time is registered automatically, labelled with its phone number (or the last four digits of its ICCID when the number is unreadable), with Forwarding on. The owner can rename a SIM and switch its Forwarding on or off. Each SIM shows its number, operator, signal strength, registration state including roaming, and the time of its last Message. A SIM keeps its label, settings and Messages when it moves to a different Modem.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] An unknown ICCID creates a SIM automatically and it receives immediately
- [ ] The default label is the phone number, or the last four ICCID digits when no number is available
- [ ] Forwarding is on by default for a new SIM
- [ ] The owner can rename a SIM and the new label appears on its Messages
- [ ] The owner can toggle Forwarding per SIM (the toggle takes effect once ticket 05 is in place)
- [ ] The page shows operator, signal strength, registration state (home, roaming, not registered) and last Message time per SIM
- [ ] Moving a SIM to another Modem keeps its label, Forwarding setting and Message history
