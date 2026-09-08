"""Verifier agent: two independent judge perspectives + mandatory arbiter.

- View A (self-containment first) and View B (global backtrace first) judge
  the same (question, answer) independently.
- The ARBITER reviews both perspectives (whether or not they agree) and is
  the single deliverer of the final verdict/arbiter label. 一致/分歧不改变
  该流程：最终评估结果一律由 ARBITER 交付。
- If the arbiter call fails after retries, fall back to the higher-confidence
  view and mark arbiter=HUMAN_REVIEW (the pipeline may then flag it).
"""
from __future__ import annotations

import json
import logging
import time

from rex._json import extract_json_object
from rex.hy3_client import Hy3Client, Hy3Error
from rex.models import Answer, ErrorFinding, ErrorSeverity, QuestionItem, VerificationResult, Verdict
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
        """Two perspectives judged, then a mandatory ARBITER issues the final verdict.

        无论 V1/V2 是否一致，都由 ARBITER 复核双方判定并交付最终结果
        （arbiter 恒为 "ARBITER"；仅当仲裁调用重试耗尽后回退 HUMAN_REVIEW）。

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

        log.info("verifier views done (%s vs %s), calling arbiter (mandatory)",
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
        return self._chat_verify(system, user)

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
        return self._chat_verify(ARBITER_SYSTEM, user)

    @property
    def call_count(self) -> int:
        """模型调用计数（含重试），供成本核算。"""
        return self._client.call_count

    def _chat_json(self, system: str, user: str,
                   validator=None) -> VerificationResult:
        """模型调用 + 重试，覆盖 JSON 提取失败与 schema 校验失败两类错误。

        ``validator``：``str -> VerificationResult`` 的解析函数（含 pydantic
        enum/结构校验）。LLM 可能输出合法 JSON 但字段非法（如
        ``error_type='concept/logic'`` 连写、severity 拼错），此类错误此前
        不重试直接抛 Hy3Error → 单题失败。现把 schema 错误一并反馈重试。
        """
        last_err: str | None = None
        for attempt in range(self._max_json_retries + 1):
            msg = user
            if last_err and attempt > 0:
                msg = (
                    f"{user}\n\n注意：你上次输出不合格，错误：{last_err}\n"
                    "请只输出一个合法的 JSON 对象（不要代码块围栏、不要解释文字），"
                    "并确保 error_type 必须是枚举值之一、severity 只能是 fatal 或 minor。"
                )
            raw = self._client.chat(msg, system=system, reasoning_effort=self._reasoning)
            try:
                extract_json_object(raw)  # 先验证可提取
                if validator is None:
                    return raw  # type: ignore[return-value]  # 兼容旧调用方
                return validator(raw)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = str(e)
                log.warning("verifier output invalid (attempt %d): %s", attempt + 1, last_err)
        raise Hy3Error(f"verifier: invalid output after {self._max_json_retries + 1} attempts")

    def _chat_verify(self, system: str, user: str) -> VerificationResult:
        """view/arbiter 的模型调用：JSON 提取 + schema 校验统一重试。"""
        return self._chat_json(system, user, validator=_parse_verification)

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
    _enforce_fatal_consistency(result)
    return result


def _enforce_fatal_consistency(result: VerificationResult) -> None:
    """程序化一致性：存在 fatal finding 时 verdict 不得为 CORRECT。

    防止 LLM 自相矛盾（报了实质缺陷却仍判 CORRECT）。无 fatal 时不动 verdict
    ——"剥离 minor"依赖 answer_correct 客观信号，在 pipeline 层完成（那里有
    沙盒结果）；此处只消除 fatal↔CORRECT 的硬矛盾。
    """
    if result.verdict == Verdict.CORRECT:
        has_fatal = any(
            getattr(f, "severity", ErrorSeverity.FATAL) == ErrorSeverity.FATAL
            for f in result.findings
        )
        if has_fatal:
            # LLM 自相矛盾：报了实质缺陷却仍判 CORRECT → 强制 PROCESS_INCORRECT
            result.verdict = Verdict.PROCESS_INCORRECT
            log.info("verifier: 存在 fatal finding 却判 CORRECT，强制 PROCESS_INCORRECT")
        return
    # 非 CORRECT：若完全没有 fatal（只有 minor 或无 findings），此处无沙盒信号
    # 无法判断答案对错——保留判定让 pipeline 依据 answer_correct 做最终裁决。
    if result.verdict in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
        has_fatal = any(
            getattr(f, "severity", ErrorSeverity.FATAL) == ErrorSeverity.FATAL
            for f in result.findings
        )
        if not has_fatal:
            log.info("verifier: 无 fatal finding 却判 %s（共 %d findings），"
                     "交由 pipeline 依据答案正确性裁决",
                     result.verdict.value, len(result.findings))
