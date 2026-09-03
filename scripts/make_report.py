"""Generate reports/REPORT.md from eval/refine/audit data.

Usage:
    python scripts/make_report.py [--out reports/REPORT.md]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.models import AuditRecord, EvalRecord, GoldenSample, QuestionItem, RefineRecord
from rex.pipeline import load_jsonl

ROOT = Path(__file__).resolve().parents[1]
TYPE_CN = {
    "concept": "概念理解错误", "calculation": "计算错误", "misread": "题意误读",
    "condition": "条件遗漏", "jump": "跳步推导", "format": "格式不符",
    "logic": "逻辑缺陷", "boundary": "边界条件", "complexity": "复杂度不达标",
}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def build() -> str:
    cfg = Config.from_env(ROOT)
    evals: list[EvalRecord] = []
    for f in ("eval_algorithm.jsonl",):
        p = cfg.outputs_dir / f
        if p.exists():
            evals += load_jsonl(p, EvalRecord)
    refines: list[RefineRecord] = []
    for f in ("refine_algorithm.jsonl",):
        p = cfg.outputs_dir / f
        if p.exists():
            refines += load_jsonl(p, RefineRecord)
    audits = load_jsonl(cfg.outputs_dir / "audit_records.jsonl", AuditRecord)
    qmap: dict[str, QuestionItem] = {}
    for f in ("algorithm.jsonl", "abc_selfbuilt.jsonl", "cf_selfbuilt.jsonl"):
        p = cfg.data_dir / "questions" / f
        if p.exists():
            qmap.update({q.id: q for q in load_jsonl(p, QuestionItem)})
    golden = load_jsonl(cfg.data_dir / "golden" / "golden_algorithm.jsonl", GoldenSample)

    L: list[str] = []
    w = L.append
    w("# HY3Coder 分析报告")
    w(f"\n> 生成时间：{datetime.now():%Y-%m-%d %H:%M} ｜ 数据：`data/outputs/`（eval/refine 严格分离）\n")

    # ---- 1. 总览 ----
    w("## 1. 评估总览")
    if not evals:
        w("\n_暂无可评估数据，先运行 `run-eval`。_\n")
        return "\n".join(L)
    m = compute_metrics(evals)
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 评估样本数 | {m.n} |")
    w(f"| 答案准确率 | {pct(m.answer_accuracy)} |")
    w(f"| 过程正确率 | {pct(m.process_correctness)} |")
    w(f"| 判定分布 | {', '.join(f'{k}={v}' for k, v in sorted(m.verdict_dist.items()))} |")
    sf = m.verdict_dist.get("SILENT_FAILURE", 0)
    if sf:
        w(f"| 沉默失败检出 | {sf}（{pct(sf / m.n)}） |")
    failed = m.verdict_dist.get("FAILED", 0)
    if failed:
        # 运行失败（网络/超时）样本无真实判定，已从正确率分母中排除，仅在此标注可见性。
        w(f"| 运行失败（不计入指标） | {failed} |")
    w("")

    # ---- 2. 分层退化 ----
    w("## 2. 分层退化分析")
    w("\n| 难度 | 样本 | 答案准确率 | 过程正确率 |")
    w("|---|---|---|---|")
    for tier, t in sorted(m.per_tier.items()):
        w(f"| {tier} | {t.n} | {pct(t.answer_accuracy)} | {pct(t.process_correctness)} |")
    w("")

    # ---- 3. 错误类型分布 ----
    w("## 3. 错误类型分布")
    w("\n| 错误类型 | 数量 | 占比（过程错误样本中） |")
    w("|---|---|---|")
    total_inc = sum(m.error_type_dist.values()) or 1
    for k, v in sorted(m.error_type_dist.items(), key=lambda x: -x[1]):
        w(f"| {TYPE_CN.get(k, k)} | {v} | {v / total_inc * 100:.1f}% |")
    w("")

    # ---- 4. 典型 case 归因 ----
    w("## 4. 典型 case 归因")
    notable = [r for r in evals if r.verification.verdict.value == "SILENT_FAILURE"][:5]
    if not notable:
        w("\n_当前样本中暂无 SILENT_FAILURE，选过程错误样本展示。_\n")
        notable = [r for r in evals if r.verification.verdict.value == "PROCESS_INCORRECT"][:5]
    for r in notable:
        q = qmap.get(r.question_id)
        qtext = (q.prompt[:80] + "…") if q and len(q.prompt) > 80 else (q.prompt if q else r.question_id)
        findings = "；".join(
            f"第{f.step_id}步 {TYPE_CN.get(f.error_type.value, f.error_type.value)}：{f.detail[:50]}"
            for f in r.verification.findings[:3])
        w(f"\n### {r.question_id}（{r.scene} / {r.difficulty.value}）")
        w(f"- 判定：**{r.verification.verdict.value}**（置信度 {r.verification.confidence:.2f}）")
        w(f"- 题目：{qtext}")
        w(f"- 答案正确：{r.answer_correct}，测试通过率：{r.test_pass_rate}")
        w(f"- 定位发现：{findings or '无'}")
    w("")

    # ---- 5. 修正前后对比 ----
    w("## 5. 修正闭环（ReAct 前后对比）")
    if refines:
        rc = refine_comparison(refines)
        w("\n| 指标 | 数值 |")
        w("|---|---|")
        w(f"| 修正样本数 | {rc.n} |")
        w(f"| 修正前过程正确率 | {pct(rc.before_correct)} |")
        w(f"| 修正后过程正确率 | {pct(rc.after_correct)} |")
        w(f"| 收敛率 | {pct(rc.converged)} |")
        w(f"| 提升幅度 | {pct(rc.improved)} |")
        w("")
        fixed = [r for r in refines
                 if r.initial.verdict.value != "CORRECT" and r.final.verdict.value == "CORRECT"]
        if fixed:
            w("成功修正样本：")
            for r in fixed[:5]:
                first = r.rounds[0].feedbacks[0] if r.rounds and r.rounds[0].feedbacks else None
                fb = f"（定位第{first.step_id}步 · {TYPE_CN.get(first.error_type.value, first.error_type.value)}）" if first else ""
                w(f"- `{r.question_id}`：初始 {r.initial.verdict.value} → 最终 CORRECT{fb}")
            w("")
    else:
        w("\n_暂无 refine 数据。_\n")

    # ---- 6. 人工抽检 ----
    w("## 6. 人工抽检")
    if audits:
        am = audit_metrics(evals, audits)
        w("\n| 指标 | 数值 |")
        w("|---|---|")
        w(f"| 已标注样本 | {sum(1 for a in audits if a.verdict_human)} / {len(audits)} |")
        if am:
            # 对齐任务书 P4 口径：定位准确率用答案错误样本，误报率用答案正确样本
            w(f"| 定位准确率（答案错误样本 {am.localization_n}） | {pct(am.error_localization_hit_rate)} |")
            w(f"| 误报率（答案正确且判过程有错 {am.fp_n}） | {pct(am.false_positive_rate)} |")
        w("")
        w("> 口径说明：定位准确率分母为「答案错误」样本（用标准答案判定），"
          "误报率分母为「答案正确」样本中被评估器判过程有错者（经人工抽检确认）。\n")
    else:
        w("\n_暂无抽检标注，运行 `python -m src.cli audit --results data/outputs/eval_algorithm.jsonl` 生成模板。_\n")

    # ---- 7. Golden ----
    w("## 7. Golden 沉默失败样本库")
    w(f"\n共 {len(golden)} 条（算法），全部为「答案正确但过程有缺陷」陷阱样本：\n")
    for g in golden:
        w(f"- `{g.question.id}` [{g.question.scene}] {g.question.title} — 真实缺陷："
          f"{TYPE_CN.get(g.flaw_type.value, g.flaw_type.value)}（{g.construction_note[:60]}…）")
    w("")

    ge_path = cfg.outputs_dir / "golden_eval.jsonl"
    golden_eval: list[dict] = []
    if ge_path.exists():
        import json as _json
        with ge_path.open(encoding="utf-8") as f:
            golden_eval = [_json.loads(l) for l in f if l.strip()]
    if golden_eval:
        w("\n### 7.1 评估器检出验证（陷阱答案直喂验证器）\n")
        w("| 样本 | 真实缺陷 | 判定 |")
        w("|---|---|---|")
        for r in golden_eval:
            v = r["verdict"]
            tag = ("未检出(放行)" if v == "CORRECT"
                   else ("严格检出(答案对+过程错)" if v == "SILENT_FAILURE"
                         else ("宽口径检出(判过程有错)" if v in ("PROCESS_INCORRECT",)
                               else "识别(答案/格式)")))
            w(f"| {r['question_id']} | {TYPE_CN.get(r['flaw_type'], r['flaw_type'])} | {v} — {tag} |")
        n = len(golden_eval)
        strict = sum(1 for r in golden_eval if r["verdict"] == "SILENT_FAILURE")
        broad = sum(1 for r in golden_eval
                    if r["verdict"] in ("SILENT_FAILURE", "PROCESS_INCORRECT"))
        passed = sum(1 for r in golden_eval if r["verdict"] != "CORRECT")
        missed = n - passed
        # 口径说明：宽口径把 PROCESS_INCORRECT 也算"检出过程有错"；严格口径只认
        # SILENT_FAILURE（答案正确 + 过程根本缺陷），是最能体现沉默失败识别能力的指标。
        w(f"\n**检出统计（n={n}）**\n")
        w(f"- 严格口径（判定 SILENT_FAILURE）：{strict} 条（{strict/n*100:.1f}%）")
        w(f"- 宽口径（SILENT_FAILURE + PROCESS_INCORRECT，判过程有错）：{broad} 条（{broad/n*100:.1f}%）")
        w(f"- 答案/格式识别：{passed - broad} 条（ANSWER_INCORRECT 等，识别到异常但未判过程）")
        w(f"- 误放行（CORRECT 放过陷阱）：{missed} 条")
        w("")
        if strict < broad:
            w(f"> 注：严格口径 {strict} 条 < 宽口径 {broad} 条，"
              "说明部分陷阱被判为 PROCESS_INCORRECT 而非 SILENT_FAILURE——"
              "评估器识别到了过程错误，但未单独标注【答案正确】这一性质。\n")
    w("")

    # ---- 8. 能力画像 ----
    w("## 8. 能力画像弱项清单")
    w("\n| 维度 | 观察 | 建议 |")
    w("|---|---|---|")
    w("| 复杂度控制 | 见第 3 节错误类型占比，若 `复杂度不达标`/`边界条件` 占比高，反映算法场景实现严谨性不足 | 增加静态检查前置；对声明复杂度与实现做一致性校验 |")
    w("| 跳步推导 | 算法场景 `跳步推导` 高发说明步骤颗粒度过粗 | 验证 prompt 强化逐步自含性要求 |")
    w("| 沉默失败 | golden 检出率与抽检误报率联动监控 | 高误报时收紧定位条件，低检出时增强回溯审查 |")
    w("| 分层退化 | 若 hard 档过程正确率显著低于 basic，符合预期；关注 medium 档是否突然跌落 | 对跌落档补充针对性用例 |")
    w("")

    w("---")
    w("\n_数据纯净性说明：以上全部指标仅基于 eval 模式结果；refine 数据单独用于第 5 节对比，不混入评估指标。_\n")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "REPORT.md")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(), encoding="utf-8")
    print(f"report written -> {args.out}")


if __name__ == "__main__":
    main()
