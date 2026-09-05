"""SPJ checker for Codeforces 1717B "Madoka and Underground Competitions".

题意：n×n 表填 '.'/'X'（n 为 k 倍数），要求任意 k 个连续横向或纵向格至少
一个 X；X 总数最少；且指定格 (r,c) 必须为 X。输出任一最小表。

最小 X 数 = n*n//k（按对角线周期放置达到）。

checker 判定（每个 test case）：
  1. 恰好 n 行，每行长度 n，仅含 '.'/'X'。
  2. (r,c) 为 'X'。
  3. 每行任意连续 k 格含 X；每列任意连续 k 格含 X。
  4. X 总数 == n*n//k。
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
    try:
        t = int(in_lines[0].strip())
    except (ValueError, IndexError):
        print("WA: t 解析失败")
        return
    cases = []
    for i in range(t):
        if len(in_lines) < 1 + t:
            print("WA: 测试用例行不足")
            return
        n, k, r, c = map(int, in_lines[1 + i].split())
        cases.append((n, k, r, c))

    o_lines = out.splitlines()
    pos = 0
    for ci, (n, k, r, c) in enumerate(cases):
        # 跳过空行
        while pos < len(o_lines) and not o_lines[pos].strip():
            pos += 1
        if pos + n > len(o_lines):
            print(f"WA: case{ci+1} 输出行不足")
            return
        grid = [o_lines[pos + i].rstrip("\r") for i in range(n)]
        pos += n
        # 每行长度检查
        for i, row in enumerate(grid):
            if len(row) != n:
                print(f"WA: case{ci+1} 第{i+1}行长度 {len(row)} != {n}")
                return
            if any(ch not in ".X" for ch in row):
                print(f"WA: case{ci+1} 第{i+1}行非法字符")
                return
        # (r,c) 为 X
        if grid[r - 1][c - 1] != "X":
            print(f"WA: case{ci+1} ({r},{c}) 非 X")
            return
        # 行滑动窗口
        for i in range(n):
            for j in range(n - k + 1):
                if "X" not in grid[i][j:j + k]:
                    print(f"WA: case{ci+1} 行{i+1} 窗[{j},{j+k}) 无 X")
                    return
        # 列滑动窗口
        for j in range(n):
            col = "".join(grid[i][j] for i in range(n))
            for i in range(n - k + 1):
                if "X" not in col[i:i + k]:
                    print(f"WA: case{ci+1} 列{j+1} 窗[{i},{i+k}) 无 X")
                    return
        cnt = sum(row.count("X") for row in grid)
        if cnt != n * n // k:
            print(f"WA: case{ci+1} X 数 {cnt} != 最小 {n*n//k}")
            return
    # 尾部不应有多余非空内容
    for extra in o_lines[pos:]:
        if extra.strip():
            print("WA: 输出存在多余内容")
            return
    print("AC")


if __name__ == "__main__":
    main()
