"""EvalRunner tests: serial scheduling, retry, resume, cost aggregation."""
from __future__ import annotations

import json

from rex.config import Config
from rex.hy3_client import Hy3Client
from rex.models import (
    Answer,
    Difficulty,
    EvalRecord,
    QuestionItem,
    Step,
)
from rex.runner import EvalRunner

Q = [
    QuestionItem(id="M000", scene="algorithm", title="t1", prompt="p1",
                 difficulty="basic", source="self", standard_answer="1/2"),
    QuestionItem(id="M001", scene="algorithm", title="t2", prompt="p2",
                 difficulty="medium", source="self", standard_answer="2"),
]

SOLVE = json.dumps({
    "steps": [{"id": 1, "kind": "understand", "content": "c", "conclusion": "c", "deps": []}],
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
        self.call_count += 1
        if not self.responses:
            raise AssertionError("unexpected chat()")
        return self.responses.pop(0)


def _cfg(tmp_path) -> Config:
    return Config(data_dir=tmp_path / "data", outputs_dir=tmp_path / "data" / "outputs")


def _make_factory(per_question_responses, fail_once=False):
    """Return a pipeline factory where each question gets its OWN Fake client.

    per_question_responses: list of response-lists, one per question (each
      question consumes exactly its own list, e.g. [SOLVE, verdict, verdict]).

    fail_once: if True, the VERY FIRST chat() across all clients raises a
      transient RuntimeError once; afterwards everything proceeds normally.
      This exercises the whole-question retry path (the retried question uses a
      fresh client and succeeds).
    """
    seq = list(per_question_responses)
    state = {"i": 0, "clients": [], "failed": False}

    def factory(cfg):
        from rex.pipeline import Pipeline
        idx = state["i"]
        state["i"] += 1
        responses = seq[idx] if idx < len(seq) else []
        client = FakeHy3(responses)

        if fail_once and not state["failed"]:
            real_chat = client.chat

            def chat(user, system=None, **kw):
                if not state["failed"]:
                    state["failed"] = True
                    client.calls += 1
                    client.call_count += 1
                    raise RuntimeError("transient failure")
                return real_chat(user, system=system, **kw)

            client.chat = chat  # type: ignore[method-assign]
        state["clients"].append(client)
        return Pipeline(cfg, client=client)

    return factory, state


def test_runner_eval_basic(tmp_path) -> None:
    factory, state = _make_factory([
        [SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")],
        [SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")],
    ])
    runner = EvalRunner(_cfg(tmp_path), retries=0, concurrency=1, pipeline_factory=factory)
    out = tmp_path / "eval_algorithm.jsonl"
    records, costs = runner.run_eval(Q, out, resume=False)
    assert len(records) == 2
    by_id = {r.question_id: r for r in records}
    # 模型对两题都判 CORRECT，但 M001 答案错（1/2 != 2）→ 客观优先降级
    assert by_id["M000"].verification.verdict.value == "CORRECT"
    assert by_id["M001"].verification.verdict.value == "ANSWER_INCORRECT"
    assert by_id["M000"].answer_correct is True
    assert by_id["M001"].answer_correct is False
    # 每个 client 响应全部消费，各自恰好 3 次
    for cli in state["clients"]:
        assert cli.responses == []
        assert cli.calls == 3
    assert costs["calls"] == 6              # 2 题 × 3 次
    assert all(r.cost_calls == 3 for r in records)


def test_runner_resume_skips_done(tmp_path) -> None:
    factory, _ = _make_factory([
        [SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")],
        [SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")],
    ])
    runner = EvalRunner(_cfg(tmp_path), retries=0, concurrency=1, pipeline_factory=factory)
    out = tmp_path / "eval_algorithm.jsonl"
    runner.run_eval(Q, out, resume=False)      # 全部完成
    # 第二次 resume：全部已完成，不再建 client / 不再调用模型
    factory2, state2 = _make_factory([])
    runner2 = EvalRunner(_cfg(tmp_path), retries=0, concurrency=1, pipeline_factory=factory2)
    records2, _ = runner2.run_eval(Q, out, resume=True)
    assert len(records2) == 2
    assert state2["clients"] == []           # 未创建任何 client → 未调用模型


def test_runner_retry_transient_failure(tmp_path) -> None:
    """全局第一次调用失败一次；重试（新建 client）后成功，不中断批。"""
    # 共享响应池：无论多少次 retry / 多少 client，都从同一池按序消费。
    # 6 个响应 = 两题各 [SOLVE, verdict, verdict]；全局第一次调用前注入一次失败。
    pool = [
        SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT"),
        SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT"),
    ]
    shared = {"responses": list(pool), "failed": False}
    total_attempted = {"n": 0}

    def factory(cfg):
        from rex.pipeline import Pipeline
        client = FakeHy3(shared["responses"])
        real_chat = client.chat

        def chat(user, system=None, **kw):
            total_attempted["n"] += 1
            if not shared["failed"]:
                shared["failed"] = True
                client.calls += 1
                client.call_count += 1
                raise RuntimeError("transient failure")
            return real_chat(user, system=system, **kw)

        client.chat = chat  # type: ignore[method-assign]
        return Pipeline(cfg, client=client)

    runner = EvalRunner(_cfg(tmp_path), retries=2, backoff_base=0.0, concurrency=1, pipeline_factory=factory)
    out = tmp_path / "eval_algorithm.jsonl"
    records, _ = runner.run_eval(Q, out, resume=False)
    assert len(records) == 2
    by_id = {r.question_id: r for r in records}
    # 重试后成功；M001 答案错（1/2 != 2）→ 客观优先降级 ANSWER_INCORRECT
    assert by_id["M000"].verification.verdict.value == "CORRECT"
    assert by_id["M001"].verification.verdict.value == "ANSWER_INCORRECT"
    # 失败 1 次 + 成功 6 次 = 7 次模型调用（验证 retry 不重复算、不遗漏）
    assert total_attempted["n"] == 7


def test_runner_retry_exhausted_placeholder(tmp_path) -> None:
    # 两题均永远失败 → 重试耗尽 → 写占位记录，不中断批
    factory, state = _make_factory([
        [],  # 首题：无响应 → 每调用都 unexpected chat() 抛异常
        [],
    ])
    runner = EvalRunner(_cfg(tmp_path), retries=1, backoff_base=0.0, concurrency=1, pipeline_factory=factory)
    out = tmp_path / "eval_algorithm.jsonl"
    records, _ = runner.run_eval(Q, out, resume=False)
    assert len(records) == 2
    for r in records:
        assert r.error is not None
        # 占位记录用 FAILED，避免运行失败被误判为过程错误
        assert r.verification.verdict.value == "FAILED"
        assert r.verification.arbiter == "FAILED"


def test_runner_parallel_thread_safe(tmp_path) -> None:
    """并发（线程池）下：不丢题、断点正确、成本正确、无共享状态竞争。"""
    import threading

    n_questions = 8
    questions = [
        QuestionItem(id=f"M{i:03d}", scene="algorithm", title=f"t{i}", prompt=f"p{i}",
                     difficulty="basic", source="self", standard_answer="1/2")
        for i in range(n_questions)
    ]
    # 每题 [SOLVE, verdict, verdict] = 3 响应
    per_question = [[SOLVE, _verdict_json("CORRECT"), _verdict_json("CORRECT")]
                    for _ in range(n_questions)]

    idx_lock = threading.Lock()          # 保护计数器（每个 worker 取独立题目响应池）
    state = {"i": 0, "clients": []}
    client_lock = threading.Lock()

    def factory(cfg):
        from rex.pipeline import Pipeline
        with idx_lock:                   # 线程安全：每次分配一个独立响应池
            idx = state["i"]
            state["i"] += 1
        responses = per_question[idx] if idx < n_questions else []
        client = FakeHy3(responses)      # 每 client 独立响应池 → 无共享竞争
        with client_lock:
            state["clients"].append(client)
        return Pipeline(cfg, client=client)

    runner = EvalRunner(_cfg(tmp_path), retries=0, concurrency=4, pipeline_factory=factory)
    out = tmp_path / "eval_algorithm.jsonl"
    records, costs = runner.run_eval(questions, out, resume=False)
    # 8 题全部完成，无丢失、无重复
    assert len(records) == n_questions
    assert {r.question_id for r in records} == {q.id for q in questions}
    assert all(r.verification.verdict.value == "CORRECT" for r in records)
    # 总调用 = 8 题 × 3 = 24
    assert costs["calls"] == n_questions * 3
    # 每个 client 响应全部消费
    assert all(not c.responses for c in state["clients"])

    # 再次并发 resume：全部已完成，不再创建 client / 不再调用
    before = len(state["clients"])
    runner2 = EvalRunner(_cfg(tmp_path), retries=0, concurrency=4, pipeline_factory=factory)
    records2, _ = runner2.run_eval(questions, out, resume=True)
    assert len(records2) == n_questions
    assert len(state["clients"]) == before   # resume 未创建新 client → 未调用模型
