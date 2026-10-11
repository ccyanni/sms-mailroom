# 05: Forward Messages to Telegram

**What to build:** Every Message on a SIM with Forwarding on is delivered to the owner's private Telegram chat within seconds, showing which SIM received it, the sender, the time and the full text. If Telegram cannot be reached, Mailroom keeps retrying until it succeeds, and the web page shows which Messages have been forwarded. A multi-Part Message is forwarded once complete, or after the one-minute timeout marked incomplete and then updated when completed. The bot only sends; it accepts no commands. The bot token and chat ID come from a config file outside the repository.

**Blocked by:** 01, 04

**Status:** ready-for-agent

- [ ] A stored Message is sent to the configured Telegram chat with SIM label, sender, Taipei time and full text
- [ ] A failed send is retried until it succeeds, across restarts of Mailroom
- [ ] A Message is never forwarded twice
- [ ] The web page shows whether each Message has been forwarded
- [ ] An incomplete Message is forwarded marked as incomplete after the timeout, and the owner is shown the full text when it completes
- [ ] The bot token and chat ID are read from configuration outside the repository and never logged
- [ ] Tests replace only the outbound Telegram HTTP call with a recording fake
