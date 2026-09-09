"""SPJ checker for Codeforces 1054C "Candies Distribution" (构造/多解).

题意：n 个孩子按 1..n 坐。给定每个孩子的 l_i（左侧糖果多于他的人数）与
r_i（右侧多于他的人数）。构造糖果数 a_i（1..n）使所有孩子算得一致，否则
NO。多解任取。

checker：
  1. 输出 NO → 用标准贪心尝试构造；构造并全量验证成功则 NO 错误(WA)，
     否则接受 NO。
  2. 输出 YES + a_1..a_n → a_i∈[1,n]，且逐孩子重算 l_i/r_i 与输入一致。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def try_build(n, L, R):
    """标准构造：按 l_i+r_i 降序发糖 1..n（少糖=多人比他多）。返回 a 或 None。"""
    order = sorted(range(n), key=lambda i: -(L[i] + R[i]))
    a = [0] * n
    for rank, idx in enumerate(order):
        a[idx] = rank + 1  # 0..n-1 对应 1..n
    # 验证
    for i in range(n):
        l = sum(1 for j in range(i) if a[j] > a[i])
        r = sum(1 for j in range(i + 1, n) if a[j] > a[i])
        if l != L[i] or r != R[i]:
            return None
    return a


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
    if len(in_lines) < 3:
        print("WA: 输入不足")
        return
    L = list(map(int, in_lines[1].split()))
    R = list(map(int, in_lines[2].split()))
    if len(L) != n or len(R) != n:
        print("WA: L/R 长度不符")
        return

    first = out.splitlines()[0].strip() if out.splitlines() else ""
    if first.upper() == "NO":
        sol = try_build(n, L, R)
        if sol is not None:
            print("WA: 实际有解，不应 NO")
        else:
            print("AC")
        return
    if first.upper() != "YES":
        print("WA: 首行应为 YES/NO")
        return
    # 第二行 n 个整数
    if len(out.splitlines()) < 2:
        print("WA: 缺 a 行")
        return
    a = list(map(int, out.splitlines()[1].split()))
    if len(a) != n:
        print(f"WA: a 数量 {len(a)} != n")
        return
    if any(x < 1 or x > n for x in a):
        print("WA: a 越界")
        return
    for i in range(n):
        l = sum(1 for j in range(i) if a[j] > a[i])
        r = sum(1 for j in range(i + 1, n) if a[j] > a[i])
        if l != L[i] or r != R[i]:
            print(f"WA: 孩子{i+1} 应 l={L[i]} r={R[i]}，实算 l={l} r={r}")
            return
    print("AC")


if __name__ == "__main__":
    main()
