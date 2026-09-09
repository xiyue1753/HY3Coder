"""SPJ checker for AtCoder ABC271_D "Flip and Adjust" (Yes/No + 构造).

判定谓词：N 张卡，每张可显示 a_i（正面 H）或 b_i（背面 T），问能否使显示和
恰为 S。可行则输出 Yes + 长度 N 的 H/T 串；否则 No。方案多解时任一可行即可。

checker 策略：
  1) 独立做**可达性判定**：DP(布尔) 判断是否存在选择序列使和为 S。
  2) AI 输出 "No"    → 仅当不可达才接受。
  3) AI 输出 "Yes\n串" → 校验串长 N、仅含 H/T、且按 H->a_i / T->b_i 求和 == S。
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
        n, s = map(int, lines[0].split())
    except ValueError:
        print("WA: N/S 解析失败")
        return
    ab = []
    if len(lines) < n + 1:
        print("WA: 卡行不足")
        return
    for j in range(n):
        a, b = map(int, lines[1 + j].split())
        ab.append((a, b))

    # 可达性判定 DP
    reachable = {0}
    for a, b in ab:
        nxt = {v + a for v in reachable} | {v + b for v in reachable}
        reachable = nxt
        if not reachable:
            break
    ok_exists = s in reachable

    if not out:
        print("WA: 输出为空")
        return
    if out.strip().lower() == "no":
        print("AC" if not ok_exists else "WA: 实际可达，不应输出 No")
        return

    oline = out.splitlines()
    if len(oline) < 2 or not oline[0].strip().lower().startswith("yes"):
        print("WA: 输出须为 No 或 Yes+方案串")
        return
    S = oline[1].strip()
    if len(S) != n or any(ch not in "HT" for ch in S):
        print("WA: 方案串长度/字符非法")
        return
    total = sum(a if ch == "H" else b for (a, b), ch in zip(ab, S))
    if total != s:
        print(f"WA: 方案和 {total} != {s}")
        return
    print("AC")


if __name__ == "__main__":
    main()
