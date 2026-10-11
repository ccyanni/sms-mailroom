# Talk to modems over libusb, not a serial port

macOS has no driver for the A7672G's AT interfaces: they are vendor-specific USB interfaces (class 255), so no `/dev/cu.*` device appears (verified on macOS 27, Apple Silicon, 2026-10-11). Mailroom therefore claims the AT interface itself through libusb and reads and writes its bulk endpoints directly, in Python, running natively on the Mac mini. A spike confirmed this works without root or a driver install and received a UCS2 SMS on a Taiwan Mobile SIM.

## Considered Options

- **Attach the modems to Linux** (a VM with USB passthrough, or a Raspberry Pi), where the `option` driver exposes ordinary serial ports. Rejected: it adds a second machine or a VM to keep alive for a single-user service.
- **Write a DriverKit serial driver for macOS.** Rejected: far more work than the service itself, and it needs signing entitlements.

## Consequences

- Modems are found by USB vendor/product ID (`1e0e:9011`) and told apart by IMEI, never by a device path. The USB serial number is useless for this: every unit reports the same factory default (`200806006809080000`).
- Mailroom holds the AT interface exclusively; no other tool can talk to a Modem while it runs.
- macOS still binds the modem's ECM interface as a network service, so mobile data has to be disabled separately.
