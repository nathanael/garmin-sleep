#!/bin/bash
# ============================================================
# Garmy MCP Server Setup for Claude Desktop
# For: Nate @ /Users/monster
# ============================================================

set -e

# Add Python user bin to PATH (where pip installs scripts)
export PATH="/Users/monster/Library/Python/3.8/bin:$PATH"

echo ""
echo "=========================================="
echo "  Garmy + Claude Desktop MCP Setup"
echo "=========================================="
echo ""

# ----------------------------------------------------------
# Step 1: Check Python
# ----------------------------------------------------------
echo "[1/5] Checking Python..."
if command -v python3 &> /dev/null; then
    echo "  Found: $(python3 --version 2>&1)"
else
    echo "  Python 3 not found. Installing via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install python
    else
        echo "  ERROR: Need Python 3. Install from https://python.org or run:"
        echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    brew install python"
        exit 1
    fi
fi

# ----------------------------------------------------------
# Step 2: Install garmy
# ----------------------------------------------------------
echo ""
echo "[2/5] Installing garmy..."
pip3 install "garmy[all]"
echo "  Done."

# ----------------------------------------------------------
# Step 3: Sync 90 days of health data
# ----------------------------------------------------------
echo ""
echo "[3/5] Syncing 90 days of Garmin data..."
echo "  (You'll be prompted for your Garmin email and password on first run.)"
echo "  (Credentials are stored as OAuth tokens, not plain text.)"
echo ""

DB_PATH="/Users/monster/dev/garmy/health.db"
garmy-sync sync --last-days 90 --database "$DB_PATH"
echo ""
echo "  Database saved to: $DB_PATH"

# ----------------------------------------------------------
# Step 4: Configure Claude Desktop
# ----------------------------------------------------------
echo ""
echo "[4/5] Configuring Claude Desktop..."

CLAUDE_CONFIG_DIR="/Users/monster/Library/Application Support/Claude"
CLAUDE_CONFIG="$CLAUDE_CONFIG_DIR/claude_desktop_config.json"
GARMY_MCP_PATH=$(which garmy-mcp 2>/dev/null || echo "/Users/monster/Library/Python/3.8/bin/garmy-mcp")

mkdir -p "$CLAUDE_CONFIG_DIR"

if [ -f "$CLAUDE_CONFIG" ]; then
    # Check if garmy is already configured
    if grep -q "garmy-localdb" "$CLAUDE_CONFIG" 2>/dev/null; then
        echo "  garmy-localdb already in config. Skipping."
    else
        echo "  Existing config found. Merging garmy-localdb entry..."
        # Use python to safely merge JSON
        python3 -c "
import json, sys
with open('$CLAUDE_CONFIG', 'r') as f:
    config = json.load(f)
if 'mcpServers' not in config:
    config['mcpServers'] = {}
config['mcpServers']['garmy-localdb'] = {
    'command': '$GARMY_MCP_PATH',
    'args': ['server', '--database', '$DB_PATH', '--max-rows', '500']
}
with open('$CLAUDE_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
print('  Merged successfully.')
"
    fi
else
    cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "garmy-localdb": {
      "command": "$GARMY_MCP_PATH",
      "args": ["server", "--database", "$DB_PATH", "--max-rows", "500"]
    }
  }
}
EOF
    echo "  Config created."
fi

echo "  Config location: $CLAUDE_CONFIG"

# ----------------------------------------------------------
# Step 5: Create a daily sync helper
# ----------------------------------------------------------
echo ""
echo "[5/5] Creating daily sync shortcut..."

cat > /Users/monster/dev/garmy/sync-garmin.sh << 'SYNCEOF'
#!/bin/bash
# Quick sync — run this anytime to pull latest Garmin data
export PATH="/Users/monster/Library/Python/3.8/bin:$PATH"
garmy-sync sync --last-days 7 --database /Users/monster/dev/garmy/health.db
echo "Sync complete."
SYNCEOF
chmod +x /Users/monster/dev/garmy/sync-garmin.sh

echo "  Created: /Users/monster/dev/garmy/sync-garmin.sh"
echo "  Run this anytime to refresh your data."

# ----------------------------------------------------------
# Done
# ----------------------------------------------------------
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  Now:"
echo "    1. Quit Claude Desktop completely (Cmd+Q)"
echo "    2. Reopen Claude Desktop"
echo "    3. Look for the hammer icon (bottom-left of chat)"
echo "    4. Ask: 'Analyze my sleep patterns over the last month'"
echo ""
echo "  To refresh data anytime:"
echo "    ./sync-garmin.sh"
echo ""
