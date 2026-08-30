"""SQLite access for health.db.

WAL so dashboard reads are not blocked by an in-flight sync write.
"""

import sqlite3

BUSY_TIMEOUT_MS = 5000


def connect(path):
    """Open health.db with WAL and a busy timeout.

    journal_mode persists in the file, so re-applying it per open is cheap
    and covers the first run, where stage 1 creates the database.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
