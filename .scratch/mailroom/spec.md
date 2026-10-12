# SMS Mailroom v1: receive SMS on several SIMs, read and forward them remotely

Status: ready-for-agent

Vocabulary follows `CONTEXT.md` (SMS Mailroom, Modem, SIM, Message, Part, Forwarding, Alert, USB hub). The transport decision is recorded in `docs/adr/0001-talk-to-modems-over-libusb.md`.

## Problem Statement

The owner has several SIMs (Taiwan Mobile, China Mobile, China Unicom) that mostly exist to receive SMS, typically short-lived verification codes. Today each SIM sits in a separate phone left at home, so a code that arrives while the owner is out cannot be read. The codes expire in minutes, so "read it when I get home" is the same as not receiving it.

## Solution

SMS Mailroom runs on the owner's always-on Mac mini. Each SIM sits in a SIMCom A7672G USB Modem plugged into a USB hub. SMS Mailroom receives every SMS, stores it, forwards it to the owner's private Telegram chat within seconds, and offers a web page, reachable from anywhere through Cloudflare Tunnel behind Cloudflare Access, to read past Messages and see whether each SIM is healthy. When a Modem or SIM stops working, SMS Mailroom says so instead of failing silently.

## User Stories

1. As the owner, I want an SMS arriving on any of my SIMs to appear in my Telegram chat within seconds, so that I can use a verification code before it expires.
2. As the owner, I want each forwarded Message to show which SIM received it, the sender, the time and the full text, so that I know which account the code is for.
3. As the owner, I want Chinese text (Traditional and Simplified) and mixed Chinese/English text to be displayed correctly, so that I can read what was sent.
4. As the owner, I want a long SMS that the network split into Parts to reach me as one Message, so that I do not have to piece it together.
5. As the owner, I want Parts that arrive out of order to be assembled in the right order, so that the text reads correctly.
6. As the owner, I want a Message whose Parts have not all arrived after one minute to be forwarded anyway, marked incomplete, so that a lost Part does not hide a code from me.
7. As the owner, I want an incomplete Message to be updated when its missing Part arrives later, so that I eventually see the whole text.
8. As the owner, I want to open a web page from my phone and see all Messages, newest first, so that I can read anything I missed in Telegram.
9. As the owner, I want to filter the Message list by SIM, so that I can find Messages for one number.
10. As the owner, I want to search Message text, so that I can find a specific Message.
11. As the owner, I want the web page to refresh itself every few seconds, so that a new Message shows up without my reloading.
12. As the owner, I want the web page to be readable on a phone screen, so that I can use it while away from a computer.
13. As the owner, I want to see for each SIM its label, phone number, operator, signal strength, registration state (including roaming) and the time of its last Message, so that I can tell whether it is working.
14. As the owner, I want a SIM SMS Mailroom has never seen to be registered automatically and start receiving at once, so that adding a SIM needs no setup.
15. As the owner, I want a new SIM to be labelled with its phone number, or the last four digits of its ICCID when the number is unreadable, so that I can recognise it before I rename it.
16. As the owner, I want to rename a SIM in the web page, so that Messages are tagged with a name I understand.
17. As the owner, I want Forwarding to be on by default for a new SIM, so that I never miss Messages because I forgot a setting.
18. As the owner, I want to switch Forwarding on or off per SIM, so that I can silence a noisy number.
19. As the owner, I want a SIM's Messages to stay with that SIM when I move it to a different Modem, so that swapping hardware does not split my history.
20. As the owner, I want to plug in or unplug a Modem while SMS Mailroom is running, so that I can change hardware without restarting anything.
21. As the owner, I want to delete a single Message from the web page, so that I can remove sensitive content.
22. As the owner, I want Messages kept indefinitely unless I delete them, so that old Messages remain searchable.
23. As the owner, I want a Message to be removed from the SIM only after SMS Mailroom has stored it, so that a crash never loses a Message.
24. As the owner, I want the SIM's own storage kept empty, so that a full SIM never blocks new Messages.
25. As the owner, I want Messages that arrived while SMS Mailroom was not running to be collected when it starts, so that downtime does not lose anything.
26. As the owner, I want a Message that could not be sent to Telegram to be retried until it succeeds, so that a network outage only delays Forwarding.
27. As the owner, I want the web page to show whether each Message has been forwarded, so that I can see what Telegram has not yet received.
28. As the owner, I want an Alert in Telegram when a SIM has been off the network for several minutes, so that I learn about an outage before I need a code.
29. As the owner, I want an Alert when a Modem disappears, so that I notice a loose cable or a crashed module.
30. As the owner, I want an Alert when a Modem or SIM recovers, so that I know the problem is over.
31. As the owner, I want an Alert when a SIM's storage is nearly full or Telegram keeps failing, so that I can act before Messages are lost.
32. As the owner, I want Alerts to be visibly different from forwarded Messages, so that I do not mistake one for the other.
33. As the owner, I want SMS Mailroom never to cause mobile data traffic, so that roaming SIMs do not incur data charges.
34. As the owner, I want an Alert if the Mac's network service for the Modems has been re-enabled, so that I know the data safeguard has been undone.
35. As the owner, I want the web page to be reachable only after I sign in through Cloudflare Access, so that nobody else can read my verification codes.
36. As the owner, I want SMS Mailroom to reject requests that did not come through Cloudflare Access, so that a tunnel misconfiguration does not expose my Messages.
37. As the owner, I want SMS Mailroom to start when the Mac mini boots and restart if it crashes, so that I never have to start it by hand.
38. As the owner, I want my Telegram bot token and chat ID kept outside the repository, so that they are never committed.
39. As the owner, I want all times shown in Taipei time, so that I do not have to convert.

## Implementation Decisions

**Platform and stack**

- Python, managed with `uv`, running natively on the Mac mini (macOS 27, Apple Silicon). The importable package is named `mailroom`; the repository directory stays `4g-hub`.
- One long-running process contains the Modem handling, the store, the Forwarding and Alert logic, and the web server.
- Web UI: FastAPI with server-rendered HTML and no front-end build step. The page polls for updates every few seconds.
- Storage: one SQLite database file on the Mac mini. No backup in v1; the Telegram chat is the second copy.
- Runs as a launchd service: starts at boot, restarts on crash. The Mac mini is configured not to sleep.

**Modules**

- **Modem transport**: finds Modems by USB vendor/product ID `1e0e:9011`, claims both AT-capable interfaces (4, the AT port, and 5, the MODEM port; vendor class 255) through libusb, exchanges AT commands and unsolicited result codes on interface 4, and continuously drains interface 5. ADR 0001 explains why both must be read. This is the only module that touches USB.
- **PDU codec**: decodes SMS-DELIVER PDUs into sender, network timestamp with timezone, text, and concatenation header (reference, total, sequence). Must handle GSM 7-bit and UCS2, and alphanumeric sender addresses. Pure functions, no I/O.
- **Receiver**: per Modem, identifies the Modem (IMEI) and SIM (ICCID, number), reads PDUs in PDU mode, hands them to the store, then deletes them from the SIM. Reacts to new-message indications and also polls SIM storage periodically as a safety net. Drains SIM storage on startup and when a Modem appears.
- **Store**: SIMs, Messages and Parts in SQLite. Assembles Parts into Messages by SIM, sender and concatenation reference, ordered by sequence number, never by arrival order. Tracks completeness and Forwarding state per Message.
- **Forwarder**: sends Messages to Telegram for SIMs with Forwarding on, retries until success, and edits or follows up when an incomplete Message is completed. The bot only sends; it accepts no commands.
- **Health monitor**: tracks Modem presence and SIM registration and raises and clears Alerts.
- **Web**: Message list (filter by SIM, text search), SIM status, rename SIM, toggle Forwarding, delete Message. Binds to `127.0.0.1` only and validates the Cloudflare Access JWT on every request. No accounts or passwords of its own.

**Identity**

- A Modem is identified by IMEI. The USB serial number and the ECM MAC address are identical on every unit (`200806006809080000`, `ae:0c:29:a3:9b:6d`) and must not be used.
- A SIM is identified by ICCID. A Modem holds at most one SIM (the carrier board has one slot, although the firmware is a dual-SIM build reporting two IMEIs; use IMEI1).
- A Message belongs to a SIM, not to a Modem.

**Behaviour**

- SIM onboarding is automatic: unknown ICCID creates a SIM, labelled with its number or the last four ICCID digits, Forwarding on.
- A Message is forwarded when all its Parts are present, or after one minute with what has arrived, marked incomplete.
- A Message is deleted from the SIM only after it is durably stored. Receiving the same PDU twice must not create a duplicate.
- Deleting a Message in the web UI is permanent.
- SIMs have no PIN; SMS Mailroom does not handle PIN entry.
- Alerts fire when a SIM has been unregistered for several minutes, when a Modem disappears, when SIM storage is nearly full, when Telegram fails repeatedly, and on recovery.

**Mobile data**

- A single global "mobile data" setting exists and defaults to off. v1 implements only the off state.
- Off means: SMS Mailroom keeps each Modem's USB network sharing disabled (`AT+DIALMODE=1`, which is the factory default) and checks at startup that the macOS network service "A76XX Series LTE Module" is disabled, raising an Alert if it is not.
- SMS Mailroom does not try to tear down the Modem's data bearer. `AT+CGACT=0,1` succeeds but the firmware re-establishes the bearer within about 20 seconds, on both a home and a roaming SIM. The goal is no data traffic, not no bearer.

**Configuration**

- Telegram bot token, chat ID, and Cloudflare Access team domain and audience tag live in a config file outside the repository.

## Testing Decisions

- A good test drives SMS Mailroom through its outer edges and asserts on what the owner would observe (a stored Message, a Telegram send, an Alert, a rendered page), not on internal calls.
- The primary seam is the Modem transport: tests replace it with a scripted fake Modem that answers AT commands and emits indications. Everything above it (Receiver, Store, Forwarder, Health monitor, Web) runs for real against a temporary SQLite database. The second seam is the outbound Telegram HTTP call, replaced by a recording fake. No other seams.
- The PDU codec is additionally tested directly with captured PDUs, since it is pure and the inputs are byte-exact.
- Scenarios that must be covered: single-Part UCS2 Message; two-Part Message arriving in reverse order; a Part that never arrives (one-minute timeout, incomplete flag, later completion); duplicate PDU; SIM moved between Modems; Modem unplugged and replugged; Telegram failing then recovering; Messages already on the SIM at startup; request without a valid Access JWT.
- There is no prior art in the repository; this is the first code.
- Real-hardware behaviour is checked by hand against the attached Modems, not in the automated suite.

## Out of Scope

- Sending SMS, voice calls, USSD, and using a Modem for internet access.
- The "on" state of the mobile data setting.
- Multiple users, roles, statistics, charts, export.
- Keyword or per-sender Forwarding rules.
- Database backup and a recycle bin for deleted Messages.
- Telegram bot commands.
- Setting up the Cloudflare Tunnel, the Access application and the Telegram bot themselves; these are owner-performed steps (covered by ticket 10).

## Further Notes

**Verified on real hardware (2026-10-11/12)**

- Model `A7672G-LABE`, firmware `A124B01A7672M7_DS`. macOS creates no serial device; libusb access works without root or a driver.
- Taiwan Mobile SIM: registered on 466-97, received a single-Part UCS2 SMS.
- China Mobile SIM roaming in Taiwan: registered on 466-01 (`+CEREG: 0,5`), received a two-Part UCS2 SMS whose Parts were stored in reverse order.
- Three Modems ran concurrently on one USB hub and were addressed independently.
- Defaults observed: `+CMGF: 0` (PDU mode), `+CNMI: 2,1,0,0,0` (new Messages stored and indicated with `+CMTI`), `+CSCS: "IRA"`, preferred storage `"SM"` (capacity 40 or 50 depending on the SIM; the module's own `"ME"` storage holds 180).
- Commands used in the spike: `AT+CGSN` (IMEI), `AT+CICCID`, `AT+CNUM`, `AT+CPIN?`, `AT+CSQ`, `AT+CPSI?`, `AT+CEREG?`, `AT+COPS?`, `AT+CPMS?`, `AT+CMGL=4` (list all, PDU mode).
- A Modem with an unreadable SIM answers `+CME ERROR: SIM not inserted` to `AT+CICCID` and `+CMS ERROR` to SMS commands; the Receiver must treat this as a state, not a crash.

**Captured fixture: one Message in two Parts, stored out of order (China Mobile, sender `10086910`, expired code)**

Storage index 1 (sequence 2 of 2):

```
0891683108701305F06408A00180960100086201113285442314050003C40202300230104E2D56FD79FB52A83011
```

Storage index 2 (sequence 1 of 2):

```
0891683108701305F06408A0018096010008620111328544238C050003C4020100289A8C8BC15BC678010029003500300034003100320036FF0C5C0A656C768475286237FF0C60A8768453F778016B6357284E004E2A65B08BBE59074E0A767B5F554E2D56FD79FB52A80020004100500050FF0C8BE59A8C8BC1780100355206949F51856709654830028BF752FF6CC4973262168F6C53D14ED64EBAFF0C8C28963288AB9A97
```

Expected text: `(验证密码)504126，尊敬的用户，您的号码正在一个新设备上登录中国移动 APP，该验证码5分钟内有效。请勿泄露或转发他人，谨防被骗。【中国移动】`, network timestamp 2026-10-11 23:58:44 +08:00.

**Open items**

- The China Unicom SIM could not be read by a Modem or a phone; cause unknown (damaged card or suspended number). Not a blocker.
- The USB hub is currently bus-powered. Connect its external power supply before relying on three Modems; under-powered Modems reset at random and the fault is hard to see from software.
- Vendor manuals are in `docs/reference/` (git-ignored). The *A76XX Series AT Command Manual* (V1.09 and the newer V1.12) and the A76XX Sleep Mode and Linux USB application notes match this Modem; SIM76XX and SIM767XX manuals describe a different chipset and were removed. Treat every manual as a lead and confirm on the hardware.
