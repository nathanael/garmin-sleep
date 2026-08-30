"""Background Garmin sync jobs.

Deliberately knows nothing about HTTP or garmy so it can be unit-tested
with a stub script and no Garmin account.
"""

import subprocess
import threading
import uuid
from datetime import timedelta

SYNC_TIMEOUT = 1800

# (days_ago_start, days_ago_end) inclusive. Contiguous, no overlap, 365 days.
CHAIN = [(6, 0), (29, 7), (364, 30)]


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
                    {"stage": index, "range": [start, end], "ok": ok, "output": output}
                )
                if not ok:
                    self._job["error"] = error or f"Stage {index} failed"
                    self._job["running"] = False
                    return

        with self._lock:
            if self._job is not None and self._job["id"] == job_id:
                self._job["running"] = False
