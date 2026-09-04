"""SPJ checker for Codeforces 1912E "Evaluate It and Back Again".

题意：给定 p, q，输出一个算术表达式（仅数字 0-9 与 + - *，无括号、无空格、
无一元 +-、数字无前导零，且表达式与其整体反转都 well-formed），长度 ≤1000。
要求：按标准优先级正读求值 = p；将表达式**整体反转**后再按标准优先级求值 = q。

判定谓词：
  1) 表达式语法合法（字符集/长度/前导零/一元运算/首尾 token）。
  2) 反转串同样语法合法（反转后数字可能翻转，前导零约束同样适用）。
  3) eval(expr) == p 且 eval(expr[::-1]) == q。

stdin 协议见 rex/executor/judge.py（输入 + @@REX_USER_OUTPUT@@ + 选手输出）。
"""
from __future__ import annotations

import re
import sys

SEP = "@@REX_USER_OUTPUT@@"


# ---- 表达式求值（+ - *，标准优先级，无括号，无空格）----------------------
def tokenize(s: str) -> list[str]:
    """拆成 token：非负整数与 + - *。若含非法字符返回 []。"""
    if not re.fullmatch(r"[0-9+\-*]+", s):
        return []
    return re.findall(r"\d+|[+\-*]", s)


def eval_tokens(tokens: list[str]) -> int | None:
    """按 + - * 标准优先级求值（乘除优先级高、左结合）。"""
    if not tokens:
        return None
    # 数值栈 + 运算符（遇到 + - 暂存；* 立即合并）
    values: list[int] = []
    ops: list[str] = []
    try:
        values.append(int(tokens[0]))
        i = 1
        while i < len(tokens):
            op = tokens[i]
            num = int(tokens[i + 1])
            if op == "*":
                values[-1] *= num
            else:
                ops.append(op)
                values.append(num)
            i += 2
    except (ValueError, IndexError):
        return None
    total = values[0]
    for op, v in zip(ops, values[1:]):
        total = total + v if op == "+" else total - v
    return total


def is_well_formed(s: str) -> bool:
    """表达式（或其反转）语法合法性检查。"""
    if not s:
        return False
    if len(s) > 1000:
        return False
    if not re.fullmatch(r"[0-9+\-*]+", s):
        return False
    toks = tokenize(s)
    if not toks:
        return False
    # 首尾不能是运算符；不能出现连续运算符（无一元运算）
    if toks[0] in "+-*" or toks[-1] in "+-*":
        return False
    if any(t in "+-*" and nxt in "+-*" for t, nxt in zip(toks, toks[1:])):
        return False
    # 数字无前导零（'0' 单独合法；'00'/'01' 非法）
    for t in toks:
        if t not in "+-*" and len(t) > 1 and t[0] == "0":
            return False
    return True


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    lines = inp.splitlines()
    if not lines:
        print("WA: 输入为空")
        return
    try:
        p, q = map(int, lines[0].split())
    except ValueError:
        print("WA: p/q 解析失败")
        return

    expr = out
    if not expr:
        print("WA: 输出为空")
        return
    if "\n" in expr or "\r" in expr:
        print("WA: 输出不能包含换行/空格")
        return
    if not is_well_formed(expr):
        print("WA: 表达式语法非法（字符/前导零/一元运算）")
        return
    if not is_well_formed(expr[::-1]):
        print("WA: 反转后表达式语法非法（反转数字前导零）")
        return

    v1 = eval_tokens(tokenize(expr))
    v2 = eval_tokens(tokenize(expr[::-1]))
    if v1 is None or v2 is None:
        print("WA: 表达式求值失败")
        return
    if v1 != p:
        print(f"WA: 正读值 {v1} != {p}")
        return
    if v2 != q:
        print(f"WA: 反读值 {v2} != {q}")
        return
    print("AC")


if __name__ == "__main__":
    main()
