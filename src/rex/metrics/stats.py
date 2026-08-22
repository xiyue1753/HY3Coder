"""Statistical inference: Wilson score interval + sampling stability check.

Wilson interval is the right tool for accuracy-style proportions on small
samples (per-tier 50~100) — it never collapses to a point estimate and stays
inside [0,1].
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from rex.models import EvalRecord, Verdict


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (lower, upper).

    successes <= n, n > 0. z=1.96 → 95% CI.
    """
    if n <= 0:
        return (0.0, 0.0)
    successes = min(successes, n)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass
class ProportionEstimate:
    value: float
    ci_low: float
    ci_high: float


def estimate_process_correctness(
    records: list[EvalRecord], z: float = 1.96,
) -> ProportionEstimate:
    n = len(records)
    k = sum(r.verification.verdict == Verdict.CORRECT for r in records)
    low, high = wilson_interval(k, n, z)
    return ProportionEstimate(k / n if n else 0.0, low, high)


def estimate_answer_accuracy(
    records: list[EvalRecord], z: float = 1.96,
) -> ProportionEstimate:
    n = len(records)
    k = sum(_answer_correct(r) for r in records)
    low, high = wilson_interval(k, n, z)
    return ProportionEstimate(k / n if n else 0.0, low, high)


def _answer_correct(r: EvalRecord) -> bool:
    if r.answer_correct is not None:
        return bool(r.answer_correct)
    return r.test_pass_rate is not None and r.test_pass_rate >= 1.0 and r.error is None


# ---------------------------------------------------------------------------
# Sampling stability: same-tier re-sampling comparison (可复现性验证)
# ---------------------------------------------------------------------------
@dataclass
class StabilityReport:
    seed_a: float
    seed_b: float
    drift: float      # 两次抽样过程正确率之差
    stable: bool      # drift < 5pp 视为稳定


def stability_check(
    records: list[EvalRecord],
    seed_a: int = 42,
    seed_b: int = 2026,
    sample_fraction: float = 0.6,
) -> StabilityReport:
    """Split records into two sub-samples with different seeds; compare metrics.

    Implementation: re-sample per difficulty tier with each seed, then compute
    process-correctness on both subsets. Large drift ⇒ stratification or
    sample size not yet representative.
    """
    from collections import defaultdict
    pools: dict[str, list[EvalRecord]] = defaultdict(list)
    for r in records:
        pools[r.difficulty.value].append(r)

    def _subsample(seed: int) -> list[EvalRecord]:
        rng = random.Random(seed)
        out: list[EvalRecord] = []
        for diff, pool in pools.items():
            rng.shuffle(pool)
            k = max(1, int(len(pool) * sample_fraction))
            out.extend(pool[:k])
        return out

    a, b = _subsample(seed_a), _subsample(seed_b)
    if not a or not b:
        return StabilityReport(0.0, 0.0, 0.0, False)
    pa = sum(r.verification.verdict == Verdict.CORRECT for r in a) / len(a)
    pb = sum(r.verification.verdict == Verdict.CORRECT for r in b) / len(b)
    drift = abs(pa - pb)
    return StabilityReport(pa, pb, drift, drift < 0.05)
