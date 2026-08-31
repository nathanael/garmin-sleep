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


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--range":
        start_date = date.fromisoformat(sys.argv[2])
        end_date = date.fromisoformat(sys.argv[3])
    elif len(sys.argv) > 1:
        days = int(sys.argv[1])
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
    else:
        days = days_since_last_sync()
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

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
