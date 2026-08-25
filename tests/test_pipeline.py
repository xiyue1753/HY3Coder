"""Pipeline tests: eval/refine dual mode, resume, math answer normalization."""
from __future__ import annotations

import json

from rex.config import Config
from rex.hy3_client import Hy3Client
from rex.models import (
    Answer,
    Difficulty,
    EvalRecord,
    QuestionItem,
    RefineRecord,
    Step,
)
from rex.pipeline import Pipeline, normalize_math_answer

Q = [
    QuestionItem(id="M000", scene="math", title="t1", prompt="p1",
                 difficulty="basic", source="self", standard_answer="1/2"),
    QuestionItem(id="M001", scene="math", title="t2", prompt="p2",
                 difficulty="medium", source="self", standard_answer="2"),
]

SOLVE = json.dumps({
    "steps": [{"id": 1, "kind": "derive", "content": "c", "conclusion": "c", "deps": []}],
    "final_answer": "1/2",
})


def _verdict_json(verdict: str) -> str:
    return json.dumps({"verdict": verdict, "findings": [], "confidence": 0.9})


class FakeHy3(Hy3Client):
    def __init__(self, responses: list[str]) -> None:
        super().__init__("k", "https://example.invalid/v1", model="hy3", max_retries=0)
        self.responses = list(responses)
        self.calls = 0

    def chat(self, user, system=None, **kw) -> str:
        self.calls += 1
        self.call_count += 1  # 与真实客户端同口径（每次请求计一次）
        if not self.responses:
            raise AssertionError("unexpected chat()")
        return self.responses.pop(0)


def _cfg(tmp_path) -> Config:
    return Config(data_dir=tmp_path / "data", outputs_dir=tmp_path / "data" / "outputs")


def test_normalize_math_answer() -> None:
    assert normalize_math_answer(" 1 / 2 ") == "1/2"
    assert normalize_math_answer("x = 3（答案）") == "x=3(答案)"
    assert normalize_math_answer("√2") == "√2"
    # LaTeX 归一化：\frac → /、\sqrt → √、\boxed/\text 去壳
    assert normalize_math_answer(r"\frac{1}{2}") == normalize_math_answer("1/2")
    assert normalize_math_answer(r"\dfrac{1}{2}") == normalize_math_answer("1/2")
    assert normalize_math_answer(r"\sqrt{2}") == normalize_math_answer("√2")
    assert normalize_math_answer(r"\boxed{3}") == normalize_math_answer("3")
    assert normalize_math_answer(r"\text{x=1}") == normalize_math_answer("x=1")
    # 嵌套分数
    assert normalize_math_answer(r"\frac{\frac{1}{2}}{3}") == normalize_math_answer("(1/2)/(3)")


def test_run_eval_dual_mode(tmp_path) -> None:
    # M000: solve + verify(A) + verify(B) = 3 calls；M001 因无 key 异常前先给足响应
    client = FakeHy3([SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT"),
                      SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    out = tmp_path / "eval_math.jsonl"
    records = pipe.run_eval(Q, out, resume=False)
    assert len(records) == 2
    assert all(r.verification.verdict.value == "CORRECT" for r in records)
    assert records[0].answer_correct is True  # 1/2 == 1/2
    # 断言响应全部消费（无多余调用）
    assert client.responses == []


def test_run_eval_resume_skips_done(tmp_path) -> None:
    client = FakeHy3([SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    out = tmp_path / "eval_math.jsonl"
    first = pipe.run_eval(Q, out, resume=False)   # 跑 M000，M001 失败占位
    assert len(first) == 2
    # 第二次 resume：全部已完成，不再调用模型
    client2 = FakeHy3([])
    pipe2 = Pipeline(cfg, client=client2)
    second = pipe2.run_eval(Q, out, resume=True)
    assert len(second) == 2
    assert client2.responses == [] and client2.calls == 0


def test_run_refine_convergence(tmp_path) -> None:
    # 调用序列：solve(1) + verify A/B(2) → revise(1) + verify A/B(2) = 6 次
    incorrect = json.dumps({"verdict": "PROCESS_INCORRECT",
                            "findings": [{"step_id": 1, "error_type": "calculation",
                                          "detail": "d", "evidence": "e"}],
                            "confidence": 0.8})
    client = FakeHy3([
        SOLVE, incorrect, incorrect,   # 首轮：求解 + 双视角一致判错
        SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT"),  # 修订 + 双视角判对
    ])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    out = tmp_path / "refine_math.jsonl"
    records = pipe.run_refine(Q[:1], out, resume=False)
    assert len(records) == 1
    r: RefineRecord = records[0]
    assert r.initial.verdict.value == "PROCESS_INCORRECT"
    assert r.converged is True
    assert len(r.rounds) == 1
    assert r.rounds[0].cost_calls == 3  # revise(1) + 重验证 A/B(2)
    assert client.responses == []
