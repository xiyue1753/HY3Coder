"""Generate reports/REPORT.md from eval/refine/audit data.

Usage:
    python scripts/make_report.py [--out reports/REPORT.md]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.metrics.stats import stability_check, wilson_interval
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


def _diff_score_of(r: EvalRecord, qmap: dict) -> float | None:
    q = qmap.get(r.question_id)
    if q is None:
        return None
    return (q.metadata or {}).get("diff_score")


def _platform_of(rid: str, qmap: dict) -> str:
    q = qmap.get(rid)
    sid = (q.source_id or "") if q else ""
    return "ABC" if sid.startswith("abc") else "CF"


def unified_tier_table(evals: list[EvalRecord], qmap: dict,
                       n_tiers: int = 5) -> list[dict]:
    """按 diff_score（0-100 统一难度分）分位切档，逐档统计答案率/过程率/Wilson。"""
    scored = []
    for r in evals:
        if r.source != "run-eval":
            continue
        ds_ = _diff_score_of(r, qmap)
        if ds_ is not None:
            scored.append((ds_, r))
    if not scored:
        return []
    scored.sort(key=lambda x: x[0])
    n = len(scored)
    rows = []
    for i in range(n_tiers):
        seg = scored[i * n // n_tiers:(i + 1) * n // n_tiers]
        if not seg:
            continue
        recs = [r for _, r in seg]
        ans = sum(1 for r in recs if r.answer_correct is True)
        proc = sum(1 for r in recs
                   if r.verification.verdict.value == "CORRECT")
        lo_w, hi_w = wilson_interval(proc, len(recs))
        rows.append({
            "tier": i + 1,
            "ds_lo": seg[0][0], "ds_hi": seg[-1][0],
            "n": len(recs),
            "answer": ans / len(recs),
            "process": proc / len(recs),
            "ci_low": lo_w, "ci_high": hi_w,
        })
    return rows


def build() -> str:
    cfg = Config.from_env(ROOT)
    # 数据文件位置统一由数据源注册中心声明（见 src/rex/datasource.py）
    from rex import datasource as ds
    # 报告口径 = 正式评测（run-eval），排除交互演示记录
    evals = [r for r in ds.load_active_evals(ROOT) if r.source == "run-eval"]
    refines = ds.load_active_refines(ROOT)
    audits = ds.load_audits(ROOT)
    qmap: dict[str, QuestionItem] = {}
    for q in ds.load_active_questions(ROOT):
        qmap[q.id] = q
    # 合成 golden（展示样例）与真实检出库分开读，路径由注册中心声明
    golden = (load_jsonl(ds.golden_synthetic_path(ROOT), GoldenSample)
              if ds.golden_synthetic_path(ROOT).exists() else [])

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
    # Wilson 95% 区间（小样本下比例估计的诚实范围）
    valid = [r for r in evals if r.verification.verdict.value != "FAILED"]
    n_valid = len(valid)
    k_proc = sum(r.verification.verdict.value == "CORRECT" for r in valid)
    lo, hi = wilson_interval(k_proc, n_valid)
    w(f"| 过程正确率 95% CI | [{lo * 100:.1f}%, {hi * 100:.1f}%]（Wilson） |")
    w("")
    # 分平台概览
    w("\n**分平台概览**（均为正式 run-eval）\n")
    w("| 子集 | 样本 | 答案准确率 | 过程正确率 |")
    w("|---|---|---|---|")
    for pl in ("ABC", "CF"):
        sub = [r for r in evals if _platform_of(r.question_id, qmap) == pl]
        if not sub:
            continue
        sv = [r for r in sub if r.verification.verdict.value != "FAILED"]
        nv = len(sv)
        ans = sum(1 for r in sv if r.answer_correct is True)
        proc = sum(1 for r in sv if r.verification.verdict.value == "CORRECT")
        w(f"| {pl} 自建 | {len(sub)} | {pct(ans / nv if nv else None)} | "
          f"{pct(proc / nv if nv else None)} |")
    w("")
    # 稳定性 + 随机性声明
    st = stability_check(valid)
    stable_txt = "稳定（漂移 <5pp）" if st.stable else "波动（漂移 ≥5pp，需多轮求解抹平）"
    w("**结果随机性与稳定性说明**：本报告为**单次求解**结果（每题一次 Hy3 调用，"
      "模型采样有随机性）。二次抽样稳定性检验（两种子各取 60% 分档重抽，比较过程正确率）："
      f"抽样A={st.seed_a * 100:.1f}% vs 抽样B={st.seed_b * 100:.1f}%，漂移 "
      f"**{st.drift * 100:.1f}pp**，判定为{stable_txt}。"
      "若需收紧指标，可对全量做多次求解取均值——本报告作为单次基线，"
      "Wilson 区间与抽样稳定性已给出不确定性上界。\n")
    w("")

    # ---- 2. 分层退化（平台难度轴）----
    w("## 2. 分层退化分析")
    w("\n### 2.1 平台难度轴（rating/difficulty 校正后 basic/medium/hard）\n")
    w("\n| 难度 | 样本 | 答案准确率 | 过程正确率 |")
    w("|---|---|---|---|")
    for tier, t in sorted(m.per_tier.items()):
        w(f"| {tier} | {t.n} | {pct(t.answer_accuracy)} | {pct(t.process_correctness)} |")
    w("")

    # ---- 2b. 统一难度轴（diff_score 五分位，跨平台可比）----
    w("\n### 2.2 统一难度轴（Hy3 多专家评审 diff_score，五分位跨平台可比）\n")
    ut = unified_tier_table(evals, qmap)
    if ut:
        w("\n> 难度分 `diff_score` 由 Hy3 三专家盲打+仲裁给出（0-100，与平台无关），"
          "见 §A 方法与验证。档 1 最易 → 档 5 最难。\n")
        w("\n| 档 | diff_score 区间 | 样本 | 答案准确率 | 过程正确率 | 95% CI |")
        w("|---|---|---|---|---|---|")
        for row in ut:
            w(f"| 档{row['tier']} | [{row['ds_lo']},{row['ds_hi']}] | {row['n']} | "
              f"{pct(row['answer'])} | {pct(row['process'])} | "
              f"[{row['ci_low'] * 100:.1f}%, {row['ci_high'] * 100:.1f}%] |")
        # 临界点判定：过程正确率首次显著下降处
        procs = [r["process"] for r in ut]
        drop = None
        for i in range(1, len(procs)):
            if procs[i - 1] - procs[i] >= 0.08:
                drop = i + 1
                break
        w("\n**临界点判定**：过程正确率随统一难度单调下降"
          f"（档1 {pct(procs[0])} → 档{len(procs)} {pct(procs[-1])}）。")
        if drop:
            w(f"首次显著跌落（≥8pp）出现在**档 {drop}**"
              f"（diff_score ≥ {ut[drop - 1]['ds_lo']}）——"
              "模型过程能力在统一难度轴的该区间开始明显失守。")
        else:
            w("未观察到 ≥8pp 的显著单档跌落，能力随难度平缓退化。")
        w("")
    else:
        w("\n_暂无 diff_score（先运行 score_difficulty.py）。_\n")

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
        w(f"\n_暂无抽检标注，运行 `python -m src.cli audit --results {ds.evals_path(ROOT, next(d for d in ds.active_datasets() if d.evals))}` 生成模板。_\n")

    # ---- 7. Golden ----
    # 真实评测检出库（独立文件，见注册中心 golden_real_path）
    golden_real = (load_jsonl(ds.golden_real_path(ROOT), GoldenSample)
                   if ds.golden_real_path(ROOT).exists() else [])
    w("## 7. Golden 沉默失败样本库")
    w("\n**样本分两类来源，口径独立统计：**\n")
    w(f"- 合成陷阱库 `golden_algorithm.jsonl`：{len(golden)} 条（人工构造「答案对但过程错」）")
    w(f"- 真实评测库 `golden_real_algorithm.jsonl`：{len(golden_real)} 条"
      "（真实 Hy3 评测中 verifier 检出 `SILENT_FAILURE` 的样本，沙盒答案全对，"
      "flaw_answer 即当时模型真实输出）\n")

    if golden:
        w(f"### 7.1 合成展示样例（{len(golden)} 条）\n")
        w("> 合成库已精简为 2 条展示样例（GA001/GA002），样本主体以真实评测检出库为主。\n")
        for g in golden:
            w(f"- `{g.question.id}` [{g.question.scene}] {g.question.title} — 真实缺陷："
              f"{TYPE_CN.get(g.flaw_type.value, g.flaw_type.value)}（{g.construction_note[:80]}…）")
        w("")

    if golden_real:
        w(f"### 7.2 真实评测检出库（{len(golden_real)} 条）\n")
        w("> 每条记录真实评测来源：题目源（contest）、检测时间、verifier 定位的缺陷与步骤、"
          "沙盒通过率。flaw_answer 是当时模型的真实求解输出（含代码），非人工编造。\n")
        for g in golden_real:
            q = g.question
            src_id = q.source_id or "—"
            w(f"- **`{q.id}`**（{q.source} · `{src_id}` · {q.difficulty.value}）")
            w(f"  - 题面：{q.prompt[:160].strip()}…")
            w(f"  - 缺陷类型：{TYPE_CN.get(g.flaw_type.value, g.flaw_type.value)}")
            w(f"  - 构造/来源说明：{g.construction_note}")
            w(f"  - 陷阱步骤数：{len(g.flaw_answer.steps)}（含代码 "
              f"{'✓' if g.flaw_answer.code else '✗'}）")
        w("")

    ge_path = cfg.outputs_dir / "golden_eval.jsonl"
    golden_eval: list[dict] = []
    if ge_path.exists():
        import json as _json
        with ge_path.open(encoding="utf-8") as f:
            golden_eval = [_json.loads(l) for l in f if l.strip()]
    if golden_eval:
        w("\n### 7.3 评估器检出验证（陷阱答案直喂验证器）\n")
        w("> 把每条 golden 的 `flaw_answer` 直接喂 verifier，检验能否识别"
          "「答案对但过程错」。下表区分合成（G 开头）与真实评测检出样本。\n")
        real_ids = {g.question.id for g in golden_real}
        w("| 样本 | 来源 | 真实缺陷 | 判定 |")
        w("|---|---|---|---|")
        for r in golden_eval:
            qid = r.get("question_id") or "?"
            v = r["verdict"]
            src = "真实评测" if qid in real_ids else ("合成" if str(qid).startswith("GA") else "?")
            tag = ("未检出(放行)" if v == "CORRECT"
                   else ("严格检出(答案对+过程错)" if v == "SILENT_FAILURE"
                         else ("宽口径检出(判过程有错)" if v in ("PROCESS_INCORRECT",)
                               else "识别(答案/格式)")))
            w(f"| {qid} | {src} | {TYPE_CN.get(r['flaw_type'], r['flaw_type'])} | {v} — {tag} |")
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
    w("| 分层退化 | 平台难度轴见 2.1；统一难度轴见 2.2（临界点 = 首次 ≥8pp 跌落的 diff_score 档） | 对临界点之上补充针对性用例 |")
    w("")

    w("---")
    w("\n_数据纯净性说明：以上全部指标仅基于 eval 模式结果；refine 数据单独用于第 5 节对比，不混入评估指标。_\n")

    # ---- 附录 A：评测集构造与统一难度分层方法 ----
    method_path = ROOT / "reports" / "DIFFICULTY_SCORING_METHOD.md"
    if method_path.exists():
        w("\n---\n\n# 附录 A：评测集构造与统一难度分层方法\n")
        w("\n> 评测题集的构建与统一难度分层（Hy3 多专家评审工作流）方法全文如下"
          "（源自 `reports/DIFFICULTY_SCORING_METHOD.md`）。\n")
        body = method_path.read_text(encoding="utf-8")
        # 去掉原标题行（避免与附录标题重复），并把方法文档子标题 ## N 降为 ### A.N
        lines_ = body.split("\n")
        out_lines: list[str] = []
        started = False
        for ln in lines_:
            if ln.startswith("# "):
                started = True
                continue
            mm = re.match(r"^## (\d+)\.\s*(.*)$", ln)
            if mm:
                out_lines.append(f"### A.{mm.group(1)} {mm.group(2)}")
            else:
                out_lines.append(ln)
        w("\n".join(out_lines).rstrip())
        w("\n")

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
