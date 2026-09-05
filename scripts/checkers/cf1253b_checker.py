"""SPJ checker for Codeforces 1253B "Silly Mistake" (切分/多解).

题意：事件序列 a[1..n]（+i = i 进入，-i = i 离开）。切成若干连续段
（每天），每天须为"合法日"：同一人一天至多进一次；离开前必须在场；
日初/日末办公室空。求任意合法划分（输出每段长度 c_1..c_d，和为 n）；
若不可能输出 -1。

checker：
  1. 输出 -1 → 独立贪心判定整个序列能否划分合法日（贪心：每当在场集合
     变空即结束一天；出现重复进入/非法离开即失败）。-1 仅当贪心失败。
  2. 划分 → 段长度和 = n；逐段验证合法性。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def valid_day(seg: list[int]) -> bool:
    """单段是否合法日：同日无重复进入、无未进先出、日末办公室空。"""
    inside = set()
    seen_in = set()
    for e in seg:
        if e > 0:
            if e in seen_in:
                return False  # 同日二次进入
            seen_in.add(e)
            inside.add(e)
        else:
            p = -e
            if p not in inside:
                return False  # 未进就出
            inside.remove(p)
    return not inside  # 日末必须空


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
        print("WA: 事件行缺失")
        return
    ev = list(map(int, in_lines[1].split()))
    if len(ev) != n:
        print("WA: 事件数不符")
        return

    # ---- 独立贪心可行性：可否分成合法日 ----
    def feasible() -> bool:
        i = 0
        inside = set()
        seen_this_day = set()
        while i < n:
            e = ev[i]
            if e > 0:
                if e in seen_this_day:
                    return False
                seen_this_day.add(e)
                inside.add(e)
                i += 1
            else:
                p = -e
                if p not in inside:
                    return False
                inside.remove(p)
                i += 1
                if not inside:
                    # 关闭一天
                    seen_this_day = set()
        return not inside

    o_lines = out.splitlines()
    first = o_lines[0].strip() if o_lines else ""
    if first == "-1":
        print("AC" if not feasible() else "WA: 存在合法划分，不应 -1")
        return
    # 划分
    try:
        d = int(first)
    except ValueError:
        print("WA: 首行非整数")
        return
    if not (1 <= d <= n):
        print("WA: d 越界")
        return
    cs = []
    if len(o_lines) > 1:
        cs = list(map(int, o_lines[1].split()))
    if len(cs) != d:
        print(f"WA: 需输出 {d} 个长度，实际 {len(cs)}")
        return
    if any(c <= 0 for c in cs):
        print("WA: 天长度须为正")
        return
    if sum(cs) != n:
        print(f"WA: 长度和 {sum(cs)} != n={n}")
        return
    # 逐段验证
    ptr = 0
    for ci, c in enumerate(cs):
        if ptr + c > n:
            print(f"WA: 段{ci+1} 越界")
            return
        seg = ev[ptr:ptr + c]
        if not valid_day(seg):
            print(f"WA: 段{ci+1} 非合法日")
            return
        ptr += c
    print("AC")


if __name__ == "__main__":
    main()
