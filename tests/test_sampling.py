"""Tests for stratified sampling: deprecated filtering, tier pools, full mode."""
from __future__ import annotations

from rex.datasets.sampling import (
    audit_records_sample,
    difficulty_stats,
    sample_sizes,
    stratified_sample,
)
from rex.models import (
    Answer,
    Difficulty,
    EvalRecord,
    QuestionItem,
    Step,
    VerificationResult,
    Verdict,
)


def _q(qid: str, diff: Difficulty, deprecated: bool = False) -> QuestionItem:
    return QuestionItem(
        id=qid,
        scene="algorithm",
        title="t",
        prompt="p",
        difficulty=diff,
        source="test",
        standard_answer="",
        metadata={"deprecated": True} if deprecated else {},
    )


def _pool() -> list[QuestionItem]:
    return [
        _q("A001", Difficulty.BASIC),
        _q("A002", Difficulty.BASIC),
        _q("A003", Difficulty.MEDIUM),
        _q("A004", Difficulty.MEDIUM),
        _q("A005", Difficulty.HARD),
        _q("D001", Difficulty.BASIC, deprecated=True),
        _q("D002", Difficulty.MEDIUM, deprecated=True),
        _q("D003", Difficulty.HARD, deprecated=True),
    ]


def test_stratified_sample_excludes_deprecated() -> None:
    picked = stratified_sample(_pool(), "algorithm", "10", seed=1)
    ids = {q.id for q in picked}
    assert "D001" not in ids and "D002" not in ids and "D003" not in ids


def test_stratified_sample_full_excludes_deprecated() -> None:
    picked = stratified_sample(_pool(), "algorithm", "full", seed=1)
    ids = {q.id for q in picked}
    assert ids == {"A001", "A002", "A003", "A004", "A005"}


def test_difficulty_stats_excludes_deprecated() -> None:
    stats = difficulty_stats(_pool())
    assert stats == {"basic": 2, "medium": 2, "hard": 1}


def test_sample_sizes_uses_active_pool() -> None:
    # 5 档算法每档 2 题：active 池 basic2/medium2/hard1 → 2+2+1=5
    assert sample_sizes("algorithm", "5", _pool()) == 5


# ---------------------------------------------------------------------------
# audit_records_sample：人工抽检分层（对齐任务书两套分母）
# ---------------------------------------------------------------------------
def _er(qid: str, answer_correct: bool, verdict: Verdict) -> EvalRecord:
    return EvalRecord(
        question_id=qid, scene="algorithm", difficulty=Difficulty.HARD,
        answer=Answer(steps=[Step(id=1, kind="understand", content="c",
                                  conclusion="c", deps=[])],
                      final_answer="x"),
        answer_correct=answer_correct, test_pass_rate=1.0 if answer_correct else 0.0,
        verification=VerificationResult(verdict=verdict, confidence=0.9, arbiter="V1"),
    )


def _audit_pool() -> list[EvalRecord]:
    return [
        # 答案对 + CORRECT（对照组）
        _er("c1", True, Verdict.CORRECT), _er("c2", True, Verdict.CORRECT),
        _er("c3", True, Verdict.CORRECT), _er("c4", True, Verdict.CORRECT),
        # 答案对 + PROCESS_INCORRECT（误报率分母，应全抽）
        _er("rp1", True, Verdict.PROCESS_INCORRECT), _er("rp2", True, Verdict.SILENT_FAILURE),
        # 答案错 + PROCESS_INCORRECT（定位关键层，应全抽）
        _er("wp1", False, Verdict.PROCESS_INCORRECT),
        # 答案错 + ANSWER_INCORRECT
        _er("w1", False, Verdict.ANSWER_INCORRECT), _er("w2", False, Verdict.ANSWER_INCORRECT),
        _er("w3", False, Verdict.ANSWER_INCORRECT), _er("w4", False, Verdict.ANSWER_INCORRECT),
    ]


def test_audit_sample_covers_critical_layers_fully() -> None:
    picked = audit_records_sample(_audit_pool(), n=8, seed=1)
    ids = {r.question_id for r in picked}
    # 误报率分母（right_pi）与定位关键层（wrong_pi）必须全部覆盖
    assert {"rp1", "rp2", "wp1"} <= ids
    # 对照组有覆盖但非全量
    assert len(ids & {"c1", "c2", "c3", "c4"}) >= 1
    assert len(ids & {"c1", "c2", "c3", "c4"}) < 4


def test_audit_sample_reproducible_and_bounded() -> None:
    a = audit_records_sample(_audit_pool(), n=8, seed=7)
    b = audit_records_sample(_audit_pool(), n=8, seed=7)
    assert [r.question_id for r in a] == [r.question_id for r in b]
    assert len(a) <= 8

    # n 很小也不能丢弃关键层
    small = audit_records_sample(_audit_pool(), n=3, seed=7)
    assert {"rp1", "rp2", "wp1"} <= {r.question_id for r in small}
