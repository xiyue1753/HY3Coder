"""SPJ checker for AtCoder ABC315_E "Prerequisites" (构造/多解: 拓扑序任意).

判定谓词：给定 N 本书的依赖（读 i 前须读完 P_i 全部），输出一个"读第 1 本书
所需的最小书集合"的合法读序（集合唯一、不含书 1；顺序只需满足依赖）。
校验：
  1. 输出集合 == 从书 1 出发的依赖闭包（不含 1）——集合唯一，必须精确相等。
  2. 输出是一组不重复的编号（2..N 之间）。
  3. 输出顺序是合法拓扑序：每本书出现前，其所需先修书（属于该集合的）均已出现。
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

    lines = inp.splitlines()
    if not lines:
        print("WA: 输入为空")
        return
    try:
        n = int(lines[0].strip())
    except ValueError:
        print("WA: N 解析失败")
        return
    prereq = [[] for _ in range(n + 1)]  # prereq[i] = 读 i 前需读的书
    if len(lines) - 1 < n:
        print("WA: 依赖行不足")
        return
    for i in range(1, n + 1):
        parts = lines[i].split()
        if not parts:
            continue
        c = int(parts[0])
        prereq[i] = [int(x) for x in parts[1:1 + c]]
        if len(prereq[i]) != c:
            print("WA: 依赖数量与声明不符")
            return

    # 收集从书 1 出发的依赖闭包（必须读的书，不含 1）
    must = set()
    stack = [1]
    while stack:
        u = stack.pop()
        for v in prereq[u]:
            if v not in must:
                must.add(v)
                stack.append(v)

    cand = [int(x) for x in out.split() if x.strip()]
    # 集合精确相等
    if set(cand) != must:
        missing = sorted(must - set(cand))
        extra = sorted(set(cand) - must)
        print(f"WA: 输出集合不等 缺{missing} 多{extra}")
        return
    # 不重复且不含 1
    if len(cand) != len(set(cand)):
        print("WA: 输出含重复书号")
        return
    if 1 in cand:
        print("WA: 输出不应含书 1")
        return
    # 拓扑序校验：每本书出现时其先修（在 must 内的）均已出现
    seen = set()
    for b in cand:
        for p in prereq[b]:
            if p != b and p in must and p not in seen:
                print(f"WA: 书 {p} 应先于 {b} 读")
                return
        seen.add(b)
    print("AC")


if __name__ == "__main__":
    main()
