"""Run public + hidden test cases against solver-produced code."""
from __future__ import annotations

from dataclasses import dataclass, field

from rex.executor.sandbox import run_code
from rex.models import TestCase

_MAX_REPORTED_FAILURES = 5


@dataclass
class TestRunResult:
    total: int
    passed: int
    pass_rate: float
    failed_public: list[int] = field(default_factory=list)  # 失败公开用例序号
    failed_hidden: int = 0                                   # 失败隐藏用例数（不泄露内容）
    error: str | None = None                                 # 编译/运行级错误
    timed_out: bool = False


def run_test_cases(
    code: str,
    test_cases: list[TestCase],
    timeout: float = 10.0,
) -> TestRunResult:
    """Execute each test case in isolation; compare stdout to expected output.

    Normalization: strip trailing whitespace from both sides, and ignore a
    single trailing blank line difference (many judges accept it).
    """
    if not code:
        return TestRunResult(0, 0, 0.0, error="no code to run")
    total = len(test_cases)
    passed = 0
    failed_public: list[int] = []
    failed_hidden = 0
    compile_err: str | None = None

    for i, tc in enumerate(test_cases):
        res = run_code(code, stdin=tc.input, timeout=timeout)
        if res.error:
            # 运行级错误：首个非超时错误记为 error（如语法错误），其余继续
            if not res.timed_out:
                compile_err = compile_err or res.error or res.stderr.strip()[:300]
            if res.timed_out:
                pass  # 计入失败
        else:
            actual = res.stdout.rstrip("\n")
            expected = tc.output.rstrip("\n")
            if actual == expected:
                passed += 1
                continue
        if tc.hidden:
            failed_hidden += 1
        elif len(failed_public) < _MAX_REPORTED_FAILURES:
            failed_public.append(i)

    return TestRunResult(
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        failed_public=failed_public,
        failed_hidden=failed_hidden,
        error=compile_err,
        timed_out=False,
    )
