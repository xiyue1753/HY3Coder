"""SPJ checker for AtCoder ABC299_E "Nearest Black Vertex" (Yes/No + 构造).

判定谓词：无向连通图，给定 K 组 (p_i, d_i)，问是否存在黑白染色（至少一个黑）
使每个 p_i 到最近黑点的距离恰为 d_i。若有解须输出 Yes + 0/1 串；无解输出 No。

checker 策略：
  1) 独立做**可行性判定**（与 AI 输出无关）：
     黑点候选域 C = {v : 对每个 i, dist(p_i, v) >= d_i}（黑点不得使任一 p_i 近于 d_i）。
     有解 ⟺ C 非空 且 每个 i 都有 v in C 使 dist(p_i, v) == d_i。
  2) 对 AI 输出分派：
     - "No"        → 仅当可行性判定为无解才接受。
     - "Yes\nS"    → 校验 S：长度 N、0/1、至少一个 1；再以黑点为源做多源 BFS，
                     逐个核对 dist(p_i, 最近黑) == d_i。任一不符拒绝。
     - 其它格式     → 拒绝。
stdin 协议见 rex/executor/judge.py。
"""
import sys
from collections import deque

SEP = "@@REX_USER_OUTPUT@@"


def bfs_adj(adj, srcs):
    """多源 BFS，返回 {v: 到最近 src 的距离}（含源本身为 0）。"""
    dist = {s: 0 for s in srcs}
    q = deque(srcs)
    while q:
        u = q.popleft()
        for w in adj[u]:
            if w not in dist:
                dist[w] = dist[u] + 1
                q.append(w)
    return dist


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    lines = inp.splitlines()
    if not lines:
        print("WA: 输入为空")
        return
    try:
        n, m = map(int, lines[0].split())
    except ValueError:
        print("WA: N/M 解析失败")
        return
    adj = [[] for _ in range(n + 1)]
    if len(lines) < 1 + m + 1:
        print("WA: 输入行不足")
        return
    for j in range(m):
        u, v = map(int, lines[1 + j].split())
        adj[u].append(v)
        adj[v].append(u)
    k = int(lines[1 + m].strip())
    cons = []
    if len(lines) < 1 + m + 1 + k:
        print("WA: 约束行不足")
        return
    for j in range(k):
        p, d = map(int, lines[1 + m + 1 + j].split())
        cons.append((p, d))

    # 预计算每个 p_i 到全图距离（N 小场景够用；N 大时可加缓存复用）
    dists = []  # dists[i][v]
    for p, _d in cons:
        dists.append(bfs_adj(adj, [p]))

    # 可行性判定
    def feasible() -> bool:
        cand = [True] * (n + 1)          # C 成员标记
        # 构造 C = {v : ∀i dist_i[v] >= d_i}
        for i, (p, d) in enumerate(cons):
            di = dists[i]
            for v in range(1, n + 1):
                if di.get(v, 10 ** 9) < d and cand[v]:
                    cand[v] = False
        C = [v for v in range(1, n + 1) if cand[v]]
        if not C:
            return False
        for i, (p, d) in enumerate(cons):
            di = dists[i]
            if not any(cand[v] and di.get(v, 10 ** 9) == d for v in range(1, n + 1)):
                return False
        return True

    ok_exists = feasible()

    # 输出 No
    if out.strip().lower().startswith("no"):
        print("AC" if not ok_exists else "WA: 实际存在解，不应输出 No")
        return

    # 输出 Yes + S
    oline = out.splitlines()
    if len(oline) < 2 or not oline[0].strip().lower().startswith("yes"):
        print("WA: 输出须为 No 或 Yes+染色串")
        return
    S = oline[1].strip()
    if len(S) != n or any(ch not in "01" for ch in S):
        print("WA: 染色串长度/字符非法")
        return
    blacks = [v for v, ch in enumerate(S, start=1) if ch == "1"]
    if not blacks:
        print("WA: 至少需要一个黑点")
        return
    # 黑点距离验证
    dblack = bfs_adj(adj, blacks)
    for p, d in cons:
        if dblack.get(p, 10 ** 9) != d:
            print(f"WA: p{p} 最近黑点距离 {dblack.get(p, 'inf')} != {d}")
            return
    print("AC")


if __name__ == "__main__":
    main()
