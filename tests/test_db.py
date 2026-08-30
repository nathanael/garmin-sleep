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
        reader = db.connect(self.path)
        self.addCleanup(reader.close)

        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (v) VALUES ('during')")

        # WAL lets the reader see the pre-write snapshot instead of erroring.
        rows = reader.execute("SELECT v FROM t").fetchall()
        self.assertEqual(rows, [("before",)])

        writer.commit()
        self.assertEqual(len(reader.execute("SELECT v FROM t").fetchall()), 2)


if __name__ == "__main__":
    unittest.main()
