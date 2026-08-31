import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import db  # noqa: E402


class ConnectTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "test.db"
        seed = sqlite3.connect(str(self.path))
        seed.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        seed.execute("INSERT INTO t (v) VALUES ('before')")
        seed.commit()
        seed.close()

    def test_enables_wal(self):
        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_sets_busy_timeout(self):
        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_reader_is_not_blocked_by_an_open_writer(self):
        writer = db.connect(self.path)
        self.addCleanup(writer.close)
        reader = db.connect(self.path, isolation_level=None)
        self.addCleanup(reader.close)

        # Reader holds an open transaction spanning the writer's commit
        reader.execute("BEGIN")
        reader.execute("SELECT v FROM t").fetchall()

        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (v) VALUES ('during')")

        # WAL allows the writer to commit even while reader holds SHARED lock.
        # Under DELETE mode, this would raise "database is locked" because the
        # writer needs EXCLUSIVE lock at commit but reader holds SHARED.
        writer.commit()

        # Reader sees the pre-commit snapshot due to WAL isolation.
        rows = reader.execute("SELECT v FROM t").fetchall()
        self.assertEqual(rows, [("before",)])

        reader.commit()
        self.assertEqual(len(reader.execute("SELECT v FROM t").fetchall()), 2)

    def test_connect_survives_lock_during_journal_mode_upgrade(self):
        """First sync run: health.db is still in its default (non-WAL) journal
        mode when db.connect() tries to upgrade it, and a writer is mid
        BEGIN IMMEDIATE. PRAGMA busy_timeout does not cover PRAGMA
        journal_mode = WAL, so that pragma can raise "database is locked"
        immediately (not after waiting out busy_timeout). db.connect() must
        still return a usable connection rather than propagating that error.
        """
        precondition_conn = sqlite3.connect(str(self.path))
        self.addCleanup(precondition_conn.close)
        mode = precondition_conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "delete")  # precondition: not WAL yet

        writer = sqlite3.connect(str(self.path), isolation_level=None)
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (v) VALUES ('during')")

        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT 1").fetchone(), (1,))

        writer.commit()


class EnsureSleepMetricColumnsTest(unittest.TestCase):
    """garmy 2.0.0's localdb SyncManager never creates sleep_score,
    avg_sleep_stress, lowest_spo2, or sleep_need_minutes on
    daily_health_metrics. db.ensure_sleep_metric_columns() must add exactly
    the ones missing, leave the rest of the schema and every existing row
    untouched, and be safe to call more than once.
    """

    FOUR_COLUMNS = {"sleep_score", "avg_sleep_stress", "lowest_spo2", "sleep_need_minutes"}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "test.db"

    def _columns(self, conn):
        return {row[1] for row in conn.execute("PRAGMA table_info(daily_health_metrics)")}

    def test_adds_exactly_the_missing_columns(self):
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE daily_health_metrics (user_id INTEGER, metric_date DATE, deep_sleep_hours FLOAT)"
        )
        conn.commit()

        db.ensure_sleep_metric_columns(conn)

        columns = self._columns(conn)
        self.assertEqual(
            columns, {"user_id", "metric_date", "deep_sleep_hours"} | self.FOUR_COLUMNS
        )

    def test_only_adds_columns_that_are_actually_absent(self):
        """A table that already has *some* of the four (e.g. an earlier,
        partial migration, or a future garmy version that creates one but
        not the others) must not have that column touched or duplicated --
        SQLite raises on ADD COLUMN of a name that already exists, which
        would be a bug for any caller running this against a mixed schema.
        """
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE daily_health_metrics ("
            "user_id INTEGER, metric_date DATE, sleep_score INTEGER)"
        )
        conn.execute(
            "INSERT INTO daily_health_metrics (user_id, metric_date, sleep_score) VALUES (1, '2026-08-01', 85)"
        )
        conn.commit()

        db.ensure_sleep_metric_columns(conn)  # must not raise

        columns = self._columns(conn)
        self.assertEqual(columns, {"user_id", "metric_date"} | self.FOUR_COLUMNS)
        row = conn.execute(
            "SELECT sleep_score, avg_sleep_stress, lowest_spo2, sleep_need_minutes "
            "FROM daily_health_metrics WHERE user_id = 1"
        ).fetchone()
        # Existing value in the pre-existing column is untouched...
        self.assertEqual(row[0], 85)
        # ...and the newly added columns are NULL on the pre-existing row,
        # not some default.
        self.assertEqual(row[1:], (None, None, None))

    def test_idempotent_second_call_is_a_no_op(self):
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE daily_health_metrics (user_id INTEGER, metric_date DATE)")
        conn.execute(
            "INSERT INTO daily_health_metrics (user_id, metric_date) VALUES (1, '2026-08-01')"
        )
        conn.commit()

        db.ensure_sleep_metric_columns(conn)
        columns_after_first = self._columns(conn)

        db.ensure_sleep_metric_columns(conn)  # must not raise "duplicate column"
        columns_after_second = self._columns(conn)

        self.assertEqual(columns_after_first, columns_after_second)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_health_metrics").fetchone()[0], 1)

    def test_database_that_already_has_all_four_columns_is_untouched(self):
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)
        conn.execute(
            "CREATE TABLE daily_health_metrics ("
            "user_id INTEGER, metric_date DATE, sleep_score INTEGER, "
            "avg_sleep_stress REAL, lowest_spo2 REAL, sleep_need_minutes INTEGER)"
        )
        conn.execute(
            "INSERT INTO daily_health_metrics VALUES (1, '2026-08-01', 85, 17.0, 89, 470)"
        )
        conn.commit()
        columns_before = self._columns(conn)
        row_before = conn.execute("SELECT * FROM daily_health_metrics").fetchone()

        db.ensure_sleep_metric_columns(conn)

        self.assertEqual(self._columns(conn), columns_before)
        self.assertEqual(conn.execute("SELECT * FROM daily_health_metrics").fetchone(), row_before)

    def test_noop_when_table_does_not_exist_yet(self):
        conn = sqlite3.connect(str(self.path))
        self.addCleanup(conn.close)

        db.ensure_sleep_metric_columns(conn)  # must not raise

        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'daily_health_metrics'"
        ).fetchone()
        self.assertIsNone(exists)


if __name__ == "__main__":
    unittest.main()
