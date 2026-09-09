"""SPJ checker for Codeforces 20C "Dijkstra?" (最短路输出/多解).

题意：n 点 m 边无向加权图（可能自环/重边），求 1->n 最短路径并输出节点
序列；若无路径输出 -1。最短路不唯一，输出任一条即可。

checker 判定：
  1. 独立 Dijkstra 求 dist[1..n]（n,m <= 1e5）。
  2. 输出 -1 → 仅当 n 不可达。
  3. 输出序列 → 起点 1、终点 n、相邻节点间有边、路径总权 == dist[n]。
stdin 协议见 rex/executor/judge.py。
"""
import heapq
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

    lines = inp.splitlines()
    if not lines:
        print("WA: 输入为空")
        return
    try:
        n, m = map(int, lines[0].split())
    except ValueError:
        print("WA: n/m 解析失败")
        return
    adj = [[] for _ in range(n + 1)]
    if len(lines) < 1 + m:
        print("WA: 边行不足")
        return
    for i in range(m):
        a, b, w = map(int, lines[1 + i].split())
        adj[a].append((b, w))
        adj[b].append((a, w))

    # Dijkstra
    INF = float("inf")
    dist = [INF] * (n + 1)
    dist[1] = 0
    pq = [(0, 1)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    reach = dist[n] != INF

    out = out.strip()
    if out == "-1":
        if reach:
            print(f"WA: 存在路径（最短 {int(dist[n])}），不应输出 -1")
        else:
            print("AC")
        return
    parts = out.split()
    try:
        path = [int(x) for x in parts]
    except ValueError:
        print("WA: 输出含非整数")
        return
    if not path:
        print("WA: 输出为空")
        return
    if path[0] != 1 or path[-1] != n:
        print("WA: 起点/终点不符")
        return
    if len(path) != len(set(path)):
        print("WA: 路径含重复节点")
        return
    if any(not (1 <= x <= n) for x in path):
        print("WA: 节点越界")
        return
    total = 0
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        best = None
        for x, w in adj[u]:
            if x == v:
                best = w if best is None else min(best, w)
        if best is None:
            print(f"WA: 无 {u}-{v} 边")
            return
        total += best
    if not reach:
        print("WA: 实际不可达，不应输出路径")
        return
    if total != dist[n]:
        print(f"WA: 路径总权 {total} != 最短 {int(dist[n])}")
        return
    print("AC")


if __name__ == "__main__":
    main()
