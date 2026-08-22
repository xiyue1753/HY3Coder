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


def run_code(
    code: str,
    stdin: str = "",
    timeout: float = 10.0,
    cwd: Path | None = None,
) -> SandboxResult:
    """Run ``code`` in a fresh interpreter with the given stdin."""
    t0 = time.time()
    work = cwd or Path(tempfile.mkdtemp(prefix="rex_sandbox_"))
    target = work / "_rex_prog.py"
    target.write_text(code, encoding="utf-8")
    # 强制子进程 UTF-8 I/O：Windows 默认控制台编码是 cp936，读 UTF-8 stdin 会乱码/崩溃
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(target)],
            input=stdin.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=str(work),
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
        # Windows 文本模式输出为 CRLF，统一为 \n 便于与期望输出比对
        out = proc.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")[:_MAX_OUTPUT]
        err = proc.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")[:_MAX_OUTPUT]
        return SandboxResult(
            returncode=proc.returncode,
            stdout=out,
            stderr=err,
            timed_out=False,
            duration=time.time() - t0,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            returncode=-1, stdout="", stderr="",
            timed_out=True, duration=time.time() - t0,
            error=f"timeout after {timeout}s",
        )
    except OSError as e:
        return SandboxResult(
            returncode=-1, stdout="", stderr="",
            timed_out=False, duration=time.time() - t0,
            error=f"sandbox launch failed: {e}",
        )
