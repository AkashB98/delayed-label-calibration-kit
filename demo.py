"""End-to-end demo: generate -> curves -> three arms -> maturity
report -> check gate -> live localhost serve round-trip.

SYNTHETIC DATA ONLY (fictional Meridian Sample Lending book). Runs
fully offline; the serve round-trip is loopback-only on an ephemeral
port. Every stage asserts.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration import build_report, maturity_report  # noqa: E402
from cli import EXIT_FAIL, EXIT_OK, main as cli_main, make_server  # noqa: E402
from generator import generate_book  # noqa: E402


def _request(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def run():
    print("== delayed-label-calibration-kit demo ==")
    print("\n== 1. generate synthetic loan book (seed=42) ==")
    records = generate_book()
    again = generate_book()
    assert records == again, "generator must be deterministic"
    assert len(records) == 12000, len(records)
    print(f"   {len(records)} loans, 12 cohorts x 2 segments, deterministic")

    print("\n== 2. three arms vs planted truth ==")
    report = build_report(records)
    for segment in ("fast", "slow"):
        arm = report["arms"][segment]
        print(f"   [{segment}] truth={arm['planted_truth']} "
              f"naive={arm['naive']['rate']} (bias {arm['naive']['bias_vs_truth']}) "
              f"filtered={arm['maturity_filtered']['rate']} "
              f"(excludes {len(arm['maturity_filtered']['excluded_cohorts'])} cohorts) "
              f"completion={arm['completion']['rate']} "
              f"CI [{arm['completion']['ci_low']}, {arm['completion']['ci_high']}] "
              f"covers_truth={arm['completion']['covers_truth']}")
    slow = report["arms"]["slow"]
    assert slow["naive"]["bias_vs_truth"] < -0.03, slow["naive"]
    assert slow["completion"]["covers_truth"] is True
    fast = report["arms"]["fast"]
    assert abs(fast["naive"]["bias_vs_truth"]) < abs(slow["naive"]["bias_vs_truth"])

    print("\n== 3. label-maturity report ==")
    maturity = maturity_report(records)
    for row in maturity["cohorts"]:
        print(f"   {row['cohort']} age={row['age_months']:2d} "
              f"arrived={row['arrival_fraction']} -> {row['label']}")
    print(f"   summary: {maturity['summary']}")
    assert maturity["cohorts"][-1]["label"] == "not claimable"
    assert maturity["cohorts"][0]["label"] == "claimable"

    print("\n== 4. CLI check gate ==")
    code_delayed = cli_main(["check", "--scenario", "delayed"])
    code_instant = cli_main(["check", "--scenario", "instant"])
    code_err = cli_main(["check", "--input", "/tmp/no-such-delayed-label-xyz.json"])
    print(f"   delayed={code_delayed} instant={code_instant} missing-file={code_err}")
    assert (code_delayed, code_instant, code_err) == (EXIT_FAIL, EXIT_OK, 2)

    print("\n== 5. live localhost serve round-trip ==")
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}, health
        status, served = _request(port, "/report")
        assert status == 200 and served["arms"]["slow"]["naive"]["rate"] == slow["naive"]["rate"]
        status, served_mat = _request(port, "/maturity")
        assert status == 200 and served_mat["summary"] == maturity["summary"]
        print("   GET /health, /report and /maturity match local computation")
    finally:
        server.shutdown()
        server.server_close()

    print("\nDemo OK: naive bias exposed, completion covers truth, "
          "maturity labels, check gate and serve verified.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
