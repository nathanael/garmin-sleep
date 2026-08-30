import sys
import time
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import sync_jobs  # noqa: E402

STUB = str(Path(__file__).resolve().parent / "stub_sync.py")


def wait_until_done(runner, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = runner.status()
        if not s["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


class ChainRangesTest(unittest.TestCase):
    def test_three_stages_contiguous_and_365_days(self):
        ranges = sync_jobs.chain_ranges(date(2026, 8, 30))
        self.assertEqual(
            ranges,
            [
                ("2026-08-24", "2026-08-30"),
                ("2026-08-01", "2026-08-23"),
                ("2025-08-31", "2026-07-31"),
            ],
        )

    def test_no_day_is_covered_twice(self):
        ranges = sync_jobs.chain_ranges(date(2026, 8, 30))
        seen = set()
        for start, end in ranges:
            d, last = date.fromisoformat(start), date.fromisoformat(end)
            while d <= last:
                self.assertNotIn(d, seen, f"{d} covered twice")
                seen.add(d)
                d = d.fromordinal(d.toordinal() + 1)
        self.assertEqual(len(seen), 365)


class JobRunnerTest(unittest.TestCase):
    def setUp(self):
        self.runner = sync_jobs.JobRunner(sys.executable, STUB, timeout=30)

    def test_status_before_any_job(self):
        self.assertEqual(self.runner.status(), {"running": False, "id": None})

    def test_runs_every_stage_in_order(self):
        ranges = [("2026-08-24", "2026-08-30"), ("2026-08-01", "2026-08-23")]
        job_id, job = self.runner.start(ranges)
        self.assertIsNotNone(job_id)
        self.assertEqual(job["total"], 2)
        final = wait_until_done(self.runner)
        self.assertIsNone(final["error"])
        self.assertEqual([s["stage"] for s in final["stages"]], [1, 2])
        self.assertTrue(all(s["ok"] for s in final["stages"]))

    def test_stops_chain_on_failure_and_keeps_earlier_stages(self):
        import os
        os.environ["STUB_FAIL_ON"] = "2026-08-01"
        self.addCleanup(os.environ.pop, "STUB_FAIL_ON", None)
        ranges = [
            ("2026-08-24", "2026-08-30"),
            ("2026-08-01", "2026-08-23"),
            ("2025-08-31", "2026-07-31"),
        ]
        self.runner.start(ranges)
        final = wait_until_done(self.runner)
        self.assertIsNotNone(final["error"])
        self.assertEqual([s["stage"] for s in final["stages"]], [1, 2])
        self.assertTrue(final["stages"][0]["ok"])
        self.assertFalse(final["stages"][1]["ok"])

    def test_second_start_while_running_is_refused(self):
        long_ranges = [("2026-08-24", "2026-08-30")] * 4
        self.runner.start(long_ranges)
        job_id, current = self.runner.start([("2026-01-01", "2026-01-02")])
        self.assertIsNone(job_id)
        self.assertTrue(current["running"])
        wait_until_done(self.runner)

    def test_status_copy_is_not_shared_mutable_state(self):
        self.runner.start([("2026-08-24", "2026-08-30")])
        final = wait_until_done(self.runner)
        snapshot = self.runner.status()

        # Mutate the snapshot's stages list and individual stage fields
        snapshot["stages"].append({"bogus": True})
        snapshot["stages"][0]["ok"] = False
        snapshot["stages"][0]["range"].append("mutated")

        # Verify internal state is unchanged
        current = self.runner.status()
        self.assertNotIn({"bogus": True}, current["stages"])
        self.assertTrue(current["stages"][0]["ok"])
        self.assertEqual(current["stages"][0]["range"], ["2026-08-24", "2026-08-30"])

    def test_nonexistent_script_path_clears_running_and_records_error(self):
        runner = sync_jobs.JobRunner(sys.executable, "/nonexistent/path/to/sync.py", timeout=30)
        job_id, job = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id)
        final = wait_until_done(runner)
        self.assertFalse(final["running"], "running flag should be cleared after exception")
        self.assertIsNotNone(final["error"], "error should be recorded")
        self.assertEqual(len(final["stages"]), 1, "stage should be recorded despite error")
        self.assertFalse(final["stages"][0]["ok"])
        # Subsequent start should succeed (not refused)
        job_id2, job2 = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id2, "should accept new job after previous failed")


if __name__ == "__main__":
    unittest.main()
