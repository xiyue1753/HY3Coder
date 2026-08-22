"""Solver agent tests: JSON extraction, retry-on-parse-error, revise path."""
from __future__ import annotations

import json

import pytest

from rex._json import extract_json_object
from rex.hy3_client import Hy3Client, Hy3Error
from rex.models import Answer, ErrorType, QuestionItem, RefineFeedback, Step
from rex.solver.agent import SolverAgent


class FakeHy3(Hy3Client):
    """Scripted responses: list of (user_message, response) — next() semantics."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__("k", "https://example.invalid/v1", model="hy3", max_retries=0)
        self.responses = list(responses)
        self.calls: list[str] = []

    def chat(self, user, system=None, **kw) -> str:
        self.calls.append(user)
        if not self.responses:
            raise AssertionError("unexpected extra chat() call")
        return self.responses.pop(0)


Q = QuestionItem(
    id="M000",
    scene="math",
    title="x^2=4",
    prompt="求 x^2=4 的正整数解。",
    difficulty="basic",
    source="self",
    standard_answer="2",
)


def _valid_json() -> str:
    return json.dumps({
        "steps": [
            {"id": 1, "kind": "derive", "content": "因式分解", "conclusion": "x=±2", "deps": []},
        ],
        "final_answer": "2",
    })


def test_parse_plain_json() -> None:
    ans = SolverAgent._parse_answer(_valid_json(), "math")
    assert ans.final_answer == "2"
    assert ans.steps[0].kind == "derive"


def test_parse_markdown_fenced() -> None:
    raw = "好的，以下是解答：\n```json\n" + _valid_json() + "\n```\n完毕。"
    ans = SolverAgent._parse_answer(raw, "math")
    assert ans.final_answer == "2"


def test_extract_json_object_handles_string_braces() -> None:
    raw = '前文 {"a": "含 { 花括号", "b": 1} 后文'
    assert json.loads(extract_json_object(raw))["b"] == 1


def test_extract_json_object_skips_lone_brace_in_prose() -> None:
    raw = '答案含 { 细节如下: ```json ' + _valid_json() + "```"
    assert json.loads(extract_json_object(raw))["final_answer"] == "2"


def test_empty_steps_rejected() -> None:
    from rex.models import Answer
    with pytest.raises(Exception):
        Answer.model_validate({"steps": [], "final_answer": "2"})


def test_wrong_scene_kind_rejected() -> None:
    algo = QuestionItem(
        id="A000", scene="algorithm", title="t", prompt="p",
        difficulty="basic", source="self", standard_answer="",
    )
    bad = json.dumps({
        "steps": [{"id": 1, "kind": "derive", "content": "c", "conclusion": "c", "deps": []}],
        "final_answer": "2",
    })
    agent = SolverAgent(FakeHy3([bad]), max_json_retries=0)
    with pytest.raises(Hy3Error):
        agent.solve(algo)


def test_solve_happy_path() -> None:
    agent = SolverAgent(FakeHy3([_valid_json()]))
    ans = agent.solve(Q)
    assert ans.steps[0].id == 1
    assert agent._client.calls[0].startswith("题目")


def test_solve_retries_on_bad_json_then_succeeds() -> None:
    bad = "抱歉，{这不是JSON"
    agent = SolverAgent(FakeHy3([bad, _valid_json()]), max_json_retries=2)
    ans = agent.solve(Q)
    assert ans.final_answer == "2"
    # 第二次调用应附带解析错误反馈
    assert "无法解析为合法 JSON" in agent._client.calls[1]


def test_solve_fails_after_exhausting_retries() -> None:
    agent = SolverAgent(FakeHy3(["垃圾输出", "还是垃圾"]), max_json_retries=1)
    with pytest.raises(Hy3Error):
        agent.solve(Q)


def test_revise_embeds_feedback() -> None:
    prev = Answer(
        steps=[Step(id=1, kind="derive", content="c", conclusion="c", deps=[])],
        final_answer="3",
    )
    fb = RefineFeedback(
        step_id=1, error_type=ErrorType.CALCULATION,
        instruction="第 1 步计算有误，请重算", evidence="2*2=4 而非 9",
    )
    agent = SolverAgent(FakeHy3([_valid_json()]))
    ans = agent.revise(Q, prev, [fb])
    assert ans.final_answer == "2"
    msg = agent._client.calls[0]
    assert "第 1 步" in msg and "calculation" in msg and "2*2=4" in msg
