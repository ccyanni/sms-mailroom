# 10: Run Mailroom permanently on the Mac mini

**What to build:** Mailroom runs unattended. It starts when the Mac mini boots, restarts if it crashes, reads its settings from one config file outside the repository, and is reachable from outside through a Cloudflare Tunnel protected by Cloudflare Access. The steps only the owner can perform (creating the Telegram bot and finding the chat ID, creating the tunnel and the Access application, keeping the Mac mini awake) are delivered as a guided script (see the `wizard` skill) and a short runbook.

**Blocked by:** 02, 05, 09

**Status:** ready-for-agent

- [ ] Mailroom is installed as a launchd service that starts at boot and restarts on crash
- [ ] All settings (Telegram, Cloudflare Access, database location, mobile data) live in one documented config file outside the repository
- [ ] Logs are written somewhere the owner can find, and never contain the bot token
- [ ] A guided script walks the owner through creating the Telegram bot, the Cloudflare Tunnel and the Access application, and verifies each step
- [ ] A runbook explains how to start, stop, update and check the service, and how to keep the Mac mini from sleeping
- [ ] After a reboot, a real SMS reaches Telegram and the web page with no manual steps
