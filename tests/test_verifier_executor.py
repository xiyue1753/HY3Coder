"""Verifier + executor tests: two-view cross-check, arbiter, sandbox, static."""
from __future__ import annotations

import json

from rex.executor.sandbox import run_code
from rex.executor.static_check import check_static
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


def test_verifier_agree_merges_and_sets_arbiter() -> None:
    agent = VerifierAgent(FakeHy3([
        _verdict_json("CORRECT", 0.9),
        _verdict_json("CORRECT", 0.7, [{"step_id": 1, "error_type": "format",
                                        "detail": "d", "evidence": "e"}]),
    ]))
    res = agent.verify(Q, OK_ANSWER)
    assert res.verdict == Verdict.CORRECT
    assert res.arbiter == "V1"
    assert len(res.findings) == 1  # 合并去重保留
    assert res.timestamp is not None


def test_verifier_disagreement_triggers_arbiter() -> None:
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
    # V1(0.6 CORRECT) vs V2(0.9 PROCESS_INCORRECT) 分歧，但 arbiter 抛错 → 取高置信 + HUMAN_REVIEW
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


def test_static_complexity_mismatch() -> None:
    code = (
        "n = int(input())\narr = list(map(int, input().split()))\n"
        "for i in range(n):\n    for j in range(n):\n        print(arr[i] + arr[j])\n"
    )
    ans = Answer(
        steps=[
            Step(id=1, kind="complexity", content="时间复杂度 O(n)", conclusion="O(n)", deps=[]),
        ],
        final_answer="",
        code=code,
    )
    res = check_static(Q, ans)
    assert res.mismatch is True
    assert any(d.category == "complexity" and d.severity == "warn" for d in res.diagnostics)


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


def test_static_infinite_loop_while_true_no_break() -> None:
    res = check_static(AQ, _algo_answer("while True:\n    print(1)\n"))
    assert res.loop_risk is True
    assert any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_while_condition_var_not_updated() -> None:
    res = check_static(AQ, _algo_answer("i = 0\nwhile i < 10:\n    print(i)\n"))
    assert res.loop_risk is True
    assert any(d.category == "loop" for d in res.diagnostics)


def test_static_loop_no_risk_normal_while() -> None:
    res = check_static(AQ, _algo_answer("i = 0\nwhile i < 10:\n    i += 1\n    print(i)\n"))
    assert res.loop_risk is False
    assert not any(d.category == "loop" for d in res.diagnostics)


def test_static_loop_no_risk_container_method_mutation() -> None:
    """`while dq:` + 循环内 dq.popleft() 是常见 BFS 终止模式，不应误报死循环。"""
    res = check_static(AQ, _algo_answer(
        "from collections import deque\ndq = deque([1])\n"
        "while dq:\n    u = dq.popleft()\n    print(u)\n"
    ))
    assert res.loop_risk is False
    assert not any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_recursion_no_base_case() -> None:
    res = check_static(AQ, _algo_answer(
        "def fib(n):\n    return fib(n - 1) + fib(n - 2)\nprint(fib(5))\n"
    ))
    assert res.recursion_risk is True
    assert any(d.category == "recursion" and d.severity == "warn" for d in res.diagnostics)


def test_static_recursion_with_base_no_risk() -> None:
    res = check_static(AQ, _algo_answer(
        "def fib(n):\n    if n <= 1:\n        return n\n    return fib(n - 1) + fib(n - 2)\nprint(fib(5))\n"
    ))
    assert res.recursion_risk is False
    assert not any(d.category == "recursion" for d in res.diagnostics)


def test_static_evidence_block_only_warns() -> None:
    from rex.executor.static_check import static_evidence_block

    ok = check_static(AQ, _algo_answer("print(1)\n"))
    assert static_evidence_block(ok) is None
    bad = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    block = static_evidence_block(bad)
    assert block is not None
    assert "规则校验证据" in block


def test_static_result_to_dict_roundtrip() -> None:
    from rex.executor.static_check import static_result_to_dict

    res = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    d = static_result_to_dict(res)
    assert d["loop_risk"] is True
    assert d["declared"] is None
    assert any(x["category"] == "loop" for x in d["diagnostics"])


def _static_q(prompt: str) -> QuestionItem:
    return QuestionItem(id="X", scene="algorithm", title="t", prompt=prompt,
                        difficulty="medium", source="self", standard_answer="")


def test_static_boundary_negative_missing_detected() -> None:
    """题目含负数但代码只用 max()（未真正处理负数）→ 应报 boundary warn。

    回归保护：旧规则把 max() 当负数处理信号导致漏检（return max(a) 不报错）。
    """
    from rex.executor.static_check import check_static

    q = _static_q("数组中可能含负数，求最大子数组和。")
    res = check_static(q, _algo_answer("def f(a):\n    return max(a)\n"))
    assert any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_static_boundary_negative_handled_no_warn() -> None:
    """Kadane（负无穷初始化 + 比较）视为已处理负数 → 不报 boundary warn。"""
    from rex.executor.static_check import check_static

    q = _static_q("数组中可能含负数，求最大子数组和。")
    code = ("def f(a):\n    cur = 0\n    best = -10**9\n"
            "    for x in a:\n        cur = max(x, cur + x)\n"
            "        best = max(best, cur)\n    return best\n")
    res = check_static(q, _algo_answer(code))
    assert not any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_static_boundary_empty_missing_detected() -> None:
    from rex.executor.static_check import check_static

    q = _static_q("若输入为空，返回空数组。")
    res = check_static(q, _algo_answer("def f(n):\n    return sum(n)\n"))
    assert any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_verifier_receives_static_evidence() -> None:
    from rex.executor.static_check import check_static, static_evidence_block

    agent = VerifierAgent(FakeHy3([
        _verdict_json("PROCESS_INCORRECT", 0.8,
                      [{"step_id": 1, "error_type": "logic", "detail": "死循环", "evidence": "while True"}]),
        _verdict_json("PROCESS_INCORRECT", 0.7,
                      [{"step_id": 1, "error_type": "logic", "detail": "死循环", "evidence": "while True"}]),
    ]))
    static = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    res = agent.verify(AQ, _algo_answer("while True:\n    pass\n"),
                       static_evidence=static_evidence_block(static))
    assert res.verdict == Verdict.PROCESS_INCORRECT
    # 两个视角的 prompt 都应包含规则校验证据块
    assert all("规则校验证据" in c for c in agent._client.calls[:2])
