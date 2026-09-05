# -*- coding: utf-8 -*-
"""校正极端错标：官方锚点档与 difficulty 跨≥2档的题。

依据官方 ELO 难度锚点（ABC: data/cache/abc_models.json 拉取的 difficulty_ap；
CF: metadata.rating）逐题核对，把"官方 basic 却标 hard / 官方 hard 却标 basic"
这类跨 ≥2 档的极端错标改回官方档，并同步：
  1) 题集 difficulty + layer_basis（补校正依据）
  2) 评测快照 eval_*.jsonl 中对应 question_id 的 difficulty（供分层统计）

差 1 档视为人工复核/阈值边界，不自动动（ABC 在 <600/≥1000 阈值下已无差1档，
因为该阈值刻意偏严；实际保留人工分层的差异由后续决策处理）。

用法：
  python scripts/fix_extreme_mislabel.py --dry-run   # 预览将改清单
  python scripts/fix_extreme_mislabel.py             # 写回
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ORDER = {"basic": 0, "medium": 1, "hard": 2}
TIER_AP = lambda d: "basic" if d < 600 else ("medium" if d < 1000 else "hard")
TIER_CF = lambda rt: "basic" if rt < 1200 else ("medium" if rt <= 1800 else "hard")


def collect(path: Path, key: str, tier_f):
    """返回 (all_rows, [(row, official_tier, gap)])。"""
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    fixes = []
    for r in rows:
        meta = r.get("metadata") or {}
        v = meta.get(key)
        if v is None:
            continue
        official = tier_f(v)
        gap = abs(ORDER[official] - ORDER[r["difficulty"]])
        if gap >= 2:
            fixes.append((r, official, gap))
    return rows, fixes


def layer_new(old: str, official: str, key: str, val: int) -> str:
    """旧 layer_basis 保留主体描述，追加官方锚点校正依据。"""
    base = old.split(" → ")[0] if " → " in old else old
    base = base.split("；")[0] if "；" in base else base
    return f"{base}；官方{key}={val}校正极端错标→{official}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    qpath = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"
    rows, fixes = collect(qpath, "difficulty_ap", TIER_AP)
    print(f"== ABC 极端错标待校正: {len(fixes)} 题")
    for r, official, gap in fixes:
        print(f"   {r['id']} {r['source_id']}: {r['difficulty']} -> {official} "
              f"(difficulty_ap={r['metadata'].get('difficulty_ap')}, 跨{gap}档)")
    if not fixes:
        print("   无")
    if args.dry_run:
        return

    # 写回题集
    for r, official, _ in fixes:
        r["difficulty"] = official
        r["layer_basis"] = layer_new(r.get("layer_basis", ""), official,
                                     "difficulty_ap", r["metadata"]["difficulty_ap"])
    with qpath.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"已写回题集 {qpath.name}")

    # 同步评测快照 difficulty
    qmap = {r["id"]: r for r in rows}
    epath = ROOT / "data" / "outputs" / "eval_selfbuilt_all.jsonl"
    erows = [json.loads(l) for l in epath.open(encoding="utf-8") if l.strip()]
    changed = 0
    for r in erows:
        q = qmap.get(r["question_id"])
        if q and q["difficulty"] != r["difficulty"]:
            r["difficulty"] = q["difficulty"]
            changed += 1
    with epath.open("w", encoding="utf-8") as f:
        for r in erows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"评测快照 eval_selfbuilt_all.jsonl difficulty 同步变更 {changed} 条")


if __name__ == "__main__":
    main()
