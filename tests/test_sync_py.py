"""Tests for sync.py's has_sleep_need_column() guard (IMPORTANT 5).

Only imports sync.py as a module -- that runs no Garmin code (main() is
gated by `if __name__ == "__main__"`), so this never touches the network
or a real account. Never call sync.main() from a test; see CLAUDE.md /
the task brief for why sync.py must never actually run in this repo.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import sync  # noqa: E402


class HasSleepNeedColumnTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "test.db"

    def _connect(self, extra_columns=""):
        db = sqlite3.connect(str(self.path))
        db.execute(f"CREATE TABLE daily_health_metrics (user_id INTEGER, metric_date DATE{extra_columns})")
        return db

    def test_true_when_column_present(self):
        db = self._connect(", sleep_need_minutes INTEGER")
        self.addCleanup(db.close)
        self.assertTrue(sync.has_sleep_need_column(db))

    def test_false_on_garmy_2_0_0_shape_without_the_column(self):
        # garmy 2.0.0's daily_health_metrics has no sleep_need_minutes
        # column at all -- this is the exact case that used to make
        # sync.py's backfill loop call the Garmin sleep API once per day
        # in the range only to have every UPDATE raise and get silently
        # swallowed.
        db = self._connect(", deep_sleep_hours FLOAT")
        self.addCleanup(db.close)
        self.assertFalse(sync.has_sleep_need_column(db))

    def test_false_on_empty_table_with_no_columns_at_all(self):
        db = sqlite3.connect(str(self.path))
        self.addCleanup(db.close)
        db.execute("CREATE TABLE daily_health_metrics (user_id INTEGER)")
        self.assertFalse(sync.has_sleep_need_column(db))


if __name__ == "__main__":
    unittest.main()
