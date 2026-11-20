import io
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibration import maturity_report  # noqa: E402
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main, make_server  # noqa: E402
from generator import PLANTED_RATES, generate_book, planted_completion  # noqa: E402

EXPECTED_LABELS = (["claimable"] * 6 + ["provisional"] * 4 + ["not claimable"] * 2)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue()


def _planted_label(age):
    frac = sum(PLANTED_RATES[s] * planted_completion(s, age) for s in PLANTED_RATES) / sum(PLANTED_RATES.values())
    if frac >= 0.95:
        return "claimable"
    if frac >= 0.50:
        return "provisional"
    return "not claimable"


class TestMaturityReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = maturity_report(generate_book())

    def test_labels_match_expected_sequence(self):
        labels = [row["label"] for row in self.report["cohorts"]]
        self.assertEqual(labels, EXPECTED_LABELS)

    def test_summary_counts(self):
        self.assertEqual(self.report["summary"],
                         {"claimable": 6, "provisional": 4, "not claimable": 2})

    def test_labels_match_planted_arrival_fractions(self):
        for row in self.report["cohorts"]:
            self.assertEqual(row["label"], _planted_label(row["age_months"]),
                             row["cohort"])

    def test_arrival_fraction_increases_with_age(self):
        by_age = sorted(self.report["cohorts"], key=lambda r: r["age_months"])
        fracs = [row["arrival_fraction"] for row in by_age]
        self.assertEqual(fracs, sorted(fracs))

    def test_mature_cohorts_arrival_fraction_is_one(self):
        for row in self.report["cohorts"]:
            if row["age_months"] >= 8:
                self.assertEqual(row["arrival_fraction"], 1.0, row["cohort"])

    def test_every_row_states_what_can_be_claimed(self):
        texts = set()
        for row in self.report["cohorts"]:
            self.assertTrue(row["can_claim"])
            texts.add(row["can_claim"])
        self.assertEqual(len(texts), 3)  # one statement per label


class TestCLI(unittest.TestCase):
    def test_generate_ok(self):
        code, out = _run(["generate"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["n_records"], 12000)

    def test_report_ok_and_matches_library(self):
        code, out = _run(["report"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["arms"]["slow"]["naive"]["rate"], 0.125)
        self.assertEqual(payload["maturity"]["summary"]["claimable"], 6)

    def test_maturity_ok(self):
        code, out = _run(["maturity"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["summary"]["not claimable"], 2)

    def test_check_exit_codes(self):
        self.assertEqual(_run(["check", "--scenario", "delayed"])[0], EXIT_FAIL)
        self.assertEqual(_run(["check", "--scenario", "instant"])[0], EXIT_OK)
        self.assertEqual(_run(["check", "--input", "/nonexistent-book.json"])[0], EXIT_ERROR)

    def test_report_missing_input_is_error(self):
        code, _out = _run(["report", "--input", "/nonexistent-book.json"])
        self.assertEqual(code, EXIT_ERROR)


class TestServe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    def test_health(self):
        status, payload = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})

    def test_report_endpoint(self):
        status, payload = self._get("/report")
        self.assertEqual(status, 200)
        self.assertEqual(payload["arms"]["slow"]["completion"]["covers_truth"], True)

    def test_maturity_endpoint(self):
        status, payload = self._get("/maturity")
        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"], {"claimable": 6, "provisional": 4, "not claimable": 2})

    def test_unknown_endpoint_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
