"""Life-table completion, three evaluation arms, and the maturity report.

The completion method is the standard actuarial life-table /
cumulative-incidence idea (chain-ladder style development factors,
in the form long used for insurance claims and credit vintages):
from cohorts old enough to be fully labeled, learn what share of
ultimate defaults has typically surfaced by each month on book; then
divide a young cohort's observed defaults by that share to project
its ultimate defaults. Nothing here is a new statistical method --
the kit's work is applying the standard method honestly, with
intervals that widen as less of a cohort has surfaced, and with an
explicit statement of what cannot be claimed yet.

Estimation reads ONLY observed fields (``observed_default``,
``arrival_mob``, ``cohort``, ``age_months``, ``segment``). The
``ultimate_default`` field is read in exactly one place --
``evaluate_arms`` -- to score the arms against the synthetic ground
truth, which is the point of a planted-truth POC.
"""
from __future__ import annotations

import math

from generator import COHORTS, PLANTED_RATES, SEGMENTS, horizons_for, planted_completion

Z_95 = 1.96

# Claimability thresholds on the estimated fraction of a cohort's
# ultimate defaults that have already surfaced.
CLAIMABLE_AT = 0.95
PROVISIONAL_AT = 0.50

_CLAIMS = {
    "claimable": "Ultimate default rate can be claimed for this cohort: "
                 "essentially all labels have arrived, so the observed "
                 "rate and the completion projection agree.",
    "provisional": "Report direction only, using the completion "
                   "projection and its confidence interval. Do not claim "
                   "a final ultimate default rate for this cohort yet.",
    "not claimable": "Do not claim an ultimate default rate for this "
                     "cohort yet: most of its defaults have not surfaced, "
                     "so any rate quoted now would understate the truth.",
}


def _r6(x):
    return round(float(x), 6)


# ------------------------------------------------------------ completion

def build_completion_curves(records, scenario="delayed"):
    """Per-segment completion curve built ONLY from matured cohorts.

    A cohort counts as matured for a segment when its age reaches the
    segment horizon (the last MOB at which a default can surface), so
    every default it will ever show has already shown. Pooling those
    cohorts, the curve at MOB m is: defaults with arrival_mob <= m,
    divided by all defaults in the pooled matured cohorts.
    """
    horizons = horizons_for(scenario)
    curves = {}
    for segment in SEGMENTS:
        horizon = horizons[segment]
        matured = [r for r in records
                   if r["segment"] == segment and r["age_months"] >= horizon]
        matured_cohorts = sorted({r["cohort"] for r in matured})
        defaults = [r for r in matured if r["observed_default"] == 1]
        total = len(defaults)
        curve = {"0": 0.0}
        for m in range(1, horizon + 1):
            cum = sum(1 for r in defaults if r["arrival_mob"] is not None and r["arrival_mob"] <= m)
            curve[str(m)] = _r6(cum / total) if total else 0.0
        curves[segment] = {
            "horizon": horizon,
            "built_from_cohorts": matured_cohorts,
            "matured_n": len(matured),
            "matured_defaults": total,
            "curve": curve,
        }
    return curves


def completion_at(curve_entry, age):
    """Estimated share of ultimate defaults surfaced by ``age`` MOB."""
    horizon = curve_entry["horizon"]
    if age >= horizon:
        return 1.0
    return float(curve_entry["curve"][str(age)])


def project_group(n, observed_defaults, completion):
    """Project one cohort-segment group's ultimate rate + 95% CI.

    Observed defaults k out of n, with only ``completion`` of ultimate
    defaults surfaced: p_observed = p_ultimate * completion, so the
    projection divides by completion. The normal-approximation CI on
    p_observed divides by the same factor, which is exactly why the
    interval widens as completion (maturity) falls.
    """
    if n <= 0:
        raise ValueError("group size must be positive")
    if completion <= 0:
        return {"n": n, "observed_defaults": observed_defaults,
                "completion": _r6(completion), "observed_rate": _r6(observed_defaults / n),
                "projected_rate": None, "ci_low": None, "ci_high": None,
                "ci_width": None}
    p_obs = observed_defaults / n
    se = math.sqrt(p_obs * (1.0 - p_obs) / n) if 0.0 < p_obs < 1.0 else 0.0
    lo = max(0.0, p_obs - Z_95 * se) / completion
    hi = min(1.0, (p_obs + Z_95 * se) / completion)
    return {"n": n, "observed_defaults": observed_defaults,
            "completion": _r6(completion), "observed_rate": _r6(p_obs),
            "projected_rate": _r6(p_obs / completion),
            "ci_low": _r6(lo), "ci_high": _r6(hi), "ci_width": _r6(hi - lo)}


def _groups(records):
    """(cohort, segment) -> list of records, in canonical order."""
    out = {}
    for cohort, _age in COHORTS:
        for segment in SEGMENTS:
            out[(cohort, segment)] = []
    for r in records:
        out[(r["cohort"], r["segment"])].append(r)
    return out


# ------------------------------------------------------------ three arms

def evaluate_arms(records, scenario="delayed"):
    """Score the three evaluation arms against planted truth.

    1. naive: observed rate over every cohort (not-yet-surfaced
       defaults counted as non-defaults -- the lie this kit exposes).
    2. maturity-filtered: observed rate over matured cohorts only.
       Unbiased for those cohorts, but stale: it says nothing about
       any recent vintage.
    3. completion: every cohort-segment group projected through the
       completion curve, then pooled. Current, with an honest CI.
    """
    horizons = horizons_for(scenario)
    curves = build_completion_curves(records, scenario=scenario)
    groups = _groups(records)
    arms = {}
    for segment in SEGMENTS:
        horizon = horizons[segment]
        seg_records = [r for r in records if r["segment"] == segment]
        n_all = len(seg_records)
        k_all = sum(r["observed_default"] for r in seg_records)
        naive = k_all / n_all if n_all else 0.0

        matured = [r for r in seg_records if r["age_months"] >= horizon]
        n_mat = len(matured)
        k_mat = sum(r["observed_default"] for r in matured)
        filtered = k_mat / n_mat if n_mat else 0.0
        excluded = sorted({r["cohort"] for r in seg_records
                           if r["age_months"] < horizon})

        proj_defaults = 0.0
        var_defaults = 0.0
        n_proj = 0
        for (cohort, seg), rows in groups.items():
            if seg != segment or not rows:
                continue
            age = rows[0]["age_months"]
            comp = completion_at(curves[segment], age)
            k = sum(r["observed_default"] for r in rows)
            n = len(rows)
            n_proj += n
            if comp > 0:
                proj_defaults += k / comp
                p_obs = k / n if n else 0.0
                var_defaults += (n * p_obs * (1.0 - p_obs)) / (comp * comp) if n else 0.0
        comp_rate = proj_defaults / n_proj if n_proj else 0.0
        se_rate = math.sqrt(var_defaults) / n_proj if n_proj else 0.0
        ci_low = max(0.0, comp_rate - Z_95 * se_rate)
        ci_high = min(1.0, comp_rate + Z_95 * se_rate)

        truth = PLANTED_RATES[segment]
        empirical = (sum(r["ultimate_default"] for r in seg_records) / n_all) if n_all else 0.0
        arms[segment] = {
            "planted_truth": truth,
            "empirical_ultimate_rate": _r6(empirical),
            "naive": {"rate": _r6(naive), "n": n_all,
                      "bias_vs_truth": _r6(naive - truth)},
            "maturity_filtered": {"rate": _r6(filtered), "n": n_mat,
                                  "bias_vs_truth": _r6(filtered - truth),
                                  "excluded_cohorts": excluded},
            "completion": {"rate": _r6(comp_rate), "n": n_proj,
                           "bias_vs_truth": _r6(comp_rate - truth),
                           "ci_low": _r6(ci_low), "ci_high": _r6(ci_high),
                           "ci_width": _r6(ci_high - ci_low),
                           "covers_truth": bool(ci_low <= truth <= ci_high)},
        }
    return {"scenario": scenario, "curves": curves, "segments": arms}


# ------------------------------------------------------------ maturity report

def maturity_report(records, scenario="delayed"):
    """Per-cohort label-maturity report -- the headline artifact.

    For each cohort, the fraction of its ultimate defaults estimated
    to have surfaced is observed defaults / projected ultimate
    defaults (projection via the completion curve). Labels:
    >= 0.95 claimable, >= 0.50 provisional, below that not claimable.
    """
    curves = build_completion_curves(records, scenario=scenario)
    groups = _groups(records)
    rows = []
    for cohort, age in COHORTS:
        n = 0
        observed = 0
        projected = 0.0
        seg_detail = {}
        for segment in SEGMENTS:
            grp = groups[(cohort, segment)]
            k = sum(r["observed_default"] for r in grp)
            comp = completion_at(curves[segment], age)
            proj = (k / comp) if comp > 0 else 0.0
            seg_detail[segment] = {
                "n": len(grp), "observed_defaults": k,
                "completion": _r6(comp), "projected_defaults": _r6(proj),
                "planted_arrival_fraction": planted_completion(segment, age, scenario),
            }
            n += len(grp)
            observed += k
            projected += proj
        fraction = (observed / projected) if projected > 0 else 0.0
        if fraction >= CLAIMABLE_AT:
            label = "claimable"
        elif fraction >= PROVISIONAL_AT:
            label = "provisional"
        else:
            label = "not claimable"
        rows.append({
            "cohort": cohort, "age_months": age, "n": n,
            "observed_defaults": observed,
            "projected_ultimate_defaults": _r6(projected),
            "arrival_fraction": _r6(fraction),
            "label": label,
            "can_claim": _CLAIMS[label],
            "segments": seg_detail,
        })
    summary = {label: sum(1 for r in rows if r["label"] == label)
               for label in ("claimable", "provisional", "not claimable")}
    return {"scenario": scenario, "thresholds": {"claimable_at": CLAIMABLE_AT,
                                                 "provisional_at": PROVISIONAL_AT},
            "cohorts": rows, "summary": summary}


def build_report(records, scenario="delayed"):
    """Full report: curves, three arms vs truth, and the maturity report."""
    arms = evaluate_arms(records, scenario=scenario)
    maturity = maturity_report(records, scenario=scenario)
    return {
        "kit": "delayed-label-calibration-kit",
        "lender": "Meridian Sample Lending (fictional)",
        "scenario": scenario,
        "n_records": len(records),
        "planted_truth": dict(PLANTED_RATES),
        "completion_curves": arms["curves"],
        "arms": arms["segments"],
        "maturity": maturity,
    }
