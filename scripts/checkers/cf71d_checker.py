"""SPJ checker for Codeforces 71D "Solitaire" (纸牌构造/多解).

题意：n*m 张牌摆成矩形（n,m<=17, n*m<=52）。若含 joker(J1/J2)，用 54 张
中其余未摆出的标准牌(52 张中不在棋盘上的)替换，使棋盘无 joker、牌不重复。
Solitaire solved 当且仅当替换后存在两个**不重叠的 3x3 方块**，每块内所有
9 张牌要么同花色、要么点数两两不同。输出任一方案或 "No solution."。

checker 职责（"逆过程验证"——丢弃标准答案，只校验选手输出相对题目谓词）：
  A) 选手输出具体方案 → 解析替换行与两个方块坐标，重建棋盘验证：
       1. 替换行与输入实际 joker 数/名称一致；替换用牌 ∈ 52 标准牌、
          不在原棋盘、J1/J2 替换不同牌。
       2. 两个方块坐标在棋盘内、互不重叠（行列差至少一个方向 >=3）。
       3. 每个方块内 9 张满足"同花 或 点数互异"。
  B) 选手输出 "No solution." → 用与题意一致的完整搜索独立判定确实无解
     （否则 WA）。
stdin 协议见 rex/executor/judge.py。
"""
import re
import sys

SEP = "@@REX_USER_OUTPUT@@"

SUITS = "CDHS"
RANKS = list("23456789") + ["T", "J", "Q", "K", "A"]
ALL_CARDS = sorted(RANKS, key=lambda x: RANKS.index(x) if x in RANKS else 99)
# 直接用 52 张标准牌列表
DECK = []
for r in RANKS:
    for s in SUITS:
        DECK.append(r + s)


def parse_board(inp: str):
    lines = inp.splitlines()
    n, m = map(int, lines[0].split())
    grid = []
    for i in range(n):
        grid.append(lines[1 + i].split())
    used = set()
    jokers = []  # (name, r, c)
    for i in range(n):
        for j in range(m):
            v = grid[i][j]
            if v in ("J1", "J2"):
                jokers.append((v, i, j))
            else:
                used.add(v)
    return n, m, grid, used, jokers


def square_ok(grid, r, c):
    """3x3 方块左上角 (r,c)(0-based)：全同花 或 点数互异。"""
    suit0 = grid[r][c][1]
    suits_ok = True
    ranks = set()
    for i in range(r, r + 3):
        for j in range(c, c + 3):
            if grid[i][j][1] != suit0:
                suits_ok = False
            ranks.add(grid[i][j][0])
    return suits_ok or len(ranks) == 9


def overlaps(a, b):
    r1, c1 = a
    r2, c2 = b
    return abs(r1 - r2) < 3 and abs(c1 - c2) < 3


def find_solution(grid, n, m):
    """在给定棋盘（无 joker）上找两个不重叠合法方块。返回 ((r1,c1),(r2,c2)) 或 None。"""
    toplefts = [(r, c) for r in range(n - 2) for c in range(m - 2)]
    ok_squares = [(r, c) for r, c in toplefts if square_ok(grid, r, c)]
    for idx, a in enumerate(ok_squares):
        for b in ok_squares[idx + 1:]:
            if not overlaps(a, b):
                return (a, b)
    return None


def no_joker_solution_exists(n, m, grid):
    return find_solution(grid, n, m) is not None


def exists_with_jokers(n, m, grid, used, jokers):
    """枚举 joker 替换（52 张中未用的牌），看替换后是否存在解。返回 bool。"""
    free = [c for c in DECK if c not in used]
    k = len(jokers)
    # 每步尝试：为 jokers 依次赋 free 中不同牌
    import itertools
    for combo in itertools.permutations(free, k):
        g2 = [row[:] for row in grid]
        for (name, r, c), card in zip(jokers, combo):
            g2[r][c] = card
        if find_solution(g2, n, m) is not None:
            return True
    return False


def main() -> None:
    data = sys.stdin.read()
    idx = data.find(SEP)
    if idx == -1:
        print("WA: 缺分隔符")
        return
    inp = data[:idx].strip()
    out = data[idx + len(SEP):].strip()

    n, m, grid, used, jokers = parse_board(inp)
    out_lines = out.splitlines()

    if out_lines and out_lines[0].strip() == "No solution.":
        if len(out_lines) > 1:
            print("WA: No solution. 后有多余内容")
            return
        # 独立判定确实无解
        if not jokers:
            solvable = no_joker_solution_exists(n, m, grid)
        else:
            solvable = exists_with_jokers(n, m, grid, used, jokers)
        print("AC" if not solvable else "WA: 实际有解，不应 No solution.")
        return

    # 方案输出：4 行
    if len(out_lines) < 4:
        print("WA: 方案输出不足 4 行")
        return
    if out_lines[0].strip() != "Solution exists.":
        print("WA: 首行应 Solution exists.")
        return
    repl = out_lines[1].strip()
    m1 = re.match(r"Put the first square to \((\d+), (\d+)\)\.$", out_lines[2].strip())
    m2 = re.match(r"Put the second square to \((\d+), (\d+)\)\.$", out_lines[3].strip())
    if not m1 or not m2:
        print("WA: 方块坐标行格式非法")
        return
    r1, c1 = int(m1.group(1)) - 1, int(m1.group(2)) - 1
    r2, c2 = int(m2.group(1)) - 1, int(m2.group(2)) - 1
    for r, c in ((r1, c1), (r2, c2)):
        if not (0 <= r <= n - 3 and 0 <= c <= m - 3):
            print(f"WA: 方块左上角 ({r+1},{c+1}) 越界")
            return
    if overlaps((r1, c1), (r2, c2)):
        print("WA: 两个方块重叠")
        return

    # 替换行解析
    joker_names = [j[0] for j in jokers]
    repl_cards: list[str] = []
    if not joker_names:
        if repl != "There are no jokers.":
            print("WA: 输入无 joker，替换行应为 There are no jokers.")
            return
    else:
        if len(joker_names) == 1:
            jn = joker_names[0]
            mrep = re.match(rf"Replace {jn} with ([A-Z0-9]+)\.$", repl)
            if not mrep:
                print(f"WA: 替换行格式非法（期望 Replace {jn} with ...）")
                return
            repl_cards = [mrep.group(1)]
        else:
            mrep = re.match(r"Replace J1 with ([A-Z0-9]+) and J2 with ([A-Z0-9]+)\.$", repl)
            if not mrep:
                print("WA: 替换行格式非法（J1/J2）")
                return
            repl_cards = [mrep.group(1), mrep.group(2)]
        # 校验替换牌
        if any(c not in DECK for c in repl_cards):
            print("WA: 替换牌不在标准 52 张中")
            return
        if len(set(repl_cards)) != len(repl_cards):
            print("WA: 两张替换牌相同")
            return
        if any(c in used for c in repl_cards):
            print("WA: 替换牌已在棋盘中出现")
            return

    # 重建棋盘并验证两个方块
    g2 = [row[:] for row in grid]
    for (name, r, c), card in zip(jokers, repl_cards):
        g2[r][c] = card
    if not square_ok(g2, r1, c1):
        print("WA: 第一个方块不满足条件")
        return
    if not square_ok(g2, r2, c2):
        print("WA: 第二个方块不满足条件")
        return
    print("AC")


if __name__ == "__main__":
    main()
