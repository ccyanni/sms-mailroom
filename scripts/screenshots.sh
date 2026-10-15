#!/usr/bin/env bash
#
# Retake the README screenshots from invented sample data, in both languages:
#
#     scripts/screenshots.sh              # writes docs/images/*.png
#     scripts/screenshots.sh <directory>  # writes them somewhere else, to look first
#
# Needs Google Chrome. Takes about three minutes, most of it waiting so the
# Status page shows a service that has been up for a minute.
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(cd "${1:-$REPO/docs/images}" && pwd)"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PORT="${SCREENSHOT_PORT:-8799}"
BASE="http://127.0.0.1:$PORT"
WORK="$(mktemp -d)"
SERVER=""

cleanup() {
  [[ -n "$SERVER" ]] && kill "$SERVER" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

[[ -x "$CHROME" ]] || { echo "Google Chrome not found; set CHROME to its executable" >&2; exit 1; }

shot() {  # name, height, page
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size=500,"$2" --screenshot="$OUT/$1.png" "file://$3" >/dev/null 2>&1
}

with_theme() {  # page in, page out, light|dark: pin the appearance, whatever this Mac uses
  python3 -I -c '
import sys
page, out, theme = sys.argv[1:]
html = open(page, encoding="utf-8").read()
html = html.replace("<html lang=", f"<html data-theme=\"{theme}\" lang=", 1)
html = html.replace("localStorage.getItem(\"theme\")", f"\"{theme}\"", 1)
open(out, "w", encoding="utf-8").write(html)' "$@"
}

take() {  # language, then the three SIM labels
  local lang=$1
  (cd "$REPO" && exec uv run -q python scripts/screenshot_server.py "$lang" "$PORT") &
  SERVER=$!
  until curl -sf -o /dev/null "$BASE/status"; do sleep 0.5; done
  sleep 3  # let the Modems be read and the Messages arrive

  curl -sf -o /dev/null -X POST --data-urlencode "label=$2" "$BASE/sims/89886000000000000001/details"
  curl -sf -o /dev/null -X POST --data-urlencode "label=$3" "$BASE/sims/89860000000000000002/details"
  curl -sf -o /dev/null -X POST --data-urlencode "label=$4" "$BASE/sims/89886010000000000003/details"
  local oldest
  oldest=$(curl -sf "$BASE/" | grep -o '/messages/[0-9]*/archive' | tail -1)
  curl -sf -o /dev/null -X POST -d archived=1 "$BASE$oldest"
  sleep 62

  # The newest Message is shown opened, with its code and buttons.
  curl -sf -H "Cookie: lang=$lang" "$BASE/" \
    | python3 -I -c 'import sys; sys.stdout.write(sys.stdin.read().replace("<details>", "<details open>", 1))' > "$WORK/messages.html"
  curl -sf -H "Cookie: lang=$lang" "$BASE/status" > "$WORK/status.html"
  kill "$SERVER"; wait "$SERVER" 2>/dev/null || true; SERVER=""

  with_theme "$WORK/messages.html" "$WORK/m-light.html" light
  with_theme "$WORK/messages.html" "$WORK/m-dark.html" dark
  with_theme "$WORK/status.html" "$WORK/s-light.html" light
  shot "messages-$lang" 900 "$WORK/m-light.html"
  shot "messages-dark-$lang" 900 "$WORK/m-dark.html"
  shot "status-$lang" 1510 "$WORK/s-light.html"
  echo "took the $lang screenshots"
}

take zh "台灣大哥大" "中國移動" "遠傳電信"
take en "Taiwan Mobile" "China Mobile" "Far EasTone"
echo "written to $OUT"
