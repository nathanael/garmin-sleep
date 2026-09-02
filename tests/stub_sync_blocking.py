#!/usr/bin/env python3
"""Stand-in for sync.py, like stub_sync.py, but stage 1 blocks until a
release file appears.

Used only by test_endpoints.py's concurrent-POST test, so that test can
observe a genuinely-still-running job deterministically instead of hoping
a fast stub script hasn't already finished the whole chain by the time the
second request lands. Once STUB_RELEASE_FILE exists, this behaves exactly
like stub_sync.py (immediate success) for every stage, including the one
that was waiting.
"""
import os
import sys
import time

args = sys.argv[1:]
start = args[1] if len(args) >= 3 and args[0] == "--range" else ""

release_file = os.environ.get("STUB_RELEASE_FILE")
if release_file:
    deadline = time.time() + 10
    while not os.path.exists(release_file) and time.time() < deadline:
        time.sleep(0.01)

print(f"stub synced {start}")
