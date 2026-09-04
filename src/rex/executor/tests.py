"""Run public + hidden test cases against solver-produced code."""
from __future__ import annotations

from dataclasses import dataclass, field

from rex.executor.judge import run_checker
from rex.executor.sandbox import run_code
from rex.models import Judge, TestCase

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


_FLOAT_TOL = 1e-5


def _text_match(got: str, expected: str) -> bool:
    """宽松文本比较：逐行、逐空白 token 精确比对；两侧 token 皆浮点数时按误差容忍。

    支持一行含多个空格分隔数值（如坐标输出 `0.000 1.000 2.000`）：整行解析
    为单个 float 会失败，故按 token 比较。token 数不一致视为不匹配。
    """
    g = [ln.strip() for ln in got.rstrip().split("\n")]
    e = [ln.strip() for ln in expected.rstrip().split("\n")]
    if len(g) != len(e):
        return False
    for gl, el in zip(g, e):
        gt, et = gl.split(), el.split()
        if gt == et:
            continue
        if len(gt) != len(et):
            return False
        for a, b in zip(gt, et):
            if a == b:
                continue
            try:
                fa, fb = float(a), float(b)
            except ValueError:
                return False
            if abs(fa - fb) > _FLOAT_TOL * max(1.0, abs(fb), abs(fa)):
                return False
    return True


def run_test_cases(
    code: str,
    test_cases: list[TestCase],
    timeout: float = 10.0,
    language: str = "python",
    judge: Judge | str = Judge.EXACT,
    checker_code: str | None = None,
    checker_language: str = "python",
    checker_timeout: float = 20.0,
) -> TestRunResult:
    """Execute each test case in isolation; compare stdout to expected output.

    Normalization: strip trailing whitespace from both sides, and ignore a
    single trailing blank line difference (many judges accept it).
    ``language`` is passed to the sandbox (python/cpp).

    Judge modes:
    - exact (default): text compare (with float tolerance, see _text_match)
    - special: output has no unique reference text (constructive problems);
      run ``checker_code`` against (tc.input, solver stdout) to decide AC.
    """
    if not code:
        return TestRunResult(0, 0, 0.0, error="no code to run")
    special = Judge(judge) == Judge.SPECIAL
    if special and not checker_code:
        return TestRunResult(len(test_cases), 0, 0.0, error="special judge missing checker_code")
    total = len(test_cases)
    passed = 0
    failed_public: list[int] = []
    failed_hidden = 0
    compile_err: str | None = None

    for i, tc in enumerate(test_cases):
        res = run_code(code, stdin=tc.input, timeout=timeout, language=language)
        if res.error:
            # 运行级错误：首个非超时错误记为 error（如语法错误），其余继续
            if not res.timed_out:
                compile_err = compile_err or res.error or res.stderr.strip()[:300]
            if res.timed_out:
                pass  # 计入失败
        elif special:
            # SPJ：判定输出是否满足题目谓词（不比对期望文本）
            ok, _msg = run_checker(checker_code, checker_language,
                                   tc.input, res.stdout, timeout=checker_timeout)
            if ok:
                passed += 1
                continue
        else:
            # 多数 OJ 判题忽略行尾空白/尾部换行差异：两边统一 rstrip() 比较。
            # 浮点输出：若两侧同位置行都可解析为浮点数，按相对/绝对误差 1e-5 判定
            # （不同 AC 提交打印精度不同，如 1.0000000001 vs 1.0）。
            if _text_match(res.stdout, tc.output):
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
