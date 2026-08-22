"""Golden 沉默失败检出验证：把陷阱答案直接喂验证器，检验"答案对但过程错"的识别能力。

产出 data/outputs/golden_eval.jsonl 与检出统计。核心指标：
  - 沉默失败检出率 = 判定为 SILENT_FAILURE（或 PROCESS_INCORRECT 且答案正确）的占比
  - 定位命中率 = findings 覆盖真实缺陷步骤的比例

用法:
    python scripts/eval_golden.py [--scene math|algorithm|all]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config
from rex.models import GoldenSample, Verdict
from rex.pipeline import load_jsonl
from rex.verifier.agent import VerifierAgent

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outputs" / "golden_eval.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="all", choices=["all", "math", "algorithm"])
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    golden: list[GoldenSample] = []
    for name in ("golden_math.jsonl", "golden_algorithm.jsonl"):
        if args.scene != "all" and name != f"golden_{args.scene}.jsonl":
            continue
        golden += load_jsonl(ROOT / "data" / "golden" / name, GoldenSample)

    from rex.hy3_client import Hy3Client
    verifier = VerifierAgent(client=Hy3Client(
        api_key=cfg.hy3_api_key, base_url=cfg.hy3_base_url, model=cfg.hy3_model,
        reasoning_effort=cfg.hy3_reasoning_effort, max_retries=cfg.max_retries,
        timeout=cfg.timeout))
    done = set()
    if OUT.exists():
        for l in OUT.open(encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["question_id"])
        print(f"resume: {len(done)} already done")

    with OUT.open("a", encoding="utf-8") as f:
        for g in golden:
            if g.question.id in done:
                continue
            v = verifier.verify(g.question, g.flaw_answer)
            rec = {"question_id": g.question.id, "scene": g.question.scene,
                   "flaw_type": g.flaw_type.value,
                   "verdict": v.verdict.value,
                   "findings": [x.model_dump() for x in v.findings],
                   "confidence": v.confidence}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{g.question.id}: {v.verdict.value} ({v.confidence:.2f})")
            time.sleep(0.5)
    # 脚本退出时 client 自动清理

    # 统计
    results = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    detected = [r for r in results if r["verdict"] in ("SILENT_FAILURE", "PROCESS_INCORRECT")]
    hit = sum(
        1 for r in detected
        if any(f["step_id"] == i for f in r["findings"] for i in [0, 1, 2])
    )
    n = len(results)
    print(f"\n===== golden 检出统计 =====  n={n}")
    print(f"检出（SILENT_FAILURE/PROCESS_INCORRECT）：{len(detected)}（{len(detected)/n*100:.1f}%）")
    print(f"其中判 SILENT_FAILURE：{sum(1 for r in results if r['verdict']=='SILENT_FAILURE')}")
    print(f"误放行（判 CORRECT 放过陷阱）：{sum(1 for r in results if r['verdict']=='CORRECT')}")
    print(f"结果见 {OUT}")


if __name__ == "__main__":
    main()
