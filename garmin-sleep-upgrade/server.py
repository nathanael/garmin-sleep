#!/usr/bin/env python3
"""HTTP server for the sleep analyzer. Run with: .venv/bin/python garmin-sleep-upgrade/server.py"""

import json
import sqlite3
import sys
import threading
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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

# Guards `mfa_state` and every call into `auth` (login/resume_login/logout/
# refresh_tokens/is_authenticated/needs_refresh). Under the old single-
# threaded HTTPServer only one request was ever in flight, so this was
# implicitly safe; ThreadingHTTPServer makes concurrent requests possible,
# and garmy.AuthClient's internal thread-safety is unknown, so we serialize
# access at this boundary instead. This deliberately holds the lock across
# the network call inside auth.login()/resume_login()/logout()/
# refresh_tokens() -- there's no way to safely serialize calls into an
# opaque client object without covering the call itself, so two concurrent
# auth requests will block on each other rather than run in parallel. That
# is an acceptable tradeoff for a single-user local tool where correctness
# under a rare double-submit matters more than auth-endpoint throughput.
AUTH_LOCK = threading.Lock()

RUNNER = sync_jobs.JobRunner(
    str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable,
    str(SYNC_SCRIPT),
)

# /api/sleep field map: (source_column, sql_expression, output_alias).
#
# garmy's `localdb` schema has changed columns across versions (garmy 2.0.0
# dropped avg_sleep_stress, sleep_score, lowest_spo2, and sleep_need_minutes
# from daily_health_metrics), and will likely change again. build_sleep_query()
# checks each source_column against the table's live schema and substitutes
# NULL AS <alias> for anything missing, so the endpoint keeps returning its
# usual response shape instead of raising sqlite3.OperationalError.
SLEEP_FIELDS = [
    ("metric_date", "metric_date", "calendarDate"),
    ("deep_sleep_hours", "CAST(ROUND(deep_sleep_hours * 3600) AS INTEGER)", "deepSleepSeconds"),
    ("light_sleep_hours", "CAST(ROUND(light_sleep_hours * 3600) AS INTEGER)", "lightSleepSeconds"),
    ("rem_sleep_hours", "CAST(ROUND(rem_sleep_hours * 3600) AS INTEGER)", "remSleepSeconds"),
    ("awake_hours", "CAST(ROUND(awake_hours * 3600) AS INTEGER)", "awakeSleepSeconds"),
    ("avg_sleep_respiration_value", "avg_sleep_respiration_value", "averageRespiration"),
    ("lowest_respiration_value", "lowest_respiration_value", "lowestRespiration"),
    ("avg_sleep_stress", "avg_sleep_stress", "avgSleepStress"),
    ("sleep_score", "sleep_score", "sleep_score"),
    ("average_spo2", "average_spo2", "average_spo2"),
    ("lowest_spo2", "lowest_spo2", "lowest_spo2"),
    ("hrv_last_night_avg", "hrv_last_night_avg", "hrvOvernight"),
    ("hrv_weekly_avg", "hrv_weekly_avg", "hrvWeeklyAvg"),
    ("hrv_status", "hrv_status", "hrvStatus"),
    ("resting_heart_rate", "resting_heart_rate", "restingHr"),
    ("body_battery_high", "body_battery_high", "bodyBatteryHigh"),
    ("sleep_need_minutes", "sleep_need_minutes", "sleepNeedMinutes"),
]

# Columns referenced by the "row has some sleep data" filter. Guarded the
# same way: any that don't exist are dropped out of the OR'd condition, and
# if none exist at all the whole clause is omitted.
SLEEP_PRESENCE_COLUMNS = ["deep_sleep_hours", "light_sleep_hours", "rem_sleep_hours"]

SLEEP_TABLE = "daily_health_metrics"


def table_columns(conn, table):
    """Return the set of column names that currently exist in `table`.

    `table` is always one of our own constants, never request input.
    """
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def build_sleep_query(available_columns, date_filter=""):
    """Build the /api/sleep SELECT against whatever columns actually exist.

    `available_columns` is the live set of column names on daily_health_metrics
    (from table_columns()). `date_filter` is the pre-formatted, already-safe
    "  AND metric_date >= date(...)\\n" fragment (or "") from serve_sleep_api.
    """
    available_columns = set(available_columns)

    select_list = ",\n    ".join(
        f"{expr} AS {alias}" if source in available_columns else f"NULL AS {alias}"
        for source, expr, alias in SLEEP_FIELDS
    )

    presence_conditions = [
        f"{col} IS NOT NULL" for col in SLEEP_PRESENCE_COLUMNS if col in available_columns
    ]
    presence_clause = (
        f"  AND ({' OR '.join(presence_conditions)})\n" if presence_conditions else ""
    )

    return f"""
SELECT
    {select_list}
FROM {SLEEP_TABLE}
WHERE user_id = 1
{presence_clause}{date_filter}ORDER BY calendarDate
"""


def shape_sleep_row(row):
    """Nest spo2 and sleep-score fields the way the frontend expects.

    A field reads as None here whether the DB column exists but the value is
    NULL, or the column doesn't exist and build_sleep_query() substituted
    NULL AS <alias> for it — both cases are handled identically, so a garmy
    schema that's missing a column produces the same JSON shape (key absent)
    as one that has the column with a NULL value in it.
    """
    r = dict(row)
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
    return r


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
        elif parsed.path == "/api/sync/status":
            json_response(self, RUNNER.status())
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
        with AUTH_LOCK:
            if not auth.is_authenticated and auth.needs_refresh:
                try:
                    auth.refresh_tokens()
                except Exception:
                    pass
            authenticated = auth.is_authenticated
        json_response(self, {"authenticated": authenticated})

    def serve_auth_login(self):
        global mfa_state
        body = read_body(self)
        email = body.get("email", "")
        password = body.get("password", "")
        if not email or not password:
            json_response(self, {"ok": False, "error": "Email and password required"}, 400)
            return

        with AUTH_LOCK:
            try:
                result = auth.login(email, password, return_on_mfa=True)
                if isinstance(result, tuple) and result[0] == "needs_mfa":
                    mfa_state = result[1]
                    response, status = {"ok": True, "mfa_required": True}, 200
                else:
                    mfa_state = {}
                    response, status = {"ok": True, "mfa_required": False}, 200
            except Exception as e:
                response, status = {"ok": False, "error": str(e)}, 401

        json_response(self, response, status)

    def serve_auth_mfa(self):
        global mfa_state
        body = read_body(self)
        code = body.get("code", "")

        with AUTH_LOCK:
            if not code or not mfa_state:
                response, status = {"ok": False, "error": "MFA code required"}, 400
            else:
                try:
                    auth.resume_login(code, mfa_state)
                    mfa_state = {}
                    response, status = {"ok": True}, 200
                except Exception as e:
                    response, status = {"ok": False, "error": str(e)}, 401

        json_response(self, response, status)

    def serve_auth_logout(self):
        with AUTH_LOCK:
            auth.logout()
        json_response(self, {"ok": True})

    # --- Sync endpoint ---

    def serve_sync_api(self):
        body = read_body(self)
        start_date = body.get("start")
        end_date = body.get("end")

        if start_date and end_date:
            ranges = [(start_date, end_date)]
        else:
            ranges = sync_jobs.chain_ranges(date.today())

        job_id, job = RUNNER.start(ranges)
        if job_id is None:
            json_response(
                self, {"error": "sync already running", "job": job}, 409
            )
            return

        json_response(
            self,
            {"job_id": job_id, "stage": job["stage"], "total": job["total"]},
            202,
        )

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

        conn = None
        try:
            conn = db.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            query = build_sleep_query(table_columns(conn, SLEEP_TABLE), date_filter)
            rows = conn.execute(query).fetchall()
            records = [shape_sleep_row(row) for row in rows]
            json_response(self, records)
        except sqlite3.OperationalError as e:
            self.send_error(503, f"Database busy: {e}")
        finally:
            if conn is not None:
                conn.close()

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8484))
    server = ThreadingHTTPServer(("", port), Handler)
    print(f"Garmin Sleep Love → http://localhost:{port}")
    print(f"Database: {DB_PATH} ({'found' if DB_PATH.exists() else 'NOT FOUND'})")
    print(f"Authenticated: {auth.is_authenticated}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
