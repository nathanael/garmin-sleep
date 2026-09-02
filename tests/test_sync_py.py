"""Tests for sync.py's extract_sleep_metrics() (IMPORTANT 9).

Only imports sync.py as a module -- that runs no Garmin code (main() is
gated by `if __name__ == "__main__"`), so this never touches the network
or a real account. Never call sync.main() from a test; see CLAUDE.md /
the task brief for why sync.py must never actually run in this repo.
"""
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import sync  # noqa: E402


class ExtractSleepMetricsTest(unittest.TestCase):
    """extract_sleep_metrics() is the pure function sync.py's per-day
    backfill loop uses to pull sleep_score, avg_sleep_stress, lowest_spo2,
    and sleep_need_minutes out of the `sleep_summary` object garmy's sleep
    API returns -- verified live against the user's real account (see the
    task brief): sleep_scores["overall"]["value"], avg_sleep_stress,
    lowest_sp_o2_value (garmy's spelling), and sleep_need["baseline"].
    """

    def test_extracts_all_four_fields_from_a_full_summary(self):
        # Shape verified live: 2026-08-30, overall score 85.
        summary = SimpleNamespace(
            sleep_scores={
                "overall": {"value": 85, "qualifier_key": "GOOD"},
                "total_duration": {"value": 70},
            },
            avg_sleep_stress=17.0,
            lowest_sp_o2_value=89,
            sleep_need={"baseline": 470, "actual": 470, "feedback": "MET"},
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(
            result,
            {
                "sleep_score": 85,
                "avg_sleep_stress": 17.0,
                "lowest_spo2": 89,
                "sleep_need_minutes": 470,
            },
        )

    def test_sleep_score_comes_from_the_nested_overall_value_path(self):
        # Isolates the specific nested path (sleep_scores -> "overall" ->
        # "value") from the other three fields, which are flat attributes.
        summary = SimpleNamespace(
            sleep_scores={"overall": {"value": 71, "qualifier_key": "FAIR"}},
            avg_sleep_stress=None,
            lowest_sp_o2_value=None,
            sleep_need=None,
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(result["sleep_score"], 71)

    def test_summary_missing_every_field_entirely_returns_all_none(self):
        # A bare object with none of the expected attributes at all --
        # not even set to None. getattr's default must carry every field,
        # and the function must not raise.
        summary = SimpleNamespace()

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(
            result,
            {
                "sleep_score": None,
                "avg_sleep_stress": None,
                "lowest_spo2": None,
                "sleep_need_minutes": None,
            },
        )

    def test_summary_itself_is_none_returns_all_none(self):
        # e.g. a night with no sleep recorded -- the caller passes
        # sleep.sleep_summary straight through, which can be None.
        result = sync.extract_sleep_metrics(None)

        self.assertEqual(
            result,
            {
                "sleep_score": None,
                "avg_sleep_stress": None,
                "lowest_spo2": None,
                "sleep_need_minutes": None,
            },
        )

    def test_malformed_sleep_scores_does_not_blank_the_other_fields(self):
        # sleep_scores present but not a dict (or missing "overall"/"value")
        # must null out only sleep_score, not the three sibling fields.
        summary = SimpleNamespace(
            sleep_scores="not a dict",
            avg_sleep_stress=22,
            lowest_sp_o2_value=90,
            sleep_need={"baseline": 460},
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertIsNone(result["sleep_score"])
        self.assertEqual(result["avg_sleep_stress"], 22)
        self.assertEqual(result["lowest_spo2"], 90)
        self.assertEqual(result["sleep_need_minutes"], 460)

    def test_sleep_need_without_baseline_key_is_none(self):
        summary = SimpleNamespace(
            sleep_scores={"overall": {"value": 82}},
            avg_sleep_stress=15,
            lowest_sp_o2_value=91,
            sleep_need={"feedback": "MET"},  # no "baseline"
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertIsNone(result["sleep_need_minutes"])
        self.assertEqual(result["sleep_score"], 82)


if __name__ == "__main__":
    unittest.main()


class EarliestMissingSleepTests(unittest.TestCase):
    """The scheduled runs chase missing sleep, not failed sync_status rows.

    heart_rate and body_battery fail on every single run (Garmin returns null
    samples; the timeseries table rejects them), so a status-based window never
    closes. These tests pin the behaviour that replaced it.
    """

    def _db(self, rows):
        import sqlite3
        path = Path(self.tmp.name) / "health.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE daily_health_metrics ("
            "metric_date TEXT, sleep_duration_hours REAL)"
        )
        conn.executemany(
            "INSERT INTO daily_health_metrics VALUES (?, ?)", rows
        )
        conn.commit()
        conn.close()
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _day(self, offset):
        return (date.today() - timedelta(days=offset)).isoformat()

    def test_returns_none_when_every_recent_night_has_sleep(self):
        path = self._db([(self._day(i), 7.5) for i in range(5)])
        self.assertIsNone(sync.earliest_missing_sleep(path))

    def test_returns_the_oldest_night_that_is_missing_sleep(self):
        path = self._db([
            (self._day(0), 7.5),
            (self._day(2), None),
            (self._day(4), None),
        ])
        self.assertEqual(
            sync.earliest_missing_sleep(path),
            date.today() - timedelta(days=4),
        )

    def test_ignores_missing_nights_older_than_the_window(self):
        path = self._db([(self._day(0), 7.5), (self._day(40), None)])
        self.assertIsNone(sync.earliest_missing_sleep(path))

    def test_a_permanently_failing_metric_does_not_hold_the_window_open(self):
        """The whole point: days can be riddled with failed metric rows and
        still be complete as far as this job is concerned."""
        path = self._db([(self._day(i), 8.0) for i in range(14)])
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sync_status (sync_date TEXT, metric_type TEXT, status TEXT)")
        conn.executemany(
            "INSERT INTO sync_status VALUES (?, 'heart_rate', 'failed')",
            [(self._day(i),) for i in range(14)],
        )
        conn.commit()
        conn.close()
        self.assertIsNone(sync.earliest_missing_sleep(path))

    def test_missing_database_is_treated_as_nothing_missing(self):
        self.assertIsNone(
            sync.earliest_missing_sleep(Path(self.tmp.name) / "absent.db")
        )


class TodaysSleepRecordedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _db(self, rows):
        import sqlite3
        path = Path(self.tmp.name) / "health.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE daily_health_metrics ("
            "metric_date TEXT, sleep_duration_hours REAL)"
        )
        conn.executemany("INSERT INTO daily_health_metrics VALUES (?, ?)", rows)
        conn.commit()
        conn.close()
        return path

    def test_true_when_today_has_a_duration(self):
        path = self._db([(date.today().isoformat(), 7.4)])
        self.assertTrue(sync.todays_sleep_recorded(path))

    def test_false_when_todays_row_exists_but_sleep_is_null(self):
        path = self._db([(date.today().isoformat(), None)])
        self.assertFalse(sync.todays_sleep_recorded(path))

    def test_false_when_today_has_no_row_at_all(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        path = self._db([(yesterday, 8.0)])
        self.assertFalse(sync.todays_sleep_recorded(path))
