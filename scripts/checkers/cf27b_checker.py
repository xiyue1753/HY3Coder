"""SPJ checker for Codeforces 27B "Tournament" (补全记录/多解).

题意：n 名选手两两比赛一次（共 C(n,2) 场），无平局。已知除一场外的全部
记录（每行 "x y" 表示 x 胜 y）。求缺失的那场。若多个可行输出任一。

缺失场 = 唯一一对没有交手记录的选手 (a,b)。补全胜负二者皆可（题目只问
结果，any solution），但必须与给定记录不自相矛盾——由于 (a,b) 没在给定
记录中，补谁赢都与现有记录兼容（总可以安排两人速度为补全胜负所需）。

checker：输出须为"彼此无记录的选手对"（x!=y，均在 [1,n]），且这样的对
应恰有一对（否则数据本身非法 → WA 属于输入问题，正常不会出现）。
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
    try:
        n = int(lines[0].strip())
    except (ValueError, IndexError):
        print("WA: n 解析失败")
        return
    total = n * (n - 1) // 2 - 1
    played = [[False] * (n + 1) for _ in range(n + 1)]
    if len(lines) < 1 + total:
        print("WA: 记录行不足")
        return
    for i in range(total):
        a, b = map(int, lines[1 + i].split())
        if not (1 <= a <= n and 1 <= b <= n and a != b):
            print("WA: 记录行非法")
            return
        played[a][b] = played[b][a] = True
    missing = []
    for a in range(1, n + 1):
        for b in range(a + 1, n + 1):
            if not played[a][b]:
                missing.append((a, b))
    if len(missing) != 1:
        print(f"WA: 缺失对数量 {len(missing)} != 1（输入数据问题？）")
        return
    u, v = missing[0]

    parts = out.split()
    if len(parts) != 2:
        print("WA: 需输出两个整数")
        return
    try:
        x, y = map(int, parts)
    except ValueError:
        print("WA: 输出解析失败")
        return
    if not (1 <= x <= n and 1 <= y <= n and x != y):
        print("WA: 输出越界/自环")
        return
    if not ({x, y} == {u, v}):
        print(f"WA: 缺失对应为 ({u},{v})，输出 ({x},{y})")
        return
    print("AC")


if __name__ == "__main__":
    main()
