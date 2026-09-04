"""ReAct refinement loop: verify → feedback → revise → re-verify (≤max_rounds).

Data-purity contract:
  - eval mode never routes verifier feedback back into the solver (refine is
    a separate mode with its own output files).
  - refine mode records every round (revised answer + feedback + verification)
    so the report can show a before/after comparison, but these rounds are
    never mixed into the eval-based metrics.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from rex.models import (
    QuestionItem,
    RefineRecord,
    RefineRound,
    VerificationResult,
    Verdict,
)
from rex.refine.prompts import findings_to_feedback
from rex.solver.agent import SolverAgent
from rex.verifier.agent import VerifierAgent

log = logging.getLogger(__name__)


class Refiner:
    def __init__(
        self,
        solver: SolverAgent,
        verifier: VerifierAgent,
        max_rounds: int = 3,
    ) -> None:
        self._solver = solver
        self._verifier = verifier
        self._max_rounds = max_rounds
        # solver/verifier 共享同一底层 client，调用计数以 client 单值为准
        # （不可用 solver+verifier 相加，否则会双倍计数）
        self._client = solver._client  # noqa: SLF001

    def refine(self, question: QuestionItem,
               progress: Callable[[str, object | None], None] | None = None) -> RefineRecord:
        """ReAct 修正闭环。``progress(phase, payload)`` 报告阶段与中间解答。"""
        t0 = time.time()
        # 首轮：独立求解 + 验证（与 eval 模式同路径，保证 initial 可比）
        if progress:
            progress("solve", None)
        answer = self._solver.solve(question)
        if progress:
            progress("answer", answer)
        if progress:
            progress("verify", None)
        initial = self._verifier.verify(question, answer)
        rounds: list[RefineRound] = []
        current_answer = answer
        current_v = initial
        cost_base = self._client.call_count

        if initial.verdict != Verdict.CORRECT:
            for round_no in range(1, self._max_rounds + 1):
                feedbacks = findings_to_feedback(initial if round_no == 1 else current_v)
                if not feedbacks:
                    break  # 无反馈可生成（理论上 CORRECT 才出现）
                if progress:
                    progress(f"revise-{round_no}", None)
                revised = self._solver.revise(question, current_answer, feedbacks)
                if progress:
                    progress(f"answer-{round_no}", revised)
                if progress:
                    progress(f"verify-{round_no}", None)
                current_v = self._verifier.verify(question, revised)
                cost_now = self._client.call_count
                rounds.append(RefineRound(
                    round_no=round_no,
                    revised_answer=revised,
                    feedbacks=feedbacks,
                    verification=current_v,
                    cost_calls=cost_now - cost_base,
                ))
                current_answer = revised
                cost_base = cost_now
                if current_v.verdict == Verdict.CORRECT:
                    break  # 收敛

        converged = current_v.verdict == Verdict.CORRECT
        log.info("refine %s: rounds=%d converged=%s verdict=%s",
                 question.id, len(rounds), converged, current_v.verdict.value)
        return RefineRecord(
            question_id=question.id,
            scene=question.scene,
            difficulty=question.difficulty,
            initial=initial,
            rounds=rounds,
            final=current_v,
            converged=converged,
            cost_calls=self._client.call_count,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
