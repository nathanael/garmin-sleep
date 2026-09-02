# Login-first landing screen + progressive sync

Date: 2026-08-30
Status: approved in chat, pending spec review

## Problem

The app's empty state is a drag-and-drop JSON dropzone. Live Garmin sync —
the primary path, and the only one that yields HRV — is buried as a small
underlined link beneath it. A new user lands on a screen that advertises
the fallback and hides the feature.

Separately, sync is all-or-nothing and blocking. `POST /api/sync` runs
`subprocess.run(cmd, timeout=1800)` (`server.py:158`) on a single-threaded
`HTTPServer` (`server.py:222`). While a sync runs the server answers
nothing at all, `/api/sleep` included. A first-run user picking "2yr" gets
a dead browser tab with no feedback until it finishes or times out.

## Goals

- Signed-out users see a Garmin sign-in screen, not a dropzone.
- A signed-in user reaches a populated dashboard in seconds, not minutes.
- Longer history fills in behind them without blocking the UI.
- Standalone (export-file) mode survives, demoted.

## Non-goals

- Multi-account support. `health.db` and `~/.garmy/` stay single-user.
- Reconciling `garmin_sleep_analyzer.jsx` with `index.html`. The `.jsx` is
  a stale export that never runs in the browser; it stays untouched.
- Any change to the chart/analysis code below the landing screen.
- A test framework. The repo has none; this change does not add one.

## Screen states

Driven by `authStatus` (from `/api/auth/status`) and whether sleep data has
loaded.

1. **Signed out** — the login form *is* the screen. Moon glyph, title,
   email + password inline (the current `LoginModal` content, unwrapped
   from its overlay). MFA resolves in place as a second step, reusing the
   existing `/api/auth/mfa` flow. One quiet link below the form —
   "or load a Garmin export instead" — expands the existing dropzone.
2. **Signed in, no data yet** — progress: "Getting your last 7 days…"
3. **Signed in, data present** — the dashboard. A small status pill shows
   while background stages are still running.

The `LoginModal` overlay is retained for re-authentication from inside the
dashboard (token expiry, explicit sign-out). Only the empty state changes.

## Sync staging

Each stage covers only days no earlier stage has fetched, via the
`--range` mode `sync.py` already supports. No day is fetched twice.

| Stage | Range              | Days | Mode                  |
|-------|--------------------|------|-----------------------|
| 1     | today−6 → today    | 7    | foreground, awaited   |
| 2     | today−29 → today−7 | 23   | background            |
| 3     | today−364 → today−30 | 335 | background           |
| 4+    | older windows      | —    | on demand, from dashboard |

Stage 4+ is a "Load more history" control in the dashboard: a select
offering 2yr / 3yr / 5yr, which issues one `--range` sync from that bound
forward to `today-365` — the oldest day the automatic chain reached. It is
not part of the automatic chain and never runs on its own.

## Server design

### Threading

`HTTPServer` → `ThreadingHTTPServer`. Without this, a background sync
still blocks `/api/sleep` and the whole design fails.

### Job model

One module-level job record guarded by a `threading.Lock`:

    {
      "id": str,          # uuid4 hex
      "stage": int,       # 1-based, currently running
      "total": int,       # 3 for the automatic chain
      "running": bool,
      "error": str|None,  # first stage failure, if any
      "stages": [         # per-stage outcome, appended as they finish
        {"stage": 1, "range": [start, end], "ok": true, "output": "..."}
      ]
    }

At most one job at a time. The lock guards reads and writes of the record;
the worker thread holds it only to mutate, never across a subprocess call.

### Endpoints

- `POST /api/sync`
  - If a job is running → `409` with the current job record.
  - Otherwise create a job, spawn a daemon worker thread, return
    `{"job_id": ..., "stage": 1, "total": 3}` immediately.
  - Body may carry `{"start": ..., "end": ...}` for a one-off stage-4
    window; that path runs a single-stage job.
- `GET /api/sync/status` → the current job record, or
  `{"running": false, "id": null}` if none has run this process lifetime.

`POST /api/sync`'s existing blocking `days` behavior is removed. Nothing
else consumes it — the only caller is this page.

### Worker

Runs stages in order. Each stage shells out to
`sync.py --range <start> <end>` exactly as today, same 1800s timeout. On a
non-zero exit or timeout: record the error, mark the job stopped, and skip
remaining stages. Data written by completed stages stays valid.

### SQLite concurrency

`sync.py` writes `health.db` while `/api/sleep` reads it. Set
`PRAGMA journal_mode=WAL` when opening the DB — the setting persists in
the file, so one successful application is enough, but applying it on each
open is harmless and covers the first-run case where stage 1 creates the
file. Reads additionally get `PRAGMA busy_timeout=5000` so a brief writer
lock retries rather than surfacing "database is locked".

## Client design

- On mount, `/api/auth/status` decides screen state (unchanged).
- Successful login → `POST /api/sync` → poll `/api/sync/status` every 2s.
- After each stage completes, re-fetch `/api/sleep` and re-render. The
  dashboard appears once stage 1 lands.
- Polling stops when `running` is false. On a 409 at start, the client
  adopts the returned job and polls it — this is what makes a mid-sync
  page reload recover instead of stranding.
- `/api/sleep` returning 404 means "no data yet" and renders the progress
  state, not the current red `Server error: 404`.

## Error handling

| Failure | Behavior |
|---|---|
| Bad credentials | Inline in the login form (existing behavior) |
| MFA required | Second step in the same form (existing behavior) |
| Stage fails | Chain stops; completed data retained; dismissible banner names the stage |
| Sync already running | Client adopts the live job and polls |
| DB missing | Progress state, not an error |
| DB locked | `busy_timeout` retries; WAL should prevent it |

## Files touched

- `garmin-sleep-upgrade/server.py` — threading, job runner, two endpoints, WAL
- `garmin-sleep-upgrade/index.html` — login screen, progressive sync UI, dropzone demotion
- `README.md` — install steps no longer run `login.py` by hand
- `garmin-sleep-upgrade/README.md` — note that standalone is now behind a link

## Verification

The repo has no test suite, and the honest limit is that the end-to-end
path needs real Garmin credentials, which the implementer does not have.

Testable without an account:
- Job runner and stage sequencing, with `sync.py` stubbed by a script that
  sleeps and exits 0 / non-zero.
- `/api/sync/status` shape and the 409-adoption path.
- Concurrent `/api/sleep` reads during a simulated write, confirming WAL
  holds up.
- Each screen state, with `/api/auth/status` faked.

Requires the account owner:
- Real login, real MFA, and a real Garmin pull populating `health.db`.

## Risks

- Garmin may rate-limit three syncs in quick succession. Stage 3 is 335
  days of API calls; if throttling appears, the mitigation is a delay
  between stages, not a redesign.
- `sync.py`'s `days_since_last_sync()` fallback is unused by the staged
  path, which always passes explicit ranges. Left as-is for CLI callers.
