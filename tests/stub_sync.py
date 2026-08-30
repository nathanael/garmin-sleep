#!/usr/bin/env python3
"""Stand-in for sync.py in tests. Never touches Garmin.

Exits non-zero when the range start equals $STUB_FAIL_ON, so a test can
force a specific stage to fail.
"""
import os
import sys

args = sys.argv[1:]
start = args[1] if len(args) >= 3 and args[0] == "--range" else ""

if start and start == os.environ.get("STUB_FAIL_ON", ""):
    print(f"stub failing on {start}", file=sys.stderr)
    sys.exit(1)

print(f"stub synced {start}")
