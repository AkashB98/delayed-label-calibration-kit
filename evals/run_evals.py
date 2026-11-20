"""Golden evals for delayed-label-calibration-kit.

Deterministic: eval_report.json is byte-identical across runs
(no timestamps, no temp paths). Run: python3 evals/run_evals.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibration import (build_completion_curves, build_report,  # noqa: E402
                         maturity_report, project_group)
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main  # noqa: E402
from generator import PLANTED_RATES, generate_book, planted_completion  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def _planted_label(age):
    frac = sum(PLANTED_RATES[s] * planted_completion(s, age)
               for s in PLANTED_RATES) / sum(PLANTED_RATES.values())
    return "claimable" if frac >= 0.95 else "provisional" if frac >= 0.50 else "not claimable"


def main():
    print("== golden evals: delayed-label-calibration-kit ==")
    records = generate_book()
    report = build_report(records)
    arms = report["arms"]
    curves = build_completion_curves(records)
    maturity = maturity_report(records)

    slow = arms["slow"]
    check("G1 naive understates slow segment by the planted amount (rate 0.125, bias -0.055)",
          slow["naive"]["rate"] == 0.125 and slow["naive"]["bias_vs_truth"] == -0.055,
          f"naive={slow['naive']['rate']} bias={slow['naive']['bias_vs_truth']} truth={slow['planted_truth']}")

    comp = slow["completion"]
    check("G2 completion estimate for slow lands within its CI of planted truth",
          comp["rate"] == 0.176126 and comp["ci_low"] == 0.158605
          and comp["ci_high"] == 0.193646 and comp["covers_truth"] is True,
          f"rate={comp['rate']} ci=[{comp['ci_low']}, {comp['ci_high']}] truth=0.18")

    fcomp = arms["fast"]["completion"]
    check("G3 completion estimate for fast covers planted truth; naive bias is small",
          fcomp["rate"] == 0.075926 and fcomp["covers_truth"] is True
          and arms["fast"]["naive"]["rate"] == 0.074
          and arms["fast"]["naive"]["bias_vs_truth"] == -0.006,
          f"fast completion={fcomp['rate']} naive={arms['fast']['naive']['rate']}")

    widths = [project_group(1000, round(1000 * 0.18 * c), c)["ci_width"]
              for c in (1.0, 0.5, 0.25)]
    check("G4 completion CI width increases as maturity (completion) decreases",
          widths[0] < widths[1] < widths[2],
          f"widths at completion 1.0/0.5/0.25 = {widths}")

    expected_labels = ["claimable"] * 6 + ["provisional"] * 4 + ["not claimable"] * 2
    labels = [row["label"] for row in maturity["cohorts"]]
    check("G5 maturity report labels pinned (6 claimable / 4 provisional / 2 not claimable)",
          labels == expected_labels
          and maturity["summary"] == {"claimable": 6, "provisional": 4, "not claimable": 2},
          f"summary={maturity['summary']}")

    check("G6 maturity labels match planted label-arrival fractions",
          all(row["label"] == _planted_label(row["age_months"]) for row in maturity["cohorts"])
          and maturity["cohorts"][-1]["arrival_fraction"] == 0.322304
          and maturity["cohorts"][5]["arrival_fraction"] == 0.962356,
          "per-cohort labels recomputed from planted arrival distributions agree")

    check("G7 completion curves pinned and built only from matured cohorts",
          curves["slow"]["curve"] == {"0": 0.0, "1": 0.055024, "2": 0.133971, "3": 0.277512,
                                      "4": 0.4689, "5": 0.700957, "6": 0.849282,
                                      "7": 0.949761, "8": 1.0}
          and curves["fast"]["curve"] == {"0": 0.0, "1": 0.70024, "2": 1.0}
          and curves["slow"]["built_from_cohorts"] == ["2024-07", "2024-08", "2024-09",
                                                       "2024-10", "2024-11"]
          and curves["slow"]["matured_defaults"] == 418,
          f"slow curve at MOB4={curves['slow']['curve']['4']} (planted 0.5)")

    filt = slow["maturity_filtered"]
    check("G8 maturity-filtered arm is unbiased-er but stale (excludes 7 slow cohorts)",
          filt["rate"] == 0.1672 and filt["n"] == 2500
          and len(filt["excluded_cohorts"]) == 7
          and abs(filt["bias_vs_truth"]) < abs(slow["naive"]["bias_vs_truth"]),
          f"filtered={filt['rate']} excluded={len(filt['excluded_cohorts'])}")

    codes = (_run_cli(["check", "--scenario", "delayed"]),
             _run_cli(["check", "--scenario", "instant"]),
             _run_cli(["check", "--input", "/nonexistent-book.json"]))
    check("G9 CLI check exit codes 1/0/2 (bias detected / instant control clean / IO error)",
          codes == (EXIT_FAIL, EXIT_OK, EXIT_ERROR),
          f"codes={codes}")

    instant = build_report(generate_book(scenario="instant"), scenario="instant")
    report2 = build_report(generate_book())
    check("G10 instant control has no naive bias + full report is deterministic",
          instant["arms"]["slow"]["naive"]["bias_vs_truth"] == -0.001833
          and instant["arms"]["slow"]["naive"]["rate"] == instant["arms"]["slow"]["completion"]["rate"]
          and json.dumps(report, sort_keys=True) == json.dumps(report2, sort_keys=True),
          f"instant slow naive={instant['arms']['slow']['naive']['rate']}")

    passed = sum(1 for r in RESULTS if r["passed"])
    out_report = {"kit": "delayed-label-calibration-kit",
                  "passed": passed, "total": len(RESULTS), "results": RESULTS}
    out = os.path.join(HERE, "eval_report.json")
    with open(out, "w") as f:
        json.dump(out_report, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"evals: {passed}/{len(RESULTS)} passed -> {out}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
