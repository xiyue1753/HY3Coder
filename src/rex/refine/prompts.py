"""Mapping VerificationResult findings -> actionable RefineFeedback.

The feedback must be *actionable*: point at a step id, name the error type,
state why it is wrong, and say how to fix it. Only error findings produce
feedback; a CORRECT verdict yields no feedback (loop terminates).
"""
from __future__ import annotations

from rex.models import ErrorFinding, ErrorSeverity, RefineFeedback, VerificationResult, Verdict
from rex.verifier.errors import describe


def findings_to_feedback(verification: VerificationResult) -> list[RefineFeedback]:
    """Convert verifier findings into revision instructions (limited set).

    severity 语义（P1）：只有 fatal（实质缺陷）才驱动修正——minor 不破坏
    推理链成立性，不产生修订指令（避免对表述瑕疵空转修正轮）。
    """
    if verification.verdict == Verdict.CORRECT:
        return []
    feedbacks: list[RefineFeedback] = []
    for f in verification.findings:
        # minor 不驱动修正；仅 fatal（默认 severity=fatal 也视为 fatal）
        if getattr(f, "severity", ErrorSeverity.FATAL) == ErrorSeverity.MINOR:
            continue
        # 相同 step+type 只保留首条，避免同一步被重复指令轰炸
        key = (f.step_id, f.error_type.value)
        if any((x.step_id, x.error_type.value) == key for x in feedbacks):
            continue
        feedbacks.append(_to_feedback(f))
    if not feedbacks:
        # 无具体 finding（如 verdict=ANSWER_INCORRECT 但没定位）→ 生成整体指令
        feedbacks.append(RefineFeedback(
            step_id=None,
            error_type=verification.findings[0].error_type if verification.findings else None,
            instruction=(
                f"整体判定为 {verification.verdict.value}，请重新完整推导并核对最终答案，"
                "确保每一步都可验证。"
            ),
            evidence="verifier 未给出具体步骤定位",
        ))
    return feedbacks


def _to_feedback(f: ErrorFinding) -> RefineFeedback:
    desc = describe(f.error_type)
    where = f"第 {f.step_id} 步" if f.step_id is not None else "整体过程"
    instruction = (
        f"{where}存在{f.error_type.value}类型问题（{desc}）：{f.detail}。"
        "请修正该步骤及相关联步骤，并重新输出完整解题过程。"
    )
    return RefineFeedback(
        step_id=f.step_id,
        error_type=f.error_type,
        instruction=instruction,
        evidence=f.evidence,
    )
