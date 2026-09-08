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


def test_compute_metrics_minor_as_error_dual_caliber() -> None:
    """副口径：若把 minor 瑕疵也计入过程错误，过程正确率变化。"""
    from rex.metrics.compute import _is_process_correct
    from rex.models import ErrorSeverity, ErrorType

    # CORRECT + minor finding → 主口径算对，副口径算错
    rec_minor = _rec("a", Verdict.CORRECT,
                     findings=[ErrorFinding(step_id=1, error_type=ErrorType.FORMAT,
                                            severity=ErrorSeverity.MINOR,
                                            detail="d", evidence="e")])
    rec_clean = _rec("b", Verdict.CORRECT)
    rec_fatal = _rec("c", Verdict.PROCESS_INCORRECT,
                     findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                            severity=ErrorSeverity.FATAL,
                                            detail="d", evidence="e")])
    records = [rec_minor, rec_clean, rec_fatal]
    m_main = compute_metrics(records)
    m_strict = compute_metrics(records, minor_as_error=True)
    assert m_main.process_correctness == 2 / 3        # a(CORRECT+minor) 算对
    assert m_strict.process_correctness == 1 / 3      # 副口径下 a 算错
    assert _is_process_correct(rec_minor, False) is True
    assert _is_process_correct(rec_minor, True) is False


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


def test_audit_metrics_minor_as_error_dual_caliber() -> None:
    """副口径：CORRECT+minor findings 也算"被判过程有错"→ 误报率分母扩大。"""
    from rex.models import ErrorSeverity, ErrorType

    rec_minor = _rec("a", Verdict.CORRECT,
                     findings=[ErrorFinding(step_id=1, error_type=ErrorType.FORMAT,
                                            severity=ErrorSeverity.MINOR,
                                            detail="d", evidence="e")])
    rec_pi = _rec("b", Verdict.PROCESS_INCORRECT,
                  findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                         severity=ErrorSeverity.FATAL,
                                         detail="d", evidence="e")])

    class Audit:
        def __init__(self, qid, fp=False):
            self.question_id = qid
            self.error_step_id = None
            self.is_false_positive = fp
            self.verdict_human = "CORRECT"

    # 主口径：a(CORRECT+minor) 不算被判过程有错 → fp_n=1
    am_main = audit_metrics([rec_minor, rec_pi], [Audit("a"), Audit("b")])
    assert am_main is not None and am_main.fp_n == 1
    # 副口径：a 也算 → fp_n=2
    am_strict = audit_metrics([rec_minor, rec_pi], [Audit("a"), Audit("b")],
                              minor_as_error=True)
    assert am_strict is not None and am_strict.fp_n == 2


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


def test_audit_metrics_three_way_dual_caliber() -> None:
    """human_severity_match 三层复核支撑误报率区间（下界=仅完全不符，上界=含层次不符）。

    三层针对「系统 fatal/minor 分级是否属实」：
      match          = 完全相符：系统 fatal 分级正确 → 非误报
      level_mismatch = 层次不符：系统把 minor 判 fatal（分级打反）
                      → 主口径（minor 不算过程错）误报；副口径不算
      fp             = 完全不符：系统说有错但实际过程正确 → 两口径均误报
    """
    def _rec_rp(qid: str) -> EvalRecord:
        return _rec(qid, Verdict.SILENT_FAILURE, answer_correct=True,
                    findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                           detail="d", evidence="e")])

    recs = [_rec_rp("a"), _rec_rp("b"), _rec_rp("c")]

    class Audit:
        def __init__(self, qid, tw):
            self.question_id = qid
            self.verdict_human = "SILENT_FAILURE"
            self.error_step_id = None
            self.human_severity_match = tw

    audits = [Audit("a", "fp"), Audit("b", "level_mismatch"), Audit("c", "match")]
    am = audit_metrics(recs, audits)
    assert am is not None
    assert am.fp_n == 3
    assert am.fp_human_n == 1      # 完全不符
    assert am.level_mismatch_n == 1
    assert am.match_n == 1
    # 上界（主口径）：fp + level_mismatch = 2/3
    assert am.false_positive_rate == 2 / 3
    # 下界（副口径）：仅 fp = 1/3
    assert am.false_positive_rate_strict == 1 / 3


def test_audit_metrics_three_way_fallback_legacy() -> None:
    """旧标注（is_false_positive / human_error_severity）回退到三层。"""
    from rex.metrics.compute import _three_way

    class AuditOld:
        def __init__(self, qid, fp=None, sev=None):
            self.question_id = qid
            self.verdict_human = "CORRECT"
            self.error_step_id = None
            self.is_false_positive = fp
            self.human_error_severity = sev
            # 无 human_severity_match

    # human_error_severity 优先于 is_false_positive
    assert _three_way(AuditOld("a", fp=True, sev="fatal")) == "match"
    assert _three_way(AuditOld("b", fp=False, sev="minor")) == "level_mismatch"
    assert _three_way(AuditOld("c", fp=True, sev="none")) == "fp"
    # 无 severity → 回退 is_false_positive
    assert _three_way(AuditOld("d", fp=True)) == "fp"
    assert _three_way(AuditOld("e", fp=False)) == "match"
    # 完全无标记 → None
    assert _three_way(AuditOld("f")) is None

    # 指标层：旧字段经 _three_way 归入对应层
    rec = _rec("a", Verdict.SILENT_FAILURE, answer_correct=True,
               findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                      detail="d", evidence="e")])
    am = audit_metrics([rec], [AuditOld("a", fp=False, sev="minor")])
    assert am is not None and am.fp_n == 1
    assert am.level_mismatch_n == 1
    assert am.false_positive_rate == 1.0   # 主口径含层次不符
    assert am.false_positive_rate_strict == 0.0
