#!/usr/bin/env python3
"""Stand-in for sync.py that reproduces IMPORTANT 4's live evidence: a run
where some per-day Garmin API calls failed, but the process still exits 0
(sync.py catches per-day failures and only counts them, never raises), so
subprocess.run's returncode alone can't tell the caller the sync was only
partly successful.

Prints the same "Done: N completed, N skipped, N failed" summary line
real sync.py prints, so sync_jobs.parse_stage_counts() has something to
parse.
"""
import sys

args = sys.argv[1:]
start = args[1] if len(args) >= 3 and args[0] == "--range" else ""

print(f"Syncing stub range starting {start}")
print("Done: 48 completed, 14 skipped, 8 failed")
sys.exit(0)
