#!/bin/bash
# Keep the dashboard server running: start at login, restart if it dies.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$REPO_DIR/com.garmy.server.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.garmy.server.plist"

if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  echo "No .venv found. Run ./setup-garmy.sh first." >&2
  exit 1
fi

# Stop anything already listening on 8484 so the agent can bind it.
launchctl unload "$PLIST_DST" 2>/dev/null || true
if lsof -ti:8484 >/dev/null 2>&1; then
  echo "Port 8484 is busy; stopping the process holding it."
  kill "$(lsof -ti:8484)" 2>/dev/null || true
  sleep 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$PLIST_SRC" > "$PLIST_DST"
launchctl load "$PLIST_DST"

echo "Installed: the dashboard now starts at login and restarts if it stops."
echo "Open:    http://localhost:8484"
echo "Logs:    $REPO_DIR/server.log"
echo ""
echo "Check:   launchctl list | grep garmy"
echo "Remove:  launchctl unload $PLIST_DST && rm $PLIST_DST"
