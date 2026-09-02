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

DB_PATH = Path(__file__).parent / "health.db"


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


def earliest_recent_failure():
    """Return the oldest failed sync date within the last 14 days, if any."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        cur = db.cursor()
        cur.execute(
            "SELECT MIN(sync_date) FROM sync_status "
            "WHERE status = 'failed' AND sync_date >= date('now', '-14 days')"
        )
        row = cur.fetchone()[0]
        db.close()
        return date.fromisoformat(row) if row else None
    except Exception:
        return None


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
        # Failed days (e.g. sleep not yet uploaded from watch at 7am) would
        # otherwise never be retried, since MAX(metric_date) is always fresh.
        failed = earliest_recent_failure()
        if failed and failed < start_date:
            start_date = failed

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

    # Backfill sleep_need from sleep API
    sleep_metric = api.metrics.get("sleep")
    db = sqlite3.connect(str(DB_PATH))
    updated = 0
    current = start_date
    while current <= end_date:
        try:
            sleep = sleep_metric.get(current)
            need = getattr(sleep.sleep_summary, "sleep_need", None)
            if need and "baseline" in need:
                db.execute(
                    "UPDATE daily_health_metrics SET sleep_need_minutes = ? WHERE user_id = 1 AND metric_date = ?",
                    (need["baseline"], current.isoformat()),
                )
                updated += 1
        except Exception:
            pass
        current += timedelta(days=1)
    db.commit()
    db.close()
    if updated:
        print(f"Sleep need: updated {updated} day{'s' if updated != 1 else ''}")

if __name__ == "__main__":
    main()
