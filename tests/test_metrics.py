"""Metrics tests: core indicators, Wilson interval, stability, refine compare."""
from __future__ import annotations

from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.metrics.stats import stability_check, wilson_interval
from rex.models import (
    Answer,
    Difficulty,
    EvalRecord,
    ErrorFinding,
    ErrorType,
    QuestionItem,
    RefineRecord,
    RefineRound,
    Step,
    VerificationResult,
    Verdict,
)

Q = QuestionItem(
    id="A000", scene="algorithm", title="t", prompt="p",
    difficulty="basic", source="self", standard_answer="2",
)


def _rec(qid: str, verdict: Verdict, answer_correct: bool = True,
         findings: list | None = None, diff: Difficulty = Difficulty.BASIC) -> EvalRecord:
    return EvalRecord(
        question_id=qid, scene="algorithm", difficulty=diff,
        answer=Answer(steps=[Step(id=1, kind="understand", content="c", conclusion="c", deps=[])],
                      final_answer="2"),
        answer_correct=answer_correct, test_pass_rate=1.0,
        verification=VerificationResult(verdict=verdict, findings=findings or [],
                                        confidence=0.9, arbiter="V1"),
    )


def test_wilson_interval_bounds() -> None:
    low, high = wilson_interval(50, 100)
    assert 0.0 < low < 0.5 < high < 1.0
    assert low >= 0.0 and high <= 1.0
    assert wilson_interval(0, 10) == (0.0, 0.0) or wilson_interval(0, 10)[0] == 0.0


def test_compute_metrics_basic() -> None:
    records = [
        _rec("a", Verdict.CORRECT),
        _rec("b", Verdict.PROCESS_INCORRECT,
             findings=[ErrorFinding(step_id=1, error_type=ErrorType.CALCULATION,
                                    detail="d", evidence="e")]),
        _rec("c", Verdict.SILENT_FAILURE,
             findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                    detail="d", evidence="e")]),
    ]
    m = compute_metrics(records)
    assert m.n == 3
    assert m.answer_accuracy == 1.0
    assert m.process_correctness == 1 / 3
    assert m.verdict_dist == {"CORRECT": 1, "PROCESS_INCORRECT": 1, "SILENT_FAILURE": 1}
    assert m.error_type_dist == {"calculation": 1, "logic": 1}


def test_compute_metrics_per_tier() -> None:
    records = [
        _rec("a", Verdict.CORRECT, diff=Difficulty.BASIC),
        _rec("b", Verdict.PROCESS_INCORRECT, diff=Difficulty.BASIC),
        _rec("c", Verdict.CORRECT, diff=Difficulty.HARD),
    ]
    m = compute_metrics(records)
    assert m.per_tier["basic"].process_correctness == 0.5
    assert m.per_tier["hard"].n == 1


def test_audit_metrics_localization_and_fp() -> None:
    """对齐任务书口径：定位准确率用答案错误样本，误报率用答案正确样本。"""
    # 答案错误的样本（answer_correct=False），用于测定位准确率
    rec_wrong1 = _rec("a", Verdict.PROCESS_INCORRECT,
                      answer_correct=False,
                      findings=[ErrorFinding(step_id=1, error_type=ErrorType.CALCULATION,
                                             detail="d", evidence="e")])
    rec_wrong2 = _rec("b", Verdict.PROCESS_INCORRECT,
                      answer_correct=False,
                      findings=[ErrorFinding(step_id=2, error_type=ErrorType.LOGIC,
                                             detail="d", evidence="e")])
    # 答案正确但被判过程有错（answer_correct=True），用于测误报率
    rec_right = _rec("c", Verdict.SILENT_FAILURE,
                     answer_correct=True,
                     findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                            detail="d", evidence="e")])

    class Audit:
        def __init__(self, qid, step=None, fp=False):
            self.question_id = qid
            self.error_step_id = step
            self.is_false_positive = fp
            self.verdict_human = "CORRECT"   # 人工已回填

    # 定位：a 命中（step1 被覆盖），b 未命中（step99 未被覆盖）
    audits = [Audit("a", step=1), Audit("b", step=99), Audit("c", step=1)]
    am = audit_metrics([rec_wrong1, rec_wrong2, rec_right], audits)
    assert am is not None
    assert am.localization_n == 2          # 答案错误样本数（分母）
    assert am.error_localization_hit_rate == 0.5   # 1 命中 / 2 答案错误样本
    assert am.fp_n == 1                    # 答案正确且被判过程有错（误报率分母）
    assert am.false_positive_rate == 0.0   # 人工未标 c 为误报

    # 误报：c 被人工标为误报 → 误报率 1.0
    am2 = audit_metrics([rec_wrong1, rec_wrong2, rec_right],
                        [Audit("a", step=1), Audit("b", step=99), Audit("c", fp=True)])
    assert am2 is not None and am2.false_positive_rate == 1.0

    # 未回填（verdict_human=None）的审计不计入分母
    class AuditPending:
        def __init__(self, qid):
            self.question_id = qid
            self.error_step_id = None
            self.is_false_positive = None
            self.verdict_human = None
    am3 = audit_metrics([rec_wrong1, rec_wrong2, rec_right],
                        [Audit("a", step=1), Audit("b", step=99),
                         Audit("c", step=1), AuditPending("a")])
    assert am3 is not None and am3.n == 3   # 未回填被排除，不稀释分母


def test_audit_metrics_answer_unknown_excluded() -> None:
    """答案正确性未知（answer_correct=None）的样本不进两个分母，但计入 n。"""
    rec_unknown = _rec("u", Verdict.PROCESS_INCORRECT, answer_correct=None,
                       findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                              detail="d", evidence="e")])

    class Audit:
        def __init__(self, qid, step=None, fp=False):
            self.question_id = qid
            self.error_step_id = step
            self.is_false_positive = fp
            self.verdict_human = "PROCESS_INCORRECT"   # 人工已回填

    am = audit_metrics([rec_unknown], [Audit("u", step=1)])
    assert am is not None
    assert am.n == 1                       # 计入总样本
    assert am.localization_n == 0          # 答案正确性未知 → 不进定位分母
    assert am.fp_n == 0                    # 不进误报分母
    assert am.error_localization_hit_rate == 0.0
    assert am.false_positive_rate == 0.0


def test_stability_check() -> None:
    records = [_rec(f"q{i}", Verdict.CORRECT if i % 2 == 0 else Verdict.PROCESS_INCORRECT)
               for i in range(60)]
    rep = stability_check(records)
    assert rep.stable is True or rep.drift < 0.5
    assert 0.0 <= rep.drift <= 1.0


def test_refine_comparison() -> None:
    def _vr(v: Verdict) -> VerificationResult:
        return VerificationResult(verdict=v, findings=[], confidence=0.9, arbiter="V1")

    def _round(no: int, v: Verdict) -> RefineRound:
        return RefineRound(
            round_no=no,
            revised_answer=Answer(steps=[Step(id=1, kind="understand", content="c",
                                              conclusion="c", deps=[])],
                                  final_answer="2"),
            feedbacks=[], verification=_vr(v), cost_calls=2,
        )

    recs = [
        RefineRecord(question_id="a", scene="algorithm", difficulty=Difficulty.BASIC,
                     initial=_vr(Verdict.PROCESS_INCORRECT),
                     rounds=[_round(1, Verdict.PROCESS_INCORRECT), _round(2, Verdict.CORRECT)],
                     final=_vr(Verdict.CORRECT), converged=True),
        RefineRecord(question_id="b", scene="algorithm", difficulty=Difficulty.BASIC,
                     initial=_vr(Verdict.CORRECT),
                     rounds=[],   # 初始即正确 → 无修正轮，修正前必须计入
                     final=_vr(Verdict.CORRECT), converged=True),
    ]
    rc = refine_comparison(recs)
    assert rc.n == 2
    assert rc.before_correct == 0.5
    assert rc.after_correct == 1.0
    assert rc.converged == 1.0
    assert rc.improved == 0.5


def test_compute_metrics_excludes_failed() -> None:
    """运行失败（FAILED）样本不计入正确率分母，但仍保留在 verdict_dist。"""
    def _failed(qid: str) -> EvalRecord:
        return EvalRecord(
            question_id=qid, scene="algorithm", difficulty=Difficulty.BASIC,
            answer=Answer(steps=[Step(id=1, kind="understand", content="c", conclusion="c", deps=[])],
                          final_answer=""),
            answer_correct=None, test_pass_rate=None,
            verification=VerificationResult(verdict=Verdict.FAILED, findings=[],
                                            confidence=0.0, arbiter="FAILED"),
            error="network failed",
        )

    records = [
        _rec("a", Verdict.CORRECT),
        _rec("b", Verdict.PROCESS_INCORRECT),
        _failed("c"),
        _failed("d"),
    ]
    m = compute_metrics(records)
    assert m.n == 4                       # 总样本含失败
    assert m.verdict_dist["FAILED"] == 2  # 失败仍可见
    assert m.process_correctness == 0.5   # 排除失败后：1 CORRECT / 2 有效 = 0.5（而非 1/4）
    assert m.answer_accuracy == 1.0       # 排除失败后：2 有效均 answer_correct


def test_refine_comparison_excludes_failed() -> None:
    """运行失败（FAILED）的 refine 样本不计入前后对比。"""
    def _vr(v: Verdict) -> VerificationResult:
        return VerificationResult(verdict=v, findings=[], confidence=0.9, arbiter="V1")

    recs = [
        RefineRecord(question_id="ok", scene="algorithm", difficulty=Difficulty.BASIC,
                     initial=_vr(Verdict.PROCESS_INCORRECT), rounds=[],
                     final=_vr(Verdict.CORRECT), converged=True),
        RefineRecord(question_id="bad", scene="algorithm", difficulty=Difficulty.BASIC,
                     initial=_vr(Verdict.FAILED), rounds=[],
                     final=_vr(Verdict.FAILED), converged=False),
    ]
    rc = refine_comparison(recs)
    assert rc.n == 1                     # 失败样本被排除
    assert rc.before_correct == 0.0
    assert rc.after_correct == 1.0
    assert rc.improved == 1.0
