#!/bin/bash
# Bootstrap: create .venv, install garmy, and log you in to Garmin Connect.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO_DIR/.venv"

echo "[1/3] Creating venv at $VENV"
python3 -m venv "$VENV"

echo "[2/3] Installing garmy"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install "garmy[all]"

echo "[3/3] Logging in to Garmin Connect (one-time; tokens saved to ~/.garmy/)"
"$VENV/bin/python" "$REPO_DIR/login.py"

echo ""
echo "Setup complete. Next:"
echo "  $VENV/bin/python sync.py 30         # pull 30 days of data"
echo "  $VENV/bin/python garmin-sleep-upgrade/server.py"
