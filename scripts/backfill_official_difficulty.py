# -*- coding: utf-8 -*-
"""回填官方难度锚点到题集 metadata（可复现，不改 difficulty 分层标记）。

背景（构造叙事）：difficulty 分层目前靠人工 PLAN 指定且 layer_basis 未记录
官方难度数值，无法复现"为什么这题是 medium"。本脚本为每道自建题回填
**跨场可比**的官方难度锚点字段：
  - CF  : metadata.rating          ← data/cache/cf_problemset.json（本地反查）
  - ABC : metadata.difficulty_ap   ← AtCoder Problems API（kenkoooo，ELO 型跨场可比）
         首次运行时拉取全量 problem-models.json 缓存到 data/cache/abc_models.json，
         之后离线读取。回填后不修改题目 difficulty。

用法：
  python scripts/backfill_official_difficulty.py --dry-run   # 只预览覆盖率/分布
  python scripts/backfill_official_difficulty.py             # 写回两题集 metadata
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_ABC = ROOT / "data" / "cache" / "abc_models.json"
API_ABC = "https://kenkoooo.com/atcoder/resources/problem-models.json"

TIER_CF = lambda rt: "basic" if rt < 1200 else ("medium" if rt <= 1800 else "hard")
TIER_AP = lambda d: "basic" if d < 600 else ("medium" if d < 1000 else "hard")


def load_abc_models() -> dict:
    """拉取（或读缓存）AtCoder problem-models 全量。"""
    if CACHE_ABC.exists():
        return json.loads(CACHE_ABC.read_text(encoding="utf-8"))
    print("首次拉取 AtCoder problem-models（~5MB，无 cookie）…")
    req = urllib.request.Request(API_ABC, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    CACHE_ABC.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"已缓存 {len(data)} 题模型 -> {CACHE_ABC.name}")
    return data


def load_cf_index() -> dict:
    """cf_problemset.json -> {contest-index: {rating,...}}"""
    raw = json.loads((ROOT / "data" / "cache" / "cf_problemset.json").read_text(encoding="utf-8"))
    return {f"{p['contestId']}-{p['index']}": p for p in raw}


def cf_rating_for(meta: dict, idx: dict) -> int | None:
    """metadata.problem='cf1660a' / 'cf2044g2' → 反查 rating。"""
    prob = (meta.get("problem") or "").replace("cf", "")
    c = meta.get("contest")
    if not prob or not c:
        return None
    for i, ch in enumerate(prob):
        if ch.isalpha():
            index = prob[i:].upper()
            for cand in (f"{c}-{index}", f"{c}-{index[0]}"):
                if cand in idx and "rating" in idx[cand]:
                    return idx[cand]["rating"]
            return None
    return None


def process(path: Path, key: str, dry: bool) -> None:
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    done = 0
    vals: list[int] = []
    miss = []
    for r in rows:
        meta = r.setdefault("metadata", {})
        v = None
        if key == "rating":
            v = cf_rating_for(meta, _CF_IDX)
            if v is not None:
                meta["rating"] = v
                meta["rating_tier"] = TIER_CF(v)
        elif key == "difficulty_ap":
            prob = meta.get("problem")
            m = _AP_MODELS.get(prob)
            if m and "difficulty" in m:
                v = m["difficulty"]
                meta["difficulty_ap"] = v
                meta["ap_tier"] = TIER_AP(v)
        if v is not None:
            done += 1
            vals.append(v)
        else:
            miss.append(r["source_id"])
    print(f"== {path.name} 回填 {key}: {done}/{len(rows)}")
    if miss:
        print(f"   未命中 {len(miss)}: {miss[:8]}")
    if vals:
        tiers = Counter(TIER_AP(v) if key == "difficulty_ap" else TIER_CF(v) for v in vals)
        print(f"   锚点档分布: {dict(tiers)}")
        if key == "difficulty_ap":
            print(f"   difficulty_ap 范围: {min(vals)} .. {max(vals)}")
        else:
            print(f"   rating 范围: {min(vals)} .. {max(vals)}")
    if not dry:
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"   已写回 {path.name}")


_AP_MODELS: dict = {}
_CF_IDX: dict = {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写回")
    args = ap.parse_args()
    global _AP_MODELS, _CF_IDX
    _AP_MODELS = load_abc_models()
    _CF_IDX = load_cf_index()
    process(ROOT / "data" / "questions" / "abc_selfbuilt.jsonl", "difficulty_ap", args.dry_run)
    process(ROOT / "data" / "questions" / "cf_selfbuilt.jsonl", "rating", args.dry_run)


if __name__ == "__main__":
    main()
