#!/bin/bash
# Install the daily 7am Garmin sync (launchd).
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$REPO_DIR/com.garmy.sync.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.garmy.sync.plist"

# Unload existing agent if present
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Render template → LaunchAgents
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

launchctl load "$PLIST_DST"

echo "Installed: Garmin sync will run every day at 7am."
echo "Logs:      $REPO_DIR/sync.log"
echo ""
echo "Check:   launchctl list | grep garmy"
echo "Remove:  launchctl unload $PLIST_DST"
