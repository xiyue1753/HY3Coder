"""Special Judge (SPJ) runner for multi-solution / constructive problems.

背景：常规算法题输出唯一，用"期望文本比对"（exact）即可判定。但构造类/多解题
（如 AtCoder abc216_c Many Balls：输出任意合法操作序列）没有唯一期望文本，
必须由 checker 判定"输出是否满足题目谓词"。本模块提供 checker 执行约定与入口。

checker 协议
------------
checker 是一段**可信代码**（Python 或 C++，由人工为题目编写，非模型输出），
通过 stdin 收到两段拼接内容：

    第一段：原题输入（原样）
    分隔行：``@@REX_USER_OUTPUT@@``（单独一行）
    第二段：被判定程序（AI 解 / 候选 AC）的标准输出（stdout，原样）

checker 解析出这两段后，按题目约束校验第二段是否合法，最后在 stdout 打印
``AC``（接受）或任意其它内容（拒绝，建议打印具体原因便于诊断）。

安全说明：checker 由我们编写（可信），但统一走 run_code 沙盒执行，避免
checker 自身 bug 影响宿主进程，并继承超时/输出上限等约束。
"""
from __future__ import annotations

import re

from rex.executor.sandbox import run_code

# 拼接分隔符（单独一行）。出现在题目正常输入/输出的概率极低。
SEPARATOR = "@@REX_USER_OUTPUT@@"


def build_checker_stdin(problem_input: str, user_output: str) -> str:
    """按协议拼接 checker 的 stdin。"""
    return f"{problem_input}\n{SEPARATOR}\n{user_output}"


def parse_split_stdin(stdin: str) -> tuple[str, str]:
    """从拼接 stdin 还原 (原题输入, 被测输出)。供 checker 人工编写时参考。"""
    idx = stdin.rfind(SEPARATOR)
    if idx == -1:
        return stdin, ""
    before = stdin[:idx]
    rest = stdin[idx + len(SEPARATOR):]
    if before.endswith("\n"):
        before = before[:-1]
    if rest.startswith("\n"):
        rest = rest[1:]
    return before, rest


def run_checker(
    checker_code: str,
    checker_language: str,
    problem_input: str,
    user_output: str,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """运行 checker 判定 user_output 是否满足题目谓词。

    Returns (accepted, message)。accepted=True 当且仅当 checker 输出 ``AC``。
    """
    if not checker_code:
        return False, "no checker_code"
    stdin = build_checker_stdin(problem_input, user_output)
    res = run_code(checker_code, stdin=stdin, timeout=timeout, language=checker_language)
    if res.error:
        return False, f"checker 运行失败: {res.error}"
    out = res.stdout.strip()
    accepted = bool(re.match(r"^AC\b", out, re.IGNORECASE))
    return accepted, out[:200]
