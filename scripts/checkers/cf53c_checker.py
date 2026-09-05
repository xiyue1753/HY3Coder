"""SPJ checker for Codeforces 53C "Little Frog" (排列构造/多解).

题意：输出 1..n 的一个排列 p[1..n]，使得所有相邻差的绝对值 |p[i]-p[i+1]|
(i=1..n-1) 两两互不相同。

checker 判定：
  1. 恰好 n 个整数，是 {1,...,n} 的一个排列（不重不漏）。
  2. n-1 个相邻差绝对值互不相同。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    try:
        n = int(inp.splitlines()[0].strip())
    except (ValueError, IndexError):
        print("WA: n 解析失败")
        return

    parts = out.split()
    if len(parts) != n:
        print(f"WA: 需输出 {n} 个数，实际 {len(parts)}")
        return
    try:
        arr = [int(x) for x in parts]
    except ValueError:
        print("WA: 含非整数")
        return
    if min(arr) < 1 or max(arr) > n:
        print("WA: 数值越界")
        return
    if len(set(arr)) != n:
        print("WA: 不是排列（有重复/缺失）")
        return
    diffs = [abs(arr[i + 1] - arr[i]) for i in range(n - 1)]
    if any(d < 1 or d > n - 1 for d in diffs):
        print("WA: 存在越界差值")
        return
    if len(set(diffs)) != n - 1:
        print("WA: 相邻差绝对值有重复")
        return
    print("AC")


if __name__ == "__main__":
    main()
