# -*- coding: utf-8 -*-
"""把跨平台统一难度分写回题集 metadata.diff_score（报告/仪表盘展示用）。

用法（score_difficulty.py 全量产出 diff_scores.jsonl 后）：
  python scripts/apply_diff_score.py --dry-run    # 预览命中
  python scripts/apply_diff_score.py              # 写回两题集
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "outputs" / "diff_scores.jsonl"


def load_scores() -> dict[str, dict]:
    out = {}
    if SCORES.exists():
        for l in SCORES.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                out[r["question_id"]] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    scores = load_scores()
    if not scores:
        print("diff_scores.jsonl 为空/不存在")
        return
    for fname in ("abc_selfbuilt.jsonl", "cf_selfbuilt.jsonl"):
        path = ROOT / "data" / "questions" / fname
        rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
        hit = 0
        for r in rows:
            s = scores.get(r["id"])
            if s and s.get("final_score") is not None:
                hit += 1
                if not args.dry_run:
                    md = r.setdefault("metadata", {})
                    md["diff_score"] = s["final_score"]
        print(f"{fname}: 命中 {hit}/{len(rows)}"
              + (" (dry-run 未写回)" if args.dry_run else " 已写回"))
        if not args.dry_run:
            with path.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
