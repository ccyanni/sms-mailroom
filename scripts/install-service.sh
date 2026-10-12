#!/usr/bin/env bash
#
# Install Mailroom as a system service that starts at boot, before anyone logs
# in, and restarts if it stops. Run from the repository:
#
#     sudo scripts/install-service.sh            # install or update, then start
#     sudo scripts/install-service.sh uninstall  # stop and remove
#
set -euo pipefail

LABEL="us.b612.mailroom"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="${SUDO_USER:-}"

if [[ $EUID -ne 0 || -z "$OWNER" || "$OWNER" == "root" ]]; then
  echo "Run this with sudo from your own account: sudo $0" >&2
  exit 1
fi

OWNER_HOME="$(dscl . -read "/Users/$OWNER" NFSHomeDirectory | awk '{print $2}')"
PYTHON="$REPO/.venv/bin/python"
LOG_FILE="$OWNER_HOME/Library/Logs/Mailroom/mailroom.log"

launchctl bootout "system/$LABEL" 2>/dev/null || true
if [[ "${1:-}" == "uninstall" ]]; then
  rm -f "$PLIST"
  echo "Mailroom service removed."
  exit 0
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "No virtual environment at $REPO/.venv. Run 'uv sync' in the repository first." >&2
  exit 1
fi

# The service listens where the Cloudflare Tunnel points. Starting it without
# Cloudflare Access configured would put the owner's Messages on the internet.
if ! sudo -u "$OWNER" env HOME="$OWNER_HOME" "$PYTHON" -c \
  'import sys; from mailroom import config; sys.exit(0 if config.load().access else 1)'; then
  echo "Refusing to install: the config file has no [access] team_domain and audience." >&2
  echo "Set them in '$OWNER_HOME/Library/Application Support/Mailroom/config.toml' first." >&2
  exit 1
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>UserName</key><string>${OWNER}</string>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>-m</string>
    <string>mailroom</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>${OWNER_HOME}</string>
    <key>MAILROOM_LOG_FILE</key><string>${LOG_FILE}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardErrorPath</key><string>${OWNER_HOME}/Library/Logs/Mailroom/launchd.log</string>
  <key>StandardOutPath</key><string>${OWNER_HOME}/Library/Logs/Mailroom/launchd.log</string>
</dict>
</plist>
PLIST
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
sudo -u "$OWNER" mkdir -p "$OWNER_HOME/Library/Logs/Mailroom"

launchctl bootstrap system "$PLIST"
echo "Mailroom service installed and started."
echo "Log: $LOG_FILE"
