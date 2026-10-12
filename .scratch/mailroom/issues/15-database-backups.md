# 15: Back up the database every day

**What to build:** SMS Mailroom keeps a copy of its database from each of the last 14 days, so a damaged or mistakenly emptied database can be put back. A backup is made when the service starts and then once per calendar day (Taipei time), as a consistent snapshot taken while SMS Mailroom keeps running. Backups live beside the database on the same computer, readable only by the owner, and older ones are removed. The Status section shows when the last backup was made and says so if backing up is failing. The directory and how many to keep can be set in the config file.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] A backup of the current database exists shortly after the service starts
- [x] At most one backup is made per day, and a new one appears when the day changes while the service runs
- [x] A backup is a complete, valid database containing the Messages stored at that moment
- [x] Only the newest 14 (configurable) are kept
- [x] Backup files can be read only by the owner
- [x] The Status section shows the date of the last backup and how many are kept, and flags a failure
- [x] How to restore is written in the runbook
