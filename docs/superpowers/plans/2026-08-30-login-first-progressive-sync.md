# Login-First Landing Screen + Progressive Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the signed-out screen a Garmin sign-in form, and fill the dashboard progressively — 7 days immediately, then 30, then 12 months in the background.

**Architecture:** Extract the sync job runner into its own dependency-free module so it can be unit-tested without an HTTP server or a Garmin account. `server.py` becomes threaded and gains two thin endpoints that delegate to it. `index.html` gains a login-first empty state that starts a sync on login and polls for stage completion.

**Tech Stack:** Python 3.10+ stdlib only (`http.server`, `sqlite3`, `threading`, `subprocess`, `unittest`), garmy 2.0.0, React 18 + Recharts via CDN with in-browser Babel.

**Spec:** `docs/superpowers/specs/2026-08-30-login-first-progressive-sync-design.md`

## Global Constraints

- **No new pip dependencies.** Standard library only. Tests use stdlib `unittest`.
- **Python 3.10+** — the floor stated in the root README.
- **Single-user.** `health.db` and `~/.garmy/` stay single-user; do not add account switching.
- **`index.html` has no build step.** JSX lives inside `<script type="text/babel">` and is compiled in the browser. Do not introduce a bundler, and do not use syntax Babel Standalone 7.17 cannot parse.
- **Do not modify `garmin-sleep-upgrade/garmin_sleep_analyzer.jsx`.** It is a stale export that never runs; editing it creates false confidence.
- **Do not modify the chart or analysis code** below the landing screen.
- **`health.db` is gitignored.** Never `git add` it, and never add a test fixture that writes into the repo root.
- **Sync subprocess timeout stays 1800s.**
- **Stage ranges are fixed:** 7 / 23 / 335 days, contiguous, no overlap, 365 total.
- **All line numbers refer to the files as they are at the start of this plan.** Earlier tasks add imports, so positions drift — match on the quoted content, not the number.

### Note on testing vs. the spec

The spec lists "a test framework" as a non-goal. That means **no new dependency** — no pytest. Tasks 1-3 still use TDD via stdlib `unittest`, which is exactly what the spec's Verification section asks for. Tasks 4-6 touch `index.html`, which has no build step and therefore no practical unit-test harness; those tasks carry scripted manual verification instead of tests. This is a deliberate deviation, not an oversight.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `garmin-sleep-upgrade/sync_jobs.py` | Create | Stage range math + background job runner. No HTTP, no garmy imports. |
| `garmin-sleep-upgrade/db.py` | Create | SQLite connection helper: WAL + busy timeout. |
| `garmin-sleep-upgrade/server.py` | Modify | Threaded server; `/api/sync` + `/api/sync/status` delegate to `sync_jobs`. |
| `garmin-sleep-upgrade/index.html` | Modify | Login-first empty state; progressive sync polling. |
| `tests/stub_sync.py` | Create | Stand-in for `sync.py` so tests never touch Garmin. |
| `tests/test_sync_jobs.py` | Create | Unit tests for the runner. |
| `tests/test_db.py` | Create | Concurrency test for WAL. |
| `tests/test_endpoints.py` | Create | HTTP-level tests for the two new endpoints. |
| `README.md` | Modify | Install steps drop the manual `login.py`. |
| `garmin-sleep-upgrade/README.md` | Modify | Note standalone mode is now behind a link. |

---

### Task 1: Sync job runner module

**Files:**
- Create: `garmin-sleep-upgrade/sync_jobs.py`
- Create: `tests/stub_sync.py`
- Create: `tests/test_sync_jobs.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `chain_ranges(today: datetime.date) -> list[tuple[str, str]]` — three `(start_iso, end_iso)` pairs, oldest day first within each pair.
  - `JobRunner(python: str, sync_script: str, timeout: int = 1800)`
  - `JobRunner.start(ranges: list[tuple[str, str]]) -> tuple[str | None, dict]` — returns `(job_id, job)` on success, `(None, current_job)` when one is already running.
  - `JobRunner.status() -> dict` — `{"running": False, "id": None}` if none has run.
  - Job dict shape: `{"id": str, "stage": int, "total": int, "running": bool, "error": str | None, "stages": list[dict]}`

- [ ] **Step 1: Write the stub sync script**

Create `tests/stub_sync.py`:

```python
#!/usr/bin/env python3
"""Stand-in for sync.py in tests. Never touches Garmin.

Exits non-zero when the range start equals $STUB_FAIL_ON, so a test can
force a specific stage to fail.
"""
import os
import sys

args = sys.argv[1:]
start = args[1] if len(args) >= 3 and args[0] == "--range" else ""

if start and start == os.environ.get("STUB_FAIL_ON", ""):
    print(f"stub failing on {start}", file=sys.stderr)
    sys.exit(1)

print(f"stub synced {start}")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_sync_jobs.py`:

```python
import sys
import time
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import sync_jobs  # noqa: E402

STUB = str(Path(__file__).resolve().parent / "stub_sync.py")


def wait_until_done(runner, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = runner.status()
        if not s["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


class ChainRangesTest(unittest.TestCase):
    def test_three_stages_contiguous_and_365_days(self):
        ranges = sync_jobs.chain_ranges(date(2026, 8, 30))
        self.assertEqual(
            ranges,
            [
                ("2026-08-24", "2026-08-30"),
                ("2026-08-01", "2026-08-23"),
                ("2025-08-31", "2026-07-31"),
            ],
        )

    def test_no_day_is_covered_twice(self):
        ranges = sync_jobs.chain_ranges(date(2026, 8, 30))
        seen = set()
        for start, end in ranges:
            d, last = date.fromisoformat(start), date.fromisoformat(end)
            while d <= last:
                self.assertNotIn(d, seen, f"{d} covered twice")
                seen.add(d)
                d = d.fromordinal(d.toordinal() + 1)
        self.assertEqual(len(seen), 365)


class JobRunnerTest(unittest.TestCase):
    def setUp(self):
        self.runner = sync_jobs.JobRunner(sys.executable, STUB, timeout=30)

    def test_status_before_any_job(self):
        self.assertEqual(self.runner.status(), {"running": False, "id": None})

    def test_runs_every_stage_in_order(self):
        ranges = [("2026-08-24", "2026-08-30"), ("2026-08-01", "2026-08-23")]
        job_id, job = self.runner.start(ranges)
        self.assertIsNotNone(job_id)
        self.assertEqual(job["total"], 2)
        final = wait_until_done(self.runner)
        self.assertIsNone(final["error"])
        self.assertEqual([s["stage"] for s in final["stages"]], [1, 2])
        self.assertTrue(all(s["ok"] for s in final["stages"]))

    def test_stops_chain_on_failure_and_keeps_earlier_stages(self):
        import os
        os.environ["STUB_FAIL_ON"] = "2026-08-01"
        self.addCleanup(os.environ.pop, "STUB_FAIL_ON", None)
        ranges = [
            ("2026-08-24", "2026-08-30"),
            ("2026-08-01", "2026-08-23"),
            ("2025-08-31", "2026-07-31"),
        ]
        self.runner.start(ranges)
        final = wait_until_done(self.runner)
        self.assertIsNotNone(final["error"])
        self.assertEqual([s["stage"] for s in final["stages"]], [1, 2])
        self.assertTrue(final["stages"][0]["ok"])
        self.assertFalse(final["stages"][1]["ok"])

    def test_second_start_while_running_is_refused(self):
        long_ranges = [("2026-08-24", "2026-08-30")] * 4
        self.runner.start(long_ranges)
        job_id, current = self.runner.start([("2026-01-01", "2026-01-02")])
        self.assertIsNone(job_id)
        self.assertTrue(current["running"])
        wait_until_done(self.runner)

    def test_status_copy_is_not_shared_mutable_state(self):
        self.runner.start([("2026-08-24", "2026-08-30")])
        snapshot = self.runner.status()
        snapshot["stages"].append({"bogus": True})
        wait_until_done(self.runner)
        self.assertNotIn({"bogus": True}, self.runner.status()["stages"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_sync_jobs -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sync_jobs'`

- [ ] **Step 4: Write the implementation**

Create `garmin-sleep-upgrade/sync_jobs.py`:

```python
"""Background Garmin sync jobs.

Deliberately knows nothing about HTTP or garmy so it can be unit-tested
with a stub script and no Garmin account.
"""

import subprocess
import threading
import uuid
from datetime import timedelta

SYNC_TIMEOUT = 1800

# (days_ago_start, days_ago_end) inclusive. Contiguous, no overlap, 365 days.
CHAIN = [(6, 0), (29, 7), (364, 30)]


def chain_ranges(today):
    """Return [(start_iso, end_iso)] for the automatic three-stage chain."""
    return [
        (
            (today - timedelta(days=start)).isoformat(),
            (today - timedelta(days=end)).isoformat(),
        )
        for start, end in CHAIN
    ]


class JobRunner:
    """Runs sync stages sequentially on a worker thread. One job at a time."""

    def __init__(self, python, sync_script, timeout=SYNC_TIMEOUT):
        self._python = python
        self._sync_script = sync_script
        self._timeout = timeout
        self._lock = threading.Lock()
        self._job = None

    def _snapshot(self):
        """Caller must hold the lock. Copies the mutable stages list."""
        if self._job is None:
            return {"running": False, "id": None}
        return {**self._job, "stages": list(self._job["stages"])}

    def status(self):
        with self._lock:
            return self._snapshot()

    def start(self, ranges):
        """Start a job. Returns (job_id, job) or (None, current_job) if busy."""
        with self._lock:
            if self._job is not None and self._job["running"]:
                return None, self._snapshot()
            self._job = {
                "id": uuid.uuid4().hex,
                "stage": 1,
                "total": len(ranges),
                "running": True,
                "error": None,
                "stages": [],
            }
            job_id = self._job["id"]
            snapshot = self._snapshot()

        threading.Thread(
            target=self._run, args=(job_id, list(ranges)), daemon=True
        ).start()
        return job_id, snapshot

    def _run(self, job_id, ranges):
        for index, (start, end) in enumerate(ranges, 1):
            with self._lock:
                if self._job is None or self._job["id"] != job_id:
                    return  # superseded
                self._job["stage"] = index

            cmd = [self._python, self._sync_script, "--range", start, end]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self._timeout
                )
                ok = result.returncode == 0
                output = result.stdout.strip()
                error = result.stderr.strip() or output
            except subprocess.TimeoutExpired:
                ok, output = False, ""
                error = f"Stage {index} timed out after {self._timeout}s"

            with self._lock:
                if self._job is None or self._job["id"] != job_id:
                    return
                self._job["stages"].append(
                    {"stage": index, "range": [start, end], "ok": ok, "output": output}
                )
                if not ok:
                    self._job["error"] = error or f"Stage {index} failed"
                    self._job["running"] = False
                    return

        with self._lock:
            if self._job is not None and self._job["id"] == job_id:
                self._job["running"] = False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_sync_jobs -v`
Expected: PASS — 7 tests

- [ ] **Step 6: Commit**

```bash
git add garmin-sleep-upgrade/sync_jobs.py tests/stub_sync.py tests/test_sync_jobs.py
git commit -m "feat: add background sync job runner with staged ranges"
```

---

### Task 2: SQLite WAL connection helper

**Files:**
- Create: `garmin-sleep-upgrade/db.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `connect(path) -> sqlite3.Connection` — WAL enabled, `busy_timeout` 5000ms.

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import db  # noqa: E402


class ConnectTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "test.db"
        seed = sqlite3.connect(str(self.path))
        seed.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        seed.execute("INSERT INTO t (v) VALUES ('before')")
        seed.commit()
        seed.close()

    def test_enables_wal(self):
        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_sets_busy_timeout(self):
        conn = db.connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_reader_is_not_blocked_by_an_open_writer(self):
        writer = db.connect(self.path)
        self.addCleanup(writer.close)
        reader = db.connect(self.path)
        self.addCleanup(reader.close)

        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO t (v) VALUES ('during')")

        # WAL lets the reader see the pre-write snapshot instead of erroring.
        rows = reader.execute("SELECT v FROM t").fetchall()
        self.assertEqual(rows, [("before",)])

        writer.commit()
        self.assertEqual(len(reader.execute("SELECT v FROM t").fetchall()), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_db -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Write the implementation**

Create `garmin-sleep-upgrade/db.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_db -v`
Expected: PASS — 3 tests

- [ ] **Step 5: Point the sleep endpoint at the helper**

In `garmin-sleep-upgrade/server.py`, add to the imports after line 10:

```python
import db
import sync_jobs
```

Then replace line 190:

```python
        conn = sqlite3.connect(str(DB_PATH))
```

with:

```python
        conn = db.connect(DB_PATH)
```

- [ ] **Step 6: Verify the server still serves data**

Run: `.venv/bin/python garmin-sleep-upgrade/server.py` then in another shell `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8484/api/sleep`
Expected: `404` when `health.db` is absent (unchanged), `200` when present. Stop the server afterwards.

- [ ] **Step 7: Commit**

```bash
git add garmin-sleep-upgrade/db.py garmin-sleep-upgrade/server.py tests/test_db.py
git commit -m "feat: open health.db in WAL mode with a busy timeout"
```

---

### Task 3: Threaded server and sync endpoints

**Files:**
- Modify: `garmin-sleep-upgrade/server.py:8` (import), `:87-95` (POST routes), `:148-172` (replace `serve_sync_api`), `:224` (server class)
- Create: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: `sync_jobs.JobRunner`, `sync_jobs.chain_ranges` from Task 1.
- Produces:
  - `POST /api/sync` → `202 {"job_id": str, "stage": 1, "total": 3}`, or `409 {"error": "sync already running", "job": {...}}`
  - `GET /api/sync/status` → the job dict from `JobRunner.status()`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_endpoints.py`:

```python
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "garmin-sleep-upgrade"))

import server  # noqa: E402
import sync_jobs  # noqa: E402

STUB = str(Path(__file__).resolve().parent / "stub_sync.py")


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read())


def post(url, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class SyncEndpointTest(unittest.TestCase):
    def setUp(self):
        # Swap in a runner backed by the stub so no Garmin call happens.
        server.RUNNER = sync_jobs.JobRunner(sys.executable, STUB, timeout=30)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)

    def wait_until_done(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = get(f"{self.base}/api/sync/status")
            if not body["running"]:
                return body
            time.sleep(0.05)
        raise AssertionError("job did not finish in time")

    def test_status_before_any_sync(self):
        status, body = get(f"{self.base}/api/sync/status")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"running": False, "id": None})

    def test_post_starts_a_three_stage_chain_and_returns_immediately(self):
        status, body = post(f"{self.base}/api/sync")
        self.assertEqual(status, 202)
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["stage"], 1)
        self.assertTrue(body["job_id"])
        final = self.wait_until_done()
        self.assertIsNone(final["error"])
        self.assertEqual(len(final["stages"]), 3)

    def test_explicit_range_runs_a_single_stage(self):
        status, body = post(
            f"{self.base}/api/sync", {"start": "2024-01-01", "end": "2024-01-05"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["total"], 1)
        final = self.wait_until_done()
        self.assertEqual(final["stages"][0]["range"], ["2024-01-01", "2024-01-05"])

    def test_concurrent_post_returns_409_with_the_live_job(self):
        post(f"{self.base}/api/sync")
        status, body = post(f"{self.base}/api/sync")
        self.assertEqual(status, 409)
        self.assertTrue(body["job"]["running"])
        self.wait_until_done()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_endpoints -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'RUNNER'`

If instead it fails at import with a garmy/`AuthClient()` error, that means module-level `auth = AuthClient()` (server.py:19) cannot construct in this environment. Fix by making it lazy rather than by skipping the test.

- [ ] **Step 3: Add the runner and thread the server**

In `garmin-sleep-upgrade/server.py`, change line 8:

```python
from http.server import SimpleHTTPRequestHandler, HTTPServer
```

to:

```python
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
```

After line 20 (`mfa_state = {}`), add:

```python
RUNNER = sync_jobs.JobRunner(
    str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable,
    str(SYNC_SCRIPT),
)
```

Change line 224:

```python
    server = HTTPServer(("", port), Handler)
```

to:

```python
    server = ThreadingHTTPServer(("", port), Handler)
```

- [ ] **Step 4: Add the status route**

In `do_GET`, after the `/api/auth/status` branch (server.py:80-81), add:

```python
        elif parsed.path == "/api/sync/status":
            json_response(self, RUNNER.status())
```

- [ ] **Step 5: Replace the blocking sync handler**

Replace the whole `serve_sync_api` method (server.py:148-172) with:

```python
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
```

Add `from datetime import date` to the imports (after line 7).

`subprocess` is no longer used by `server.py` — remove its import (line 6).

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_endpoints -v`
Expected: PASS — 4 tests

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS — 14 tests

- [ ] **Step 8: Commit**

```bash
git add garmin-sleep-upgrade/server.py tests/test_endpoints.py
git commit -m "feat: run syncs in the background behind a job status endpoint"
```

---

### Task 4: Login-first empty state

**Files:**
- Modify: `garmin-sleep-upgrade/index.html:863-996` (the `sleepData.length === 0` block)

**Interfaces:**
- Consumes: existing `authStatus`, `loginForm`, `loginState`, `loginError`, `handleLogin`, `handleMfa` (index.html:38-224).
- Produces: `showDropzone` state, consumed by Task 5's progress rendering.

There is no build step and no unit-test harness for this file. Verification is scripted and manual.

- [ ] **Step 1: Add the dropzone toggle state**

After line 44 (`const [showLogin, setShowLogin] = useState(false);`), add:

```jsx
  const [showDropzone, setShowDropzone] = useState(false);
  const [syncJob, setSyncJob] = useState(null);
```

- [ ] **Step 2: Replace the empty state's header block**

In the `sleepData.length === 0` return (starting line 863), replace the inner card — from `<div className="text-6xl mb-6">🌙</div>` through the closing `</div>` of the `space-y-4` block — with a login-first layout:

```jsx
            <div className="text-6xl mb-6">🌙</div>
            <h1 className="text-3xl font-bold mb-2 text-blue-400">Garmin Sleep Analyzer</h1>
            <p className="text-gray-400 mb-8">v1.9.1</p>

            {authStatus === false && (
              <form onSubmit={loginState === 'mfa' ? handleMfa : handleLogin} className="space-y-3 text-left max-w-sm mx-auto">
                {loginState === 'mfa' ? (
                  <>
                    <p className="text-sm text-gray-400">Enter the MFA code from your authenticator app.</p>
                    <input
                      type="text" autoFocus placeholder="MFA Code"
                      value={loginForm.mfa}
                      onChange={e => setLoginForm(f => ({...f, mfa: e.target.value}))}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                    />
                  </>
                ) : (
                  <>
                    <input
                      type="email" autoFocus placeholder="Garmin email"
                      value={loginForm.email}
                      onChange={e => setLoginForm(f => ({...f, email: e.target.value}))}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                    />
                    <input
                      type="password" placeholder="Password"
                      value={loginForm.password}
                      onChange={e => setLoginForm(f => ({...f, password: e.target.value}))}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                    />
                  </>
                )}
                {loginError && <p className="text-red-400 text-xs">{loginError}</p>}
                <button
                  type="submit" disabled={loginState === 'loading'}
                  className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white rounded-lg text-sm font-medium"
                >
                  {loginState === 'loading' ? 'Signing in…' : loginState === 'mfa' ? 'Verify' : 'Sign in to Garmin'}
                </button>
                <p className="text-xs text-gray-600 text-center pt-1">
                  Credentials go straight to Garmin. Tokens are saved to ~/.garmy/ on this machine.
                </p>
              </form>
            )}

            {authStatus === null && (
              <p className="text-sm text-gray-500">Requires server.py — run it and reload.</p>
            )}

            <div className="mt-6 pt-4 border-t border-gray-700">
              <button
                onClick={() => setShowDropzone(v => !v)}
                className="text-xs text-gray-500 hover:text-gray-300 underline"
              >
                {showDropzone ? 'Hide export loader' : 'or load a Garmin export instead'}
              </button>
              {showDropzone && (
                <div className="mt-4 space-y-2">
                  <p className="text-sm text-gray-300">
                    {dragOver ? 'Drop files here!' : 'Drop your Garmin sleep JSON files anywhere'}
                  </p>
                  <p className="text-xs text-gray-500">
                    Export from <a href="https://www.garmin.com/account/datamanagement/" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">garmin.com/account/datamanagement</a>
                  </p>
                  <p className="text-xs text-gray-600">Look for files in: DI_CONNECT/DI_CONNECT_FITNESS/</p>
                  <button
                    onClick={loadFromGarmy}
                    disabled={garmyLoading}
                    className="mt-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-gray-200 rounded-lg text-sm"
                  >
                    {garmyLoading ? 'Loading…' : 'Load from local DB'}
                  </button>
                </div>
              )}
            </div>
```

This removes the old always-visible range `<select>`, the green "Load from Garmy DB" button, the "Sign in to Garmin to sync" link, and the 30d/90d/6mo/1yr/2yr sync row. Those are replaced by the login form plus Task 5's automatic chain.

- [ ] **Step 3: Verify the signed-out screen renders**

Run the server, then:

```bash
curl -s http://localhost:8484/ | grep -c "Sign in to Garmin"
```

Expected: `1`. Then open `http://localhost:8484` in a browser with no valid token and confirm: the login form is the focus of the screen, the export link is a small grey link, and clicking it reveals the dropzone.

- [ ] **Step 4: Verify the dropzone still accepts files**

With the export loader expanded, drag a Garmin sleep JSON onto the page. Expected: it parses and renders the dashboard exactly as before this change.

- [ ] **Step 5: Commit**

```bash
git add garmin-sleep-upgrade/index.html
git commit -m "feat: make the signed-out screen a Garmin login form"
```

---

### Task 5: Progressive sync on login

**Files:**
- Modify: `garmin-sleep-upgrade/index.html` — `handleLogin`/`handleMfa` success paths (lines 136-180), `loadFromGarmy` (line 228), the empty-state render from Task 4, and the dashboard header near line 1003

**Interfaces:**
- Consumes: `POST /api/sync` and `GET /api/sync/status` from Task 3; `syncJob` state from Task 4.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the sync starter and poller**

After `handleLogout` (index.html:184), add:

```jsx
  const pollSyncStatus = async () => {
    const res = await fetch('/api/sync/status');
    const job = await res.json();
    setSyncJob(job);
    return job;
  };

  const startProgressiveSync = async () => {
    const res = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    // 409 means a job is already running — adopt it instead of starting a second.
    const body = await res.json();
    setSyncJob(res.status === 409 ? body.job : { ...body, running: true, stages: [] });
  };
```

- [ ] **Step 2: Poll while a job is running, reloading data as stages land**

Add this effect after the existing auth-status effect (index.html:80):

```jsx
  useEffect(() => {
    if (!syncJob || !syncJob.running) return;
    let cancelled = false;
    const id = setInterval(async () => {
      const job = await pollSyncStatus();
      if (cancelled) return;
      loadFromGarmy();               // re-read whatever has landed so far
      if (!job.running) clearInterval(id);
    }, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [syncJob?.running, syncJob?.id]);
```

- [ ] **Step 3: Kick off the sync after a successful login**

In `handleLogin`, replace the success block (index.html:147-150):

```jsx
      setAuthStatus(true);
      setShowLogin(false);
      setLoginState('idle');
      setLoginForm({ email: '', password: '', mfa: '' });
```

with:

```jsx
      setAuthStatus(true);
      setShowLogin(false);
      setLoginState('idle');
      setLoginForm({ email: '', password: '', mfa: '' });
      startProgressiveSync();
```

Make the identical change in `handleMfa`'s success block (index.html:170-173).

- [ ] **Step 4: Treat a missing database as "no data yet"**

In `loadFromGarmy` (index.html:228), the current handler surfaces `Server error: 404`. Change the response check so a 404 clears the error instead:

```jsx
      if (res.status === 404) { setError(null); return; }   // DB not created yet
      if (!res.ok) { setError(`Garmy DB: Server error: ${res.status}`); return; }
```

- [ ] **Step 5: Show sync progress in the empty state**

In the empty-state block from Task 4, immediately after the `authStatus === null` paragraph, add:

```jsx
            {authStatus === true && syncJob?.running && (
              <div className="space-y-2">
                <p className="text-lg text-gray-200">
                  {syncJob.stage === 1 ? 'Getting your last 7 days…' : `Filling in history — stage ${syncJob.stage} of ${syncJob.total}`}
                </p>
                <div className="w-full bg-gray-700 rounded-full h-1.5 max-w-sm mx-auto">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full transition-all"
                    style={{ width: `${((syncJob.stages?.length || 0) / (syncJob.total || 3)) * 100}%` }}
                  />
                </div>
              </div>
            )}
            {authStatus === true && syncJob && !syncJob.running && syncJob.error && (
              <p className="text-sm text-red-400">{syncJob.error}</p>
            )}
```

- [ ] **Step 6: Add the background-progress pill to the dashboard**

In the dashboard header near index.html:1003, immediately after the `<h1>` containing `Garmin Sleep Analyzer`, add:

```jsx
          {syncJob?.running && (
            <span className="ml-3 text-xs text-blue-300 bg-blue-900/40 px-2 py-1 rounded-full">
              Syncing history — stage {syncJob.stage} of {syncJob.total}
            </span>
          )}
          {syncJob && !syncJob.running && syncJob.error && (
            <button
              onClick={() => setSyncJob(null)}
              className="ml-3 text-xs text-red-300 bg-red-900/40 px-2 py-1 rounded-full"
              title="Dismiss"
            >
              Sync stopped: {syncJob.error} ×
            </button>
          )}
```

- [ ] **Step 7: Verify the progression end to end**

This step needs the account owner — it makes real Garmin calls.

1. Delete any existing `health.db` so the run starts cold.
2. Start the server, open `http://localhost:8484`, sign in.
3. Expected: "Getting your last 7 days…" appears; within roughly a minute the dashboard renders with about 7 nights.
4. Expected: the header pill reads "stage 2 of 3", then "stage 3 of 3"; night count grows on each poll without the page going blank.
5. While stage 3 runs, confirm the UI stays responsive — switch charts, change the aggregation toggle. This is the check that threading actually worked.

- [ ] **Step 8: Verify reload recovery**

Mid-sync, reload the page. Expected: it re-adopts the running job via the 409 path and keeps showing progress rather than starting a second sync.

- [ ] **Step 9: Commit**

```bash
git add garmin-sleep-upgrade/index.html
git commit -m "feat: sync progressively after login, 7d then 30d then 12mo"
```

---

### Task 6: Load more history control

**Files:**
- Modify: `garmin-sleep-upgrade/index.html` — dashboard header, beside the sync pill added in Task 5

**Interfaces:**
- Consumes: `POST /api/sync` with `{start, end}` from Task 3; `syncJob` state from Task 4; `startProgressiveSync`'s sibling pattern from Task 5.
- Produces: nothing consumed by later tasks.

The automatic chain stops at `today-365`. This adds the spec's on-demand control for older windows. It never runs on its own.

- [ ] **Step 1: Add the state and the range starter**

After `startProgressiveSync` (added in Task 5), add:

```jsx
  const [historyYears, setHistoryYears] = useState('2');

  const loadMoreHistory = async () => {
    const today = new Date();
    const end = new Date(today);
    end.setDate(end.getDate() - 365);                       // where the chain stopped
    const start = new Date(today);
    start.setFullYear(start.getFullYear() - parseInt(historyYears, 10));
    const iso = (d) => d.toISOString().slice(0, 10);

    const res = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: iso(start), end: iso(end) }),
    });
    const body = await res.json();
    setSyncJob(res.status === 409 ? body.job : { ...body, running: true, stages: [] });
  };
```

- [ ] **Step 2: Add the control to the dashboard header**

Immediately after the sync pill block from Task 5 Step 6, add:

```jsx
          {!syncJob?.running && (
            <span className="ml-3 inline-flex items-center gap-2 text-xs">
              <select
                value={historyYears}
                onChange={(e) => setHistoryYears(e.target.value)}
                className="px-2 py-1 bg-gray-700 text-gray-200 rounded border border-gray-600"
              >
                <option value="2">2 years</option>
                <option value="3">3 years</option>
                <option value="5">5 years</option>
              </select>
              <button
                onClick={loadMoreHistory}
                className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded"
              >
                Load more history
              </button>
            </span>
          )}
```

- [ ] **Step 3: Verify the request range without hitting Garmin**

Start the server with the stub wired in, so no Garmin call happens:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'garmin-sleep-upgrade')
import server, sync_jobs
server.RUNNER = sync_jobs.JobRunner(sys.executable, 'tests/stub_sync.py', timeout=30)
from http.server import ThreadingHTTPServer
ThreadingHTTPServer(('', 8484), server.Handler).serve_forever()
"
```

Open the dashboard, pick "3 years", click **Load more history**, then:

```bash
curl -s http://localhost:8484/api/sync/status
```

Expected: one stage whose `range` starts three years before today and ends 365 days before today — contiguous with the chain, no overlap.

- [ ] **Step 4: Verify the control hides during a sync**

While that job runs, confirm the select and button are replaced by the progress pill, so a second overlapping job cannot be started by clicking.

- [ ] **Step 5: Commit**

```bash
git add garmin-sleep-upgrade/index.html
git commit -m "feat: add on-demand load-more-history control"
```

---

### Task 7: Update the docs

**Files:**
- Modify: `README.md` (Install section)
- Modify: `garmin-sleep-upgrade/README.md` (Quick start step 4)

- [ ] **Step 1: Update the root README install block**

Replace the fenced install block with:

```bash
git clone https://github.com/<you>/garmin-sleep.git
cd garmin-sleep
./setup-garmy.sh                                   # creates .venv, installs garmy
.venv/bin/python garmin-sleep-upgrade/server.py    # opens at http://localhost:8484
```

Then add below it:

> Sign in on the page itself. The first 7 days sync immediately; 30 days and
> then the last 12 months fill in behind you. Older history is a button in
> the dashboard.

- [ ] **Step 2: Note that `setup-garmy.sh` no longer needs to log in**

`setup-garmy.sh` step 3 runs `login.py` interactively. Since login now happens in the browser, make that step optional — change the script's step 3 to print a pointer instead of prompting:

```bash
echo "[3/3] Setup complete — sign in at http://localhost:8484 once the server is running."
```

Leave `login.py` in place for CLI users.

- [ ] **Step 3: Update the standalone README**

In `garmin-sleep-upgrade/README.md`, change Quick start step 4 to:

```markdown
4. Click **"or load a Garmin export instead"** beneath the sign-in form, then drag the JSON files onto the page. Data is cached to `localStorage` so you only need to do this once per browser.
```

- [ ] **Step 4: Verify the documented commands actually run**

Run each command in the root README's install block in a scratch clone. Expected: no step errors, and the server starts.

- [ ] **Step 5: Commit**

```bash
git add README.md garmin-sleep-upgrade/README.md setup-garmy.sh
git commit -m "docs: describe browser login and progressive sync"
```

---

## Final verification

- [ ] Run the full suite: `.venv/bin/python -m unittest discover -s tests -v` — expected 14 passing
- [ ] Confirm `git status` shows no `health.db`, no `.venv/`, no `__pycache__/`
- [ ] Confirm `garmin_sleep_analyzer.jsx` is untouched: `git diff --stat HEAD~7 -- garmin-sleep-upgrade/garmin_sleep_analyzer.jsx` prints nothing
