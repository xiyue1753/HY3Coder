"""Special Judge (SPJ) 测试：checker 执行与多解构造题判定。

用两道极小"多解"题验证判定语义：
1. 构造操作序列题（模拟 abc216_c Many Balls 语义：A=+1, B=×2）
2. 输出任意无重复排列使其前缀和均不被整除
checker 均为 Python，走沙盒执行。
"""
from __future__ import annotations

from rex.executor.judge import build_checker_stdin, parse_split_stdin, run_checker
from rex.executor.tests import run_test_cases
from rex.models import Judge, QuestionItem, TestCase

# -- 1) 多解构造题：从 0 出发用 A(+1)/B(×2) 到达 N --------------------------
# 题面谓词：S 只含 A/B，按序作用后值恰好为 N（N<=10，操作数不限）
CHECKER_OPS = r'''
import sys
data = sys.stdin.read()
idx = data.find("@@REX_USER_OUTPUT@@")
inp = data[:idx].strip()
out = data[idx + len("@@REX_USER_OUTPUT@@") :].strip()
N = int(inp)
if not out or any(c not in "AB" for c in out):
    print("WA: 必须是非空 A/B 序列")
    sys.exit(0)
x = 0
for c in out:
    if c == "A":
        x += 1
    else:
        x *= 2
    if x > 10 ** 6:
        print("WA: 中间值过大")
        sys.exit(0)
if x == N:
    print("AC")
else:
    print(f"WA: 终值 {x} != {N}")
'''


def _mk_ops_q() -> QuestionItem:
    return QuestionItem(
        id="A_SPJ1", scene="algorithm", title="t", prompt="...", difficulty="basic",
        source="self", standard_answer="",
        judge=Judge.SPECIAL, checker_code=CHECKER_OPS, checker_language="python",
        test_cases=[TestCase(input="5", output="", hidden=False),
                    TestCase(input="1", output="", hidden=True)],
    )


def test_parse_split_stdin_roundtrip() -> None:
    inp, out = parse_split_stdin(build_checker_stdin("5\n", "AABB\n"))
    assert inp == "5\n"
    assert out == "AABB\n"  # 输出尾部换行保留（属于内容，checker 自行 strip）


def test_run_checker_accepts_any_valid_sequence() -> None:
    # 多种合法序列都应被接受（这正是 exact 文本比对做不到的）
    for seq in ("AABA", "ABBA", "ABAAA", "AAAAA"):  # 均为从 0 经 A/B 到达 5
        ok, msg = run_checker(CHECKER_OPS, "python", "5", seq + "\n")
        assert ok, (seq, msg)


def test_run_checker_rejects_invalid() -> None:
    ok, msg = run_checker(CHECKER_OPS, "python", "5", "CCC\n")
    assert not ok
    assert "A/B" in msg
    ok, _ = run_checker(CHECKER_OPS, "python", "5", "AAB")  # 终值 4 != 5
    assert not ok


def test_run_test_cases_special_accepts_alternative_solution() -> None:
    """AI 解输出与官方参考解不同文本但合法 → 判对。"""
    q = _mk_ops_q()
    # 用 "AAAAA" 到达 5（参考解可能是 AABA），special 应判 100%
    alt_code = 'n = int(input())\nprint("A" * n)\n'
    res = run_test_cases(alt_code, q.test_cases, judge=q.judge,
                         checker_code=q.checker_code, checker_language=q.checker_language)
    assert res.pass_rate == 1.0


def test_run_test_cases_special_rejects_bad_solution() -> None:
    q = _mk_ops_q()
    bad_code = 'n = int(input())\nprint("A" * (n - 1))\n'
    res = run_test_cases(bad_code, q.test_cases, judge=q.judge,
                         checker_code=q.checker_code, checker_language=q.checker_language)
    assert res.pass_rate < 1.0
