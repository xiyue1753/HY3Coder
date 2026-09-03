"""Stratified sampling across difficulty tiers with a fixed seed.

题库入库规模（算法 500+ / 数学 300+）与评估运行规模（默认 300 题）
分离：sampling 从已入库的题库中按三档分层抽取运行子集，种子固定保证可复现。
--sample 档位: 5 / 10 / 50 / 100 / full

另提供 audit_records_sample：从已评估记录（EvalRecord）中按
「答案正确性 × 判定」分层抽取人工抽检样本，对齐任务书 P4 两套分母
（定位准确率用答案错误样本、误报率用答案正确样本）。
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Literal

from rex.models import Difficulty, EvalRecord, QuestionItem, Verdict

SampleSize = Literal["5", "10", "50", "100", "full"]

# 每档目标数：--sample=100 档 = 每难度档 100 题 → 运行 300 题（3 档 × 100）
# 5/10/50 为渐进 demo 档，保证分档统计置信区间的档位是 100。
_ALGO_PER_TIER = {"5": 2, "10": 4, "50": 20, "100": 100, "full": None}
_MATH_PER_TIER = {"5": 1, "10": 3, "50": 15, "100": 100, "full": None}


def _active(items: list[QuestionItem]) -> list[QuestionItem]:
    """Filter out deprecated questions (metadata.deprecated=true).

    Used by stratified_sample / sample_sizes so abandoned sources never enter
    evaluation sampling (including the `full` scale run).
    """
    return [it for it in items if not it.metadata.get("deprecated")]


def difficulty_stats(items: list[QuestionItem]) -> dict[str, int]:
    return dict(Counter(it.difficulty.value for it in _active(items)))


def stratified_sample(
    items: list[QuestionItem],
    scene: Literal["algorithm", "math"],
    sample: SampleSize,
    seed: int = 42,
) -> list[QuestionItem]:
    """Sample `per_tier` items per difficulty tier.

    Deprecated questions are excluded up front. `full` returns everything
    active (used for the final full-scale run).
    """
    items = _active(items)
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
    items = _active(items)
    pools = Counter(it.difficulty for it in items)
    return sum(min(per_tier, pools[d]) for d in Difficulty)


# ---------------------------------------------------------------------------
# 人工抽检分层抽样（基于评估结果 EvalRecord，而非题目池）
# ---------------------------------------------------------------------------
_AUDIT_FULL = "all"          # 全抽层（答案对但被判过程有错 → 误报率分母全覆盖）
_AUDIT_WEIGHTS = {
    # 层标签 → (类别过滤, 计划抽取配额比例/绝对值)
    # 优先保证任务书两个分母的关键层完整覆盖，其余按比例补足到 ~35 题。
    "wrong_pi":   (False, None),   # 答案错 + 过程错/沉默失败（定位关键层）→ 全抽
    "right_pi":   (True, None),    # 答案对 + 过程错/沉默失败（误报率分母）→ 全抽
    "wrong_ai":   (False, None),   # 答案错 + 答案错判定 → 配额 40%
    "correct":    (True, None),    # 答案对 + CORRECT → 配额 30%
}
_AUDIT_SAMPLE_TOTAL = 35


def _audit_bucket(r: EvalRecord) -> str:
    """给记录分抽检层（与 audit_metrics 分母口径一致）。"""
    v = r.verification.verdict
    if r.answer_correct is True:
        if v in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
            return "right_pi"
        return "correct"
    if r.answer_correct is False:
        if v in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
            return "wrong_pi"
        return "wrong_ai"
    return "unknown"  # answer_correct 未知/运行失败：仅可选的补充层


def audit_records_sample(
    records: list[EvalRecord],
    n: int = _AUDIT_SAMPLE_TOTAL,
    seed: int = 42,
    include_unknown: bool = False,
) -> list[EvalRecord]:
    """从评估结果中按「答案正确性 × 判定」分层抽取人工抽检样本。

    设计目标（任务书 P4 有效性验证）：
    - 答案错误 + 过程被判定有错（wrong_pi）：定位准确率的核心测试层，全抽；
    - 答案正确 + 过程被判定有错（right_pi）：误报率分母，必须全抽才能算准；
    - 答案错误 + ANSWER_INCORRECT（wrong_ai）：定位层补充，配额 40%；
    - 答案正确 + CORRECT（correct）：对照组，配额 30%；
    其余按余量从 unknown 层补充（include_unknown=True 时）。

    返回 EvalRecord 列表（原始记录），由调用方转为 AuditRecord 模板。
    种子固定，输出可复现。**期望样本数量 ≤ n**（关键层全部覆盖后由余量补足）。
    """
    buckets: dict[str, list[EvalRecord]] = {
        "wrong_pi": [], "right_pi": [], "wrong_ai": [], "correct": [], "unknown": [],
    }
    for r in records:
        b = _audit_bucket(r)
        if b in buckets:
            buckets[b].append(r)
    rng = random.Random(seed)

    picked: list[EvalRecord] = []
    # 1) 全抽层：答案错/对但过程判定有错（两类分母关键层）
    for key in ("wrong_pi", "right_pi"):
        picked.extend(buckets[key])
    # 2) 按配额补足其余层
    quota_wrong_ai = max(0, int((n - len(picked)) * 0.5))
    quota_correct = max(0, (n - len(picked)) - quota_wrong_ai)
    for key, quota in (("wrong_ai", quota_wrong_ai), ("correct", quota_correct)):
        pool = list(buckets[key])
        rng.shuffle(pool)
        picked.extend(pool[:quota])
    # 3) 余量从 unknown 层补足（默认不启用，人工抽检一般只看有判定的样本）
    if include_unknown and len(picked) < n and buckets["unknown"]:
        pool = list(buckets["unknown"])
        rng.shuffle(pool)
        picked.extend(pool[: n - len(picked)])

    # 稳定输出顺序（按 question_id）
    picked.sort(key=lambda r: r.question_id)
    return picked
