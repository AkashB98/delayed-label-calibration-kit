import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (COHORTS, HORIZONS, PLANTED_RATES, SEGMENTS,  # noqa: E402
                       generate_book, planted_completion)


class TestGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = generate_book()

    def test_deterministic(self):
        self.assertEqual(generate_book(), self.records)

    def test_total_count(self):
        self.assertEqual(len(self.records), 12000)

    def test_twelve_cohorts_with_descending_ages(self):
        self.assertEqual(len(COHORTS), 12)
        ages = [age for _c, age in COHORTS]
        self.assertEqual(ages, sorted(ages, reverse=True))
        self.assertEqual(ages[0], 12)
        self.assertEqual(ages[-1], 1)
        self.assertEqual({r["cohort"] for r in self.records}, {c for c, _a in COHORTS})

    def test_segment_counts_balanced(self):
        for segment in SEGMENTS:
            self.assertEqual(sum(1 for r in self.records if r["segment"] == segment), 6000)

    def test_each_cohort_segment_group_is_500(self):
        for cohort, _age in COHORTS:
            for segment in SEGMENTS:
                n = sum(1 for r in self.records
                        if r["cohort"] == cohort and r["segment"] == segment)
                self.assertEqual(n, 500, (cohort, segment))

    def test_observed_implies_ultimate(self):
        for r in self.records:
            if r["observed_default"] == 1:
                self.assertEqual(r["ultimate_default"], 1)

    def test_arrival_mob_only_when_observed_and_in_range(self):
        for r in self.records:
            if r["observed_default"] == 1:
                self.assertIsNotNone(r["arrival_mob"])
                self.assertGreaterEqual(r["arrival_mob"], 1)
                self.assertLessEqual(r["arrival_mob"], r["age_months"])
                self.assertLessEqual(r["arrival_mob"], HORIZONS[r["segment"]])
            else:
                self.assertIsNone(r["arrival_mob"])

    def test_matured_cohorts_fully_labeled(self):
        for r in self.records:
            if r["age_months"] >= HORIZONS[r["segment"]]:
                self.assertEqual(r["observed_default"], r["ultimate_default"])

    def test_empirical_ultimate_close_to_planted(self):
        for segment in SEGMENTS:
            rows = [r for r in self.records if r["segment"] == segment]
            rate = sum(r["ultimate_default"] for r in rows) / len(rows)
            self.assertAlmostEqual(rate, PLANTED_RATES[segment], delta=0.02)

    def test_instant_scenario_has_no_hidden_labels(self):
        records = generate_book(scenario="instant")
        for r in records:
            self.assertEqual(r["observed_default"], r["ultimate_default"])
            if r["observed_default"]:
                self.assertEqual(r["arrival_mob"], 1)

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            generate_book(scenario="nope")

    def test_planted_completion_values(self):
        self.assertEqual(planted_completion("fast", 1), 0.7)
        self.assertEqual(planted_completion("fast", 2), 1.0)
        self.assertEqual(planted_completion("slow", 1), 0.05)
        self.assertEqual(planted_completion("slow", 4), 0.5)
        self.assertEqual(planted_completion("slow", 7), 0.95)
        self.assertEqual(planted_completion("slow", 8), 1.0)
        self.assertEqual(planted_completion("slow", 0), 0.0)


if __name__ == "__main__":
    unittest.main()
