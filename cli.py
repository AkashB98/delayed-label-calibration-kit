"""CLI: generate / report / maturity / check / demo / serve.

SYNTHETIC DATA ONLY -- Meridian Sample Lending is a fictional lender
and every record handled here is fabricated sample data.

Exit codes:
  check : 0 = no material delayed-label bias detected (naive and
            completion estimates agree within tolerance),
          1 = delayed-label bias detected (the naive rate materially
            understates a segment; do not claim it),
          2 = usage / IO / data error
  others: 0 = success, 2 = usage / IO error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration import build_report, maturity_report  # noqa: E402
from generator import SCENARIOS, generate_book  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2

# A naive-vs-completion gap above this (rate points) in any segment is
# a material delayed-label bias: the naive number must not be claimed.
BIAS_TOLERANCE = 0.02


def canonical(payload):
    return json.dumps(payload, indent=2, sort_keys=True)


def _dump(obj):
    print(canonical(obj))


def _load_records(args):
    """Records from --input JSON file, or the generated book."""
    if getattr(args, "input", None):
        with open(args.input, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "records" in data:
            data = data["records"]
        if not isinstance(data, list):
            raise ValueError("input must be a JSON list of records")
        return data
    return generate_book(scenario=getattr(args, "scenario", "delayed"))


def cmd_generate(args):
    records = generate_book(scenario=args.scenario)
    summary = {}
    for cohort in sorted({r["cohort"] for r in records}):
        rows = [r for r in records if r["cohort"] == cohort]
        summary[cohort] = {
            "age_months": rows[0]["age_months"], "n": len(rows),
            "observed_default_rate": round(sum(r["observed_default"] for r in rows) / len(rows), 6),
            "ultimate_default_rate": round(sum(r["ultimate_default"] for r in rows) / len(rows), 6),
        }
    _dump({"scenario": args.scenario, "n_records": len(records), "cohorts": summary})
    return EXIT_OK


def cmd_report(args):
    records = _load_records(args)
    _dump(build_report(records, scenario=args.scenario))
    return EXIT_OK


def cmd_maturity(args):
    records = _load_records(args)
    _dump(maturity_report(records, scenario=args.scenario))
    return EXIT_OK


def cmd_check(args):
    if getattr(args, "input", None) and not os.path.exists(args.input):
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return EXIT_ERROR
    records = _load_records(args)
    report = build_report(records, scenario=args.scenario)
    worst = 0.0
    worst_segment = None
    for segment, arm in report["arms"].items():
        gap = abs(arm["completion"]["rate"] - arm["naive"]["rate"])
        print(f"segment={segment} naive={arm['naive']['rate']} "
              f"completion={arm['completion']['rate']} gap={round(gap, 6)} "
              f"tolerance={BIAS_TOLERANCE}")
        if gap > worst:
            worst, worst_segment = gap, segment
    if worst > BIAS_TOLERANCE:
        print(f"check FAIL (delayed-label bias): segment {worst_segment} "
              f"naive understates by {round(worst, 6)} -- naive rate is not claimable")
        return EXIT_FAIL
    print("check PASS: no material delayed-label bias detected")
    return EXIT_OK


def cmd_demo(args):
    import demo as demo_mod
    try:
        return demo_mod.run()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL


# ------------------------------------------------------------------- serve

class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = (canonical(payload) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if self.path == "/report":
            return self._send_json(200, build_report(generate_book(), scenario="delayed"))
        if self.path == "/maturity":
            return self._send_json(200, maturity_report(generate_book(), scenario="delayed"))
        return self._send_json(404, {"error": "unknown endpoint"})

    def log_message(self, *a):
        pass


def make_server(port):
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args):
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  (GET /health, GET /report, GET /maturity)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser():
    p = argparse.ArgumentParser(prog="cli.py",
                                description="Delayed-label calibration kit (synthetic data only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="dataset summary for the seeded book")
    g.add_argument("--scenario", choices=SCENARIOS, default="delayed")
    g.set_defaults(func=cmd_generate)

    for name, fn, helptext in (
            ("report", cmd_report, "full report: curves, three arms vs truth, maturity"),
            ("maturity", cmd_maturity, "label-maturity report per cohort")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--scenario", choices=SCENARIOS, default="delayed")
        sp.add_argument("--input", default=None)
        sp.set_defaults(func=fn)

    c = sub.add_parser("check", help="CI gate: exit 0 no bias / 1 bias detected / 2 error")
    c.add_argument("--scenario", choices=SCENARIOS, default="delayed")
    c.add_argument("--input", default=None)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    sv = sub.add_parser("serve", help="localhost JSON API")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
