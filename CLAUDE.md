# Garmy Project

## Quick Commands

- **Run server**: `.venv/bin/python garmin-sleep-upgrade/server.py` (serves on http://localhost:8484)
- **Sync data**: `.venv/bin/python sync.py [days]`
- **Login**: `.venv/bin/python login.py`

## Project Structure

- `garmin-sleep-upgrade/` — Sleep Analyzer dashboard (server.py, index.html, garmin_sleep_analyzer.jsx)
- `health.db` — SQLite database with synced Garmin health data
- `sync.py` — Syncs data from Garmin Connect to health.db
- `.venv/` — Python 3.14 virtual environment with garmy package
