"""Golden 沉默失败检出验证：把陷阱答案直接喂验证器，检验"答案对但过程错"的识别能力。

产出 data/outputs/golden_eval.jsonl 与检出统计。核心指标：
  - 沉默失败检出率 = 判定为 SILENT_FAILURE（或 PROCESS_INCORRECT 且答案正确）的占比
  - 定位命中率 = findings 覆盖真实缺陷步骤的比例

用法:
    python scripts/eval_golden.py [--scene algorithm|all]
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
    ap.add_argument("--scene", default="all", choices=["all", "algorithm"])
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    golden: list[GoldenSample] = []
    # 合成陷阱库 + 真实评测检出库（*_real_*.jsonl）都纳入检出验证
    for p in sorted((ROOT / "data" / "golden").glob("*.jsonl")):
        name = p.name
        if args.scene != "all" and args.scene not in name:
            continue  # 只加载含目标场景名的文件（如 algorithm / real_algorithm）
        golden += load_jsonl(p, GoldenSample)

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

    from rex.pipeline import _execution_feedback
    from rex.executor.sandbox import detect_language, run_code
    from rex.executor.tests import run_test_cases

    def _golden_exec_feedback(g: GoldenSample) -> str | None:
        """对陷阱答案真实跑沙盒，给出客观执行反馈（答案是否真对）。
        与正式评测同路径——SILENT_FAILURE 的判定依赖"沙盒答案全对"证据。
        """
        ans = g.flaw_answer
        q = g.question
        if ans.code and q.test_cases:
            lang = detect_language(ans.code)
            res = run_test_cases(ans.code, q.test_cases, language=lang,
                                 judge=q.judge, checker_code=q.checker_code,
                                 checker_language=q.checker_language)
            correct = res.pass_rate >= 1.0
            return _execution_feedback(q, correct, res.pass_rate, res.error)
        if q.standard_answer and ans.final_answer:
            return _execution_feedback(q, q.standard_answer.strip() == ans.final_answer.strip(),
                                       None, None)
        return None

    with OUT.open("a", encoding="utf-8") as f:
        for g in golden:
            if g.question.id in done:
                continue
            exec_fb = _golden_exec_feedback(g)
            v = verifier.verify(g.question, g.flaw_answer, execution_feedback=exec_fb)
            rec = {"question_id": g.question.id, "scene": g.question.scene,
                   "flaw_type": g.flaw_type.value,
                   "verdict": v.verdict.value,
                   "findings": [x.model_dump() for x in v.findings],
                   "confidence": v.confidence}
            if exec_fb:
                rec["exec_feedback"] = exec_fb
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{g.question.id}: {v.verdict.value} ({v.confidence:.2f}) | fb={bool(exec_fb)}")
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
