# 06: Manage and monitor SIMs from the web page

**What to build:** The owner sees every SIM SMS Mailroom knows and can manage it. A SIM seen for the first time is registered automatically, labelled with its phone number (or the last four digits of its ICCID when the number is unreadable), with Forwarding on. The owner can rename a SIM and switch its Forwarding on or off. Each SIM shows its number, operator, signal strength, registration state including roaming, and the time of its last Message. A SIM keeps its label, settings and Messages when it moves to a different Modem.

**Blocked by:** 01

**Status:** done

- [x] An unknown ICCID creates a SIM automatically and it receives immediately
- [x] The default label is the phone number, or the last four ICCID digits when no number is available
- [x] Forwarding is on by default for a new SIM
- [x] The owner can rename a SIM and the new label appears on its Messages
- [x] The owner can toggle Forwarding per SIM (the toggle takes effect once ticket 05 is in place)
- [x] The page shows operator, signal strength, registration state (home, roaming, not registered) and last Message time per SIM
- [x] Moving a SIM to another Modem keeps its label, Forwarding setting and Message history
