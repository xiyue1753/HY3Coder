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


@dataclass
class StabilitySweep:
    """多组种子的稳定性扫描结果（报告里"换种子结论不变"那句话的依据）。"""

    pairs: int
    median_drift: float      # 各对种子漂移的中位数
    max_drift: float         # 各对种子漂移的最大值（判稳看这个）
    rate_low: float          # 所有重抽子集过程正确率的下界
    rate_high: float         # 上界
    over_threshold: int      # 越过 5pp 阈值的种子对数


def stability_sweep(
    records: list[EvalRecord],
    pairs: int = 20,
    sample_fraction: float = 0.6,
    threshold: float = 0.05,
) -> StabilitySweep:
    """同一份记录、多组种子的抽样稳定性扫描。

    ``stability_check`` 只报一对种子（默认 42/2026）的结果；单看那一对无法说明
    "结论是否依赖种子选择"。这里按固定规律换 ``pairs`` 组种子重跑同一检验，
    给出漂移的中位数与最大值：最大值仍在阈值内，才说明指标对样本构成不敏感。
    纯重抽既有记录，不调用模型；同一份记录 + 同样参数的结果逐位一致。
    """
    drifts: list[float] = []
    rates: list[float] = []
    for i in range(pairs):
        rep = stability_check(records, seed_a=i + 1, seed_b=i + 1001,
                              sample_fraction=sample_fraction)
        drifts.append(rep.drift)
        rates += [rep.seed_a, rep.seed_b]
    if not drifts:
        return StabilitySweep(0, 0.0, 0.0, 0.0, 0.0, 0)
    drifts.sort()
    mid = drifts[len(drifts) // 2] if len(drifts) % 2 else (
        (drifts[len(drifts) // 2 - 1] + drifts[len(drifts) // 2]) / 2)
    return StabilitySweep(
        pairs=len(drifts), median_drift=mid, max_drift=drifts[-1],
        rate_low=min(rates), rate_high=max(rates),
        over_threshold=sum(1 for d in drifts if d >= threshold),
    )
