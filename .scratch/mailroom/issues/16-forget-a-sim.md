# 16: Forget a SIM that is no longer used

**What to build:** A SIM that has been taken out for good stays on the Status page as "not in a Modem" and keeps an Alert open. The owner can forget such a SIM: it leaves the Status page, the SIM filter, the start notice count and the Alerts, while its Messages stay stored, shown with its label and searchable. Forgetting is not deleting: if the same SIM is put into a Modem again it comes back by itself with its label, number correction and Forwarding setting.

**Blocked by:** 06, 08

**Status:** done

- [x] A SIM that is not in any Modem can be forgotten from its card on the Status page, after a confirmation that says its Messages are kept
- [x] A SIM that is in a Modem cannot be forgotten
- [x] A forgotten SIM is no longer shown on the Status page or in the SIM filter, and is not counted in the start notice
- [x] Its Messages stay in the list and in search results, with the SIM's label
- [x] An Alert open for a forgotten SIM goes away without a "recovered" notice on Telegram
- [x] A forgotten SIM put into a Modem again is remembered with its label, number correction and Forwarding setting
- [x] The runbook (both languages) says how to forget a SIM and what happens to its Messages
