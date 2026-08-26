"""Sandbox tests: python + cpp language backends."""
from __future__ import annotations

from pathlib import Path

import pytest

from rex.executor.sandbox import GPP, run_code


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


@pytest.mark.skipif(not Path(GPP).exists(), reason="g++ not available")
def test_cpp_compile_error() -> None:
    code = "#include <bits/stdc++.h>\nint main(){ undeclared_var; }"
    r = run_code(code, language="cpp")
    assert r.error is not None
    assert "compile failed" in (r.error or "")
