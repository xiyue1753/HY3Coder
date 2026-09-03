"""Subprocess sandbox for running solver-produced code.

Safety model:
  - Model output (code) is always treated as *data*. Running it is the
    intended evaluation of an algorithm answer — but we still constrain it:
    hard timeout, output-size cap, temp working dir, and (Windows) no window.
  - The sandbox never executes model instructions; the code is only fed to a
    fresh interpreter process with a plain ``input`` stream and captured
    stdout/stderr.
  - Resource limits beyond timeout (memory, CPU) are not enforceable via
    subprocess on Windows; we compensate with a conservative timeout and
    output truncation. On POSIX the same code path works unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_MAX_OUTPUT = 64 * 1024  # 64KB cap per stream (prevent flooding)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration: float
    error: str | None = field(default=None)


# 编译器路径（可用环境变量覆盖；MSYS2 ucrt64 默认）
GPP = os.environ.get("REX_GPP", r"D:\msys64\ucrt64\bin\g++.exe")


def detect_language(code: str) -> str:
    """启发式检测提交代码语言（python / cpp）。

    - 含 `#include <...>` / `using namespace` / `int main()` → cpp
    - 否则视为 python（AI 输出以两者为主，其他语言暂不支持）
    """
    head = (code or "")[:4000]
    if "#include" in head or "using namespace" in head:
        return "cpp"
    return "python"


def run_code(
    code: str,
    stdin: str = "",
    timeout: float = 10.0,
    cwd: Path | None = None,
    language: str = "python",
    compile_timeout: float = 60.0,
) -> SandboxResult:
    """Run ``code`` in a fresh interpreter with the given stdin.

    ``language``: "python" (default) or "cpp". C++ is compiled once per call
    with g++ (C++17) then executed — enables running official AC solutions.
    """
    t0 = time.time()
    work = cwd or Path(tempfile.mkdtemp(prefix="rex_sandbox_"))
    # 强制子进程 UTF-8 I/O：Windows 默认控制台编码是 cp936，读 UTF-8 stdin 会乱码/崩溃
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        if language == "cpp":
            return _run_cpp(code, stdin, timeout, work, env, compile_timeout)
        # python 路径
        target = work / "_rex_prog.py"
        target.write_text(code, encoding="utf-8")
        return _run_proc([sys.executable, str(target)], stdin, timeout, work, env, t0)
    except OSError as e:
        return SandboxResult(
            returncode=-1, stdout="", stderr="",
            timed_out=False, duration=time.time() - t0,
            error=f"sandbox launch failed: {e}",
        )


def _run_proc(cmd: list[str], stdin, timeout, work, env, t0) -> SandboxResult:
    try:
        proc = subprocess.run(
            cmd,
            input=stdin.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=str(work),
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")[:_MAX_OUTPUT]
        err = proc.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")[:_MAX_OUTPUT]
        # 非零退出 = 运行/语法/崩溃错误：stderr 是诊断依据，标记为 error 便于上层识别
        # （此前仅 cpp 编译错误标记 error，python 语法/运行错误被当成普通 WA，诊断信息丢失）
        err_note = None
        if proc.returncode != 0:
            err_note = (err.strip() or f"exit code {proc.returncode}")[:400]
        return SandboxResult(
            returncode=proc.returncode, stdout=out, stderr=err,
            timed_out=False, duration=time.time() - t0,
            error=err_note,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            returncode=-1, stdout="", stderr="",
            timed_out=True, duration=time.time() - t0,
            error=f"timeout after {timeout}s",
        )


def _run_cpp(code: str, stdin, timeout, work, env, compile_timeout) -> SandboxResult:
    """Compile C++ (C++17) with g++ then run the executable."""
    t0 = time.time()
    src = work / "_rex_prog.cpp"
    exe = work / "_rex_prog.exe"
    src.write_text(code, encoding="utf-8")
    # 编译
    try:
        proc = subprocess.run(
            [GPP, "-std=c++17", "-O2", str(src), "-o", str(exe)],
            capture_output=True, timeout=compile_timeout,
            cwd=str(work), env=env, creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(-1, "", "", timed_out=True, duration=time.time() - t0,
                             error=f"compile timeout after {compile_timeout}s")
    if proc.returncode != 0 or not exe.exists():
        err = proc.stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT]
        return SandboxResult(proc.returncode, "", err, False, time.time() - t0,
                             error="compile failed: " + (err[:200] or "g++ error"))
    # 运行编译产物
    return _run_proc([str(exe)], stdin, timeout, work, env, t0)
