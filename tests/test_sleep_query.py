import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import server  # noqa: E402

# Column -> (sqlite type, seed value). Covers every column referenced by
# SLEEP_FIELDS / SLEEP_PRESENCE_COLUMNS plus the user_id the WHERE clause
# filters on. Values are chosen to be distinguishable from each other so a
# mismatched mapping would show up as a wrong value, not just a missing one.
ALL_COLUMNS = {
    "user_id": ("INTEGER", 1),
    "metric_date": ("DATE", "2026-08-24"),
    "deep_sleep_hours": ("FLOAT", 1.5),
    "light_sleep_hours": ("FLOAT", 6.0),
    "rem_sleep_hours": ("FLOAT", 1.25),
    "awake_hours": ("FLOAT", 0.5),
    "avg_sleep_respiration_value": ("FLOAT", 15.5),
    "lowest_respiration_value": ("FLOAT", 11.0),
    "avg_sleep_stress": ("INTEGER", 22),
    "sleep_score": ("INTEGER", 87),
    "average_spo2": ("FLOAT", 95.0),
    "lowest_spo2": ("FLOAT", 90.0),
    "hrv_last_night_avg": ("FLOAT", 45.0),
    "hrv_weekly_avg": ("FLOAT", 42.0),
    "hrv_status": ("TEXT", "BALANCED"),
    "resting_heart_rate": ("INTEGER", 50),
    "body_battery_high": ("INTEGER", 88),
    "sleep_need_minutes": ("INTEGER", 470),
}

# The four columns garmy 2.0.0's localdb schema does not create. This is the
# real-world defect shape: a `daily_health_metrics` table missing exactly
# these, which the old static SLEEP_QUERY crashed against.
GARMY_2_0_0_MISSING = {"avg_sleep_stress", "sleep_score", "lowest_spo2", "sleep_need_minutes"}


def make_db(path, present_columns):
    """Create daily_health_metrics with only `present_columns`, seeded with
    one row from ALL_COLUMNS, mimicking a real garmy schema (a superset or
    subset of the columns our field map wants)."""
    conn = sqlite3.connect(str(path))
    cols_sql = ", ".join(f"{name} {ALL_COLUMNS[name][0]}" for name in present_columns)
    conn.execute(f"CREATE TABLE daily_health_metrics ({cols_sql})")
    placeholders = ", ".join("?" for _ in present_columns)
    values = [ALL_COLUMNS[name][1] for name in present_columns]
    conn.execute(
        f"INSERT INTO daily_health_metrics ({', '.join(present_columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


class BuildSleepQueryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_all_columns_present_returns_real_values_for_every_field(self):
        path = Path(self.dir.name) / "full.db"
        conn = make_db(path, list(ALL_COLUMNS))
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        self.assertEqual(columns, set(ALL_COLUMNS))

        query = server.build_sleep_query(columns)
        row = conn.execute(query).fetchone()
        self.assertIsNotNone(row)
        record = dict(row)

        self.assertEqual(record["calendarDate"], "2026-08-24")
        self.assertEqual(record["deepSleepSeconds"], round(1.5 * 3600))
        self.assertEqual(record["lightSleepSeconds"], round(6.0 * 3600))
        self.assertEqual(record["remSleepSeconds"], round(1.25 * 3600))
        self.assertEqual(record["awakeSleepSeconds"], round(0.5 * 3600))
        self.assertEqual(record["averageRespiration"], 15.5)
        self.assertEqual(record["lowestRespiration"], 11.0)
        self.assertEqual(record["avgSleepStress"], 22)
        self.assertEqual(record["sleep_score"], 87)
        self.assertEqual(record["average_spo2"], 95.0)
        self.assertEqual(record["lowest_spo2"], 90.0)
        self.assertEqual(record["hrvOvernight"], 45.0)
        self.assertEqual(record["hrvWeeklyAvg"], 42.0)
        self.assertEqual(record["hrvStatus"], "BALANCED")
        self.assertEqual(record["restingHr"], 50)
        self.assertEqual(record["bodyBatteryHigh"], 88)
        self.assertEqual(record["sleepNeedMinutes"], 470)

    def test_garmy_2_0_0_shape_executes_without_error_and_nulls_missing_fields(self):
        """Reproduces the real defect: a daily_health_metrics table shaped
        like garmy 2.0.0's localdb output, missing avg_sleep_stress,
        sleep_score, lowest_spo2, and sleep_need_minutes. The old static
        SLEEP_QUERY raised sqlite3.OperationalError against this shape; the
        dynamic query must execute cleanly and null out just those fields.
        """
        present = [c for c in ALL_COLUMNS if c not in GARMY_2_0_0_MISSING]
        path = Path(self.dir.name) / "garmy2.db"
        conn = make_db(path, present)
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        self.assertEqual(columns, set(present))
        for missing in GARMY_2_0_0_MISSING:
            self.assertNotIn(missing, columns)

        query = server.build_sleep_query(columns)
        # This is the assertion that fails against the old static SLEEP_QUERY
        # (sqlite3.OperationalError: no such column: avg_sleep_stress).
        row = conn.execute(query).fetchone()
        self.assertIsNotNone(row)
        record = dict(row)

        # The four columns garmy 2.0.0 doesn't create come back NULL/None...
        self.assertIsNone(record["avgSleepStress"])
        self.assertIsNone(record["sleep_score"])
        self.assertIsNone(record["lowest_spo2"])
        self.assertIsNone(record["sleepNeedMinutes"])

        # ...while every field backed by a present column still carries its
        # real value.
        self.assertEqual(record["calendarDate"], "2026-08-24")
        self.assertEqual(record["deepSleepSeconds"], round(1.5 * 3600))
        self.assertEqual(record["remSleepSeconds"], round(1.25 * 3600))
        self.assertEqual(record["hrvOvernight"], 45.0)
        self.assertEqual(record["average_spo2"], 95.0)
        self.assertEqual(record["restingHr"], 50)

    def test_presence_filter_omitted_when_none_of_its_columns_exist(self):
        # A schema with none of deep/light/rem sleep hours at all: the "has
        # some sleep data" filter must not reference columns that don't
        # exist, and the query must still run (returning the lone row).
        present = [
            c
            for c in ALL_COLUMNS
            if c not in {"deep_sleep_hours", "light_sleep_hours", "rem_sleep_hours"}
        ]
        path = Path(self.dir.name) / "no_presence_cols.db"
        conn = make_db(path, present)
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        query = server.build_sleep_query(columns)
        self.assertNotIn("deep_sleep_hours", query)
        self.assertNotIn("light_sleep_hours IS NOT NULL", query)

        row = conn.execute(query).fetchone()
        self.assertIsNotNone(row)


class ShapeSleepRowTest(unittest.TestCase):
    """Covers the spo2SleepSummary/sleepScores response-shaping behavior
    when their source columns are absent from the schema (NULL AS <alias>)
    rather than merely NULL-valued."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_spo2_and_sleep_score_absent_when_source_columns_missing(self):
        present = [c for c in ALL_COLUMNS if c not in GARMY_2_0_0_MISSING]
        path = Path(self.dir.name) / "shape.db"
        conn = make_db(path, present)
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        query = server.build_sleep_query(columns)
        row = conn.execute(query).fetchone()

        record = server.shape_sleep_row(row)

        # lowest_spo2 is missing -> spo2SleepSummary has only averageSPO2.
        self.assertIn("spo2SleepSummary", record)
        self.assertEqual(record["spo2SleepSummary"], {"averageSPO2": 95.0})
        self.assertNotIn("lowestSPO2", record["spo2SleepSummary"])

        # sleep_score is missing entirely -> no sleepScores key at all.
        self.assertNotIn("sleepScores", record)

        # The raw source keys are never leaked into the shaped record.
        self.assertNotIn("average_spo2", record)
        self.assertNotIn("lowest_spo2", record)
        self.assertNotIn("sleep_score", record)

    def test_spo2_summary_absent_entirely_when_both_spo2_columns_missing(self):
        present = [
            c for c in ALL_COLUMNS if c not in {"average_spo2", "lowest_spo2", "sleep_score"}
        ]
        path = Path(self.dir.name) / "no_spo2.db"
        conn = make_db(path, present)
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        query = server.build_sleep_query(columns)
        row = conn.execute(query).fetchone()

        record = server.shape_sleep_row(row)

        self.assertNotIn("spo2SleepSummary", record)
        self.assertNotIn("sleepScores", record)

    def test_matches_todays_behavior_when_columns_exist_but_values_are_null(self):
        """A column that exists but holds NULL must produce exactly the same
        shaped output as a column that doesn't exist at all — the frontend
        must not be able to tell the difference."""
        path = Path(self.dir.name) / "null_values.db"
        conn = sqlite3.connect(str(path))
        cols_sql = ", ".join(f"{name} {ALL_COLUMNS[name][0]}" for name in ALL_COLUMNS)
        conn.execute(f"CREATE TABLE daily_health_metrics ({cols_sql})")
        # Insert a row with every column present but the four garmy-2.0.0
        # fields explicitly NULL.
        non_null = [c for c in ALL_COLUMNS if c not in GARMY_2_0_0_MISSING]
        placeholders = ", ".join("?" for _ in non_null)
        conn.execute(
            f"INSERT INTO daily_health_metrics ({', '.join(non_null)}) VALUES ({placeholders})",
            [ALL_COLUMNS[c][1] for c in non_null],
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)

        columns = server.table_columns(conn, "daily_health_metrics")
        self.assertEqual(columns, set(ALL_COLUMNS))  # all columns exist, just NULL-valued
        query = server.build_sleep_query(columns)
        row = conn.execute(query).fetchone()
        record = server.shape_sleep_row(row)

        self.assertIn("spo2SleepSummary", record)
        self.assertEqual(record["spo2SleepSummary"], {"averageSPO2": 95.0})
        self.assertNotIn("sleepScores", record)


if __name__ == "__main__":
    unittest.main()
