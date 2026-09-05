# -*- coding: utf-8 -*-
"""知识点标签标准化：为 ABC/CF 自建题生成统一主类标签。

设计目标（一次做对）：
- CF：官方 problemset tags 是多标签（每题 1~8 个），按固定优先级映射为标准
  主类列表（`metadata.alg_classes`，保持官方顺序），保留官方原始 tags 到
  `metadata.official_tags`。**不丢多解法信息**（如 implementation+math 双标）。
- ABC：官方无 tags，现有 metadata.type 是人工中文复合串（"DP/背包"等），
  按关键词拆分为标准主类列表 `metadata.alg_classes`（主类去重保序）。

标准主类（互斥可判的算法范式，供 per_type 能力画像）：
  sim 实现/模拟 · greedy 贪心 · dp 动态规划 · graph 图论 · ds 数据结构 ·
  math 数学/数论 · string 字符串 · sort 排序 · binary 二分/搜索 ·
  brute 暴力/枚举 · construct 构造 · twoptr 双指针 · game 博弈

用法：
    python scripts/normalize_tags.py            # 写回两题集 metadata
    python scripts/normalize_tags.py --dry-run  # 只打印覆盖率报告，不写文件
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 标准主类 → 显示名
# ---------------------------------------------------------------------------
ALG_CN = {
    "sim": "实现/模拟", "greedy": "贪心", "dp": "动态规划",
    "graph": "图论", "ds": "数据结构", "math": "数学",
    "string": "字符串", "sort": "排序", "binary": "二分/搜索",
    "brute": "暴力/枚举", "construct": "构造", "twoptr": "双指针",
    "game": "博弈",
}
ALG_ORDER = list(ALG_CN.keys())

# ---------------------------------------------------------------------------
# CF tag → 标准主类（官方 tag 全集见 data/cache/cf_problemset.json）
# ---------------------------------------------------------------------------
CF_TAG_MAP: dict[str, str] = {
    "implementation": "sim",
    "greedy": "greedy",
    "dp": "dp",
    "graphs": "graph",
    "dfs and similar": "graph",
    "trees": "graph",
    "shortest paths": "graph",
    "dsu": "graph",
    "2-sat": "graph",
    "flows": "graph",
    "graph matchings": "graph",
    "data structures": "ds",
    "string suffix structures": "ds",
    "math": "math",
    "number theory": "math",
    "combinatorics": "math",
    "matrices": "math",
    "probabilities": "math",
    "strings": "string",
    "sortings": "sort",
    "binary search": "binary",
    "ternary search": "binary",
    "divide and conquer": "binary",
    "brute force": "brute",
    "bitmasks": "brute",
    "constructive algorithms": "construct",
    "two pointers": "twoptr",
    "games": "game",
    "interactive": "sim",
    "hashing": "ds",
    "schedules": "sim",
    "geometry": "math",
    "meet-in-the-middle": "binary",
}
# 若官方 tag 未能映射（罕见），落入此集合便于人工核查
CF_UNMAPPED: dict[str, int] = defaultdict(int)


def cf_classes(tags: list[str]) -> list[str]:
    """官方 tags → 标准主类（去重、保官方顺序）。未映射 tag 记录并忽略。"""
    out: list[str] = []
    for t in tags:
        cls = CF_TAG_MAP.get(t)
        if cls is None:
            CF_UNMAPPED[t] += 1
            continue
        if cls not in out:
            out.append(cls)
    return out


# ---------------------------------------------------------------------------
# ABC 中文复合串 → 标准主类（关键词匹配）
# ---------------------------------------------------------------------------
ABC_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"贪心"), "greedy"),
    (re.compile(r"DP|dp|记忆化|递归"), "dp"),
    (re.compile(r"BFS|DFS|图|最短路|树|并查集|拓扑|生成树|MST|传递闭包|判环|倍增|置换"), "graph"),
    (re.compile(r"数据结构|栈|堆|队列|集合|哈希|链表|单调|有序|第K|第k|区间合并"), "ds"),
    (re.compile(r"二分|三分|分治"), "binary"),
    (re.compile(r"双指针|滑窗|滑动窗口"), "twoptr"),
    (re.compile(r"字符串|回文|LCP"), "string"),
    (re.compile(r"排序"), "sort"),
    (re.compile(r"构造"), "construct"),
    (re.compile(r"枚举|暴力|状压|位枚举|组合|字符画"), "brute"),
    (re.compile(r"博弈"), "game"),
    (re.compile(r"模拟"), "sim"),
    # 数学族放最后（覆盖面广，避免抢占具体类）；包含"计数/数论/前缀/差分/几何/位"等
    (re.compile(r"数学|数论|几何|gcd|素数|质数|进制|前缀|差分|概率|期望|位|计数|倍数|整除|回文数|取模"), "math"),
]

# 人工判定覆盖表（source_id -> 主类），优先于关键词。用于：
#   - ABC 无 type 的题（官方无 tags，人工从题面判定）
#   - 关键词易误判的复合题（如"字符画/区间"等
ABC_MANUAL: dict[str, str] = {
    "abc161_d": "math",    # 数位 DFS 生成（数字规律/枚举）
    "abc328_b": "sim",     # 日期 repdigit 枚举模拟
    "abc139_a": "sim",     # 字符串比对
    "abc248_d": "binary",  # 值域位置二分（离线查询）
    "abc229_d": "twoptr",  # 滑动窗口
    "abc330_c": "math",    # sqrt 数学逼近
    "abc148_f": "graph",   # 树上距离 + 贪心博弈
    "abc088_b": "greedy",  # 排序轮流取
    "abc248_c": "dp",      # 序列计数 DP
    "abc330_d": "math",    # 网格行列计数
    "abc300_c": "sim",     # 网格字符画统计
    "abc294_e": "sim",     # 区间合并扫描
    "abc297_e": "ds",      # 第 K 小（堆/生成）
    "abc207_c": "ds",      # 区间端点排序扫描
    "abc236_d": "dp",      # 状压 DP 分组
    "abc251_d": "construct",  # 砝码构造
    "abc340_c": "dp",      # 记忆化递归
    "abc367_e": "graph",   # 置换倍增
}


def abc_classes(source_id: str, type_str: str | None) -> list[str]:
    """ABC → 标准主类：人工表优先，其次关键词匹配（保序去重）。

    无 type 且无人工表项 → 返回 []（调用方记为待补）。
    """
    manual = ABC_MANUAL.get(source_id)
    if manual:
        return [manual]
    if not type_str:
        return []
    out: list[str] = []
    for pat, cls in ABC_KEYWORDS:
        if pat.search(type_str) and cls not in out:
            out.append(cls)
    return out


# ---------------------------------------------------------------------------
# 处理
# ---------------------------------------------------------------------------
def _read(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印报告不写回")
    args = ap.parse_args()

    # ---- CF ----
    cf_path = ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"
    probs_path = ROOT / "data" / "cache" / "cf_problemset.json"
    probs = json.loads(probs_path.read_text(encoding="utf-8"))
    id2tags = {f"cf{p.get('contestId')}{p.get('index').lower()}": p.get("tags", [])
               for p in probs}
    cf_rows = _read(cf_path)
    cf_dist: Counter = Counter()
    cf_none = 0
    for r in cf_rows:
        otags = id2tags.get(r["source_id"], [])
        if not otags:
            cf_none += 1
        cls = cf_classes(otags)
        for c in cls:
            cf_dist[c] += 1
        if not args.dry_run:
            r.setdefault("metadata", {})["official_tags"] = otags
            r["metadata"]["alg_classes"] = cls
    print(f"== CF {len(cf_rows)} 题 ==")
    print("官方 tag 缺失(未查到):", cf_none)
    print("主类分布:", {ALG_CN[k]: v for k, v in cf_dist.most_common()})
    if CF_UNMAPPED:
        print("未映射官方 tag:", dict(CF_UNMAPPED))

    # ---- ABC ----
    abc_path = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"
    abc_rows = _read(abc_path)
    abc_dist: Counter = Counter()
    abc_none = 0
    abc_unmapped = []
    for r in abc_rows:
        t = (r.get("metadata", {}) or {}).get("type")
        cls = abc_classes(r["source_id"], t)
        if not t:
            abc_none += 1
            if not cls:
                abc_unmapped.append(r["source_id"])
        elif not cls:
            abc_unmapped.append(r["source_id"])
        for c in cls:
            abc_dist[c] += 1
        if not args.dry_run:
            r.setdefault("metadata", {})["alg_classes"] = cls
    print(f"\n== ABC {len(abc_rows)} 题 ==")
    print("无 type 或未拆出主类:", abc_none, abc_unmapped)
    print("主类分布:", {ALG_CN[k]: v for k, v in abc_dist.most_common()})

    if not args.dry_run:
        _write(cf_path, cf_rows)
        _write(abc_path, abc_rows)
        print("\n已写回 metadata.alg_classes")
    else:
        print("\n[dry-run] 未写回")


if __name__ == "__main__":
    main()
