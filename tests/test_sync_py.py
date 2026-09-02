"""Tests for sync.py's extract_sleep_metrics() (IMPORTANT 9).

Only imports sync.py as a module -- that runs no Garmin code (main() is
gated by `if __name__ == "__main__"`), so this never touches the network
or a real account. Never call sync.main() from a test; see CLAUDE.md /
the task brief for why sync.py must never actually run in this repo.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import sync  # noqa: E402


class ExtractSleepMetricsTest(unittest.TestCase):
    """extract_sleep_metrics() is the pure function sync.py's per-day
    backfill loop uses to pull sleep_score, avg_sleep_stress, lowest_spo2,
    and sleep_need_minutes out of the `sleep_summary` object garmy's sleep
    API returns -- verified live against the user's real account (see the
    task brief): sleep_scores["overall"]["value"], avg_sleep_stress,
    lowest_sp_o2_value (garmy's spelling), and sleep_need["baseline"].
    """

    def test_extracts_all_four_fields_from_a_full_summary(self):
        # Shape verified live: 2026-08-30, overall score 85.
        summary = SimpleNamespace(
            sleep_scores={
                "overall": {"value": 85, "qualifier_key": "GOOD"},
                "total_duration": {"value": 70},
            },
            avg_sleep_stress=17.0,
            lowest_sp_o2_value=89,
            sleep_need={"baseline": 470, "actual": 470, "feedback": "MET"},
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(
            result,
            {
                "sleep_score": 85,
                "avg_sleep_stress": 17.0,
                "lowest_spo2": 89,
                "sleep_need_minutes": 470,
            },
        )

    def test_sleep_score_comes_from_the_nested_overall_value_path(self):
        # Isolates the specific nested path (sleep_scores -> "overall" ->
        # "value") from the other three fields, which are flat attributes.
        summary = SimpleNamespace(
            sleep_scores={"overall": {"value": 71, "qualifier_key": "FAIR"}},
            avg_sleep_stress=None,
            lowest_sp_o2_value=None,
            sleep_need=None,
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(result["sleep_score"], 71)

    def test_summary_missing_every_field_entirely_returns_all_none(self):
        # A bare object with none of the expected attributes at all --
        # not even set to None. getattr's default must carry every field,
        # and the function must not raise.
        summary = SimpleNamespace()

        result = sync.extract_sleep_metrics(summary)

        self.assertEqual(
            result,
            {
                "sleep_score": None,
                "avg_sleep_stress": None,
                "lowest_spo2": None,
                "sleep_need_minutes": None,
            },
        )

    def test_summary_itself_is_none_returns_all_none(self):
        # e.g. a night with no sleep recorded -- the caller passes
        # sleep.sleep_summary straight through, which can be None.
        result = sync.extract_sleep_metrics(None)

        self.assertEqual(
            result,
            {
                "sleep_score": None,
                "avg_sleep_stress": None,
                "lowest_spo2": None,
                "sleep_need_minutes": None,
            },
        )

    def test_malformed_sleep_scores_does_not_blank_the_other_fields(self):
        # sleep_scores present but not a dict (or missing "overall"/"value")
        # must null out only sleep_score, not the three sibling fields.
        summary = SimpleNamespace(
            sleep_scores="not a dict",
            avg_sleep_stress=22,
            lowest_sp_o2_value=90,
            sleep_need={"baseline": 460},
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertIsNone(result["sleep_score"])
        self.assertEqual(result["avg_sleep_stress"], 22)
        self.assertEqual(result["lowest_spo2"], 90)
        self.assertEqual(result["sleep_need_minutes"], 460)

    def test_sleep_need_without_baseline_key_is_none(self):
        summary = SimpleNamespace(
            sleep_scores={"overall": {"value": 82}},
            avg_sleep_stress=15,
            lowest_sp_o2_value=91,
            sleep_need={"feedback": "MET"},  # no "baseline"
        )

        result = sync.extract_sleep_metrics(summary)

        self.assertIsNone(result["sleep_need_minutes"])
        self.assertEqual(result["sleep_score"], 82)


if __name__ == "__main__":
    unittest.main()
