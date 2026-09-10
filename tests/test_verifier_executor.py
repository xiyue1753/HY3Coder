"""Verifier + executor tests: two-view cross-check, arbiter, sandbox.

静态规则校验的独立黄金样例集已拆到 `tests/test_static_check.py`
（与 src/rex/executor/static_check.py 规则配对，供开源直接验证规则行为）。
本文件保留 verifier↔static 的集成测试（evidence 传入）。
"""
from __future__ import annotations

import json

from rex.executor.sandbox import run_code
from rex.executor.static_check import check_static, static_evidence_block
from rex.executor.tests import run_test_cases
from rex.hy3_client import Hy3Client, Hy3Error
from rex.models import (
    Answer,
    ErrorFinding,
    ErrorType,
    QuestionItem,
    Step,
    TestCase,
    VerificationResult,
    Verdict,
)
from rex.verifier.agent import VerifierAgent

Q = QuestionItem(
    id="A100", scene="algorithm", title="t",
    prompt="给定整数 x，若满足 x^2=4 输出 2，否则输出 0。",
    difficulty="basic", source="self", standard_answer="2",
)

OK_ANSWER = Answer(
    steps=[
        Step(id=1, kind="understand", content="x^2=4", conclusion="x=±2", deps=[]),
        Step(id=2, kind="selftest", content="正整数解", conclusion="x=2", deps=[1]),
    ],
    final_answer="2",
)


class FakeHy3(Hy3Client):
    def __init__(self, responses: list[str]) -> None:
        super().__init__("k", "https://example.invalid/v1", model="hy3", max_retries=0)
        self.responses = list(responses)
        self.calls: list[str] = []

    def chat(self, user, system=None, **kw) -> str:
        self.calls.append(user)
        if not self.responses:
            raise AssertionError("unexpected extra chat() call")
        return self.responses.pop(0)


def _verdict_json(verdict: str, conf: float, findings: list | None = None) -> str:
    return json.dumps({"verdict": verdict, "findings": findings or [], "confidence": conf})


def test_verifier_always_arbitrates_agreed_views() -> None:
    # 双视角一致（CORRECT）也过仲裁：最终结果由 ARBITER 交付，arbiter 恒="ARBITER"
    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.7, [{"step_id": 1, "error_type": "format",
                                        "severity": "minor",
                                        "detail": "d", "evidence": "e"}]),
        _verdict_json("CORRECT", 0.85, [{"step_id": 1, "error_type": "format",
                                         "severity": "minor",
                                         "detail": "d", "evidence": "e"}]),
    ]))
    res = agent.verify(Q, OK_ANSWER)
    assert res.verdict == Verdict.CORRECT
    assert res.arbiter == "ARBITER"   # 总仲裁：一致也不直接合并
    assert len(res.findings) == 1  # 仲裁合并保留（minor）
    assert res.timestamp is not None
    assert len(agent._client.calls) == 3


def test_verifier_reports_phase_progress() -> None:
    """交互界面靠 on_phase 显示"评估进行到哪一步"，顺序与回调数量必须稳定。"""
    seen: list[str] = []
    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.9),
    ]))
    agent.verify(Q, OK_ANSWER, on_phase=seen.append)
    assert len(seen) == 3
    assert seen[0].startswith("V1") and seen[1].startswith("V2")
    assert "ARBITER" in seen[2]


def test_verifier_phase_callback_errors_are_ignored() -> None:
    """进度回调是展示层：它抛异常不能影响判定。"""
    def boom(_msg: str) -> None:
        raise RuntimeError("界面炸了")

    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.9),
    ]))
    res = agent.verify(Q, OK_ANSWER, on_phase=boom)
    assert res.verdict == Verdict.CORRECT and res.arbiter == "ARBITER"


def test_verifier_fatal_finding_forces_non_correct() -> None:
    """fatal finding + CORRECT 自相矛盾 → agent 层程序化强制 PROCESS_INCORRECT。

    视图2 原始输出 CORRECT+fatal → parse 时被强制 PROCESS_INCORRECT，与视图1
    的 CORRECT 分歧 → 仲裁（第3个响应）裁决 PROCESS_INCORRECT。
    """
    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.7, [{"step_id": 1, "error_type": "logic",
                                        "severity": "fatal",
                                        "detail": "d", "evidence": "e"}]),
        _verdict_json("PROCESS_INCORRECT", 0.85,
                      [{"step_id": 1, "error_type": "logic", "severity": "fatal",
                        "detail": "d", "evidence": "e"}]),
    ]))
    res = agent.verify(Q, OK_ANSWER)
    assert res.verdict == Verdict.PROCESS_INCORRECT
    assert res.arbiter == "ARBITER"


def test_verifier_invalid_enum_retries_with_feedback() -> None:
    """LLM 输出合法 JSON 但 error_type 非法（如 'concept/logic' 连写）
    → schema 校验失败应重试（此前直接抛 Hy3Error 导致单题失败）。"""
    bad = json.dumps({"verdict": "PROCESS_INCORRECT",
                      "findings": [{"step_id": 1, "error_type": "concept/logic",
                                    "severity": "fatal", "detail": "d", "evidence": "e"}],
                      "confidence": 0.8})
    ok = _verdict_json("PROCESS_INCORRECT", 0.9,
                       [{"step_id": 1, "error_type": "logic", "severity": "fatal",
                         "detail": "d", "evidence": "e"}])
    agent = VerifierAgent(FakeHy3([bad, ok, bad, ok, ok]), max_json_retries=2)
    res = agent.verify(Q, OK_ANSWER)
    assert res.verdict == Verdict.PROCESS_INCORRECT
    # 两个 view 各失败重试一次 + 总仲裁一次 → 共 5 次调用
    assert len(agent._client.calls) == 5
    # 重试消息包含 schema 错误提示
    assert any("error_type" in c and "枚举" in c for c in agent._client.calls)


def test_verifier_arbiter_delivers_final_verdict() -> None:
    """总仲裁：无论双视角一致与否，最终 verdict/arbiter 标签由 ARBITER 交付。"""
    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.8),
        _verdict_json("SILENT_FAILURE", 0.75,
                      [{"step_id": 1, "error_type": "logic", "detail": "d", "evidence": "e"}]),
        _verdict_json("SILENT_FAILURE", 0.85,
                      [{"step_id": 1, "error_type": "logic", "detail": "d", "evidence": "e"}]),
    ]))
    res = agent.verify(Q, OK_ANSWER)
    assert res.arbiter == "ARBITER"
    assert res.verdict == Verdict.SILENT_FAILURE
    assert len(agent._client.calls) == 3


def test_verifier_arbiter_failure_falls_back_to_human_review() -> None:
    class BoomHy3(FakeHy3):
        def chat(self, user, system=None, **kw) -> str:
            self.calls.append(user)
            if len(self.calls) <= 2:
                return _verdict_json("CORRECT", 0.6) if len(self.calls) == 1 else _verdict_json("PROCESS_INCORRECT", 0.9)
            raise Hy3Error("arbiter should not be called")
    agent = VerifierAgent(BoomHy3([]), max_json_retries=0)
    res = agent.verify(Q, OK_ANSWER)
    # 总仲裁：第 3 次调用即仲裁，抛错 → 回退高置信视角 + HUMAN_REVIEW
    assert res.arbiter == "HUMAN_REVIEW"
    assert res.verdict == Verdict.PROCESS_INCORRECT


def test_sandbox_runs_code() -> None:
    code = "import sys\nfor line in sys.stdin:\n    print(int(line.strip()) * 2)\n"
    res = run_code(code, stdin="3\n5\n")
    assert res.returncode == 0
    assert res.stdout.strip() == "6\n10"


def test_sandbox_timeout() -> None:
    res = run_code("while True: pass\n", timeout=0.5)
    assert res.timed_out


def test_run_test_cases_pass_rate() -> None:
    code = "import sys\nprint(sum(int(x) for x in sys.stdin.read().split()))\n"
    cases = [
        TestCase(input="1 2 3\n", output="6"),
        TestCase(input="10 20\n", output="30"),
        TestCase(input="1 1\n", output="99", hidden=True),
    ]
    res = run_test_cases(code, cases)
    assert res.pass_rate == 2 / 3
    assert res.failed_hidden == 1
    assert len(res.failed_public) == 0


AQ = QuestionItem(
    id="A000", scene="algorithm", title="t",
    prompt="给定 n，输出 1..n 的和。", difficulty="basic",
    source="self", standard_answer="",
)


def _algo_answer(code: str) -> Answer:
    return Answer(
        steps=[
            Step(id=1, kind="implement", content=code, conclusion="实现", deps=[]),
        ],
        final_answer="",
        code=code,
    )


def test_verifier_receives_static_evidence() -> None:
    agent = VerifierAgent(FakeHy3([
        _verdict_json("PROCESS_INCORRECT", 0.8,
                      [{"step_id": 1, "error_type": "logic", "detail": "死循环", "evidence": "while True"}]),
        _verdict_json("PROCESS_INCORRECT", 0.7,
                      [{"step_id": 1, "error_type": "logic", "detail": "死循环", "evidence": "while True"}]),
        _verdict_json("PROCESS_INCORRECT", 0.85,
                      [{"step_id": 1, "error_type": "logic", "detail": "死循环", "evidence": "while True"}]),
    ]))
    static = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    res = agent.verify(AQ, _algo_answer("while True:\n    pass\n"),
                       static_evidence=static_evidence_block(static))
    assert res.verdict == Verdict.PROCESS_INCORRECT
    # 两个视角的 prompt 都应包含规则校验证据块
    assert all("规则校验证据" in c for c in agent._client.calls[:2])
