"""Static checks on solver-produced code: complexity declaration vs code,
boundary-condition hints. Heuristic diagnostics — feed the verifier and the
report, never a blocking verdict on their own.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from rex.models import Answer, QuestionItem

_COMPLEXITY_RE = re.compile(r"O\s*\(\s*(1|log\s*n|n\s*log\s*n|n\s*\^?\s*\{?2\}?|n\^?2|n\s*3?)\s*\)", re.IGNORECASE)

# 声明复杂度档次: O(1)=0, O(log n)=1, O(n)=2, O(n log n)=3, O(n^2)=4, O(n^3)=5
_DECL_ORDER: dict[str, int] = {
    "1": 0, "logn": 1, "nlogn": 3, "n": 2, "n2": 4, "n3": 5,
}


@dataclass
class StaticDiagnostic:
    category: str                      # "complexity" | "boundary"
    severity: str                      # "warn" | "info"
    detail: str
    code_ref: str = ""                 # 引用的代码片段/行


@dataclass
class StaticCheckResult:
    declared: str | None               # 声明复杂度原文
    estimated: str | None              # 启发式估计
    mismatch: bool
    diagnostics: list[StaticDiagnostic] = field(default_factory=list)


def _extract_declared(answer: Answer) -> str | None:
    for s in answer.steps:
        if s.kind == "complexity":
            m = _COMPLEXITY_RE.search(s.content)
            if m:
                return m.group(0)
    return None


def _estimate_complexity(code: str) -> str | None:
    """Heuristic: loop nesting depth + recursion + inner linear scans."""
    if not code:
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "unknown(syntax)"
    max_depth = 0
    recursion = False

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal max_depth, recursion
        if isinstance(node, (ast.For, ast.While)):
            depth += 1
            max_depth = max(max_depth, depth)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "input" and depth > 0:
                pass
        for child in ast.iter_child_nodes(node):
            walk(child, depth)

    walk(tree, 0)
    if max_depth >= 2:
        return f"O(n^{max_depth})"
    if max_depth == 1:
        return "O(n)"
    if recursion:
        return "O(recursive)"
    return "O(1)"


def _boundary_diagnostics(question: QuestionItem, answer: Answer) -> list[StaticDiagnostic]:
    """Heuristic boundary checks based on problem keywords."""
    code = answer.code or ""
    diags: list[StaticDiagnostic] = []
    prompt = question.prompt.lower()
    if not code:
        return diags

    def _has(patterns: list[str]) -> bool:
        return any(p in code.lower() for p in patterns)

    if "empty" in prompt or "空" in prompt or "非空" in prompt:
        if not _has(["if not ", "len(", "== 0", "if n == 0", "if not data", "if not s"]):
            diags.append(StaticDiagnostic(
                "boundary", "warn",
                "题目涉及空输入边界，代码中未发现显式空/长度为 0 的处理分支",
            ))
    if "negative" in prompt or "负数" in prompt:
        if not _has(["< 0", "abs(", "min(", "max("]):
            diags.append(StaticDiagnostic(
                "boundary", "warn",
                "题目涉及负数，代码中未发现负数处理相关逻辑",
            ))
    if any(k in prompt for k in ("long", "大数", "溢出", "int 范围", "10^9", "1e9")):
        if not _has(["int64", "long", "float(", "Decimal", "mod"]):
            diags.append(StaticDiagnostic(
                "boundary", "info",
                "题目可能涉及大数/溢出，代码未使用宽类型或取模（仅供参考）",
            ))
    if not diags:
        diags.append(StaticDiagnostic("boundary", "info", "未发现明显边界遗漏（启发式）"))
    return diags


def check_static(question: QuestionItem, answer: Answer) -> StaticCheckResult:
    declared = _extract_declared(answer)
    estimated = _estimate_complexity(answer.code or "")
    mismatch = False
    diags: list[StaticDiagnostic] = []
    if declared and estimated:
        est = _normalize(estimated)
        dec = _normalize(declared)
        if est and dec and est > dec:
            mismatch = True
            diags.append(StaticDiagnostic(
                "complexity", "warn",
                f"声明复杂度 {declared} 但代码启发式估计 {estimated}，可能复杂度不达标",
            ))
    diags.extend(_boundary_diagnostics(question, answer))
    return StaticCheckResult(
        declared=declared, estimated=estimated, mismatch=mismatch, diagnostics=diags,
    )


def _normalize(expr: str) -> int | None:
    e = expr.strip().lower().replace(" ", "")
    e = e.replace("o(", "").replace(")", "")
    if e.startswith("n^"):
        e = "n" + e[2:]
    mapping = {
        "1": 0, "logn": 1, "log(n)": 1, "log2n": 1,
        "n": 2, "n": 2, "nlogn": 3, "nlog(n)": 3, "nlog2n": 3,
        "n2": 4, "n^2": 4, "n{2}": 4, "n3": 5, "n^3": 5,
    }
    return mapping.get(e)
