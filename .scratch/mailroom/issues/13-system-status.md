# 13: Show the state of the system, not only of the SIMs

**What to build:** The Status section ends with a card about the installation itself, so the owner can tell at a glance whether anything outside the SIMs needs attention: whether the Mailroom service is running and for how long, whether Telegram Forwarding works and when it last delivered, whether the macOS network service for the Modems is disabled, whether the USB connection to the Modems has been stable, and whether the page is protected by Cloudflare Access. It also lists the attached Modems and their state.

**Blocked by:** 12

**Status:** done

- [x] The card shows how long the service has been running
- [x] It shows whether Telegram is set up, reachable, and when a Message was last forwarded
- [x] It shows whether the macOS network service for the Modems is disabled, enabled or could not be determined
- [x] It shows how often each Modem dropped off in the last 30 minutes and marks the connection unstable from three drops
- [x] It shows whether Cloudflare Access protects the page
- [x] Anything that needs attention is marked differently from what is fine
