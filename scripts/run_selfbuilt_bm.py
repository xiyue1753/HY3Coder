"""补测 abc_selfbuilt basic+medium 全量（resume，可分批续跑）。

用法:
    python scripts/run_selfbuilt_bm.py            # 补测全部未测 basic+medium
    python scripts/run_selfbuilt_bm.py basic      # 只补 basic
    python scripts/run_selfbuilt_bm.py medium     # 只补 medium

结果追加写入 data/outputs/eval_selfbuilt_bm.jsonl（断点续跑，重复执行自动跳过已完成）。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from rex.config import Config  # noqa: E402
from rex.datasets.schema import load_questions  # noqa: E402
from rex.runner import EvalRunner  # noqa: E402

DIFF = sys.argv[1] if len(sys.argv) > 1 else None  # None / basic / medium
if DIFF not in (None, "basic", "medium"):
    raise SystemExit("参数：basic / medium / 空(全部)")

cfg = Config.from_env(ROOT)
pool = load_questions(ROOT / "data" / "questions" / "abc_selfbuilt.jsonl")
already = set()
for f in ("eval_selfbuilt_hard.jsonl", "eval_selfbuilt_smoke.jsonl",
          "eval_selfbuilt_fixverify.jsonl", "eval_selfbuilt_bm.jsonl"):
    p = ROOT / "data" / "outputs" / f
    if p.exists():
        for line in p.open(encoding="utf-8"):
            if line.strip():
                import json as _json
                already.add(_json.loads(line)["question_id"])

pick = [q for q in pool
        if q.id not in already
        and (DIFF is None or q.difficulty.value == DIFF)]
print(f"题目池 {len(pool)}，本次补测 {len(pick)} 题（{DIFF or 'basic+medium'}）")

out = ROOT / "data" / "outputs" / "eval_selfbuilt_bm.jsonl"
if pick:
    runner = EvalRunner(cfg, retries=1, concurrency=4)
    records, costs = runner.run_eval(pick, out, resume=True, concurrency=4)
    print(f"完成：本次调用 {costs['calls']} 次，累计 {len(records)} 题 -> {out}")
else:
    print("无可补测题目（已全部完成）")
