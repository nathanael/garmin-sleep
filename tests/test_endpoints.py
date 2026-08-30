import json
import os
import sys
import tempfile
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
BLOCKING_STUB = str(Path(__file__).resolve().parent / "stub_sync_blocking.py")


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
        # A fast stub could finish all 3 chain stages before a second POST
        # ever reaches the server, which would make a 409 assertion here
        # pass or fail depending on scheduling luck rather than on real
        # behavior. To make this deterministic, swap in a stub whose first
        # stage blocks on a release file that does not exist yet, so the
        # job is *guaranteed* to still be running when the second POST is
        # sent -- this isn't a timing race, it's controlled by the test.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: os.path.exists(release) and os.unlink(release))
        release = os.path.join(tmpdir, "release")
        server.RUNNER = sync_jobs.JobRunner(sys.executable, BLOCKING_STUB, timeout=30)
        os.environ["STUB_RELEASE_FILE"] = release
        self.addCleanup(os.environ.pop, "STUB_RELEASE_FILE", None)

        try:
            status, body = post(f"{self.base}/api/sync")
            self.assertEqual(status, 202)

            # Stage 1's subprocess is blocked in the stub waiting on the
            # release file, so this status read is guaranteed to observe
            # "running" -- not merely likely to.
            _, status_body = get(f"{self.base}/api/sync/status")
            self.assertTrue(status_body["running"])

            status2, body2 = post(f"{self.base}/api/sync")
            self.assertEqual(status2, 409)
            self.assertTrue(body2["job"]["running"])
            self.assertEqual(body2["job"]["id"], body["job_id"])
        finally:
            Path(release).touch()  # let stage 1 (and the rest of the chain) finish

        self.wait_until_done()


if __name__ == "__main__":
    unittest.main()
