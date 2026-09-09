"""Sandbox tests: python + cpp language backends."""
from __future__ import annotations

from pathlib import Path

import pytest

from rex.executor.sandbox import GPP, detect_language, run_code
from rex.models import TestCase


def test_python_run() -> None:
    r = run_code("print('hi')", language="python")
    assert r.returncode == 0
    assert r.stdout.strip() == "hi"


def test_python_stdin() -> None:
    r = run_code("import sys\nprint(sum(map(int, sys.stdin.read().split())))",
                 stdin="1 2 3\n", language="python")
    assert r.stdout.strip() == "6"


def test_python_timeout() -> None:
    r = run_code("import time\ntime.sleep(5)", timeout=1, language="python")
    assert r.timed_out


def test_python_syntax_error() -> None:
    r = run_code("def broken(", language="python")
    assert r.returncode != 0


@pytest.mark.skipif(not Path(GPP).exists(), reason="g++ not available")
def test_cpp_run() -> None:
    code = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){int a,b;cin>>a>>b;cout<<a+b<<endl;}"
    r = run_code(code, stdin="2 3\n", language="cpp")
    assert r.returncode == 0
    assert r.stdout.strip() == "5"


def test_detect_language_python() -> None:
    assert detect_language("import sys\nprint('hi')\n") == "python"
    assert detect_language("def solve():\n    return 1\n") == "python"


def test_detect_language_cpp() -> None:
    # 回归：AI 可能提交 C++（#include/using namespace），执行层必须自动识别，
    # 否则 C++ 代码被按 Python 运行 → 输出全空、全判失败（曾致 hard 评测 41.7%→90% 失真）。
    code = "#include <iostream>\nusing namespace std;\nint main(){return 0;}"
    assert detect_language(code) == "cpp"
    assert detect_language("#include <bits/stdc++.h>") == "cpp"


@pytest.mark.skipif(not Path(GPP).exists(), reason="g++ not available")
def test_run_test_cases_auto_detect_cpp() -> None:
    # run_test_cases 传 language="cpp" 时 C++ 代码可正常判题（_execute 已按 detect_language 传参）
    code = ("#include <iostream>\nusing namespace std;\n"
            "int main(){long long a,b;cin>>a>>b;cout<<a+b<<endl;}")
    cases = [TestCase(input="2 3\n", output="5"), TestCase(input="1000000000000 1\n", output="1000000000001")]
    from rex.executor.tests import run_test_cases
    res = run_test_cases(code, cases, language="cpp")
    assert res.pass_rate == 1.0


@pytest.mark.skipif(not Path(GPP).exists(), reason="g++ not available")
def test_cpp_compile_error() -> None:
    code = "#include <bits/stdc++.h>\nint main(){ undeclared_var; }"
    r = run_code(code, language="cpp")
    assert r.error is not None
    assert "compile failed" in (r.error or "")


def test_text_match_multi_float_same_line() -> None:
    """回归：一行含多个空格分隔浮点数（如坐标输出）须按 token 容差比对，
    而非把整行当单个 float 解析（曾致 cf106e 等几何题全部误判失败）。"""
    from rex.executor.tests import _text_match

    # 数值相等、精度不同 → 应匹配
    assert _text_match("0.0000000 0.0000000 0.0000000", "0.000 0.000 0.000")
    assert _text_match("1.000000 2.5000000 3.00000", "1.0 2.5 3.0")
    # token 数不一致 → 不匹配
    assert not _text_match("0.000 1.000", "0.000 1.000 2.000")
    # 数值超出容差 → 不匹配
    assert not _text_match("0.0000000 10.0000000 0.0000000", "0.000 1.000 0.000")
    # 纯文本仍逐 token 精确
    assert _text_match("hello world", "hello world")
    assert not _text_match("hello world", "hello  world!")

