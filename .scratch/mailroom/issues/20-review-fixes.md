# 20: Fixes from the 2026-11-04 Codex review

**What to build:** A full-repository review (Codex, gpt-6.1-sol) found defects that can lose or corrupt a Message, stop Forwarding for good, or forward a Message the owner no longer wants forwarded. Each was confirmed against the code. Fix the ones that are cheap and can really happen; the rest are listed below as not done, with the reason.

**Blocked by:** none

**Status:** done

- [x] A PDU whose user data is shorter than its length says (a lost piece of a USB read) is not decoded: it stays on the SIM and nothing is stored. A concatenation header with an impossible sequence or total is ignored, as 3GPP TS 23.040 says, so the Part is kept as a Message of its own
- [x] A Store failure while forwarding (a full disk) does not stop Forwarding for good: it is logged and retried, like a Telegram failure
- [x] After an AT command times out, a late answer to it is not taken as the answer to the next command
- [x] A Message moved to the Trash, or whose SIM's Forwarding was switched off, while it waited behind others in the forwarding queue is not forwarded
- [x] Recording a forwarded Message (its Telegram copy and its forward state) is one write, and only lands on the Message that was sent: a restart between the two cannot cause a second copy, and a Message deleted for good while it was being sent cannot pass its copy to a newer Message that was given the same id
- [x] The README (both languages) no longer promises a Message is never sent twice: when Telegram's answer is lost on the way back, Mailroom cannot tell it was delivered and sends it again

## Not done

- Retrying the Telegram edit that takes a deleted Message's text off its copy, when that edit fails (finding 9). Needs a queue of pending edits; left for a separate issue if wanted.
- Narrowing the one-day window in which Parts with the same sender, reference and total are joined (finding 6). Needs a decision on how far apart the Parts of one Message can be sent.
- The version-1 migration is not atomic (finding 1). No database at version 1 is left; future migrations should run in one transaction.
- An alphanumeric sender ending in `@` loses it (finding 10). Too rare to be worth it.
