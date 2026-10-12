# 12: A clean, phone-first interface in Chinese and English

**What to build:** The web page is redesigned for use on a phone, following the prototype the owner approved on 2026-10-12 (`https://claude.ai/artifact/LtBH81Ksrv5iVBPtA31ybi`). Two sections reached from a bottom tab bar: Messages (search, SIM filter, inbox/Archive, each Message opening to its full text, any verification code with a copy button, and its actions) and Status (current Alerts, one card per SIM with its network details, Forwarding switch and rename). The interface is in Traditional Chinese by default and can be switched to English; Telegram texts follow the configured language. Appearance follows the system's light or dark setting or is chosen by hand. Minimal, clean, no decoration.

**Blocked by:** 11

**Status:** done

- [x] Messages and Status are separate sections with a tab bar; the Status tab shows a mark while any Alert is active
- [x] A Message shows sender, how long ago it arrived, its SIM and two lines of text; opening it shows the full text, the exact time and its Forwarding state
- [x] A 4 to 8 digit code in a Message is shown on its own with a copy button
- [x] Deleting needs a second, explicit confirmation
- [x] The page is in Traditional Chinese by default; the owner can switch to English and the choice is remembered
- [x] Forwarded Messages and Alerts on Telegram use the configured language (Chinese by default)
- [x] Appearance can be set to follow the system, light or dark, and the choice is remembered
- [x] Touch targets are at least 44 px, text contrast is at least 4.5:1 in both appearances, and nothing scrolls sideways on a phone (built to these; 2026-10-12: the owner went through the page on a real phone and reported everything working, without measuring sizes or contrast)
- [x] The page keeps refreshing itself without disturbing an open Message, a selection or a field being typed in
