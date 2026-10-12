# Talk to modems over libusb, not a serial port

macOS has no driver for the A7672G's AT interfaces: they are vendor-specific USB interfaces (class 255), so no `/dev/cu.*` device appears (verified on macOS 27, Apple Silicon, 2026-10-11). Mailroom therefore claims the AT interface itself through libusb and reads and writes its bulk endpoints directly, in Python, running natively on the Mac mini. A spike confirmed this works without root or a driver install and received a UCS2 SMS on a Taiwan Mobile SIM.

## Considered Options

- **Attach the modems to Linux** (a VM with USB passthrough, or a Raspberry Pi), where the `option` driver exposes ordinary serial ports. Rejected: it adds a second machine or a VM to keep alive for a single-user service.
- **Write a DriverKit serial driver for macOS.** Rejected: far more work than the service itself, and it needs signing entitlements.

## Consequences

- Modems are found by USB vendor/product ID (`1e0e:9011`) and told apart by IMEI, never by a device path. The USB serial number is useless for this: every unit reports the same factory default (`200806006809080000`).
- Mailroom holds the AT interface exclusively; no other tool can talk to a Modem while it runs.
- macOS still binds the modem's ECM interface as a network service, so mobile data has to be disabled separately.
- The Modem exposes two AT-capable interfaces, and both must be read at all times. Interface 4 is the AT port and interface 5 the MODEM (dial-up) port; with the default `AT+CATR=0` every unsolicited line goes to both. While one of them is left unread, SMS in the GSM 7-bit alphabet never arrive (no `+CMTI`, nothing stored, and they are not redelivered later), although UCS2 SMS still do. Reproduced on 2026-10-12 with a Taiwan Mobile SIM: seven 7-bit SMS lost with one interface unread, four received with both read. DTR state made no difference. Mailroom talks on interface 4, sets `AT+CATR=3` (indications to the AT port only) and keeps draining interface 5 regardless. The mechanism inside the Modem is not understood.
- Interfaces must be looked up by `bInterfaceNumber`, not by position: the Modem has no interface 3, so the fifth interface is number 5.
- Each endpoint is read by one blocking read with no timeout on its own thread. Reading in short timed slices made libusb on macOS abort the pipe on every timeout and produced intermittent I/O errors. Occasional I/O errors still occur, often about ten seconds after an SMS, and are retried; their cause is unknown.
- The manual that matches this Modem is the *A76XX Series AT Command Manual* (V1.09, ASR platform). The *SIM76XX* and *SIM767XX* manuals describe a different, Qualcomm QCX216 product line and disagree with it, for example on `AT+CATR` port numbers.
