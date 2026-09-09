"""SPJ checker for Codeforces 437B "The Child and Set" (集合构造/多解).

题意：找互异整数集合 S ⊆ {1..limit}，使得 Σ_{x∈S} lowbit(x) == sum
（lowbit(x) = x 的二进制最低位 1 对应的幂）。输出集合（任意顺序）或 -1。
sum, limit ≤ 1e5。

checker 判定：
  1. 输出 -1 → 必须确实不可达（用 bitset DP 独立验证）。
  2. 输出集合 → 元素互异、∈[1..limit]，且 Σ lowbit == sum。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def lowbit(x: int) -> int:
    return x & (-x)


def reachable(sumv: int, limit: int) -> bool:
    """1..limit 的 lowbit 能否凑出 sumv（bitset DP，python int 位集）。"""
    reach = 1  # bit 0
    for i in range(1, limit + 1):
        v = i & (-i)
        if v <= sumv:
            reach |= reach << v
            # 裁剪高位避免无限增长
            reach &= (1 << (sumv + 1)) - 1
        if (reach >> sumv) & 1:
            return True
    return ((reach >> sumv) & 1) == 1


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    try:
        sumv, limit = map(int, inp.splitlines()[0].split())
    except (ValueError, IndexError):
        print("WA: sum/limit 解析失败")
        return

    out = out.strip()
    if out == "-1":
        if reachable(sumv, limit):
            print("WA: 实际有解，不应输出 -1")
        else:
            print("AC")
        return
    lines = out.splitlines()
    try:
        n = int(lines[0].strip())
    except (ValueError, IndexError):
        print("WA: 首行 n 解析失败")
        return
    vals = []
    if len(lines) > 1:
        vals = lines[1].split()
    else:
        vals = []
    if len(vals) != n:
        print(f"WA: 声明 {n} 个元素，实际 {len(vals)}")
        return
    try:
        arr = [int(x) for x in vals]
    except ValueError:
        print("WA: 含非整数")
        return
    if len(set(arr)) != n:
        print("WA: 元素重复")
        return
    if any(x < 1 or x > limit for x in arr):
        print("WA: 元素越界 [1,limit]")
        return
    total = sum(x & (-x) for x in arr)
    if total != sumv:
        print(f"WA: lowbit 总和 {total} != {sumv}")
        return
    print("AC")


if __name__ == "__main__":
    main()
