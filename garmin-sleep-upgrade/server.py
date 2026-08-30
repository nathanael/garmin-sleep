#!/usr/bin/env python3
"""HTTP server for the sleep analyzer. Run with: .venv/bin/python garmin-sleep-upgrade/server.py"""

import json
import sqlite3
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import db
import sync_jobs
from garmy import AuthClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "health.db"
SYNC_SCRIPT = PROJECT_ROOT / "sync.py"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

auth = AuthClient()
mfa_state = {}  # temporary storage for MFA flow

SLEEP_QUERY = """
SELECT
    metric_date AS calendarDate,
    CAST(ROUND(deep_sleep_hours * 3600) AS INTEGER) AS deepSleepSeconds,
    CAST(ROUND(light_sleep_hours * 3600) AS INTEGER) AS lightSleepSeconds,
    CAST(ROUND(rem_sleep_hours * 3600) AS INTEGER) AS remSleepSeconds,
    CAST(ROUND(awake_hours * 3600) AS INTEGER) AS awakeSleepSeconds,
    avg_sleep_respiration_value AS averageRespiration,
    lowest_respiration_value AS lowestRespiration,
    avg_sleep_stress AS avgSleepStress,
    sleep_score,
    average_spo2,
    lowest_spo2,
    hrv_last_night_avg AS hrvOvernight,
    hrv_weekly_avg AS hrvWeeklyAvg,
    hrv_status AS hrvStatus,
    resting_heart_rate AS restingHr,
    body_battery_high AS bodyBatteryHigh,
    sleep_need_minutes AS sleepNeedMinutes
FROM daily_health_metrics
WHERE user_id = 1
  AND (deep_sleep_hours IS NOT NULL OR light_sleep_hours IS NOT NULL OR rem_sleep_hours IS NOT NULL)
{}ORDER BY metric_date
"""


def json_response(handler, data, status=200):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length)) if length else {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).resolve().parent), **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/sleep":
            self.serve_sleep_api(parsed.query)
        elif parsed.path == "/api/auth/status":
            self.serve_auth_status()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        routes = {
            "/api/sync": self.serve_sync_api,
            "/api/auth/login": self.serve_auth_login,
            "/api/auth/mfa": self.serve_auth_mfa,
            "/api/auth/logout": self.serve_auth_logout,
        }
        handler = routes.get(parsed.path)
        if handler:
            handler()
        else:
            self.send_error(404)

    # --- Auth endpoints ---

    def serve_auth_status(self):
        if not auth.is_authenticated and auth.needs_refresh:
            try:
                auth.refresh_tokens()
            except Exception:
                pass
        json_response(self, {"authenticated": auth.is_authenticated})

    def serve_auth_login(self):
        global mfa_state
        body = read_body(self)
        email = body.get("email", "")
        password = body.get("password", "")
        if not email or not password:
            json_response(self, {"ok": False, "error": "Email and password required"}, 400)
            return
        try:
            result = auth.login(email, password, return_on_mfa=True)
            if isinstance(result, tuple) and result[0] == "needs_mfa":
                mfa_state = result[1]
                json_response(self, {"ok": True, "mfa_required": True})
            else:
                mfa_state = {}
                json_response(self, {"ok": True, "mfa_required": False})
        except Exception as e:
            json_response(self, {"ok": False, "error": str(e)}, 401)

    def serve_auth_mfa(self):
        global mfa_state
        body = read_body(self)
        code = body.get("code", "")
        if not code or not mfa_state:
            json_response(self, {"ok": False, "error": "MFA code required"}, 400)
            return
        try:
            auth.resume_login(code, mfa_state)
            mfa_state = {}
            json_response(self, {"ok": True})
        except Exception as e:
            json_response(self, {"ok": False, "error": str(e)}, 401)

    def serve_auth_logout(self):
        auth.logout()
        json_response(self, {"ok": True})

    # --- Sync endpoint ---

    def serve_sync_api(self):
        body = read_body(self)
        start_date = body.get("start")
        end_date = body.get("end")
        days = body.get("days", 7)

        python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        if start_date and end_date:
            cmd = [python, str(SYNC_SCRIPT), "--range", start_date, end_date]
        else:
            cmd = [python, str(SYNC_SCRIPT), str(days)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            resp = {
                "ok": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": (result.stdout.strip() + " " + result.stderr.strip()).strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            resp = {"ok": False, "output": "", "error": "Sync timed out (10 min)"}

        json_response(self, resp)

    # --- Sleep data endpoint ---

    def serve_sleep_api(self, query_string):
        if not DB_PATH.exists():
            self.send_error(404, f"Database not found: {DB_PATH}")
            return

        params = parse_qs(query_string)
        days = None
        if "days" in params:
            try:
                days = int(params["days"][0])
            except ValueError:
                pass

        date_filter = f"  AND metric_date >= date('now', '-{days} days')\n" if days else ""
        query = SLEEP_QUERY.format(date_filter)

        conn = db.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(query).fetchall()
            records = []
            for row in rows:
                r = dict(row)
                # Nest spo2 fields as analyzer expects
                avg_spo2 = r.pop("average_spo2", None)
                low_spo2 = r.pop("lowest_spo2", None)
                spo2_obj = {}
                if avg_spo2 is not None:
                    spo2_obj["averageSPO2"] = avg_spo2
                if low_spo2 is not None:
                    spo2_obj["lowestSPO2"] = low_spo2
                if spo2_obj:
                    r["spo2SleepSummary"] = spo2_obj
                # Nest sleep score as analyzer expects
                score = r.pop("sleep_score", None)
                if score is not None:
                    r["sleepScores"] = {"overallScore": score}
                records.append(r)
            json_response(self, records)
        finally:
            conn.close()

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8484))
    server = HTTPServer(("", port), Handler)
    print(f"Garmin Sleep Love → http://localhost:{port}")
    print(f"Database: {DB_PATH} ({'found' if DB_PATH.exists() else 'NOT FOUND'})")
    print(f"Authenticated: {auth.is_authenticated}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
