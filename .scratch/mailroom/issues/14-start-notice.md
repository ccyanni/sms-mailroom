# 14: Tell the owner when SMS Mailroom starts

**What to build:** Whenever the SMS Mailroom service starts, the owner gets one Telegram notice saying so, whether that was after the Mac booted or after the service alone restarted, and how many Modems are attached and SIMs receiving. This makes a crash-and-restart visible, and confirms after a power cut that SMS Mailroom came back by itself. The notice waits a few seconds so the Modems can be counted, and is retried until Telegram accepts it, since the network may not be up yet right after boot.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] One notice is sent each time the service starts
- [x] It says whether the Mac had just booted or only the service restarted
- [x] It says how many Modems are attached and how many of the known SIMs are receiving
- [x] It is in the configured language and looks different from a forwarded Message and from an Alert
- [x] It is delivered once Telegram becomes reachable, if it was not at start
