"""SQLite access for health.db.

WAL so dashboard reads are not blocked by an in-flight sync write.
"""

import sqlite3

BUSY_TIMEOUT_MS = 5000


def connect(path, isolation_level="DEFERRED"):
    """Open health.db with WAL and a busy timeout.

    journal_mode persists in the file, so re-applying it per open is cheap
    and covers the first run, where stage 1 creates the database.

    isolation_level controls sqlite3's transaction handling; pass None for
    full manual control via explicit BEGIN/COMMIT.
    """
    conn = sqlite3.connect(str(path), isolation_level=isolation_level)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        # PRAGMA journal_mode = WAL needs an exclusive lock to rewrite the
        # database header, and busy_timeout does not cover that: on a
        # non-WAL database with a concurrent writer (e.g. first sync run,
        # before anyone has set WAL yet) this can raise "database is
        # locked" immediately instead of waiting out the timeout. The
        # connection is still perfectly usable in whatever journal mode is
        # already active; journal_mode persists in the file once any
        # connection successfully sets WAL, so this is a one-time race.
        pass
    return conn
