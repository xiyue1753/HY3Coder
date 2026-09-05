"""SPJ checker for Codeforces 1305E "Kuroni and the Score Distribution".

题意：构造 1<=a1<a2<...<an<=1e9，使满足 ai+aj=ak (i<j<k) 的三元组数恰为
m；否则输出 -1。n<=5000, m<=1e9。

checker 判定：
  - 输出 -1 → 需 m 超过最大可达三元组数（最密序列 1..n 的三元组数）。
  - 输出序列 → 严格递增、正整数、<=1e9；用 set 加速精确统计三元组数
    是否 == m。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def count_max(n):
    """1..n 序列的三元组 (i<j<k, i+j=k) 数量。"""
    s = 0
    for k in range(3, n + 1):
        s += (k - 1) // 2  # a<b<k, a+b=k -> a 从 1..floor((k-1)/2)
    return s


def count_triples(a, n):
    """对给定严格递增数组精确统计 (i<j<k, ai+aj=ak) 数量。O(n^2) 双指针。"""
    cnt = 0
    for k in range(2, n):
        target = a[k]
        lo, hi = 0, k - 1
        while lo < hi:
            s = a[lo] + a[hi]
            if s == target:
                cnt += 1
                lo += 1
                hi -= 1
            elif s < target:
                lo += 1
            else:
                hi -= 1
    return cnt


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    try:
        n, m = map(int, inp.splitlines()[0].split())
    except (ValueError, IndexError):
        print("WA: n/m 解析失败")
        return

    maxm = count_max(n)
    out = out.strip()
    if out == "-1":
        print("AC" if m > maxm else f"WA: m={m}<=maxm={maxm}，有解不应 -1")
        return

    try:
        a = list(map(int, out.split()))
    except ValueError:
        print("WA: 输出含非整数")
        return
    if len(a) != n:
        print(f"WA: 需 {n} 个整数，实际 {len(a)}")
        return
    if any(x <= 0 or x > 10 ** 9 for x in a):
        print("WA: 数值越界")
        return
    for i in range(1, n):
        if a[i] <= a[i - 1]:
            print("WA: 非严格递增")
            return
    if m > maxm:
        print(f"WA: m={m} 超过最大可达 {maxm}，不可能有解")
        return
    real = count_triples(a, n)
    if real != m:
        print(f"WA: 三元组数 {real} != m={m}")
        return
    print("AC")


if __name__ == "__main__":
    main()
