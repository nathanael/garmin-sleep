#!/bin/bash
# Install the daily 7am Garmin sync schedule

# Unload if already installed
launchctl unload ~/Library/LaunchAgents/com.garmy.sync.plist 2>/dev/null

# Copy plist to LaunchAgents
cp /Users/monster/dev/garmy/com.garmy.sync.plist ~/Library/LaunchAgents/

# Load it
launchctl load ~/Library/LaunchAgents/com.garmy.sync.plist

echo "Done! Garmin data will sync every day at 7am."
echo "Logs: ~/dev/garmy/sync.log"
echo ""
echo "To check it's running:  launchctl list | grep garmy"
echo "To stop it:             launchctl unload ~/Library/LaunchAgents/com.garmy.sync.plist"
