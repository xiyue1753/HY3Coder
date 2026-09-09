"""SPJ checker for AtCoder ABC392_E "Cables and Servers" (构造/多解).

判定谓词：N 个服务器、M 条双向电缆（i 连接 A_i-B_i，允许 self-loop）。
操作：选一条电缆，把它的一个端从当前所连服务器改连到另一服务器。
求最少操作数使全连通，并输出该最优方案（K+1 行）。任一最优方案均可。

checker 校验：
  1. 输出格式：K 为第一行；后 K 行 "c u v"。
  2. 模拟每条操作：操作前电缆 c 的某一端必须正连 u；改该端为 v (v != u)。
  3. 最终图全连通。
  4. K 必须等于最小操作数 c-1（c=原图连通分量数）。理由：每条被操作的电缆
     必须从某个连通分量"取出"一根来连接另一个分量，故至少 c-1 根电缆被改；
     又因 M>=N-1 且 (这里题意隐含可达成)，恰好 c-1 即可。
stdin 协议见 rex/executor/judge.py。
"""
import sys

SEP = "@@REX_USER_OUTPUT@@"


def parse_int(x):
    return int(x)


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    lines_in = inp.splitlines()
    if not lines_in:
        print("WA: 输入为空")
        return
    try:
        n, m = map(int, lines_in[0].split())
    except ValueError:
        print("WA: N/M 解析失败")
        return
    if len(lines_in) < 1 + m:
        print("WA: 电缆行不足")
        return
    cables = []
    for i in range(m):
        a, b = map(int, lines_in[1 + i].split())
        cables.append((a, b))

    # ---- 并查集 ----
    parent = list(range(n + 2))
    size = [1] * (n + 2)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]

    for a, b in cables:
        union(a, b)
    comps = len({find(i) for i in range(1, n + 1)})
    min_ops = comps - 1

    oline = out.splitlines() if out else []
    if not oline:
        print("WA: 输出为空")
        return
    try:
        k = int(oline[0].strip())
    except ValueError:
        print("WA: 首行 K 解析失败")
        return
    if k != min_ops:
        print(f"WA: K={k}，最小操作数应为 {min_ops}（原图连通块 {comps}）")
        return
    if k == 0:
        print("AC")
        return
    if len(oline) < 1 + k:
        print("WA: 操作行不足")
        return

    # 模拟
    cur_a = [cables[i][0] for i in range(m)]
    cur_b = [cables[i][1] for i in range(m)]
    for j in range(k):
        parts = oline[1 + j].split()
        if len(parts) != 3:
            print(f"WA: 操作{j+1}行需 3 个整数")
            return
        try:
            c, u, v = map(int, parts)
        except ValueError:
            print(f"WA: 操作{j+1}行解析失败")
            return
        if not (1 <= c <= m and 1 <= u <= n and 1 <= v <= n):
            print(f"WA: 操作{j+1}行数值越界")
            return
        if u == v:
            print(f"WA: 操作{j+1}行 u==v")
            return
        if cur_a[c - 1] != u and cur_b[c - 1] != u:
            print(f"WA: 操作{j+1} 电缆{c}当前端 ({cur_a[c-1]},{cur_b[c-1]}) 不含 {u}")
            return
        if cur_a[c - 1] == u:
            cur_a[c - 1] = v
        else:
            cur_b[c - 1] = v

    # 最终连通
    parent2 = list(range(n + 2))
    size2 = [1] * (n + 2)

    def find2(x):
        while parent2[x] != x:
            parent2[x] = parent2[parent2[x]]
            x = parent2[x]
        return x

    def union2(a, b):
        ra, rb = find2(a), find2(b)
        if ra == rb:
            return
        if size2[ra] < size2[rb]:
            ra, rb = rb, ra
        parent2[rb] = ra
        size2[ra] += size2[rb]

    for ca, cb in zip(cur_a, cur_b):
        union2(ca, cb)
    comps2 = len({find2(i) for i in range(1, n + 1)})
    if comps2 != 1:
        print(f"WA: 操作后仍有 {comps2} 个连通块")
        return
    print("AC")


if __name__ == "__main__":
    main()
