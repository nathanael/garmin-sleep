"""SQLite access for health.db.

WAL so dashboard reads are not blocked by an in-flight sync write.
"""

import sqlite3

BUSY_TIMEOUT_MS = 5000

# Column -> SQLite type. garmy 2.0.0's localdb SyncManager does not create
# any of these on daily_health_metrics, even though garmy's sleep API
# returns all four (sleep_scores["overall"]["value"], avg_sleep_stress,
# lowest_sp_o2_value, sleep_need["baseline"]) -- see sync.py's
# extract_sleep_metrics(). Centralized here so both server.py (on startup,
# to upgrade a pre-existing database) and sync.py (before its per-day
# backfill loop) can call the same migration.
SLEEP_METRIC_COLUMNS = {
    "sleep_score": "INTEGER",
    "avg_sleep_stress": "REAL",
    "lowest_spo2": "REAL",
    "sleep_need_minutes": "INTEGER",
}


def ensure_sleep_metric_columns(conn):
    """Add sleep_score, avg_sleep_stress, lowest_spo2, and
    sleep_need_minutes to daily_health_metrics if they aren't there.

    Idempotent and additive only: checks the live schema via
    PRAGMA table_info and issues ALTER TABLE ... ADD COLUMN only for
    whichever of the four are actually missing. Never touches a column or
    row that already exists, and never drops or deletes anything. Safe to
    call on every server startup and every sync run, regardless of which
    garmy version created (or last touched) the database.

    A no-op if daily_health_metrics doesn't exist yet at all (e.g. a fresh
    install before the first sync has created the table) -- there is
    nothing to migrate until the table exists, and a later call (the next
    server startup, or the next sync.py run, which creates the table
    itself via SyncManager before reaching this call) will pick it up.
    """
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'daily_health_metrics'"
    ).fetchone()
    if not table_exists:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(daily_health_metrics)")}
    for column, sqltype in SLEEP_METRIC_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE daily_health_metrics ADD COLUMN {column} {sqltype}")
    conn.commit()


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
