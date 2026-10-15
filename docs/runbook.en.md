# SMS Mailroom runbook

[正體中文](./runbook.md) | English

How to run, check and change the SMS Mailroom installation on the Mac mini. Vocabulary follows `CONTEXT.md`.

## What is installed

| Piece | Where |
|---|---|
| SMS Mailroom service | launchd daemon `us.b612.mailroom` (`/Library/LaunchDaemons/us.b612.mailroom.plist`), running as the owner's account from this repository's `.venv` |
| Web page | `https://mailroom.example.com`, served through a Cloudflare Tunnel to `127.0.0.1:8000` and guarded by Cloudflare Access |
| Tunnel | `cloudflared`, its own launchd daemon (`com.cloudflare.cloudflared`) |
| Settings | `~/Library/Application Support/Mailroom/config.toml` (private; holds the Telegram bot token) |
| Database | `~/Library/Application Support/Mailroom/mailroom.db` |
| Backups | `~/Library/Application Support/Mailroom/backups/`, one per day, 14 kept, readable only by the owner |
| Logs | `~/Library/Logs/Mailroom/mailroom.log` (rotated at 5 MB, three old files kept) |

Both daemons start at boot, before anyone logs in, and restart if they stop.

**If FileVault is on**, the Mac stops at an unlock screen after a reboot or a power cut and waits for someone to type the password at the machine. Until then macOS has not started: neither daemon runs and the Mac cannot be reached remotely. `fdesetup status` shows whether it is on. For the machine to come back entirely by itself after a power cut, FileVault has to be off, at the cost of an unencrypted disk; to restart it yourself once, `sudo fdesetup authrestart` passes the unlock screen for that one restart.

## Everyday operations

- **Is it working?** Open the web page and go to Status. Each SIM has a card with its operator, signal and registration; below are the attached Modems and the state of the system itself (service, Telegram, macOS network service, USB connection, page protection). Anything wrong is listed in a yellow box at the top, marks the Status tab with a red dot, and has also been sent to Telegram.
- **Tidying Messages:** under Messages, tap a Message to open it. Archive what is worth keeping; delete the rest. To delete several at once, tap Select and tick them, or search first and tap Select all.
- **Messages from one person:** search for their phone number. The same phone can show up as `0933…`, `+886933…` or `00886933…` depending on the SIM it wrote to; any of these finds them all.
- **Language and appearance:** the gear at the top right switches between 中文 and English, and between following the system, light and dark.
- **Start notice:** about 15 seconds after the service starts, Telegram receives "🟢 Mailroom started", saying whether the Mac had just booted or only the service restarted, and how many Modems are attached and SIMs receiving. Getting one you did not expect means the service crashed and restarted itself; read the log.
- **Read the log:** `tail -f ~/Library/Logs/Mailroom/mailroom.log`
- **Restart** (after editing `config.toml` or updating the code): `sudo launchctl kickstart -k system/us.b612.mailroom`
- **Stop and remove the service:** `sudo scripts/install-service.sh uninstall`
- **Install or reinstall the service:** `sudo scripts/install-service.sh`. It refuses to install while `config.toml` has no `[access]` settings, because the tunnel would then expose the page.
- **Update the code:** pull, run `uv sync`, run `uv run pytest`, then restart the service.

The page at `http://127.0.0.1:8000` answers 403 on the Mac itself: every request must come through Cloudflare Access.

## Backup and restore

The database is backed up when the service starts and then once a day (after midnight, Taipei time), as `mailroom-YYYY-MM-DD.db`; files beyond the number to keep are removed. The system card under Status shows the date of the last backup and flags a failure.

Backups stay on the same computer. They recover a damaged or mistakenly emptied database, not a failed disk. For an off-machine copy, include the backup directory in Time Machine or point `directory` at another disk. Backup files contain the Messages in plain text.

To restore:

```bash
sudo launchctl bootout system/us.b612.mailroom            # stop the service
cd ~/Library/Application\ Support/Mailroom
mv mailroom.db mailroom.db.broken                         # keep the current database, just in case
cp backups/mailroom-2026-10-12.db mailroom.db             # put back the day you want
cd <the repository> && sudo scripts/install-service.sh    # start the service again
```

Messages received after that backup are not in it; they are still in the Telegram chat.

## Hardware

- **Antenna:** connect it to the socket marked `MANT`. The `GPS` and `BT` sockets are not used; an antenna on either gives no signal at all.
- **Replugging a Modem:** after unplugging, wait 5 to 8 seconds before plugging it back in. Reconnected sooner, the board can power up without the module starting.
- **Changing a SIM:** unplug the Modem, swap the SIM, wait, plug it back in. The SIM is registered by itself and keeps its label, Forwarding setting and Messages whichever Modem it is in.
- **A wrong or missing number:** the number is read from the SIM, and some SIMs carry none or a wrong one. Under Status, **Edit** on that SIM takes the right number; saving it blank goes back to what the SIM reports. The number is only displayed and has no effect on receiving.
- **A SIM no longer used:** once taken out, it stays on the Status page as "not in a Modem" and keeps an Alert open. Under Status, **Edit** on that SIM, then **Forget this SIM**: it leaves the Status page and the SIM filter, and its Alert goes away without a "resolved" notice. Its Messages are kept and can still be searched. Put the same SIM into a Modem again and it comes back with its label, number and Forwarding setting. A SIM that is in a Modem cannot be forgotten.
- **Adding a Modem:** just plug it in; SMS Mailroom picks it up within a few seconds.
- **USB hub:** power it from its own 5 V supply, with enough to spare. Short of power, Modems first report read errors again and again, then drop off the bus. If the supply is a multi-port charger, check the power table in its manual: some chargers cut one port's power sharply once something is plugged into another. A Modem that keeps dropping off the bus raises a "keeps disconnecting" Alert; check the hub, its power supply and the cable, or plug the Modem straight into the Mac.
- **A Modem that is plugged in but never shows up:** try another port; if that fails too, unplug both the hub's power supply and its cable to the Mac, wait a few seconds and reconnect them. A hub can occasionally hang as a whole, and replugging the Modem does not bring it back.
- **Modems in each other's way:** a Modem board is wider than a USB port, so neighbouring ports can be blocked. A short USB extension cable moves one out of the way.

## Settings

`config.toml`, with every section SMS Mailroom reads:

```toml
language = "zh"     # optional; "zh" or "en". Used for Telegram texts, and for the page until you pick another there

[telegram]
token = "<bot token from @BotFather>"
chat_id = "<the owner's chat id>"

[access]
team_domain = "<team>.cloudflareaccess.com"
audience = "<the Access application's AUD tag>"

[alerts]
after_minutes = 3   # optional; how long a problem must last before an Alert is sent

[backup]
directory = "~/Library/Application Support/Mailroom/backups"   # optional; where backups go
keep = 14           # optional; how many to keep
```

Without `[telegram]`, Messages are stored but not forwarded. Without `[access]`, the page is locked.

## Setting up from scratch

1. **Telegram bot.** In Telegram, send `/newbot` to `@BotFather` and note the token. Open the new bot, press Start and send it any message. The chat id is the `chat.id` in `https://api.telegram.org/bot<token>/getUpdates`.
2. **Tunnel.** Install `cloudflared` (`brew install cloudflared`). In the Cloudflare Zero Trust dashboard create a tunnel, run the `cloudflared service install` command it shows, and add a public hostname that points to `http://localhost:8000`.
3. **Access.** In Zero Trust, add a self-hosted Access application for the same hostname with an Allow policy for the owner's email. Note the team domain and the application's AUD tag. Check that the hostname now redirects to a login page when opened in a private window; if it does not, the page is not protected.
4. **Config.** Write `config.toml` as above and `chmod 600` it.
5. **macOS network service.** In System Settings → Network, disable "A76XX Series LTE Module", so the Mac never sends traffic over a SIM. SMS Mailroom raises an Alert if it is ever enabled.
6. **Service.** `uv sync`, then `sudo scripts/install-service.sh`.
7. **Check.** Sign in at the public hostname, send an SMS to one of the SIMs, and see it arrive on the page and in Telegram.

## Known behaviour

- A Modem occasionally reports a read error; SMS Mailroom retries and carries on. A burst of them just before a Modem disappears points at the USB hub or its power supply.
- Roaming SIMs sometimes deliver an SMS minutes late, or twice. A repeat with the same sender, network time and text is stored once.
- A Message deleted on the page is gone for good.
