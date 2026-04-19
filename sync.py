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


def main():
    # explicit arg overrides auto-detection
    if len(sys.argv) > 1:
        days = int(sys.argv[1])
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

    print(f"Syncing {start_date} to {end_date} ({days} day{'s' if days != 1 else ''})")
    stats = manager.sync_range(user_id=1, start_date=start_date, end_date=end_date, metrics=list(MetricType))
    print(f"Done: {stats['completed']} completed, {stats['skipped']} skipped, {stats['failed']} failed")

if __name__ == "__main__":
    main()
