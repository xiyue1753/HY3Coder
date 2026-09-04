"""Metrics computation over eval records (+ optional human audit labels).

Metrics produced (DESIGN.md §量化评估):
  - answer_accuracy        答案准确率（exec 全过 或 标准答案文本比对通过）
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


def compute_metrics(records: list[EvalRecord],
                    formal_only: bool = False) -> MetricsReport:
    """Compute aggregate metrics over eval records.

    ``formal_only=True``：只统计正式评测（source="run-eval"），排除
    source="interactive" 交互演示记录——保证仪表盘指标口径 = 正式评测。
    旧实现把交互记录混入总览（交互样本无标准答案，污染指标），此参数用于
    面板层启用过滤；批处理统计与测试保持默认不过滤（兼容）。
    """
    if formal_only:
        records = [r for r in records if r.source == "run-eval"]
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
    """人工抽检口径（对齐任务书）：按"答案正确性"划分两套独立分母。

    - localization_n / error_localization_hit_rate（定位准确率）：
      分母 = 答案错误样本（answer_correct is False）；
      分子 = 其中系统判定过程有错（PROCESS_INCORRECT/SILENT_FAILURE）
            且 findings 覆盖人工标注的 error_step_id 的样本。
    - fp_n / false_positive_rate（误报率）：
      分母 = 答案正确样本（answer_correct is True）中被系统判定过程有错的样本；
      分子 = 其中人工确认为误报（is_false_positive=True）的样本。
    - n：有抽检标注的样本总数（含答案正确性未知/无法比对者，用于统计可见性）。
    """
    n: int
    error_localization_hit_rate: float
    false_positive_rate: float
    localization_n: int = 0       # 定位准确率分母：答案错误样本数
    fp_n: int = 0                 # 误报率分母：答案正确且被判过程有错的样本数


def _flagged_steps(r: EvalRecord) -> set[int]:
    return {f.step_id for f in r.verification.findings}


def audit_metrics(records: list[EvalRecord], audits: list) -> AuditMetrics | None:
    """audits: list of objects with fields question_id / error_step_id / is_false_positive.

    对齐任务书 P4 口径：利用标准答案（answer_correct）划分样本——
    - 定位准确率：在"答案错误"的样本上，评估器能否判定过程有问题并定位到出错步骤。
    - 误报率：在"答案正确"的样本上，被判过程有问题的样本经人工抽检确认真实/误报比例。
    """
    by_id = {r.question_id: r for r in records}
    pairs: list[tuple[EvalRecord, object]] = [
        (by_id[a.question_id], a) for a in audits if a.question_id in by_id
    ]
    if not pairs:
        return None

    # ---- 定位准确率：分母 = 答案错误的样本 ----
    wrong_answer = [r for r, _ in pairs if r.answer_correct is False]
    loc_hits = 0
    for r, a in pairs:
        if r.answer_correct is not False:
            continue
        # 系统必须判定过程有错，且人工标注的真实出错步骤被 findings 覆盖
        if r.verification.verdict not in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
            continue
        true_step = getattr(a, "error_step_id", None)
        if true_step is None:
            continue  # 人工未标注具体步骤，不计入命中
        if true_step in _flagged_steps(r):
            loc_hits += 1
    localization_n = len(wrong_answer)
    localization_hit_rate = loc_hits / localization_n if localization_n else 0.0

    # ---- 误报率：分母 = 答案正确且被系统判过程有错的样本 ----
    correct_judged_incorrect = [
        (r, a) for r, a in pairs
        if r.answer_correct is True
        and r.verification.verdict in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE)
    ]
    fp = sum(1 for _, a in correct_judged_incorrect if getattr(a, "is_false_positive", None) is True)
    fp_n = len(correct_judged_incorrect)
    false_positive_rate = fp / fp_n if fp_n else 0.0

    return AuditMetrics(
        n=len(pairs),
        error_localization_hit_rate=localization_hit_rate,
        false_positive_rate=false_positive_rate,
        localization_n=localization_n,
        fp_n=fp_n,
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
