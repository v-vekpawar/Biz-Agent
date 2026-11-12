"""
Decision statistics for validation sprints.

Everything in this module is pure, deterministic code - no LLM. The verdict a
user sees is computed here from the logged counts and the thresholds that were
locked BEFORE any data arrived.

Method: Wilson score interval for a binomial proportion (better behaved than
the normal approximation for small n and extreme rates).

Decision rule for one metric (k successes out of n trials, interval [lo, hi]):

    n < min_sample                      -> keep_running  (inconclusive once finished)
    lo >= success_rate                  -> go            (credibly at/above target)
    hi <  failure_rate                  -> stop          (credibly below the floor)
    lo >= failure_rate and hi < success_rate
                                        -> pivot         (credibly in between: some pull, below target)
    otherwise (interval straddles a threshold)
                                        -> keep_running  (inconclusive once finished)

Across metrics: the PRIMARY metric decides. A `go` is downgraded to `pivot`
when a supporting metric is credibly at `stop` (mixed signals are not a go).
"""

from __future__ import annotations

import math
from typing import Any

from ..domain.enums import MetricKey, Verdict

# z-scores for the confidence levels we allow (two-sided).
Z_BY_CONFIDENCE = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600}
ALLOWED_CONFIDENCE = tuple(sorted(Z_BY_CONFIDENCE))

# Hard floors: below these the interval is too wide to say anything useful.
MIN_SAMPLE_FLOOR = {
    MetricKey.WAITLIST_CONVERSION.value: 30,
    MetricKey.INTERVIEW_COMMITMENT.value: 5,
}

METRIC_LABELS = {
    MetricKey.WAITLIST_CONVERSION.value: ("Waitlist conversion", "visitors who joined the waitlist", "unique visitors"),
    MetricKey.INTERVIEW_COMMITMENT.value: ("Interview commitment", "conversations that ended in a concrete commitment", "conversations"),
}


def wilson_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval. Returns (0, 1) when there are no trials."""
    if trials <= 0:
        return 0.0, 1.0
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between 0 and trials.")
    z = Z_BY_CONFIDENCE.get(round(confidence, 2))
    if z is None:
        raise ValueError(f"confidence must be one of {ALLOWED_CONFIDENCE}.")
    p = successes / trials
    z2 = z * z
    denom = 1 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denom
    half = (z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def suggested_min_sample(success_rate: float, confidence: float = 0.90, lift: float = 1.5, cap: int = 5000) -> int:
    """Smallest n for which an observed rate of `success_rate * lift` would
    produce a Wilson lower bound at or above `success_rate`.

    Plain-language meaning: "if the true rate is 50% better than your target,
    this many trials are enough to be able to call it a go." It is a planning
    hint, not a power guarantee.
    """
    observed = min(0.99, success_rate * lift)
    for n in range(5, cap + 1):
        k = math.ceil(round(observed * n, 9))  # round: avoid float noise (0.15*60 -> 9.000000000000002)
        lo, _ = wilson_interval(k, n, confidence)
        if lo >= success_rate:
            return n
    return cap


def evaluate_metric(
    successes: int,
    trials: int,
    *,
    success_rate: float,
    failure_rate: float,
    min_sample: int,
    confidence: float,
    finished: bool,
    unit: str = "trials",
) -> dict[str, Any]:
    """Apply the decision rule to one metric. `finished` = deadline passed or
    the user ended the sprint, which turns "keep running" into "inconclusive"."""
    lo, hi = wilson_interval(successes, trials, confidence)
    rate = successes / trials if trials else None
    undecided = Verdict.INCONCLUSIVE if finished else Verdict.KEEP_RUNNING

    if trials < min_sample:
        verdict = undecided
        reason = f"{trials} of the {min_sample} required {unit} so far - too few to call."
        code = "below_min_sample"
    elif lo >= success_rate:
        verdict, code = Verdict.GO, "lower_bound_above_target"
        reason = f"Even the cautious end of the range ({_pct(lo)}) clears the {_pct(success_rate)} target."
    elif hi < failure_rate:
        verdict, code = Verdict.STOP, "upper_bound_below_floor"
        reason = f"Even the optimistic end of the range ({_pct(hi)}) is under the {_pct(failure_rate)} floor."
    elif lo >= failure_rate and hi < success_rate:
        verdict, code = Verdict.PIVOT, "between_floor_and_target"
        reason = f"The range ({_pct(lo)} to {_pct(hi)}) sits above the {_pct(failure_rate)} floor but below the {_pct(success_rate)} target."
    else:
        verdict, code = undecided, "interval_straddles_threshold"
        reason = (
            f"The range ({_pct(lo)} to {_pct(hi)}) still overlaps the "
            f"{_pct(failure_rate)} floor or the {_pct(success_rate)} target."
        )
    return {
        "successes": successes,
        "trials": trials,
        "rate": rate,
        "lower": lo,
        "upper": hi,
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "min_sample": min_sample,
        "confidence": confidence,
        "verdict": verdict.value,
        "code": code,
        "reason": reason,
    }


def combine(primary: dict[str, Any], supporting: list[dict[str, Any]]) -> tuple[Verdict, list[str]]:
    """Primary metric decides; a `go` with a credibly failing supporting metric becomes `pivot`."""
    verdict = Verdict(primary["verdict"])
    notes: list[str] = []
    stopped = [m for m in supporting if m["verdict"] == Verdict.STOP.value]
    if verdict == Verdict.GO and stopped:
        verdict = Verdict.PIVOT
        names = ", ".join(m["label"] for m in stopped)
        notes.append(f"Primary metric passed, but {names} is credibly below its floor, so this is a pivot, not a go.")
    return verdict, notes


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".0%", "%")


def pct(value: float | None) -> str:
    return "n/a" if value is None else _pct(value)
