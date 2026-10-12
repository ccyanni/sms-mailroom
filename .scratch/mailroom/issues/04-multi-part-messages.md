# 04: Long SMS arrive as one Message

**What to build:** An SMS the network split into Parts reaches the owner as a single Message. Parts are matched by SIM, sender and concatenation reference and ordered by sequence number, never by arrival order. If a Part is still missing after one minute, the Message is shown with what has arrived and marked incomplete; when the missing Part turns up, the Message is completed. `../spec.md` contains a captured two-Part fixture whose Parts were stored in reverse order.

**Blocked by:** 01

**Status:** done

- [x] Parts of one SMS are assembled into one Message in sequence order
- [x] The captured reverse-order fixture from the spec decodes to its expected text
- [x] A Message missing a Part after one minute is visible and marked incomplete
- [x] A late Part completes the existing Message instead of creating a new one
- [x] A duplicate Part does not corrupt or duplicate the Message
- [x] Parts from different senders or different SIMs with the same concatenation reference are not mixed
- [x] The web page shows whether a Message is complete
