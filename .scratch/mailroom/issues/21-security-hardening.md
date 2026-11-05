# 21: Security hardening after the 2026-11-05 review

**What to build:** Close the gaps found when checking the installation itself rather than the code.

A bot token holder can call `forwardMessage` on every message id in the owner's chat with the bot and collect the whole forwarded history, without the buttons stopping and so without an Alert. Deleting each copy a day after it was sent limits that to the last day. Telegram lets a bot delete what it sent for 48 hours only, so the keep time is under 48 hours and older copies have to be cleared by hand once.

The launchd label carried the owner's real domain into the public repository. The logs, which name the Modems and SIMs, were readable by every account on the Mac. A POST without an Origin header was let through the cross-site check.

FileVault stays off by the owner's decision (2026-11-05): the Mac must come back by itself after a power cut. The runbook records this and what it exposes.

**Blocked by:** 19

**Status:** done

- [x] A Message's Telegram copies are deleted 24 hours after sending (`[telegram] delete_after_hours`, under 48; 0 keeps them); the Message stays on the page
- [x] A copy of a Message deleted for good is deleted from Telegram at the next check, and no longer points at the Message id, which a newer Message may be given
- [x] A copy Telegram refuses to delete (already gone, or older than 48 hours) is given up; one that could not be deleted for now is tried again
- [x] Copies recorded before they had a sent time are dated by their Message's arrival, in a migration that cannot leave the table half rebuilt
- [x] The launchd label no longer names the owner's domain; the install script removes a service installed from the same repository under another label
- [x] Log files, rotated ones and launchd's own are readable only by the owner; everything Mailroom writes is created that way
- [x] A POST without Origin whose `Sec-Fetch-Site` says another site is rejected
- [x] The runbook (both languages) says the bot token is as sensitive as the Messages, how to replace it, that copies are deleted after a day and older ones need clearing by hand, and that FileVault is off on purpose

## Not done

- The old label is still in the git history of the public repository. Removing it means rewriting history and force-pushing; left to the owner.
