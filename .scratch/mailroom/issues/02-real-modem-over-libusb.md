# 02: Receive Messages from real A7672G Modems over libusb

**What to build:** Mailroom receives SMS from the physical Modems attached at startup. It finds every Modem by USB vendor/product ID, talks to its AT interface through libusb as described in ADR 0001, identifies the Modem by IMEI and the SIM by ICCID, and delivers each stored SMS into the same path the walking skeleton built. A Message is removed from the SIM only after it is stored, so the SIM's storage stays empty and nothing is lost on a crash. The verified commands, defaults and hardware quirks are listed under "Further Notes" in `../spec.md`.

**Blocked by:** 01

**Status:** done

- [x] Every Modem attached at startup is found and addressed independently; two or more Modems work at the same time
- [x] Modems are told apart by IMEI, never by USB serial number, MAC address or device path
- [x] A new SMS is picked up within seconds of the Modem's new-message indication
- [x] SIM storage is also polled periodically, so a missed indication only delays a Message
- [x] Messages already on the SIM when Mailroom starts are collected
- [x] A Message is deleted from the SIM only after it is durably stored, and receiving the same PDU twice does not create a duplicate
- [x] A Modem whose SIM is missing or unreadable is reported as a state and does not crash Mailroom or disturb other Modems
- [x] Verified by hand against the attached Taiwan Mobile and China Mobile SIMs; the automated suite still runs without hardware
