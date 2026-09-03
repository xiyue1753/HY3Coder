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
    TestCase,
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
    # M000: solve + verify(A) + verify(B) = 3 calls；M001 同
    # 模型对两题都判 CORRECT，但 M001 标准答案=2 而 SOLVE 输出 1/2 → 客观答案错误，
    # 修复后的语义要求 verdict 强制降级为 ANSWER_INCORRECT（客观优先，防漏检）。
    client = FakeHy3([SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT"),
                      SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    out = tmp_path / "eval_math.jsonl"
    records = pipe.run_eval(Q, out, resume=False)
    assert len(records) == 2
    by_id = {r.question_id: r for r in records}
    assert by_id["M000"].answer_correct is True          # 1/2 == 1/2
    assert by_id["M000"].verification.verdict.value == "CORRECT"
    assert by_id["M001"].answer_correct is False         # 1/2 != 2
    assert by_id["M001"].verification.verdict.value == "ANSWER_INCORRECT"  # 降级
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


def test_run_eval_algorithm_static_check_recorded(tmp_path) -> None:
    """算法场景：static_check 结果写入 EvalRecord，且规则校验证据进入 verifier prompt。"""
    code = "while True:\n    pass\n"
    algo_q = QuestionItem(id="A000", scene="algorithm", title="t", prompt="输出 1",
                          difficulty="basic", source="self", standard_answer="1")
    solve = json.dumps({
        "steps": [{"id": 1, "kind": "implement", "content": code,
                   "conclusion": "实现", "deps": []}],
        "final_answer": "1",
        "code": code,
    })
    client = FakeHy3([solve, _verdict_json("CORRECT"), _verdict_json("CORRECT")])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    out = tmp_path / "eval_algorithm.jsonl"
    records = pipe.run_eval([algo_q], out, resume=False)
    assert len(records) == 1
    rec: EvalRecord = records[0]
    assert rec.static_check is not None
    assert rec.static_check["loop_risk"] is True
    assert any(d["category"] == "loop" for d in rec.static_check["diagnostics"])
    # 写盘后可回读（验证 static_check 序列化可持久化）
    raw = out.read_text(encoding="utf-8")
    assert '"loop_risk":true' in raw


def test_compile_failure_gets_fallback_finding(tmp_path) -> None:
    """编译/语法失败：verifier 无 findings 时程序化补 s4 finding（不依赖 LLM）。"""
    bad_code = "def broken(\n"   # Python 语法错误 → 沙盒 SyntaxError
    algo_q = QuestionItem(id="A001", scene="algorithm", title="t", prompt="输出 1",
                          difficulty="basic", source="self", standard_answer="1",
                          test_cases=[TestCase(input="", output="1")])
    solve = json.dumps({
        "steps": [{"id": 1, "kind": "implement", "content": bad_code,
                   "conclusion": "实现", "deps": []}],
        "final_answer": "1",
        "code": bad_code,
    })
    # LLM 双视角都判 CORRECT（不看沙盒）——兜底应补 s4 finding 且降级 ANSWER_INCORRECT
    client = FakeHy3([solve, _verdict_json("CORRECT"), _verdict_json("CORRECT")])
    cfg = _cfg(tmp_path)
    pipe = Pipeline(cfg, client=client)
    rec = pipe._eval_one(algo_q)
    # 客观答案错 → 兜底降级
    assert rec.answer_correct is False
    assert rec.verification.verdict.value == "ANSWER_INCORRECT"
    # 编译失败未定位 → 程序化补 s4 finding
    assert len(rec.verification.findings) >= 1
    fb = rec.verification.findings[-1]
    assert fb.step_id == 4
    assert "编译" in fb.detail or "运行" in fb.detail
    assert client.responses == []


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
