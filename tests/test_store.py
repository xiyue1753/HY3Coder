"""RecordStore tests: centralized persistence, rich query, retention."""
from __future__ import annotations

from rex.models import (
    Answer, Difficulty, EvalRecord, Step, Verdict, VerificationResult,
)
from rex.store import RecordStore


def _rec(qid, scene="algorithm", verdict=Verdict.CORRECT, difficulty=Difficulty.BASIC,
         source="run-eval", created_at="2026-08-01T10:00:00"):
    return EvalRecord(
        question_id=qid, scene=scene, difficulty=difficulty,
        answer=Answer(steps=[Step(id=1, kind="understand", content="c", conclusion="c", deps=[])],
                      final_answer="ok"),
        answer_correct=True, test_pass_rate=None,
        verification=VerificationResult(verdict=verdict, findings=[], confidence=0.9),
        source=source, created_at=created_at,
    )


def _store(tmp_path) -> RecordStore:
    return RecordStore(tmp_path / "outputs")


def test_store_append_and_load(tmp_path) -> None:
    st = _store(tmp_path)
    st.append_eval(_rec("A001"))
    st.append_eval(_rec("A002", scene="algorithm"))
    evals = st.load_evals()
    assert len(evals) == 2
    # created_at 自动补齐
    assert all(e.created_at for e in evals)


def test_store_cache_invalidates_when_file_removed(tmp_path) -> None:
    """回归：清空交互记录后，缓存不能还返回已经被删掉的记录。"""
    from rex.datasource import INTERACTIVE_EVAL
    st = _store(tmp_path)
    st.append_eval(_rec("A001"))
    st.append_eval(_rec("IX0001", source="interactive"))
    assert len(st.load_evals()) == 2          # 首次读入并缓存
    assert len(st.load_evals()) == 2          # 命中缓存
    (tmp_path / "outputs" / INTERACTIVE_EVAL).unlink()   # 模拟"删掉演示记录"
    assert len(st.load_evals()) == 1          # 缓存必须失效


def test_store_query_filters(tmp_path) -> None:
    st = _store(tmp_path)
    st.append_eval(_rec("A001", verdict=Verdict.CORRECT, difficulty=Difficulty.BASIC))
    st.append_eval(_rec("A002", verdict=Verdict.SILENT_FAILURE, difficulty=Difficulty.HARD))
    st.append_eval(_rec("A003", verdict=Verdict.CORRECT, difficulty=Difficulty.MEDIUM,
                        source="interactive"))

    # 按判定过滤
    rows, total = st.query_evals(verdict="CORRECT")
    assert total == 2
    # 按来源过滤
    rows, total = st.query_evals(source="interactive")
    assert total == 1 and rows[0].question_id == "A003"
    # 按难度过滤
    rows, total = st.query_evals(difficulty="hard")
    assert total == 1
    # 关键词
    rows, total = st.query_evals(keyword="A001")
    assert total == 1
    # 分页
    rows, total = st.query_evals(limit=1, offset=0)
    assert len(rows) == 1 and total == 3


def test_store_expired_and_cleanup(tmp_path) -> None:
    st = _store(tmp_path)
    # 一条超期、一条新
    st.append_eval(_rec("OLD", created_at="2020-01-01T00:00:00"))
    st.append_eval(_rec("NEW", created_at="2026-08-25T00:00:00"))
    expired = st.expired(days=30)
    assert [r.question_id for r in expired] == ["OLD"]
    # dry_run 不删除
    would, removed = st.cleanup(days=30, dry_run=True)
    assert would == 1 and removed == 0
    assert len(st.load_evals()) == 2
    # 真删除
    would, removed = st.cleanup(days=30, dry_run=False)
    assert removed == 1
    assert [r.question_id for r in st.load_evals()] == ["NEW"]


def test_store_cleanup_keeps_newest_per_question(tmp_path) -> None:
    st = _store(tmp_path)
    # 同一题两次运行，一个超期一个新；清理后应保留新的
    st.append_eval(_rec("A001", created_at="2020-01-01T00:00:00"))
    st.append_eval(_rec("A001", created_at="2026-08-25T00:00:00"))
    would, removed = st.cleanup(days=30, dry_run=False)
    assert removed == 1  # 只移除旧的
    left = st.load_evals()
    assert len(left) == 1
    assert left[0].created_at == "2026-08-25T00:00:00"
