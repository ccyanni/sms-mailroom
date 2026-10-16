# 17: Show an MMS notice or a data SMS as a notice, not as garbage

**What to build:** A China Mobile SIM received the notice of a multimedia message: an 8-bit SMS addressed to the WAP Push port, whose payload is binary. It was stored, shown and forwarded as that payload read as letters, which is garbage. Such a delivery, and any other 8-bit SMS addressed to an application port, becomes a Message whose text is a notice of what arrived (an MMS, or a data message for an app), in the owner's language on the page and on Telegram. The content of an MMS is fetched over mobile data, which SMS Mailroom never uses, so it is not downloaded.

**Blocked by:** 01, 04

**Status:** done

- [x] An MMS notice is shown on the page and forwarded to Telegram as a notice saying an MMS arrived and why its content is not available
- [x] Any other 8-bit SMS addressed to an application port is shown and forwarded as a notice of a data message
- [x] An MMS notice in several Parts is one Message, whichever Part arrives first
- [x] The payload is not searchable as text; the sender still is
- [x] An MMS notice stored by an earlier version is recognised when the database is upgraded
- [x] The runbook (both languages) says what happens to an MMS
