"""Paired tests and claim-level bootstrap. Standard library only."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * p
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return sorted_values[low]
    weight = index - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _binom_two_sided(successes: int, n: int) -> float:
    """Two-sided exact test of Binomial(n, 0.5). No discordant pairs => 1."""
    if n <= 0:
        return 1.0
    tail = min(successes, n - successes)
    ways = sum(math.comb(n, i) for i in range(tail + 1))
    return min(1.0, 2.0 * ways / (1 << n))


def _align(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_right = {(row["claim_id"], row["seed"]): row for row in right}
    pairs = []
    for row in left:
        key = (row["claim_id"], row["seed"])
        if key not in by_right:
            raise KeyError(f"missing paired trial for {key[0]} seed {key[1]}")
        pairs.append((row, by_right[key]))
    if len(pairs) != len(right):
        raise KeyError("paired trials are not the same set of (claim, seed)")
    return pairs


def bootstrap_pass_rate_ci(
    trials: list[dict[str, Any]],
    *,
    resamples: int = 4000,
    seed: int = 20261115,
) -> dict[str, Any]:
    """95% percentile CI. Resample claims, keep every seed of a drawn claim.

    A claim drawn twice counts twice. That matches the question "is the rate
    sensitive to which claims we happened to include?"
    """
    if resamples < 1:
        raise ValueError("resamples must be positive")
    graded = [row for row in trials if row.get("passed") is not None]
    if not graded:
        raise ValueError("no graded trials")
    by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in graded:
        by_claim[str(row["claim_id"])].append(row)
    claims = sorted(by_claim)
    point = sum(1 for row in graded if row["passed"]) / len(graded)
    rng = random.Random(seed)
    rates: list[float] = []
    for _ in range(resamples):
        drawn = [rng.choice(claims) for _ in claims]
        passed = 0
        total = 0
        for claim_id in drawn:
            rows = by_claim[claim_id]
            total += len(rows)
            passed += sum(1 for row in rows if row["passed"])
        rates.append(passed / total)
    rates.sort()
    return {
        "point": point,
        "low": _percentile(rates, 0.025),
        "high": _percentile(rates, 0.975),
        "resamples": resamples,
        "seed": seed,
        "unit": "claim",
        "n_claims": len(claims),
        "n_trials": len(graded),
    }


def mcnemar_exact(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact McNemar on paired pass/fail. b = left fail & right pass, c = left pass & right fail."""
    b = 0
    c = 0
    for left_row, right_row in _align(left, right):
        left_pass = bool(left_row["passed"])
        right_pass = bool(right_row["passed"])
        if (not left_pass) and right_pass:
            b += 1
        elif left_pass and (not right_pass):
            c += 1
    discordant = b + c
    return {
        "b_left_fail_right_pass": b,
        "c_left_pass_right_fail": c,
        "b": b,
        "c": c,
        "discordant": discordant,
        "p_value": _binom_two_sided(b, discordant),
        "test": "exact_mcnemar_binomial_0.5",
        "alpha": 0.05,
    }


def sign_test(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    value: str,
) -> dict[str, Any]:
    """Two-sided sign test. Ties are dropped. positive means left > right."""
    positive = 0
    negative = 0
    ties = 0
    for left_row, right_row in _align(left, right):
        left_value = float(left_row[value])
        right_value = float(right_row[value])
        if left_value > right_value:
            positive += 1
        elif left_value < right_value:
            negative += 1
        else:
            ties += 1
    n = positive + negative
    return {
        "value": value,
        "positive": positive,
        "negative": negative,
        "ties": ties,
        "n": n,
        "p_value": _binom_two_sided(positive, n),
        "test": "exact_sign_test",
        "alpha": 0.05,
    }
