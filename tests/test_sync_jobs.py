import sys
import time
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import sync_jobs  # noqa: E402

STUB = str(Path(__file__).resolve().parent / "stub_sync.py")
PARTIAL_FAILURE_STUB = str(Path(__file__).resolve().parent / "stub_sync_partial_failure.py")


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


class ParseStageCountsTest(unittest.TestCase):
    def test_parses_the_real_summary_line(self):
        output = "Syncing 2026-01-01 to 2026-01-07 (7 days)\nDone: 48 completed, 14 skipped, 8 failed"
        self.assertEqual(
            sync_jobs.parse_stage_counts(output),
            {"completed": 48, "skipped": 14, "failed": 8},
        )

    def test_none_when_summary_line_absent(self):
        self.assertIsNone(sync_jobs.parse_stage_counts("stub synced 2026-08-24"))
        self.assertIsNone(sync_jobs.parse_stage_counts(""))
        self.assertIsNone(sync_jobs.parse_stage_counts(None))

    def test_all_zero_counts_still_parsed(self):
        self.assertEqual(
            sync_jobs.parse_stage_counts("Done: 0 completed, 0 skipped, 0 failed"),
            {"completed": 0, "skipped": 0, "failed": 0},
        )


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

    def test_nonexistent_interpreter_exception_clears_running_and_records_error(self):
        # Nonexistent interpreter path causes FileNotFoundError in subprocess.run
        runner = sync_jobs.JobRunner("/nonexistent/python", STUB, timeout=30)
        job_id, job = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id)
        final = wait_until_done(runner)
        self.assertFalse(final["running"], "running flag should be cleared after exception")
        self.assertIsNotNone(final["error"], "error should be recorded")
        self.assertIn("FileNotFoundError", final["error"])
        self.assertEqual(len(final["stages"]), 1, "stage should be recorded despite error")
        self.assertFalse(final["stages"][0]["ok"])
        # Subsequent start should succeed (not refused)
        job_id2, job2 = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id2, "should accept new job after previous failed")

    def test_nonexistent_script_exits_nonzero_stops_chain(self):
        # Nonexistent script path: interpreter launches successfully but exits with code 2
        runner = sync_jobs.JobRunner(sys.executable, "/nonexistent/path/to/sync.py", timeout=30)
        job_id, job = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id)
        final = wait_until_done(runner)
        self.assertFalse(final["running"], "job should complete")
        self.assertIsNotNone(final["error"], "error should be recorded for non-zero exit")
        self.assertEqual(len(final["stages"]), 1, "stage should be recorded")
        self.assertFalse(final["stages"][0]["ok"])

    def test_stage_reports_failure_counts_even_though_exit_code_is_zero(self):
        """IMPORTANT 4: sync.py exits 0 regardless of per-day failures, so
        a stage with real per-day Garmin failures still looks 'ok' by
        return code alone -- live evidence was a job with "ok": true
        whose own stdout read "Done: 48 completed, 14 skipped, 8 failed".
        The stage record must carry the parsed counts so callers (the
        UI) can tell the difference between a clean stage and one that
        silently dropped data.
        """
        runner = sync_jobs.JobRunner(sys.executable, PARTIAL_FAILURE_STUB, timeout=30)
        runner.start([("2026-08-24", "2026-08-30")])
        final = wait_until_done(runner)
        self.assertIsNone(final["error"])
        stage = final["stages"][0]
        self.assertTrue(stage["ok"], "returncode 0 still counts as ok -- sync.py's exit code is unchanged")
        self.assertEqual(stage["counts"], {"completed": 48, "skipped": 14, "failed": 8})

    def test_refuses_to_spawn_anything_named_sync_py_while_under_unittest(self):
        """Second, independent guard against the real Garmin sync ever running
        in a test process: a future test could construct its own JobRunner
        pointed at the real production sync.py and forget to swap in a
        stub (exactly what SyncEndpointTest.setUp does today, correctly,
        for /api/sync tests). sync.py makes real Garmin API calls against
        the user's real account, so this must not depend on that one
        setUp being copied correctly forever.

        The guard trips on the script's basename ("sync.py") while
        'unittest' is loaded in sys.modules -- true for the entire process
        any time tests run via `python -m unittest ...`, regardless of
        which test file or class is executing. It requires no test to opt
        in.

        The path below is not the real sync.py (it doesn't exist), so if
        the guard did NOT fire, subprocess.run would still fail --
        asserting the specific refusal message, not just "some error", is
        what proves the guard itself fired rather than a plain
        file-not-found (see test_nonexistent_script_exits_nonzero_stops_chain
        directly above, which is that plain case).
        """
        runner = sync_jobs.JobRunner(sys.executable, "/definitely/not/real/sync.py", timeout=30)
        job_id, job = runner.start([("2026-08-24", "2026-08-30")])
        self.assertIsNotNone(job_id)
        final = wait_until_done(runner)
        self.assertFalse(final["running"])
        self.assertIsNotNone(final["error"])
        self.assertIn("Refusing to spawn", final["error"])
        self.assertEqual(len(final["stages"]), 1)
        self.assertFalse(final["stages"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
