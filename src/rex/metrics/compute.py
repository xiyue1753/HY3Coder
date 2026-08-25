"""Metrics computation over eval records (+ optional human audit labels).

Metrics produced (DESIGN.md §量化评估):
  - answer_accuracy        答案准确率（exec 全过 或 数学答案比对通过）
  - process_correctness    过程正确率（verdict == CORRECT）
  - verdict distribution   四类判定占比（含 SILENT_FAILURE 检出）
  - error_type distribution 错误类型分布（能力画像输入）
  - per-difficulty         三档分档指标（分层退化分析）
  - with audits:  error_localization_hit_rate 定位命中率
                  false_positive_rate         误报率
  - refine:      修正前后对比（refine/ 模块使用）

指标只基于 eval 数据（数据纯净性：eval 与 refine 结果严格分离）。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import mean

from rex.models import Difficulty, EvalRecord, ErrorType, Verdict


@dataclass
class TierMetrics:
    n: int
    answer_accuracy: float
    process_correctness: float


@dataclass
class MetricsReport:
    n: int
    answer_accuracy: float
    process_correctness: float
    verdict_dist: dict[str, int] = field(default_factory=dict)
    error_type_dist: dict[str, int] = field(default_factory=dict)
    per_tier: dict[str, TierMetrics] = field(default_factory=dict)
    # 仅当提供人工抽检标注时才有值
    error_localization_hit_rate: float | None = None
    false_positive_rate: float | None = None
    audit_n: int = 0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "answer_accuracy": self.answer_accuracy,
            "process_correctness": self.process_correctness,
            "verdict_dist": self.verdict_dist,
            "error_type_dist": self.error_type_dist,
            "per_tier": {k: {"n": v.n, "answer_accuracy": v.answer_accuracy,
                             "process_correctness": v.process_correctness}
                         for k, v in self.per_tier.items()},
            "error_localization_hit_rate": self.error_localization_hit_rate,
            "false_positive_rate": self.false_positive_rate,
            "audit_n": self.audit_n,
        }


def _is_answer_correct(r: EvalRecord) -> bool:
    if r.answer_correct is not None:
        return bool(r.answer_correct)
    # 算法场景无答案比对时，以沙盒全过作为答案正确信号
    return r.test_pass_rate is not None and r.test_pass_rate >= 1.0 and r.error is None


def compute_metrics(records: list[EvalRecord]) -> MetricsReport:
    if not records:
        return MetricsReport(n=0, answer_accuracy=0.0, process_correctness=0.0)

    n = len(records)
    # 运行失败（Verdict.FAILED）样本没有真实判定，不计入正确率分母，但仍保留计数。
    valid = [r for r in records if r.verification.verdict != Verdict.FAILED]
    n_valid = len(valid)
    answer_correct = sum(_is_answer_correct(r) for r in valid)
    process_correct = sum(r.verification.verdict == Verdict.CORRECT for r in valid)
    verdict_dist = dict(Counter(r.verification.verdict.value for r in records))
    error_types: Counter[str] = Counter()
    for r in valid:
        for f in r.verification.findings:
            error_types[f.error_type.value] += 1
    per_tier: dict[str, TierMetrics] = {}
    for d in Difficulty:
        tier = [r for r in valid if r.difficulty == d]
        if tier:
            per_tier[d.value] = TierMetrics(
                n=len(tier),
                answer_accuracy=sum(_is_answer_correct(r) for r in tier) / len(tier),
                process_correctness=sum(r.verification.verdict == Verdict.CORRECT for r in tier) / len(tier),
            )
    return MetricsReport(
        n=n,
        answer_accuracy=(answer_correct / n_valid) if n_valid else 0.0,
        process_correctness=(process_correct / n_valid) if n_valid else 0.0,
        verdict_dist=verdict_dist,
        error_type_dist=dict(error_types),
        per_tier=per_tier,
    )


# ---------------------------------------------------------------------------
# Audit-based metrics (需要人工抽检标注)
# ---------------------------------------------------------------------------
@dataclass
class AuditMetrics:
    """人工抽检口径：定位命中率 / 误报率。"""
    n: int
    error_localization_hit_rate: float
    false_positive_rate: float


def audit_metrics(records: list[EvalRecord], audits: list) -> AuditMetrics | None:
    """audits: list of objects with fields question_id / error_step_id / is_false_positive.

    - 定位命中率：系统判定过程有错（PROCESS_INCORRECT/SILENT_FAILURE）的样本中，
      findings 覆盖了人工标注的真实错误步骤的比例。
    - 误报率：系统判定有错但人工判定为正确的比例。
    """
    by_id = {r.question_id: r for r in records}
    pairs: list[tuple[EvalRecord, object]] = [
        (by_id[a.question_id], a) for a in audits if a.question_id in by_id
    ]
    if not pairs:
        return None
    judged_incorrect = [
        (r, a) for r, a in pairs
        if r.verification.verdict in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE)
    ]
    if not judged_incorrect:
        return AuditMetrics(n=len(pairs), error_localization_hit_rate=0.0, false_positive_rate=0.0)
    hits = 0
    fp = 0
    for r, a in judged_incorrect:
        # 人工确认此样本确实有错
        if getattr(a, "is_false_positive", None) is True:
            fp += 1
            continue
        true_step = getattr(a, "error_step_id", None)
        if true_step is None:
            continue  # 人工标注无具体步骤，不计入定位命中
        flagged = {f.step_id for f in r.verification.findings}
        if true_step in flagged:
            hits += 1
    return AuditMetrics(
        n=len(pairs),
        error_localization_hit_rate=hits / len(judged_incorrect) if judged_incorrect else 0.0,
        false_positive_rate=fp / len(judged_incorrect) if judged_incorrect else 0.0,
    )


# ---------------------------------------------------------------------------
# Refine comparison（修正前后对比，供 refine 报告章节）
# ---------------------------------------------------------------------------
@dataclass
class RefineComparison:
    n: int
    before_correct: float       # 首轮过程正确率
    after_correct: float        # 收敛轮过程正确率
    converged: float            # 限轮内达成 CORRECT 比例
    improved: float             # 由错误→正确 或 错误减少 的比例


def refine_comparison(records: list) -> RefineComparison:
    """records: list of RefineRecord.

    注意：初始即 CORRECT 的样本 rounds 为空（不进入修正循环），
    因此"修正前"一律取 record.initial，不能依赖 rounds[0]。
    """
    if not records:
        return RefineComparison(0, 0.0, 0.0, 0.0, 0.0)
    # 运行失败（initial/final 为 FAILED）样本无真实判定，不计入修正前后对比。
    valid = [r for r in records
             if r.initial.verdict != Verdict.FAILED and r.final.verdict != Verdict.FAILED]
    if not valid:
        return RefineComparison(0, 0.0, 0.0, 0.0, 0.0)
    before = [r.initial.verdict == Verdict.CORRECT for r in valid]
    after = [r.final.verdict == Verdict.CORRECT for r in valid]
    improved = [
        r for r in valid
        if r.initial.verdict != Verdict.CORRECT and r.final.verdict == Verdict.CORRECT
    ]
    return RefineComparison(
        n=len(valid),
        before_correct=mean(before) if before else 0.0,
        after_correct=mean(after) if after else 0.0,
        converged=mean(after) if after else 0.0,
        improved=len(improved) / len(valid),
    )
