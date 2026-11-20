import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibration import (build_completion_curves, completion_at,  # noqa: E402
                         evaluate_arms, project_group)
from generator import generate_book, planted_completion  # noqa: E402


class TestCompletionCurves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = generate_book()
        cls.curves = build_completion_curves(cls.records)

    def test_built_only_from_matured_cohorts(self):
        self.assertEqual(self.curves["slow"]["built_from_cohorts"],
                         ["2024-07", "2024-08", "2024-09", "2024-10", "2024-11"])
        self.assertEqual(len(self.curves["fast"]["built_from_cohorts"]), 11)
        self.assertNotIn("2025-06", self.curves["fast"]["built_from_cohorts"])

    def test_curve_monotonic_and_ends_at_one(self):
        for segment in ("fast", "slow"):
            entry = self.curves[segment]
            vals = [entry["curve"][str(m)] for m in range(0, entry["horizon"] + 1)]
            self.assertEqual(vals, sorted(vals))
            self.assertEqual(vals[0], 0.0)
            self.assertEqual(vals[-1], 1.0)

    def test_slow_curve_close_to_planted(self):
        entry = self.curves["slow"]
        for m in range(1, 9):
            self.assertAlmostEqual(entry["curve"][str(m)],
                                   planted_completion("slow", m), delta=0.04,
                                   msg=f"mob {m}")

    def test_fast_curve_close_to_planted(self):
        entry = self.curves["fast"]
        self.assertAlmostEqual(entry["curve"]["1"], 0.7, delta=0.05)
        self.assertEqual(entry["curve"]["2"], 1.0)

    def test_completion_at_beyond_horizon_is_one(self):
        self.assertEqual(completion_at(self.curves["slow"], 12), 1.0)
        self.assertEqual(completion_at(self.curves["fast"], 9), 1.0)

    def test_completion_at_zero_age_is_zero(self):
        self.assertEqual(completion_at(self.curves["slow"], 0), 0.0)


class TestProjectGroup(unittest.TestCase):
    def test_full_completion_returns_observed_rate(self):
        out = project_group(1000, 80, 1.0)
        self.assertEqual(out["projected_rate"], 0.08)
        self.assertLessEqual(out["ci_low"], 0.08)
        self.assertGreaterEqual(out["ci_high"], 0.08)

    def test_projection_divides_by_completion(self):
        out = project_group(1000, 10, 0.5)
        self.assertEqual(out["projected_rate"], 0.02)

    def test_ci_width_increases_as_maturity_decreases(self):
        # Same ultimate rate (0.18) and n; only the surfaced share varies.
        widths = []
        for comp in (1.0, 0.5, 0.25):
            k = round(1000 * 0.18 * comp)
            widths.append(project_group(1000, k, comp)["ci_width"])
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])

    def test_zero_completion_is_undefined_not_zero(self):
        out = project_group(500, 0, 0.0)
        self.assertIsNone(out["projected_rate"])
        self.assertIsNone(out["ci_width"])

    def test_nonpositive_n_raises(self):
        with self.assertRaises(ValueError):
            project_group(0, 0, 0.5)


class TestArms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arms = evaluate_arms(generate_book())["segments"]

    def test_naive_understates_slow_by_planted_amount(self):
        bias = self.arms["slow"]["naive"]["bias_vs_truth"]
        self.assertEqual(bias, -0.055)
        self.assertLess(bias, -0.03)

    def test_naive_fast_bias_is_small(self):
        self.assertAlmostEqual(self.arms["fast"]["naive"]["bias_vs_truth"], 0.0, delta=0.01)

    def test_completion_covers_truth_both_segments(self):
        for segment in ("fast", "slow"):
            self.assertTrue(self.arms[segment]["completion"]["covers_truth"], segment)

    def test_completion_closer_to_truth_than_naive(self):
        for segment in ("fast", "slow"):
            self.assertLess(abs(self.arms[segment]["completion"]["bias_vs_truth"]),
                            abs(self.arms[segment]["naive"]["bias_vs_truth"]), segment)

    def test_filtered_excludes_immature_cohorts(self):
        self.assertEqual(len(self.arms["slow"]["maturity_filtered"]["excluded_cohorts"]), 7)
        self.assertEqual(self.arms["fast"]["maturity_filtered"]["excluded_cohorts"], ["2025-06"])
        self.assertEqual(self.arms["slow"]["maturity_filtered"]["n"], 2500)

    def test_filtered_closer_to_truth_than_naive_for_slow(self):
        self.assertLess(abs(self.arms["slow"]["maturity_filtered"]["bias_vs_truth"]),
                        abs(self.arms["slow"]["naive"]["bias_vs_truth"]))

    def test_arms_deterministic(self):
        again = evaluate_arms(generate_book())["segments"]
        self.assertEqual(again, self.arms)


if __name__ == "__main__":
    unittest.main()
