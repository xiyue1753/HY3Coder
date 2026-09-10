"""交互式解题留档：题池 / 会话快照 / refine 路由 / 参考解试运行（离线，不调模型）。"""
from __future__ import annotations

from pathlib import Path

from rex.models import (
    Answer, Difficulty, InteractSession, InteractTrial, QuestionItem, RefineRecord,
    Step, TestCase, VerificationResult, Verdict,
)
from rex.store import RecordStore

from web.api import InteractRequest, InteractSample, _build_question, _next_interactive_qid


def _root(tmp_path: Path) -> Path:
    """造一个 <root>/data/{questions,outputs} 的最小结构。"""
    (tmp_path / "data" / "questions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "outputs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _store(root: Path) -> RecordStore:
    return RecordStore(root / "data" / "outputs", root=root)


def _q(qid: str = "IX0001") -> QuestionItem:
    return QuestionItem(
        id=qid, scene="algorithm", title="t", prompt="p", difficulty=Difficulty.BASIC,
        source="交互解题 · A1001", standard_answer="3",
    )


def test_question_goes_to_interactive_pool(tmp_path) -> None:
    root = _root(tmp_path)
    _store(root).append_interactive_question(_q())
    p = root / "data" / "questions" / "interactive.jsonl"
    assert p.exists()
    assert '"IX0001"' in p.read_text(encoding="utf-8")
    # 交互题池不在启动数据集里（只供回放取题），但能被 load_active_questions 合并读到
    from rex.datasource import load_active_questions
    ids = [q.id for q in load_active_questions(root)]
    assert ids == ["IX0001"]


def test_session_snapshot_roundtrip(tmp_path) -> None:
    root = _root(tmp_path)
    st = _store(root)
    st.append_interact_session(InteractSession(
        session_id="IJ1", question_id="IX0001", prompt="求和", origin="dataset",
        origin_question_id="A1001", model="hy3", base_url="https://x/v1",
        trial=InteractTrial(ran=True, total=2, passed=2),
    ))
    sessions = st.load_interact_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.created_at                      # 自动补时间戳
    assert s.question_id == "IX0001" and s.origin_question_id == "A1001"
    assert s.model == "hy3" and s.trial.ran and s.trial.passed == 2
    assert (root / "data" / "outputs" / "interact_sessions.jsonl").exists()


def test_interactive_refine_writes_its_own_file(tmp_path) -> None:
    """回归：交互 refine 不能写进正式 refine 文件（报告修正闭环的数据源）。"""
    root = _root(tmp_path)
    st = _store(root)
    v = VerificationResult(verdict=Verdict.CORRECT, findings=[], confidence=0.9)
    st.append_refine(RefineRecord(
        question_id="IX0001", scene="algorithm", difficulty=Difficulty.BASIC,
        initial=v, rounds=[], final=v, converged=True, source="interactive",
    ))
    out = root / "data" / "outputs"
    assert (out / "refine_interactive.jsonl").exists()
    assert not (out / "refine_algorithm.jsonl").exists()
    from rex.datasource import load_active_refines, load_interactive_refines
    assert load_active_refines(root) == []            # 正式口径不受影响
    assert [r.question_id for r in load_interactive_refines(root)] == ["IX0001"]


def test_next_interactive_qid_increments(tmp_path) -> None:
    root = _root(tmp_path)
    assert _next_interactive_qid(root) == "IX0001"
    _store(root).append_interactive_question(_q("IX0001"))
    assert _next_interactive_qid(root) == "IX0002"


def test_build_question_carries_origin_and_reference(tmp_path) -> None:
    root = _root(tmp_path)
    req = InteractRequest(
        prompt="求两数之和", answer="3",
        samples=[InteractSample(input="1 2", output="3")],
        origin_question_id="A1001", origin_title="ABC161 D", source_id="abc161_d",
        reference_solution="import sys;print(sum(map(int,sys.stdin.read().split())))",
        reference_language="python",
    )
    q = _build_question(req, root)
    assert q.id == "IX0001"                     # 新题号，不是会话 id
    assert q.source == "交互解题 · A1001"
    assert q.title == "A1001 · ABC161 D"
    assert q.source_id == "abc161_d"
    assert q.reference_solution and q.judge.value == "exact"
    assert len(q.test_cases) == 1 and q.test_cases[0].output == "3"
    # 样例同时拼进题面（模型看到的题面含样例块）
    assert "【输入输出样例】" in q.prompt


def test_trial_reference_runs_in_sandbox() -> None:
    """参考解试运行走真沙盒：会话里的试运行证据是服务端自己跑出来的。"""
    from web.api import _trial_reference
    q = _q()
    q = q.model_copy(update={
        "reference_solution": "import sys\nprint(sum(map(int, sys.stdin.read().split())))",
        "test_cases": [TestCase(input="1 2", output="3"), TestCase(input="2 5", output="7")],
    })
    trial = _trial_reference(q)
    assert trial.ran and trial.total == 2 and trial.passed == 2
    assert [c.passed for c in trial.cases] == [True, True]
    assert trial.language == "python" and trial.judge == "exact"


def test_trial_reference_without_reference_solution() -> None:
    from web.api import _trial_reference
    trial = _trial_reference(_q())
    assert trial.ran is False and trial.total == 0


def test_session_snapshot_summarizes_result(tmp_path) -> None:
    from rex.models import InteractResult
    from web.api import _session_snapshot
    root = _root(tmp_path)
    req = InteractRequest(prompt="求两数之和", origin_question_id="A1001",
                         origin_title="ABC161 D", reference_solution="print(1)")
    q = _build_question(req, root)
    s = _session_snapshot(
        "IJ1", req, q, InteractTrial(ran=True, total=1, passed=1),
        InteractResult(mode="eval", verdict="SILENT_FAILURE", answer_correct=True,
                       test_pass_rate=1.0, confidence=0.95, findings=2),
        cost_calls=5, elapsed=12.3,
    )
    assert s.session_id == "IJ1" and s.question_id == q.id
    assert s.origin == "dataset" and s.origin_question_id == "A1001"
    assert s.prompt == "求两数之和"           # 存用户原题面，而不是拼了样例的中间产物
    assert s.result.verdict == "SILENT_FAILURE" and s.result.findings == 2
    assert s.cost_calls == 5 and s.reference_language == "python"
    assert s.n_public_cases == 0 and s.n_hidden_cases == 0


def test_session_snapshot_manual_origin(tmp_path) -> None:
    from web.api import _session_snapshot
    from rex.models import InteractResult
    root = _root(tmp_path)
    req = InteractRequest(prompt="手输的题")
    q = _build_question(req, root)
    s = _session_snapshot("IJ2", req, q, InteractTrial(ran=False),
                          InteractResult(), cost_calls=0, elapsed=0.0)
    assert s.origin == "manual" and s.origin_question_id is None
    assert s.reference_solution is None
