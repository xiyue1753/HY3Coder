"""SPJ checker for Codeforces 1991C "Absolute Zero" (操作序列构造/多解).

题意：数组 a[1..n]。每步选 x in [0,1e9]，把每个 ai 替换为 |ai-x|。
构造 ≤40 步使全部为 0；若不可能输出 -1。

不可达判据：若数组同时含奇数和偶数 → 不可达；否则可达（用二分位收敛）。

checker（每个 test case）：
  1. 解析输入（t 个 case，每组 n + a 行）。
  2. 输出 -1 → 仅当奇偶混合。
  3. 否则 k in [0,40]；后接 k 个 x（0<=x<=1e9）；模拟 k 步后全为 0。
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

    in_lines = inp.splitlines()
    if not in_lines:
        print("WA: 输入为空")
        return
    try:
        t = int(in_lines[0].strip())
    except ValueError:
        print("WA: t 解析失败")
        return
    # 读取每个 case 的数组
    pos = 1
    arrays = []
    for _ in range(t):
        if pos >= len(in_lines):
            print("WA: 输入不足")
            return
        n = int(in_lines[pos].strip())
        pos += 1
        if pos >= len(in_lines):
            print("WA: 输入不足")
            return
        arr = list(map(int, in_lines[pos].split()))
        pos += 1
        if len(arr) != n:
            print("WA: 数组长度不符")
            return
        arrays.append(arr)

    o_lines = out.splitlines()
    opos = 0
    for ci, arr in enumerate(arrays):
        while opos < len(o_lines) and not o_lines[opos].strip():
            opos += 1
        if opos >= len(o_lines):
            print(f"WA: case{ci+1} 缺输出")
            return
        line1 = o_lines[opos].strip()
        opos += 1
        if line1 == "-1":
            has_odd = any(x % 2 == 1 for x in arr)
            has_even = any(x % 2 == 0 for x in arr)
            if has_odd and has_even:
                # 奇偶混合 → 不可达，-1 正确
                continue
            else:
                print(f"WA: case{ci+1} 实际可达，-1 错误")
                return
        try:
            k = int(line1)
        except ValueError:
            print(f"WA: case{ci+1} 首行非整数")
            return
        if not (0 <= k <= 40):
            print(f"WA: case{ci+1} k={k} 超范围 [0,40]")
            return
        xs = []
        if k > 0:
            while opos < len(o_lines) and not o_lines[opos].strip():
                opos += 1
            if opos >= len(o_lines):
                print(f"WA: case{ci+1} 缺 x 行")
                return
            xs = list(map(int, o_lines[opos].split()))
            opos += 1
        if len(xs) != k:
            print(f"WA: case{ci+1} x 数量 {len(xs)} != k={k}")
            return
        if any(x < 0 or x > 10 ** 9 for x in xs):
            print(f"WA: case{ci+1} x 越界")
            return
        # 模拟
        cur = arr[:]
        for x in xs:
            cur = [abs(v - x) for v in cur]
        if any(v != 0 for v in cur):
            print(f"WA: case{ci+1} 操作后未全 0: {cur[:5]}")
            return
    print("AC")


if __name__ == "__main__":
    main()
