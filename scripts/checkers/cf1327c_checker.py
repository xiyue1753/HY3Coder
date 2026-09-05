"""SPJ checker for Codeforces 1327C "Game with Chips" (同步移动构造/多解).

题意：n×m 板，k 个 chips（初始 sxi,syi，目标 fxi,fyi）。每次操作所有
chips 同时移动一格（L/R/D/U），贴墙向墙移则不动。构造 ≤2nm 步使每个
chip 访问过其目标（无需停在目标）。输出操作序列或 -1（<=2nm 内不可）。

checker：
  1. 输出 -1 → 判定为合法仅当无法在 2nm 内达成（官方结论：任何输入都可
     在 2nm 内达成——先全部移到 (1,1)（n+m-2 步）再蛇形扫全板（nm-1 步）
     <=2nm。因此 -1 永不合法）。恒 WA。
  2. 否则：长度 L<=2nm，仅含 L/R/D/U；同步模拟 k chips（贴墙 clamp），
     每个目标至少被访问一次。
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
        n, m, k = map(int, in_lines[0].split())
    except (ValueError, IndexError):
        print("WA: n/m/k 解析失败")
        return
    if len(in_lines) < 1 + 2 * k:
        print("WA: chips 行不足")
        return
    starts = []
    targets = []
    for i in range(k):
        sx, sy = map(int, in_lines[1 + i].split())
        starts.append((sx, sy))
    for i in range(k):
        fx, fy = map(int, in_lines[1 + k + i].split())
        targets.append((fx, fy))

    o_lines = out.splitlines()
    first = o_lines[0].strip() if o_lines else ""
    if first == "-1":
        print("WA: 恒可达，-1 不合法")
        return
    # 支持两种格式：直接序列 或 "长度\n序列"
    if len(o_lines) >= 2 and o_lines[0].strip().isdigit():
        seq = o_lines[1].strip()
    else:
        seq = first
    seq = "".join(seq.split())
    if len(seq) == 0:
        print("WA: 空操作序列")
        return
    if len(seq) > 2 * n * m:
        print(f"WA: 长度 {len(seq)} > 2nm={2*n*m}")
        return
    if any(ch not in "LRDU" for ch in seq):
        print("WA: 含非法操作字符")
        return

    # 同步模拟
    pos = [list(s) for s in starts]
    visited = [False] * k
    for i in range(k):
        if pos[i][0] == targets[i][0] and pos[i][1] == targets[i][1]:
            visited[i] = True
    for ch in seq:
        for i in range(k):
            x, y = pos[i]
            if ch == "L":
                y = max(1, y - 1)
            elif ch == "R":
                y = min(m, y + 1)
            elif ch == "D":
                x = min(n, x + 1)
            elif ch == "U":
                x = max(1, x - 1)
            pos[i] = [x, y]
            if x == targets[i][0] and y == targets[i][1]:
                visited[i] = True
    missing = [i + 1 for i in range(k) if not visited[i]]
    if missing:
        print(f"WA: chips {missing} 未访问目标")
        return
    print("AC")


if __name__ == "__main__":
    main()
