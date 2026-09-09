"""SPJ checker for Codeforces 549G "Happy Line" (构造/多解).

题意：n 人排队（位置 1=队尾，位置 n=队首）。初始位置 i 的人有 a_i 美元。
规则：若 a 站在 b 正后方（a 更靠队尾），a 可付 b 1 美元后两人交换（即 a
向队首前进一位、花 1 元；b 向队尾退一位、赚 1 元）。0 元者不能付。
目标：使所有居民 happy —— 队首者天然 happy；其余人前方紧邻者钱 >= 他，
即从队尾到队首金额**非递减**。输出任一可达 happy 排列（各位置最终钱数），
否则输出 ":("。

可达性核心引理：
  一个从位置 p 移到最终位置 q 的居民，净钱变化 = p - q
  （前进一步花 1，后退一步赚 1，总和恒为 p-q）。
  因此 初始元素 i（钱 a_i，位置 i）贡献"价值" v_i = a_i + i；
  最终位置 q 的钱 b_q 必满足 b_q + q 等于某个 v_i。
  ⇒ 可行当且仅当 multiset{ a_i + i } == multiset{ b_q + q }，且 b 非递减
    （happy）。参考解即构造 b：排序 a_i+i 后逐个减 q（q 从 1 起）再查非递减。

checker 判定：
  1. 输出 ":(" → 用排序法判定是否确实无解（构造候选 b 并查非递减）。
  2. 输出序列 b → |b|=n、非递减、且 multiset(a_i+i)==multiset(b_q+q)。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def feasible(a):
    """判断是否存在 happy 可达排列。返回 True/False。"""
    n = len(a)
    v = sorted(a[i] + (i + 1) for i in range(n))  # 1-based 位置
    cand = [v[q] - (q + 1) for q in range(n)]
    return all(cand[i] <= cand[i + 1] for i in range(n - 1))


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    in_lines = inp.splitlines()
    try:
        n = int(in_lines[0].strip())
    except (ValueError, IndexError):
        print("WA: n 解析失败")
        return
    if len(in_lines) < 2:
        print("WA: 缺 a 行")
        return
    a = list(map(int, in_lines[1].split()))
    if len(a) != n:
        print("WA: a 长度不符")
        return

    out = out.strip()
    if out == ":(":
        print("AC" if not feasible(a) else "WA: 存在 happy 解，不应 :(")
        return

    parts = out.split()
    if len(parts) != n:
        print(f"WA: 需输出 {n} 个数，实际 {len(parts)}")
        return
    try:
        b = [int(x) for x in parts]
    except ValueError:
        print("WA: 输出含非整数")
        return
    # happy: 队尾->队首 非递减（前面人的钱 >= 后面）
    for i in range(n - 1):
        if b[i] > b[i + 1]:
            print(f"WA: 非 happy（位置 {i+1} 钱 {b[i]} > 前面 {b[i+1]}）")
            return
    # 价值守恒
    v_in = sorted(a[i] + (i + 1) for i in range(n))
    v_out = sorted(b[q] + (q + 1) for q in range(n))
    if v_in != v_out:
        print("WA: 价值守恒不成立（a_i+i 与 b_q+q 多重集不等）")
        return
    print("AC")


if __name__ == "__main__":
    main()
