"""Verifier agent: two independent judge perspectives + arbiter.

- View A (self-containment first) and View B (global backtrace first) judge
  the same (question, answer) independently.
- Same verdict  -> merge findings, arbiter = whichever view had higher confidence.
- Different     -> an arbiter model call decides; if the arbiter itself is
  low-confidence it still returns, and the pipeline may flag HUMAN_REVIEW.
"""
from __future__ import annotations

import json
import logging
import time

from rex._json import extract_json_object
from rex.hy3_client import Hy3Client, Hy3Error
from rex.models import Answer, ErrorFinding, QuestionItem, VerificationResult, Verdict
from rex.verifier.prompts import (
    ARBITER_SYSTEM,
    arbiter_user_prompt,
    verifier_system,
    verify_user_prompt,
)

log = logging.getLogger(__name__)


class VerifierAgent:
    def __init__(
        self,
        client: Hy3Client,
        max_json_retries: int = 2,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._max_json_retries = max_json_retries
        self._reasoning = reasoning_effort

    def verify(
        self,
        question: QuestionItem,
        answer: Answer,
        static_evidence: str | None = None,
        execution_feedback: str | None = None,
    ) -> VerificationResult:
        """Two-perspective cross-check + arbitration when they disagree.

        ``static_evidence``: optional rule-based diagnostic block (from
        static_check) fed to both views as an additional evidence source.
        The verdict remains decided by the LLM judge — static checks are an
        orthogonal signal, never a blocking verdict.

        ``execution_feedback``: optional **objective** sandbox/compare result
        (e.g. answer is provably wrong on hidden tests). It is fed to both
        views and the arbiter as factual evidence; when it shows the answer is
        wrong, the verdict must not be CORRECT.
        """
        t0 = time.time()
        v1 = self._verify_view("A", question, answer, static_evidence, execution_feedback)
        v2 = self._verify_view("B", question, answer, static_evidence, execution_feedback)

        if v1.verdict == v2.verdict:
            merged = self._merge(v1, v2)
            merged.arbiter = "V1" if v1.confidence >= v2.confidence else "V2"
            merged.timestamp = t0
            return merged

        # 分歧 -> 仲裁
        log.info("verifier views disagree (%s vs %s), calling arbiter",
                 v1.verdict.value, v2.verdict.value)
        try:
            verdict = self._arbitrate(question, answer, v1, v2, execution_feedback)
        except Hy3Error as e:
            log.warning("arbiter call failed (%s); fall back to higher-confidence view", e)
            verdict = v1 if v1.confidence >= v2.confidence else v2
            verdict.arbiter = "HUMAN_REVIEW"
            verdict.timestamp = t0
            return verdict
        verdict.arbiter = "ARBITER"
        verdict.timestamp = t0
        return verdict

    # -- internals ---------------------------------------------------------
    def _verify_view(
        self,
        view: str,
        question: QuestionItem,
        answer: Answer,
        static_evidence: str | None = None,
        execution_feedback: str | None = None,
    ) -> VerificationResult:
        system = verifier_system(view)
        user = verify_user_prompt(question, answer, static_evidence, execution_feedback)
        raw = self._chat_json(system, user)
        return _parse_verification(raw)

    def _arbitrate(
        self,
        question: QuestionItem,
        answer: Answer,
        v1: VerificationResult,
        v2: VerificationResult,
        execution_feedback: str | None = None,
    ) -> VerificationResult:
        user = arbiter_user_prompt(
            question, answer, v1.model_dump_json(indent=1),
            v2.model_dump_json(indent=1), execution_feedback,
        )
        raw = self._chat_json(ARBITER_SYSTEM, user)
        return _parse_verification(raw)

    @property
    def call_count(self) -> int:
        """模型调用计数（含重试），供成本核算。"""
        return self._client.call_count

    def _chat_json(self, system: str, user: str) -> str:
        last_err: str | None = None
        for attempt in range(self._max_json_retries + 1):
            msg = user
            if last_err and attempt > 0:
                msg = (
                    f"{user}\n\n注意：你上次输出无法解析为合法 JSON，错误：{last_err}\n"
                    "请只输出一个合法的 JSON 对象（不要代码块围栏、不要解释文字）。"
                )
            raw = self._client.chat(msg, system=system, reasoning_effort=self._reasoning)
            try:
                extract_json_object(raw)  # 先验证可提取，再交给解析
                return raw
            except ValueError as e:
                last_err = str(e)
                log.warning("verifier JSON parse failed (attempt %d): %s", attempt + 1, last_err)
        raise Hy3Error(f"verifier: invalid JSON after {self._max_json_retries + 1} attempts")

    @staticmethod
    def _merge(a: VerificationResult, b: VerificationResult) -> VerificationResult:
        """Merge two agreeing verdicts: union findings, take max confidence."""
        seen: set[tuple] = set()
        findings: list[ErrorFinding] = []
        for f in a.findings + b.findings:
            key = (f.step_id, f.error_type, f.detail)
            if key not in seen:
                seen.add(key)
                findings.append(f)
        return VerificationResult(
            verdict=a.verdict,
            findings=findings,
            confidence=max(a.confidence, b.confidence),
        )


def _parse_verification(text: str) -> VerificationResult:
    obj = json.loads(extract_json_object(text))
    result = VerificationResult.model_validate(obj)
    if result.verdict not in Verdict:
        raise ValueError(f"unknown verdict: {result.verdict}")
    return result
