"""Deterministic synthetic loan book with planted label delays, seed 42.

Fictional lender: Meridian Sample Lending. Every borrower is fictional.

The book has 12 monthly cohorts (vintages) observed at one snapshot.
The oldest cohort is 12 months on book at the snapshot; the youngest
is 1 month on book. Two segments carry different planted label lags:

- ``fast``: ultimate default rate 0.08; a default, if it happens, is
  observed at month-on-book 1 (70%) or 2 (30%) -- complete by MOB 2.
- ``slow``: ultimate default rate 0.18; defaults surface slowly --
  cumulative arrival 5% / 15% / 30% / 50% / 70% / 85% / 95% / 100%
  by MOB 1..8 -- complete by MOB 8.

A record carries both the ground truth (``ultimate_default`` -- what
the label will eventually be) and what is actually visible at the
snapshot (``observed_default`` and ``arrival_mob``, set only when the
default has already surfaced). Estimation code in this kit reads only
the observed fields; the ultimate field exists so the synthetic POC
can score each evaluation arm against planted truth.

Control scenario ``instant``: every default surfaces at MOB 1, so by
the snapshot every cohort aged >= 1 month is fully labeled and the
naive estimate is unbiased. It exists to prove the check gate stays
silent when there is no delay to detect.

Stdlib only. No network, no real data.
"""
from __future__ import annotations

import random

SEED = 42

SEGMENTS = ["fast", "slow"]

# Planted ground truth: ultimate (eventual) default rate per segment.
PLANTED_RATES = {"fast": 0.08, "slow": 0.18}

# Planted arrival distributions: {arrival MOB: probability} for a loan
# that will ultimately default. Support max = the segment horizon.
ARRIVAL_DIST = {
    "fast": {1: 0.70, 2: 0.30},
    "slow": {1: 0.05, 2: 0.10, 3: 0.15, 4: 0.20,
             5: 0.20, 6: 0.15, 7: 0.10, 8: 0.05},
}
ARRIVAL_DIST_INSTANT = {"fast": {1: 1.0}, "slow": {1: 1.0}}

# Last MOB at which a default can surface, per segment (delayed case).
HORIZONS = {"fast": 2, "slow": 8}
HORIZONS_INSTANT = {"fast": 1, "slow": 1}

# Monthly cohorts, oldest first. Age = months on book at the snapshot.
COHORTS = [
    ("2024-07", 12), ("2024-08", 11), ("2024-09", 10), ("2024-10", 9),
    ("2024-11", 8), ("2024-12", 7), ("2025-01", 6), ("2025-02", 5),
    ("2025-03", 4), ("2025-04", 3), ("2025-05", 2), ("2025-06", 1),
]
COHORT_AGES = dict(COHORTS)

N_PER_SEGMENT_COHORT = 500

SCENARIOS = ["delayed", "instant"]


def planted_completion(segment, mob, scenario="delayed"):
    """Planted cumulative share of ultimate defaults surfaced by MOB."""
    dist = ARRIVAL_DIST_INSTANT[segment] if scenario == "instant" else ARRIVAL_DIST[segment]
    return round(sum(p for m, p in dist.items() if m <= mob), 6)


def _sample_arrival(rng, dist):
    r = rng.random()
    acc = 0.0
    for mob in sorted(dist):
        acc += dist[mob]
        if r < acc:
            return mob
    return max(dist)


def _one(rng, cohort, age, segment, scenario):
    rate = PLANTED_RATES[segment]
    ultimate = 1 if rng.random() < rate else 0
    observed = 0
    arrival_mob = None
    if ultimate:
        dist = ARRIVAL_DIST_INSTANT[segment] if scenario == "instant" else ARRIVAL_DIST[segment]
        true_arrival = _sample_arrival(rng, dist)
        if true_arrival <= age:
            observed = 1
            arrival_mob = true_arrival
    return {
        "cohort": cohort,
        "age_months": age,
        "segment": segment,
        "ultimate_default": ultimate,
        "observed_default": observed,
        "arrival_mob": arrival_mob,
    }


def generate_book(scenario="delayed", seed=SEED):
    """Generate the canonical loan book (deterministic).

    12 cohorts x 2 segments x 500 loans = 12,000 records.
    Seed offsets are derived from fixed cohort/segment indices, never
    from Python's salted hash, so the book is byte-stable everywhere.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario!r} (choose from {SCENARIOS})")
    records = []
    for ci, (cohort, age) in enumerate(COHORTS):
        for si, segment in enumerate(SEGMENTS):
            rng = random.Random(seed + ci * 10000 + si * 100000 + N_PER_SEGMENT_COHORT)
            for _ in range(N_PER_SEGMENT_COHORT):
                records.append(_one(rng, cohort, age, segment, scenario))
    return records


def horizons_for(scenario="delayed"):
    return dict(HORIZONS_INSTANT if scenario == "instant" else HORIZONS)
