#!/usr/bin/env python3
"""Sync Garmin data using saved OAuth tokens (no credentials prompt)."""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from garmy import AuthClient, APIClient
from garmy.localdb.sync import SyncManager
from garmy.localdb.progress import ProgressReporter
from garmy.localdb.config import LocalDBConfig
from garmy.localdb.models import MetricType

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "garmin-sleep-upgrade"))
import db as dbmod  # noqa: E402

DB_PATH = REPO_ROOT / "health.db"


def extract_sleep_metrics(summary):
    """Pull the four dashboard metrics out of a sleep-summary-shaped object.

    `summary` is whatever `api.metrics.get("sleep").get(some_date).sleep_summary`
    returns from garmy: an object exposing `.sleep_scores` (a dict keyed by
    metric name -- the score itself is `sleep_scores["overall"]["value"]`),
    `.avg_sleep_stress`, `.lowest_sp_o2_value` (garmy's spelling: sp_o2, not
    spo2), and `.sleep_need` (a dict with a "baseline" key, in minutes).

    Pure and side-effect free -- no I/O, no network -- so it's testable
    without a live Garmin account: pass any object duck-typed the same way
    (including a plain SimpleNamespace built in a test), or None.

    Resilient per field: `summary` itself being None, missing an attribute
    entirely, or having a field in an unexpected shape (e.g. sleep_scores
    not a dict, or missing "overall"/"value") produces None for just that
    field rather than raising -- one malformed field in a day's response
    must not blank out the other three.

    Returns a dict with keys sleep_score, avg_sleep_stress, lowest_spo2,
    sleep_need_minutes -- always all four, any of which may be None.
    """
    result = {
        "sleep_score": None,
        "avg_sleep_stress": None,
        "lowest_spo2": None,
        "sleep_need_minutes": None,
    }

    try:
        sleep_scores = getattr(summary, "sleep_scores", None)
        overall = sleep_scores.get("overall") if isinstance(sleep_scores, dict) else None
        if isinstance(overall, dict) and "value" in overall:
            result["sleep_score"] = overall["value"]
    except Exception:
        pass

    try:
        result["avg_sleep_stress"] = getattr(summary, "avg_sleep_stress", None)
    except Exception:
        pass

    try:
        result["lowest_spo2"] = getattr(summary, "lowest_sp_o2_value", None)
    except Exception:
        pass

    try:
        need = getattr(summary, "sleep_need", None)
        if isinstance(need, dict) and "baseline" in need:
            result["sleep_need_minutes"] = need["baseline"]
    except Exception:
        pass

    return result


def days_since_last_sync():
    """Check the DB and return the number of days missing since the last synced date."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        cur = db.cursor()
        cur.execute("SELECT MAX(metric_date) FROM daily_health_metrics")
        latest = cur.fetchone()[0]
        db.close()
        if latest:
            last = date.fromisoformat(latest)
            gap = (date.today() - last).days
            return max(gap, 1)  # always sync at least today
    except Exception:
        pass
    return 7  # fallback if DB is empty or unreadable


def earliest_missing_sleep(db_path=None, within_days=14):
    """Oldest recent day whose sleep never landed, or None if all are present.

    This is what the scheduled runs are actually chasing: the watch often
    uploads a night hours after the first sync of the morning.

    Deliberately keyed on missing sleep rather than on failed sync_status
    rows. Some metrics fail permanently -- Garmin returns null samples for
    heart_rate and body_battery, which the timeseries table rejects with a
    NOT NULL constraint -- so those rows are rewritten as 'failed' on every
    single run and never clear. A status-based window is therefore pinned
    open forever, widening every sync to a fortnight even when every night's
    sleep is already recorded. Missing sleep, by contrast, resolves itself
    once the night uploads, and any day that never resolves ages out of the
    window on its own.

    Only considers days that already exist in the table, so it never invents
    a backfill for dates that were never synced at all.
    """
    try:
        conn = sqlite3.connect(str(db_path or DB_PATH))
        row = conn.execute(
            "SELECT MIN(metric_date) FROM daily_health_metrics "
            "WHERE sleep_duration_hours IS NULL "
            "AND metric_date >= date('now', ?)",
            (f"-{within_days} days",),
        ).fetchone()[0]
        conn.close()
        return date.fromisoformat(row) if row else None
    except Exception:
        return None


def todays_sleep_recorded(db_path=None):
    """True when today's row already carries a sleep duration."""
    try:
        conn = sqlite3.connect(str(db_path or DB_PATH))
        row = conn.execute(
            "SELECT sleep_duration_hours FROM daily_health_metrics "
            "WHERE metric_date = ?",
            (date.today().isoformat(),),
        ).fetchone()
        conn.close()
        return bool(row and row[0] is not None)
    except Exception:
        return False


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--range":
        start_date = date.fromisoformat(sys.argv[2])
        end_date = date.fromisoformat(sys.argv[3])
    elif len(sys.argv) > 1:
        days = int(sys.argv[1])
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
    else:
        # Scheduled mode runs eleven times a day to catch a late upload. Once
        # today's night is in and no recent night is missing, there is nothing
        # left to chase, so skip the whole fetch rather than re-pulling a
        # fortnight from Garmin ten more times before noon.
        missing = earliest_missing_sleep()
        if missing is None and todays_sleep_recorded():
            print("Sleep is already recorded for today and every recent night; nothing to sync.")
            return

        days = days_since_last_sync()
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        # A night the watch uploaded late would otherwise never be picked up,
        # since MAX(metric_date) is always fresh.
        if missing and missing < start_date:
            start_date = missing

    auth = AuthClient()
    if not auth.is_authenticated:
        if auth.needs_refresh:
            print("Token expired, refreshing...")
            auth.refresh_tokens()
            print("Token refreshed successfully")
        else:
            print("Not authenticated. Run: .venv/bin/python login.py")
            sys.exit(1)

    api = APIClient(auth_client=auth)
    manager = SyncManager(
        db_path=DB_PATH,
        config=LocalDBConfig(),
        progress_reporter=ProgressReporter(use_tqdm=False),
    )
    manager.api_client = api

    from garmy.localdb.sync import ActivitiesIterator
    manager.activities_iterator = ActivitiesIterator(api, manager.config.sync, manager.progress)
    manager.activities_iterator.initialize()

    # Reset sync status for the range so stale data gets refreshed
    db = sqlite3.connect(str(DB_PATH))
    db.execute(
        "DELETE FROM sync_status WHERE sync_date >= ? AND sync_date <= ? AND user_id = 1",
        (start_date.isoformat(), end_date.isoformat()),
    )
    db.commit()
    db.close()

    days = (end_date - start_date).days + 1
    print(f"Syncing {start_date} to {end_date} ({days} day{'s' if days != 1 else ''})")
    stats = manager.sync_range(user_id=1, start_date=start_date, end_date=end_date, metrics=list(MetricType))
    print(f"Done: {stats['completed']} completed, {stats['skipped']} skipped, {stats['failed']} failed")

    # Backfill sleep_score, avg_sleep_stress, lowest_spo2, and
    # sleep_need_minutes from the sleep API. garmy's SyncManager (run above)
    # never creates these columns, so make sure they exist before writing to
    # them -- this upgrades a database created by any garmy version,
    # including one that's been around since before this backfill existed.
    db = sqlite3.connect(str(DB_PATH))
    dbmod.ensure_sleep_metric_columns(db)

    sleep_metric = api.metrics.get("sleep")
    updated = 0
    current = start_date
    while current <= end_date:
        try:
            sleep = sleep_metric.get(current)
            metrics = extract_sleep_metrics(sleep.sleep_summary)
            db.execute(
                """UPDATE daily_health_metrics
                   SET sleep_score = ?, avg_sleep_stress = ?, lowest_spo2 = ?, sleep_need_minutes = ?
                   WHERE user_id = 1 AND metric_date = ?""",
                (
                    metrics["sleep_score"],
                    metrics["avg_sleep_stress"],
                    metrics["lowest_spo2"],
                    metrics["sleep_need_minutes"],
                    current.isoformat(),
                ),
            )
            if any(value is not None for value in metrics.values()):
                updated += 1
        except Exception:
            # A per-day failure (network error, missing sleep record, etc.)
            # must not abort the rest of the range.
            pass
        current += timedelta(days=1)
    db.commit()
    if updated:
        print(f"Sleep metrics: updated {updated} day{'s' if updated != 1 else ''}")
    db.close()

if __name__ == "__main__":
    main()
