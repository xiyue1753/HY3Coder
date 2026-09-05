# -*- coding: utf-8 -*-
"""数据规模档提取：为自建题集（ABC/CF）标注规模上限与规模档。

背景（dim-B）：辅助维度"数据规模约束"用于能力画像。规模不能脱离复杂度谈
难度，因此这里只标注**规模**，供报告做"difficulty × scale"二维耦合表与
per-scale 退化分析；复杂度档耦合展示放报告层（见 dim 章节）。

来源格式：
- ABC（AtCoder 官方题面，干净 LaTeX）：
    $1 \\leq N \\leq 2\\times 10^5$ / $N \\leq 10^9$ / $1≤N≤10^5$
- CF（题解 HTML 转文本，幂上标坍缩）：
    n ≤ 105（=10^5）、m ≤ 2·10^5 可能写作 2·10^5 或 200000、≤ 109
    坍缩规则：三位数 "10k"(k=3..9) → 10^k（如 105→10^5）；其余按字面。

用法：
    python scripts/dim_scale.py            # 写回 metadata.scale_max / scale_tier
    python scripts/dim_scale.py --dry-run  # 只报告覆盖率
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 规模档（用于画像分桶，语义 = 主输入维度量级）
#   S1 ≤1e3     朴素可过（O(n^2) 常见）
#   S2 ≤1e4-1e5 需 O(n log n)/O(n)
#   S3 ≤1e6-1e7 需 O(n)/O(log n)
#   S4 >1e7     需 O(log n)/O(1)/数学 或 极小操作
SCALE_TIER = [("S1", 10 ** 3), ("S2", 10 ** 5), ("S3", 10 ** 7), ("S4", 10 ** 18)]


def scale_tier(value: int) -> str:
    for name, cap in SCALE_TIER:
        if value <= cap:
            return name
    return "S4"


# ---------------------------------------------------------------------------
# bound 归一化
# ---------------------------------------------------------------------------
def _parse_bound(s: str) -> int | None:
    """解析 bound 原文 → 数值。s 已去空格。支持：
       '2×10^5' / '2\\times 10^5' / '10^5' / '10^{5}' / '105'(坍缩) / '200000' / '1e9'
    """
    s = s.replace("\\times", "×").replace("\\cdot", "×").strip()
    # 科学计数 1e9
    m = re.match(r"^(\d+)[eE](\d+)$", s)
    if m:
        return int(m.group(1)) * 10 ** int(m.group(2))
    # a × 10^b
    m = re.match(r"^(\d+)\s*[×x]\s*10\s*\^?\s*\{?\s*(\d+)\}?$", s)
    if m:
        return int(m.group(1)) * 10 ** int(m.group(2))
    # 10^b / 10^{b}（仅当显式含 ^ 或 { 时按指数；否则 '1000' 会被误拆成 10^00）
    if ("^" in s or "{" in s) and re.match(r"^10\s*\^?\s*\{?\s*(\d+)\}?$", s):
        return 10 ** int(re.match(r"^10\s*\^?\s*\{?\s*(\d+)\}?$", s).group(1))
    # 纯数字
    if re.fullmatch(r"\d+", s):
        v = int(s)
        # CF 坍缩：105→10^5 等（百位1十位0，长度3，且 >100）
        if 100 < v <= 109 and s[0] == "1" and s[1] == "0":
            return 10 ** int(s[2])
        return v
    return None


# ---------------------------------------------------------------------------
# 主提取：找 “var ≤ bound” / “1 ≤ var ≤ bound” 所有形态
# ---------------------------------------------------------------------------
_VAR = r"(?:[a-zA-Z]|[A-Za-z]_\d|\\|N\||S\||\\mathrm\{[A-Za-z]+\}|\\lvert S\\rvert)"
# 备选顺序重要：a×10^b > 10^b > 1e9 > plain（避免 plain 抢前缀拆坏指数形式）
_BOUND = r"(" \
    r"(?:\d+\s*(?:\\times|×|x|\\cdot)\s*)?10\s*\^?\s*\{?\s*\d+\}?" \
    r"|\d+(?:\.\d+)?[eE]\d+" \
    r"|\d{1,9})"

# 比较符：兼容 LaTeX 单/双反斜杠（\\leq / \leq / \le）与 Unicode ≤
_LE = r"(?:\\{1,2}(?:leq|le)|≤|<=|＜)"
CF_RE = re.compile(
    r"(?P<var>" + _VAR + r")\s*" + _LE + r"\s*(?P<b>" + _BOUND + r")"
)
ABC_RE = re.compile(
    r"\$\s*(?:(?P<lo>\d+(?:\s*(?:\\times|×|x)\s*10\s*\^?\s*\{?\s*\d+\}?)?)\s*" + _LE + r"\s*)?"
    r"(?P<var>" + _VAR + r")\s*" + _LE + r"\s*(?P<b>" + _BOUND + r")\s*\$"
)


def extract_max_bound(prompt: str, cpp_collapse: bool) -> int | None:
    """从题面提取最大规模上限（作为主要输入维度压力）。"""
    # 归一空白与 thin space
    txt = prompt.replace("\u2009", " ").replace("\u00a0", " ")
    txt = re.sub(r"\s+", " ", txt)
    bounds: list[int] = []
    # CF 风格：不限 $...$
    for m in CF_RE.finditer(txt):
        v = _parse_bound(m.group("b").replace(" ", ""))
        if v:
            bounds.append(v)
    # ABC 风格：限 $...$，只取完整 “1 ≤ X ≤ Y” 或 “X ≤ Y” 里最大的那个 Y
    for m in ABC_RE.finditer(txt):
        v = _parse_bound(m.group("b").replace(" ", ""))
        if v:
            bounds.append(v)
    # 竞赛主输入规模几乎总 >= 100（≤10 的一般是 t 测试数/固定小变量/单组输入数）；
    # 过滤掉 <100 的次级小约束后再取最大，避免把 "t≤10000" 或 "k≤40" 当主规模。
    big = [b for b in bounds if b >= 100]
    if big:
        return max(big)
    # 无 >=100 约束：保守返回 None（规模小到无需 scale 分析），避免用错档
    return None


# ---------------------------------------------------------------------------
def process(path: Path, name: str, cpp_collapse: bool, dry: bool) -> None:
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    cov = 0
    low = []
    scales: dict[str, int] = {}   # source_id -> scale_max
    for r in rows:
        mx = extract_max_bound(r.get("prompt", ""), cpp_collapse)
        if mx:
            cov += 1
            scales[r["source_id"]] = mx
            if not dry:
                r.setdefault("metadata", {})["scale_max"] = mx
                r["metadata"]["scale_tier"] = scale_tier(mx)
        else:
            low.append(r["source_id"])
    print(f"== {name} {len(rows)} 题，提取到规模 {cov}/{len(rows)} "
          f"({cov / len(rows) * 100:.0f}%)")
    if low:
        print(f"   未提取 {len(low)}: {low[:12]}")
    from collections import Counter
    tiers = Counter(scale_tier(v) for v in scales.values())
    print(f"   档分布: {dict(tiers)}")
    if not dry:
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"   已写回 {path.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    process(ROOT / "data/questions/abc_selfbuilt.jsonl", "ABC", False, args.dry_run)
    process(ROOT / "data/questions/cf_selfbuilt.jsonl", "CF", True, args.dry_run)


if __name__ == "__main__":
    main()
