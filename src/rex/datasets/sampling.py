"""Stratified sampling across difficulty tiers with a fixed seed.

题库入库规模（算法 500+ / 数学 300+）与评估运行规模（默认 300 题）
分离：sampling 从已入库的题库中按三档分层抽取运行子集，种子固定保证可复现。
--sample 档位: 5 / 10 / 50 / 100 / full
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Literal

from rex.models import Difficulty, QuestionItem

SampleSize = Literal["5", "10", "50", "100", "full"]

# 每档目标数：--sample=100 档 = 每难度档 100 题 → 运行 300 题（3 档 × 100）
# 5/10/50 为渐进 demo 档，保证分档统计置信区间的档位是 100。
_ALGO_PER_TIER = {"5": 2, "10": 4, "50": 20, "100": 100, "full": None}
_MATH_PER_TIER = {"5": 1, "10": 3, "50": 15, "100": 100, "full": None}


def difficulty_stats(items: list[QuestionItem]) -> dict[str, int]:
    return dict(Counter(it.difficulty.value for it in items))


def stratified_sample(
    items: list[QuestionItem],
    scene: Literal["algorithm", "math"],
    sample: SampleSize,
    seed: int = 42,
) -> list[QuestionItem]:
    """Sample `per_tier` items per difficulty tier.

    `full` returns everything (used for the final full-scale run).
    """
    if sample == "full":
        return list(items)

    per_tier = _ALGO_PER_TIER[sample] if scene == "algorithm" else _MATH_PER_TIER[sample]
    if per_tier is None:
        return list(items)

    rng = random.Random(seed)
    picked: list[QuestionItem] = []
    for diff in Difficulty:
        pool = [it for it in items if it.difficulty == diff]
        rng.shuffle(pool)
        n = min(per_tier, len(pool))
        picked.extend(pool[:n])
    # 稳定输出顺序（按原 id）
    order = {it.id: i for i, it in enumerate(items)}
    picked.sort(key=lambda it: order[it.id])
    return picked


def sample_sizes(
    scene: Literal["algorithm", "math"],
    sample: SampleSize,
    items: list[QuestionItem] | None = None,
) -> int | None:
    """Target sample size for the given tier setting.

    Without ``items`` this is the *theoretical upper bound* (per_tier × 3).
    Pass the real question pool to get the *actual* stratified_sample size,
    which is lower when a tier pool is smaller than per_tier
    (e.g. math hard=80 → 100 档实际 274 而非 300).
    """
    per_tier = _ALGO_PER_TIER[sample] if scene == "algorithm" else _MATH_PER_TIER[sample]
    if per_tier is None:
        return None
    if items is None:
        return per_tier * 3
    pools = Counter(it.difficulty for it in items)
    return sum(min(per_tier, pools[d]) for d in Difficulty)
