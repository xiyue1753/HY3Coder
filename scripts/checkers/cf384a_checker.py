"""SPJ checker for Codeforces 384A "Coder" (棋盘构造/多解).

题意：n×n 棋盘放 Coder（rook 一步），任意两 C 不能同行相邻或同列相邻
（水平/垂直攻击）。求最大可放数并输出任一布局。
最大值 = ceil(n^2/2)（黑白染色）。

checker 判定：
  1. 首行整数 == ceil(n^2/2)。
  2. 后 n 行每行长度 n、仅含 '.' 与 'C'。
  3. 任意水平/垂直相邻的两格不能同时为 C。
  4. C 的总数 == ceil(n^2/2)。
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
    mx = (n * n + 1) // 2

    lines = out.splitlines()
    if not lines:
        print("WA: 输出为空")
        return
    try:
        first = int(lines[0].strip())
    except ValueError:
        print("WA: 首行非整数")
        return
    if first != mx:
        print(f"WA: 最大值应为 {mx}，实际 {first}")
        return
    if len(lines) < 1 + n:
        print("WA: 棋盘行数不足")
        return

    grid = [lines[1 + i].strip() for i in range(n)]
    cnt = 0
    for i, row in enumerate(grid):
        if len(row) != n:
            print(f"WA: 第{i+1}行长度 {len(row)} != n")
            return
        for ch in row:
            if ch not in "C.":
                print(f"WA: 非法字符 {ch!r}")
                return
            if ch == "C":
                cnt += 1
        if i > 0:
            # 垂直相邻
            for j in range(n):
                if row[j] == "C" and grid[i - 1][j] == "C":
                    print(f"WA: ({i},{j}) 与上格同列相邻")
                    return
        # 水平相邻
        for j in range(1, n):
            if row[j] == "C" and row[j - 1] == "C":
                print(f"WA: ({i},{j}) 与左格相邻")
                return
    if cnt != mx:
        print(f"WA: C 数 {cnt} != {mx}")
        return
    print("AC")


if __name__ == "__main__":
    main()
