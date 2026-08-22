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
    id="M000", scene="math", title="t", prompt="p",
    difficulty="basic", source="self", standard_answer="2",
)


def _rec(qid: str, verdict: Verdict, answer_correct: bool = True,
         findings: list | None = None, diff: Difficulty = Difficulty.BASIC) -> EvalRecord:
    return EvalRecord(
        question_id=qid, scene="math", difficulty=diff,
        answer=Answer(steps=[Step(id=1, kind="derive", content="c", conclusion="c", deps=[])],
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


def test_audit_metrics_hit_and_fp() -> None:
    records = [
        _rec("a", Verdict.PROCESS_INCORRECT,
             findings=[ErrorFinding(step_id=1, error_type=ErrorType.CALCULATION,
                                    detail="d", evidence="e")]),
        _rec("b", Verdict.SILENT_FAILURE,
             findings=[ErrorFinding(step_id=1, error_type=ErrorType.LOGIC,
                                    detail="d", evidence="e")]),
    ]

    class Audit:
        def __init__(self, qid, step=None, fp=False):
            self.question_id, self.error_step_id, self.is_false_positive = qid, step, fp

    audits = [
        Audit("a", step=1),   # 命中
        Audit("b", step=99),  # 未命中
    ]
    am = audit_metrics(records, audits)
    assert am is not None
    assert am.error_localization_hit_rate == 0.5
    assert am.false_positive_rate == 0.0

    audits2 = [Audit("a", fp=True)]
    am2 = audit_metrics(records, audits2)
    assert am2 is not None and am2.false_positive_rate == 1.0


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
            revised_answer=Answer(steps=[Step(id=1, kind="derive", content="c",
                                              conclusion="c", deps=[])],
                                  final_answer="2"),
            feedbacks=[], verification=_vr(v), cost_calls=2,
        )

    recs = [
        RefineRecord(question_id="a", scene="math", difficulty=Difficulty.BASIC,
                     initial=_vr(Verdict.PROCESS_INCORRECT),
                     rounds=[_round(1, Verdict.PROCESS_INCORRECT), _round(2, Verdict.CORRECT)],
                     final=_vr(Verdict.CORRECT), converged=True),
        RefineRecord(question_id="b", scene="math", difficulty=Difficulty.BASIC,
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
