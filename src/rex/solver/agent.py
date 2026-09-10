"""Solver agent: question -> structured step-by-step Answer (JSON).

Failure-tolerant JSON parsing: model output may be wrapped in markdown fences,
may contain leading prose, or may be invalid JSON. We extract the JSON object,
validate against the Answer contract, and retry (up to max_json_retries) with
the parse error fed back to the model.

Also exposes ``revise`` — the second input surface consumed by the ReAct loop:
previous Answer + verification feedbacks -> revised Answer.
"""
from __future__ import annotations

import json
import logging

from rex._json import extract_json_object
from rex.hy3_client import Hy3Client, Hy3Error
from rex.models import Answer, QuestionItem, RefineFeedback
from rex.solver.prompts import revise_user_prompt, solve_user_prompt, solver_system

log = logging.getLogger(__name__)


class SolverAgent:
    def __init__(
        self,
        client: Hy3Client,
        max_json_retries: int = 2,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._max_json_retries = max_json_retries
        self._reasoning = reasoning_effort

    # -- public API --------------------------------------------------------
    def solve(self, question: QuestionItem, on_step=None, on_reasoning=None) -> Answer:
        """Question -> step-by-step Answer (eval path, no feedback).

        ``on_step``：可选回调。传了就改走**流式**调用，模型每吐出一段就回调一次
        ``on_step(部分 Answer dict)``，供交互界面逐 Step 显示；不传则与原来完全一致
        （正式评测路径不传，口径不变）。
        """
        system = solver_system(question.scene)
        user = solve_user_prompt(question)
        return self._ask(system, user, question.scene,
                         on_step=on_step, on_reasoning=on_reasoning)

    def revise(
        self,
        question: QuestionItem,
        previous: Answer,
        feedbacks: list[RefineFeedback],
        on_step=None,
        on_reasoning=None,
    ) -> Answer:
        """Previous attempt + findings -> revised Answer (ReAct refine path).

        ``on_step`` / ``on_reasoning``：可选流式回调，同 :meth:`solve`。
        """
        system = solver_system(question.scene)
        prev_json = previous.model_dump_json(indent=1)
        # 算法长答案（含 code）会使 refine prompt 膨胀；截断控制 token 成本
        _MAX_PREV = 8_000
        if len(prev_json) > _MAX_PREV:
            prev_json = prev_json[:_MAX_PREV] + "\n...(上一版过程过长，已截断)"
        user = revise_user_prompt(question, prev_json, feedbacks)
        return self._ask(system, user, question.scene,
                         on_step=on_step, on_reasoning=on_reasoning)

    def close(self) -> None:
        self._client.close()

    @property
    def call_count(self) -> int:
        """模型调用计数（含重试），供成本核算。"""
        return self._client.call_count

    # -- internals ---------------------------------------------------------
    def _ask(self, system: str, user: str, scene: str, on_step=None,
             on_reasoning=None) -> Answer:
        last_err: str | None = None
        for attempt in range(self._max_json_retries + 1):
            msg = user
            if last_err and attempt > 0:
                # Feed the parse failure back so the model can fix its JSON.
                msg = (
                    f"{user}\n\n注意：你上次输出无法解析为合法 JSON，错误：{last_err}\n"
                    "请只输出一个合法的 JSON 对象（不要代码块围栏、不要解释文字）。"
                )
            if on_step is None:
                raw = self._client.chat(msg, system=system, reasoning_effort=self._reasoning)
            else:
                raw = self._stream(msg, system, on_step, on_reasoning)
            try:
                return self._parse_answer(raw, scene)
            except (ValueError, json.JSONDecodeError) as e:  # noqa: BLE001
                last_err = str(e)
                log.warning("solver JSON parse failed (attempt %d): %s", attempt + 1, last_err)
        raise Hy3Error(f"solver: invalid JSON after {self._max_json_retries + 1} attempts: {last_err}")

    def _stream(self, msg: str, system: str, on_step, on_reasoning=None) -> str:
        """流式调用 + 增量解析：每收到一片就回调一次部分 Answer。

        回调异常一律吞掉（展示层问题不该影响求解）；最终判定仍走整段解析。
        """
        from rex.stream_json import partial_answer

        buf: list[str] = []

        def _on_delta(piece: str) -> None:
            buf.append(piece)
            try:
                on_step(partial_answer("".join(buf)))
            except Exception as e:  # noqa: BLE001
                log.debug("on_step callback failed: %s", e)

        return self._client.chat_stream(
            msg, system=system, reasoning_effort=self._reasoning,
            on_delta=_on_delta, on_reasoning=on_reasoning)

    @staticmethod
    def _parse_answer(text: str, scene: str) -> Answer:
        obj = json.loads(extract_json_object(text))
        # pydantic v2 strictness: ensure kinds match the scene's allowed set.
        answer = Answer.model_validate(obj)
        _validate_kinds(answer, scene)
        return answer


def _validate_kinds(answer: Answer, scene: str = "algorithm") -> None:
    # 算法竞赛允许的 step kinds（数学/MATH 已放弃）
    allowed = {"understand", "approach", "complexity", "implement", "selftest"}
    bad = [s.id for s in answer.steps if s.kind not in allowed]
    if bad:
        raise ValueError(f"step kinds not allowed in scene '{scene}': {bad}")
