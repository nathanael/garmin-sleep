"""Background Garmin sync jobs.

Deliberately knows nothing about HTTP or garmy so it can be unit-tested
with a stub script and no Garmin account.
"""

import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import timedelta

SYNC_TIMEOUT = 1800

# Real production sync.py makes live Garmin API calls against the user's
# real account and writes into their real health.db. Tests must always
# point JobRunner at a stub script; this is a second, independent guard
# against a future test forgetting to do that (see the module docstring
# and tests/test_sync_jobs.py's guard test for the full rationale). It
# does not depend on any single test's setUp: 'unittest' is present in
# sys.modules for the whole process any time tests are run via
# `python -m unittest ...`, regardless of which test file or class is
# executing, so this trips even for a brand-new test file that never
# knew to guard itself.
REAL_SYNC_SCRIPT_NAME = "sync.py"


def _refuse_if_real_sync_script_under_test(sync_script):
    if "unittest" in sys.modules and os.path.basename(str(sync_script)) == REAL_SYNC_SCRIPT_NAME:
        raise RuntimeError(
            f"Refusing to spawn {sync_script!r}: this looks like the real "
            "production sync.py and 'unittest' is loaded. That would make "
            "real Garmin API calls. Point JobRunner at a test stub instead."
        )

# (days_ago_start, days_ago_end) inclusive. Contiguous, no overlap, 365 days.
CHAIN = [(6, 0), (29, 7), (364, 30)]

# Matches sync.py's "Done: N completed, N skipped, N failed" summary line.
DONE_LINE_RE = re.compile(r"Done: (\d+) completed, (\d+) skipped, (\d+) failed")


def parse_stage_counts(output):
    """Pull the per-day completed/skipped/failed counts out of a stage's
    stdout, or None if the summary line isn't present (e.g. a stub, or a
    stage that failed before printing it).

    sync.py exits 0 regardless of per-day failures (each day's failure is
    caught and counted, not raised), so `ok` here reflects only the
    subprocess return code and can be True on a job where Garmin API
    calls failed for individual days. This is intentionally a
    stdout-parsing workaround rather than a sync.py exit-code change,
    since the exit code is also relied on by the CLI path and the
    launchd agent.
    """
    match = DONE_LINE_RE.search(output or "")
    if not match:
        return None
    completed, skipped, failed = (int(g) for g in match.groups())
    return {"completed": completed, "skipped": skipped, "failed": failed}


def chain_ranges(today):
    """Return [(start_iso, end_iso)] for the automatic three-stage chain."""
    return [
        (
            (today - timedelta(days=start)).isoformat(),
            (today - timedelta(days=end)).isoformat(),
        )
        for start, end in CHAIN
    ]


class JobRunner:
    """Runs sync stages sequentially on a worker thread. One job at a time."""

    def __init__(self, python, sync_script, timeout=SYNC_TIMEOUT):
        self._python = python
        self._sync_script = sync_script
        self._timeout = timeout
        self._lock = threading.Lock()
        self._job = None

    def _snapshot(self):
        """Caller must hold the lock. Deep copies the stages list and each stage's range."""
        if self._job is None:
            return {"running": False, "id": None}
        stages = [
            {**stage, "range": list(stage["range"])} for stage in self._job["stages"]
        ]
        return {**self._job, "stages": stages}

    def status(self):
        with self._lock:
            return self._snapshot()

    def start(self, ranges):
        """Start a job. Returns (job_id, job) or (None, current_job) if busy."""
        with self._lock:
            if self._job is not None and self._job["running"]:
                return None, self._snapshot()
            self._job = {
                "id": uuid.uuid4().hex,
                "stage": 1,
                "total": len(ranges),
                "running": True,
                "error": None,
                "stages": [],
            }
            job_id = self._job["id"]
            snapshot = self._snapshot()

        threading.Thread(
            target=self._run, args=(job_id, list(ranges)), daemon=True
        ).start()
        return job_id, snapshot

    def _run(self, job_id, ranges):
        for index, (start, end) in enumerate(ranges, 1):
            with self._lock:
                if self._job is None or self._job["id"] != job_id:
                    return  # superseded
                self._job["stage"] = index

            cmd = [self._python, self._sync_script, "--range", start, end]
            ok = False
            output = ""
            error = None
            try:
                _refuse_if_real_sync_script_under_test(self._sync_script)
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self._timeout
                )
                ok = result.returncode == 0
                output = result.stdout.strip()
                error = result.stderr.strip() or output
            except subprocess.TimeoutExpired:
                error = f"Stage {index} timed out after {self._timeout}s"
            except Exception as e:
                error = f"Stage {index} failed: {type(e).__name__}: {e}"

            with self._lock:
                if self._job is None or self._job["id"] != job_id:
                    return
                self._job["stages"].append(
                    {
                        "stage": index,
                        "range": [start, end],
                        "ok": ok,
                        "output": output,
                        "counts": parse_stage_counts(output),
                    }
                )
                if not ok:
                    self._job["error"] = error or f"Stage {index} failed"
                    self._job["running"] = False
                    return

        with self._lock:
            if self._job is not None and self._job["id"] == job_id:
                self._job["running"] = False
