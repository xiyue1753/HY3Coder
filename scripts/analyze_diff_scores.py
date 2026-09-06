# -*- coding: utf-8 -*-
"""分析跨平台统一难度打分结果（专家分 vs 官方锚点校验 + 切档）。

用法（在全量 diff_scores.jsonl 产出后）：
  python scripts/analyze_diff_scores.py
输出：
  1. 专家分分布（平台间对齐检查：ABC/CF 分数是否落在同尺度）
  2. 专家分 vs 官方锚点 Spearman 相关（验证 LLM 难度判断可靠）
  3. 统一分位切档（如按全局分位切 3/5 档），给出各档跨平台构成
  4. 专家内一致性（分歧中位数）
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "outputs" / "diff_scores.jsonl"


def load_scores() -> list[dict]:
    return [json.loads(l) for l in SCORES.open(encoding="utf-8") if l.strip()]


def anchor_of(source_id: str) -> tuple[str, float | None]:
    """返回 (平台, 官方锚点)。ABC 用 difficulty_ap，CF 用 rating。"""
    p = "abc" if source_id.startswith("abc") else "cf"
    rows = [json.loads(l) for l in
            (ROOT / "data" / "questions" / ("abc_selfbuilt.jsonl" if p == "abc"
                                            else "cf_selfbuilt.jsonl"))
            .open(encoding="utf-8") if l.strip()]
    for r in rows:
        if r["source_id"] == source_id:
            md = r.get("metadata") or {}
            return p, md.get("difficulty_ap") if p == "abc" else md.get("rating")
    return p, None


def spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    def rank(a):
        order = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        for pos, i in enumerate(order):
            r[i] = pos + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)) *
                    sum((ry[i] - my) ** 2 for i in range(n)))
    return num / den if den else 0.0


def main() -> None:
    scores = load_scores()
    print(f"已加载 {len(scores)} 条打分记录")
    if not scores:
        print("空。先跑 score_difficulty.py")
        return

    finals = [s["final_score"] for s in scores if s.get("final_score") is not None]
    print(f"\n== 1. 分数分布（0-100）==")
    print(f"   总体: min={min(finals)} p25={sorted(finals)[len(finals)//4]} "
          f"中位={sorted(finals)[len(finals)//2]} "
          f"p75={sorted(finals)[3*len(finals)//4]} max={max(finals)}")
    for pl in ("abc", "cf"):
        fs = [s["final_score"] for s in scores if s.get("platform") == pl
              and s.get("final_score") is not None]
        if fs:
            fs.sort()
            print(f"   {pl:4s}: n={len(fs)} min={fs[0]} 中位={fs[len(fs)//2]} max={fs[-1]}")

    # 专家一致性
    spreads = []
    for s in scores:
        es = [v.get("score") for v in s.get("expert_scores", {}).values()
              if v.get("score") is not None]
        if len(es) >= 2:
            spreads.append(max(es) - min(es))
    if spreads:
        spreads.sort()
        print(f"\n== 2. 专家分歧(极差) == 中位={spreads[len(spreads)//2]} "
              f"| 极差>25 占 {sum(1 for x in spreads if x > 25)}/{len(spreads)}")

    # Spearman vs 官方锚点
    print(f"\n== 3. 专家分 vs 官方锚点（验证可靠性）==")
    for pl, key in (("abc", "difficulty_ap"), ("cf", "rating")):
        xs, ys = [], []
        for s in scores:
            if s.get("platform") != pl or s.get("final_score") is None:
                continue
            _, a = anchor_of(s["source_id"])
            if a is not None:
                xs.append(float(s["final_score"]))
                ys.append(float(a))
        if len(xs) >= 5:
            print(f"   {pl:4s}: Spearman(final, {key}) = {spearman(xs, ys):.3f} "
                  f"(n={len(xs)})")
        else:
            print(f"   {pl:4s}: 样本不足 n={len(xs)}")

    # 全局切档（三档 & 五档），看跨平台构成
    def tier_for(v, cuts):
        for i, c in enumerate(cuts):
            if v <= c:
                return f"T{i+1}"
        return f"T{len(cuts)+1}"

    all_f = sorted(finals)
    q33, q67 = all_f[len(all_f) // 3], all_f[2 * len(all_f) // 3]
    print(f"\n== 4. 统一切档（全局三分位 {q33:.0f}/{q67:.0f}）==")
    mat = defaultdict(Counter)
    for s in scores:
        if s.get("final_score") is None:
            continue
        t = tier_for(s["final_score"], [q33, q67])
        mat[t][s["platform"]] += 1
    for t in sorted(mat):
        d = dict(mat[t])
        total = sum(d.values())
        print(f"   {t}: 共{total} (abc={d.get('abc',0)}, cf={d.get('cf',0)})")


if __name__ == "__main__":
    main()
