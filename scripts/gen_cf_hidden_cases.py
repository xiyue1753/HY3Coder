"""为 Codeforces 自建题补充隐藏边界测试用例（对齐 ABC gen_hidden_cases.py）。

设计原则：
1. 每道题按约束补充 2~4 个**合法边界输入**（最小规模/极端值/关键分支）。
2. 期望输出**由已验证的参考解自动生成**（参考解已通过官方样例，
   用其生成隐藏期望避免手写算错——见流程规则）。
3. 追加为 hidden=true 用例，写入 cf_selfbuilt.jsonl。

用法：
    python scripts/gen_cf_hidden_cases.py [--ids C2003 C2004 ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex.executor.sandbox import run_code  # noqa: E402
from rex.models import QuestionItem  # noqa: E402

OUT = ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"

# source_id -> 合法边界输入列表（\n 换行；期望输出由参考解生成，不手写）
BOUNDARY_INPUTS: dict[str, list[str]] = {
    # 486A Calculating Function: 奇偶求和公式，n 可达 1e15
    "cf486a": ["1", "2", "999999999999999999", "1000000000000000000"],
    # 910A The Way to Home: 跳跃最短路（0/1 串，首尾为 1）
    "cf910a": [
        "2 1\n11",
        "5 4\n10001",
        "5 1\n10001",
        "10 9\n1000000001",
        "8 1\n11111111",
    ],
    # 1660A Vasya and Coins: 最小不可支付金额（a 个 1 分、b 个 2 分）
    "cf1660a": [
        "1\n1 1",
        "1\n0 1",
        "1\n1 0",
        "1\n1000000000 1000000000",
    ],
    # 1795A Two Towers: 两塔顶移动能否无相邻同色
    "cf1795a": [
        "1\n1 1\nR\nB",
        "1\n2 2\nBR\nRB",
        "1\n3 1\nBBB\nR",
        "1\n1 3\nR\nBRB",
    ],
    # 757A Gotta Catch Em' All!: 数 "Bulbasaur" 字母出现次数下限
    "cf757a": ["Bulbasaur", "F", "Bbulbbasaur", "aaaaaaaa"],
    # 1730A Planets: 相同轨道行星可整体移除（c）或逐个（1）
    "cf1730a": [
        "1\n1 1\n1",
        "1\n3 10\n1 1 1",
        "1\n3 1\n1 1 1",
        "2\n5 1\n1 1 2 2 3\n3 3\n1 2 3",
    ],
    # 110A Nearly Lucky Number: 4/7 数字个数是否为 4 或 7
    "cf110a": ["44", "4444", "7777777", "0", "1234567890"],
    # 96A Football: 是否含 7 个连续相同
    "cf96a": ["0000000", "00000001", "01010101", "11111110000", "1000000001"],
    # 144B Meeting: 矩形周界上有多少点不被任一暖气覆盖
    "cf144b": [
        "2 5 4 2\n3\n3 1 2\n5 3 1\n1 3 2",
        "2 2 3 3\n0",
        "1 1 1 1\n1\n1 1 0",
    ],
    # 343B Alternating Current: 相邻同号成对消除后是否为空
    "cf343b": ["++", "--", "+-+-", "-++-", "++++"],
    # 455A Boredom: 选数最大分（相邻值被删除）
    "cf455a": [
        "1\n5",
        "4\n1 1 1 1",
        "3\n3 2 1",
        "5\n1 2 1 2 1",
    ],
    # 414B Mashmokh and ACM: 整除链计数
    "cf414b": ["1 1", "2 2", "5 3", "2000 2"],
    # 429A Xor-tree: 翻转子树最小次数
    "cf429a": [
        "1\n0\n1",
        "1\n1\n1",
        "2\n2 1\n0 0\n1 0",
    ],
    # 1060E Sergey and Subway: 加距离 2 边后的最短路和
    "cf1060e": [
        "2\n1 2",
        "5\n1 2\n2 3\n3 4\n4 5",
        "5\n1 2\n1 3\n1 4\n1 5",
    ],
    # 358D Dima and Hares: 喂兔顺序 DP
    "cf358d": [
        "1\n5\n3\n1",
        "2\n1 2\n2 1\n0 0",
        "3\n1 1 1\n1 2 1\n1 1 1",
    ],
    # 300C Beautiful Numbers: 好数计数
    "cf300c": ["1 2 1", "1 2 2", "1 9 100", "2 3 1000000"],
    # 676C Vasya and String: 最多改 k 个，最大同色连续段
    "cf676c": [
        "1 0\na",
        "10 1\nababababab",
        "10 2\naaaaaaaaaa",
        "3 2\naba",
        "10 10\nbbbbbbbbbb",
    ],
}


def run_output(code: str, inp: str) -> tuple[str | None, str]:
    """运行参考解，返回 (stdout, error)。"""
    res = run_code(code, stdin=inp, timeout=20, language="cpp")
    if res.error or res.timed_out:
        return None, res.error or "timeout"
    return res.stdout.rstrip(), ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None)
    args = ap.parse_args()
    rows = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    added = 0
    failed: list[str] = []
    for r in rows:
        sid = r["source_id"]
        if args.ids and r["id"] not in args.ids:
            continue
        inputs = BOUNDARY_INPUTS.get(sid)
        if not inputs:
            continue
        q = QuestionItem.model_validate(r)
        existing_hidden = {tc["input"] for tc in r["test_cases"] if tc.get("hidden")}
        new_cases = []
        for inp in inputs:
            if inp in existing_hidden:
                continue
            out, err = run_output(q.reference_solution, inp)
            if out is None:
                failed.append(f"{sid}: 输入 {inp!r} 运行失败: {err[:100]}")
                continue
            new_cases.append({"input": inp, "output": out, "hidden": True})
        if new_cases:
            r["test_cases"].extend(new_cases)
            added += len(new_cases)
            print(f"{r['id']} {sid}: +{len(new_cases)} 隐藏用例")
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"\n共新增 {added} 个隐藏用例")
    if failed:
        print("失败项（输入可能不合格式，已跳过）：")
        for f in failed:
            print(" ", f)


if __name__ == "__main__":
    main()
