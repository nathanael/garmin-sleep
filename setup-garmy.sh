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

echo "[3/3] Setup complete — sign in at http://localhost:8484 once the server is running."
