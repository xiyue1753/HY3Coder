"""P1–P3 判定语义测试：severity 驱动 verdict、重建测试、一致性兜底。"""
from __future__ import annotations

import json

from rex.models import (
    Answer,
    ErrorSeverity,
    ErrorType,
    EvalRecord,
    QuestionItem,
    Step,
    VerificationResult,
    Verdict,
)
from rex.pipeline import _reconcile_verdict
from rex.verifier.agent import _enforce_fatal_consistency, _parse_verification
from rex.refine.agent import _strip_minor_only

Q = QuestionItem(id="A000", scene="algorithm", title="t", prompt="p",
                 difficulty="basic", source="self", standard_answer="2")


def _v(verdict: str, findings: list | None = None, conf: float = 0.9) -> VerificationResult:
    return VerificationResult.model_validate(
        {"verdict": verdict, "findings": findings or [], "confidence": conf})


def _f(step: int, etype: str = "jump", sev: str = "fatal", detail: str = "d") -> dict:
    return {"step_id": step, "error_type": etype, "severity": sev,
            "detail": detail, "evidence": "e"}


def _f_no_sev(step: int = 1, etype: str = "jump", detail: str = "d") -> dict:
    """无 severity 字段（兼容旧格式 → pydantic 默认 fatal）。"""
    return {"step_id": step, "error_type": etype, "detail": detail, "evidence": "e"}


# --- severity 缺省行为（兼容旧数据/模型不输出 severity → 视为 fatal）---
def test_severity_default_is_fatal() -> None:
    v = _v("PROCESS_INCORRECT", [_f_no_sev(1)])
    assert v.findings[0].severity == ErrorSeverity.FATAL


def test_minor_severity_parsed() -> None:
    v = _v("CORRECT", [_f(1, "calculation", "minor")])
    assert v.findings[0].severity == ErrorSeverity.MINOR


# --- P3a: agent 层硬矛盾兜底：fatal finding + CORRECT → 不合法，强制 PROCESS_INCORRECT ---
def test_enforce_fatal_not_correct() -> None:
    res = _v("CORRECT", [_f(1, "concept", "fatal")])
    _enforce_fatal_consistency(res)
    assert res.verdict == Verdict.PROCESS_INCORRECT


def test_enforce_no_fatal_preserves_verdict() -> None:
    res = _v("CORRECT", [])
    _enforce_fatal_consistency(res)
    assert res.verdict == Verdict.CORRECT
    res2 = _v("PROCESS_INCORRECT", [])
    _enforce_fatal_consistency(res2)  # 无沙盒信号，不动
    assert res2.verdict == Verdict.PROCESS_INCORRECT


# --- P1: verdict 由 findings severity 驱动（pipeline 有沙盒信号，权威裁决）---
def test_reconcile_answer_correct_no_fatal_to_correct() -> None:
    """答案对 + 仅 minor → 剥离：PROCESS_INCORRECT/SILENT → CORRECT。"""
    v = _v("PROCESS_INCORRECT", [_f(1, "calculation", "minor")])
    _reconcile_verdict(v, answer_correct=True)
    assert v.verdict == Verdict.CORRECT


def test_reconcile_answer_correct_fatal_stays_silent() -> None:
    """答案对 + fatal → 强制 SILENT_FAILURE（不得 CORRECT/ANSWER_INCORRECT）。"""
    v = _v("CORRECT", [_f(1, "logic", "fatal")])
    _reconcile_verdict(v, answer_correct=True)
    assert v.verdict == Verdict.SILENT_FAILURE


def test_reconcile_answer_wrong_never_correct() -> None:
    """答案错 → CORRECT/SILENT 不合法。"""
    v = _v("CORRECT", [])
    _reconcile_verdict(v, answer_correct=False)
    assert v.verdict == Verdict.ANSWER_INCORRECT
    v2 = _v("SILENT_FAILURE", [_f(1, "logic", "fatal")])
    _reconcile_verdict(v2, answer_correct=False)
    assert v2.verdict == Verdict.PROCESS_INCORRECT


def test_reconcile_no_signal_preserves() -> None:
    v = _v("PROCESS_INCORRECT", [_f(1, "concept", "fatal")])
    _reconcile_verdict(v, answer_correct=None)
    assert v.verdict == Verdict.PROCESS_INCORRECT


# --- P3b: refine 无沙盒 → 仅 minor 视同正确（避免空转修正）---
def test_strip_minor_only_refine() -> None:
    v = _v("PROCESS_INCORRECT", [_f(1, "format", "minor")])
    out = _strip_minor_only(v)
    assert out.verdict == Verdict.CORRECT
    v2 = _v("PROCESS_INCORRECT", [_f(1, "logic", "fatal")])
    assert _strip_minor_only(v2).verdict == Verdict.PROCESS_INCORRECT


# --- P2: 重建测试语义 —— 由 prompt 保证；这里测 parse 缺 severity 的兼容路径 ---
def test_parse_verification_with_minor() -> None:
    raw = json.dumps({"verdict": "CORRECT",
                      "findings": [{"step_id": 1, "error_type": "calculation",
                                    "severity": "minor", "detail": "d", "evidence": "e"}],
                      "confidence": 0.8})
    res = _parse_verification(raw)
    assert res.findings[0].severity == ErrorSeverity.MINOR


def test_parse_verification_missing_severity_defaults_fatal() -> None:
    raw = json.dumps({"verdict": "PROCESS_INCORRECT",
                      "findings": [{"step_id": 1, "error_type": "concept",
                                    "detail": "d", "evidence": "e"}],
                      "confidence": 0.8})
    res = _parse_verification(raw)
    assert res.findings[0].severity == ErrorSeverity.FATAL
