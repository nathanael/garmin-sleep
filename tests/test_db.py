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
        mode = sqlite3.connect(str(self.path)).execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "delete")  # precondition: not WAL yet

        writer = sqlite3.connect(str(self.path), isolation_level=None)
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (v) VALUES ('during')")

        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT 1").fetchone(), (1,))

        writer.commit()


if __name__ == "__main__":
    unittest.main()
