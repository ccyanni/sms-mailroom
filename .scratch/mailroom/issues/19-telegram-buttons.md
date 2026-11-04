# 19: Archive or delete a Message from its Telegram copy

**What to build:** Every Message forwarded to Telegram carries buttons, so the owner can archive or delete it right there instead of opening the page. Deleting moves it to the Trash (issue 18), and the Telegram copy then loses the Message's text and offers to restore it; restoring puts the text and the buttons back. Mailroom fetches button presses from Telegram itself (long polling), so nothing new can reach the Mac from the internet and Cloudflare Access stays in front of the page.

A press is trusted only from the owner's own private chat with the bot. It finds its Message through the Telegram copy it was pressed on, never through an id carried in the button, because SQLite reuses the id of a Message deleted for good. Anything else the bot receives is ignored without an answer.

**Blocked by:** 05, 18

**Status:** done

- [x] A forwarded Message, and the full text sent after an incomplete one, carry Archive and Delete buttons; Alerts and the start notice carry none
- [x] Delete moves the Message to the Trash; every Telegram copy of it loses the text and shows a Restore button
- [x] Restore takes it out of the Trash; its copies show the text and the buttons again
- [x] Archive moves it to the Archive and the button becomes Move to inbox
- [x] A press acts on the Message as it is now, also when it was changed on the page since
- [x] A press on the copy of a Message deleted for good changes nothing stored, and the copy says it is gone; a newer Message that was given the same id is not touched
- [x] Presses from anyone but the owner, or in any other chat, change nothing and get no answer
- [x] Each press is answered, so the owner sees what happened
- [x] If presses cannot be fetched for longer than the Alert delay, an Alert says so and names a leaked bot token as a possible cause; it is resolved when fetching works again
- [x] The bot token never appears in the log
- [x] `[telegram] buttons = false` turns the buttons off
- [x] The runbook (both languages) explains the buttons, who can use them, and what a leaked token allows
