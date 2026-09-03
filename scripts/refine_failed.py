"""对 eval 中判定为过程错误的题目运行 refine，验证修正闭环（错误→修正）。

用法:
    python scripts/refine_failed.py --scene algorithm --limit 3

从 eval_{scene}.jsonl 挑 verdict != CORRECT 的题，加载原题后跑 ReAct 修正，
结果追加到 refine_{scene}.jsonl（与 CLI run-refine 同一文件，断点续跑兼容）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config
from rex.datasets.schema import load_questions
from rex.models import EvalRecord, Verdict
from rex.pipeline import Pipeline, load_jsonl

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="algorithm", choices=["algorithm"])
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    evals = load_jsonl(cfg.outputs_dir / f"eval_{args.scene}.jsonl", EvalRecord)
    failed = [r.question_id for r in evals
              if r.verification.verdict != Verdict.CORRECT][: args.limit]
    if not failed:
        print(f"[info] {args.scene} 无待修正样本（当前全量仍在进行，可稍后重试）")
        return
    qmap = {q.id: q for q in load_questions(cfg.data_dir / "questions" / f"{args.scene}.jsonl")}
    questions = [qmap[qid] for qid in failed if qid in qmap]
    print(f"对 {len(questions)} 题运行修正闭环: {failed}")

    pipe = Pipeline(cfg)
    pipe.refiner._max_rounds = 3
    out = cfg.outputs_dir / f"refine_{args.scene}.jsonl"
    records = pipe.run_refine(questions, out, resume=True)
    pipe.client.close()

    for r in records:
        init = r.initial.verdict.value
        final = r.final.verdict.value
        print(f"{r.question_id}: {init} -> {final} (rounds={len(r.rounds)})")


if __name__ == "__main__":
    main()
