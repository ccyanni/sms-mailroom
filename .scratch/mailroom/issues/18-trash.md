# 18: Deleting moves a Message to the Trash, emptied after 30 days

**What to build:** Deleting a Message on the page is final today, so a slip of the finger, or someone who gets hold of the owner's Telegram once Messages can be deleted from there (issue 19), loses it for good. Deleting now moves a Message to the Trash instead, where it waits 30 days and is then deleted for good by itself. From the Trash the owner can restore a Message to where it was (the inbox or the Archive), delete it for good at once, or empty the Trash. Deleting for good also really removes the text from the database file, rather than leaving it in freed space.

**Blocked by:** 11

**Status:** done

- [x] Deleting a Message, one or several, moves it to the Trash without a confirmation step; it leaves the inbox and the Archive
- [x] The Trash lists only deleted Messages, with how many days each has left; search and the SIM filter work in it, and its count is shown beside the inbox's and the Archive's
- [x] A Message restored from the Trash goes back to the inbox or the Archive, wherever it was
- [x] From the Trash a Message, several selected ones, or all of them can be deleted for good, after a confirmation step
- [x] A Message that has been in the Trash for 30 days is deleted for good, also when the service was not running on that day
- [x] A Message in the Trash is not forwarded; restored, it is forwarded if it was still owed
- [x] A Part that arrives late for a Message in the Trash joins it there; a repeat of a deleted Message is not stored again while it is in the Trash
- [x] Text deleted for good is not left in the database file, including text deleted by earlier versions
- [x] Existing databases are upgraded with nothing in the Trash
- [x] CONTEXT.md defines the Trash; the runbook (both languages) says how long deleted Messages can still be found, including in the daily backups
