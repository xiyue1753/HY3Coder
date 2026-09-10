"""Generate reports/REPORT.md from eval/refine/audit data.

Usage:
    python scripts/make_report.py [--out reports/REPORT.md]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.metrics.stats import stability_check, wilson_interval
from rex.models import (
    AuditRecord,
    ErrorSeverity,
    EvalRecord,
    QuestionItem,
    RefineRecord,
    Verdict,
)
from rex.pipeline import load_jsonl

ROOT = Path(__file__).resolve().parents[1]
TYPE_CN = {
    "concept": "概念理解错误", "calculation": "计算错误", "misread": "题意误读",
    "condition": "条件遗漏", "missing_condition": "条件遗漏",
    "jump": "跳步推导", "format": "格式不符",
    "logic": "逻辑缺陷", "boundary": "边界条件", "complexity": "复杂度不达标",
    "other": "实现层失败",
}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _emit_refine_wrong(w, records: list[dict], qmap: dict) -> None:
    """§5.1 针对答案错样本的 ReAct 修正（真实度补偿版）渲染。"""
    done = [r for r in records if not r.get("error")]
    if not done:
        return
    n = len(done)
    conv = sum(1 for r in done if r.get("converged"))
    ans_ok = sum(1 for r in done if (r.get("final") or {}).get("answer_correct") is True)
    q1 = sum(1 for r in done if r.get("converged")
             and (r.get("final") or {}).get("answer_correct") is True)
    q2 = sum(1 for r in done if r.get("converged")
             and not (r.get("final") or {}).get("answer_correct"))
    q3 = sum(1 for r in done if not r.get("converged")
             and (r.get("final") or {}).get("answer_correct") is True)
    q4 = n - q1 - q2 - q3

    w("\n### 5.1 针对答案错样本的 ReAct 修正（真实度补偿，2026-09-09）")
    w(f"\n测试对象是 temperature=0 正式评测中 `answer_correct=False` 的全部 {n} 题。"
      "与纯文本 refine 相比，每轮反馈除 verifier 审查文本（findings→修订指令，仅 fatal 驱动）"
      "外，还附上非隐藏样例的沙盒执行结果（失败用例的输入、期望输出与实际输出），"
      "作为客观观察；重验证时通过 `execution_feedback` 喂给双视角与 ARBITER"
      "（公开样例失败时不得判 CORRECT）。终局用全部用例（含 hidden）沙盒复核答案真值，"
      "记录见 `data/outputs/refine_wrong_t0.jsonl`，脚本 `scripts/run_refine_wrong_t0.py`。"
      "方法全文见附录 C。（样本数由 34 增至 36：2026-09-10 补充 hidden 后新暴露的两道"
      "答案错题 A1169/C2063 已并入。）\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 修正样本数（全部答案错） | {n} |")
    w(f"| 文本收敛（verdict → CORRECT） | {conv}（{pct(conv / n)}） |")
    w(f"| 最终答案修对（全量含 hidden 沙盒） | {ans_ok}（{pct(ans_ok / n)}） |")
    w("")
    w("\n文本收敛与沙盒真值交叉：两者一致为完全成功，其余三类是边界样本。\n")
    w("\n| | 最终答案修对 | 最终仍错 |")
    w("|---|---|---|")
    w(f"| 文本收敛 | {q1}（真收敛） | {q2}（假收敛：hidden 缺陷仍在） |")
    w(f"| 未文本收敛 | {q3}（修对但评估器未认可） | {q4}（未改善） |")
    w("")

    plat = defaultdict(list)
    for r in done:
        plat["ABC" if r.get("question_id", "").startswith("A") else "CF"].append(r)
    w("\n按平台（多标签题不重复计入）：\n")
    w("| 子集 | 样本 | 文本收敛 | 最终修对 |")
    w("|---|---|---|---|")
    for name in ("ABC", "CF"):
        rows = plat[name]
        if not rows:
            continue
        c = sum(1 for r in rows if r.get("converged"))
        a = sum(1 for r in rows if (r.get("final") or {}).get("answer_correct") is True)
        w(f"| {name} 自建 | {len(rows)} | {c}（{pct(c / len(rows))}） | {a}（{pct(a / len(rows))}） |")
    w("")

    tiers = ["basic", "medium", "hard"]
    diff = {t: [r for r in done if r.get("difficulty") == t] for t in tiers}
    w("\n按难度：\n")
    w("| 难度 | 样本 | 文本收敛 | 最终修对 |")
    w("|---|---|---|---|")
    for t in tiers:
        rows = diff[t]
        if not rows:
            continue
        c = sum(1 for r in rows if r.get("converged"))
        a = sum(1 for r in rows if (r.get("final") or {}).get("answer_correct") is True)
        w(f"| {t} | {len(rows)} | {c}（{pct(c / len(rows))}） | {a}（{pct(a / len(rows))}） |")
    w("")

    rc = defaultdict(int)
    for r in done:
        rc[r.get("rounds_used")] += 1
    w("\n修正轮次分布：" + "，".join(f"{k} 轮 {v} 题" for k, v in sorted(rc.items())) + "\n")

    w("\n文本收敛与沙盒真值一致才算完全成功；"
      f"{q2} 题文本收敛但 hidden 仍错（假收敛），反映评估器只能看到公开用例；"
      f"{q3} 题沙盒已修对但评估器未判收敛，是定位与接受滞后的另一侧证据。"
      "本节同时是过程评估定位质量的下游观察面，与第 6 节定位准确率相互印证。"
      "新并入的 2 例一正一反：`C2063` 3 轮真收敛（复杂度缺陷修正后全量通过），"
      "`A1169` 1 轮即判 CORRECT 但全量仍 60%——与它的 eval 期漏检同源，"
      "说明\"公开用例全过\"时评估器容易接受未经验证的推理链。\n")
    w("\n![fig4](figures/fig4_refine_outcome.png)")
    w(f"\n**Fig. 3** {n} 个答案错样本经 ReAct 修正后的四象限分布：柱顶为样本数，"
      "横轴四类依次为「文本收敛且答案已对 / 文本收敛但答案仍错 / 未收敛但答案已对 / 未收敛且答案仍错」。"
      f"真收敛（收敛且最终全对）{q1} 题；文本收敛但 hidden 仍错 {q2} 题、修对但未获评估器认可 {q3} 题，"
      "构成文本判定与沙盒真值的两条边界。\n")

    w("\n过程性修正记录（2026-09-09）：\n")
    w("- 编译错误反馈管道缺陷与修复。首轮实现把运行/编译错误截断到 200 字符，"
      "编译器真正的诊断行（如 `shadows a parameter`、`no match for 'operator<'`）在"
      "模板堆栈之外，模型只见 `error: declaration` 无法定位，C2070/C2082 连续三轮修不好"
      "同一编译错误。本地手动编译确认沙盒判定正确（代码确不可编译）。改为从完整 stderr"
      "提取含 `error` 的诊断行后，两题均首轮收敛且最终全量通过。执行反馈应保留原始诊断，"
      "截断会削弱真实度补偿。\n")
    w("- 三轮未收敛样本人工校验。共 8 题，逐条核对每轮 findings 与沙盒事实，未发现评估器误报。\n")
    w("  - 修正能力不足（终局仍错 3 题）：`C2049`（组合计数公式三轮反复换仍错、自测虚报）、"
      "`C2085`（只删最右 vs 删任意位置、输出索引 vs 计数等概念反复错）、"
      "`C2121`（DP 截断/最短结尾维护反复错）。\n")
    w("  - 评估器正确坚持、缺陷真实但公开用例覆盖不到（5 题，终局沙盒虽过不等于满足约束）："
      "`A1071`（代码主循环每轮全表重建、最坏 O(N²)，N=1e6 必 TLE，人工抽查终版代码属实）、"
      "`C2060`（p,q 范围 ±1e18 下小范围枚举无保证、最坏复杂度 4e9 必超时）、"
      "`C2143`（分段公式存在边界反例）、`C2145`（贪心正确性引理被可验证反例击破）、"
      "`C2149`（扫描上界不足，isp[1] 曾误把 1 当素数）。"
      "这类缺陷公开小样例不会触发，过程评估的文本审查无法被沙盒替代。\n")


def _diff_score_of(r: EvalRecord, qmap: dict) -> float | None:
    q = qmap.get(r.question_id)
    if q is None:
        return None
    return (q.metadata or {}).get("diff_score")


def _platform_of(rid: str, qmap: dict) -> str:
    q = qmap.get(rid)
    sid = (q.source_id or "") if q else ""
    return "ABC" if sid.startswith("abc") else "CF"


def _emit_algorithm_profile(w, evals: list[EvalRecord], qmap: dict) -> None:
    """§8.1 算法类别 × 能力边界（按 metadata.alg_classes 标签统计）。"""
    from collections import defaultdict
    by_cls: dict[str, list[EvalRecord]] = defaultdict(list)
    for r in evals:
        if r.source != "run-eval":
            continue
        q = qmap.get(r.question_id)
        tags = ((q.metadata or {}).get("alg_classes") or []) if q else []
        for t in tags:
            by_cls[t].append(r)
    if not by_cls:
        return
    # 全库过程正确率基线（主口径：valid 中 verdict==CORRECT）
    valid = [r for r in evals if r.source == "run-eval"
             and r.verification.verdict.value != "FAILED"]
    base_proc = (sum(r.verification.verdict.value == "CORRECT" for r in valid)
                 / len(valid)) if valid else 0.0

    rows = []
    for cls, recs in by_cls.items():
        n = len(recs)
        ans = sum(r.answer_correct is True for r in recs)
        proc = sum(r.verification.verdict.value == "CORRECT" for r in recs)
        ds = [((qmap[r.question_id].metadata or {}).get("diff_score") or 0) for r in recs]
        err: dict[str, int] = defaultdict(int)
        for r in recs:
            if r.verification.verdict.value in ("PROCESS_INCORRECT", "SILENT_FAILURE", "ANSWER_INCORRECT"):
                for f in r.verification.findings[:4]:
                    if getattr(f, "severity", "fatal") == "fatal":
                        err[f.error_type.value] += 1
        top = "，".join(f"{TYPE_CN.get(k, k)}({v})" for k, v in
                        sorted(err.items(), key=lambda x: -x[1])[:2])
        rows.append({"cls": cls, "n": n, "ans": ans / n, "proc": proc / n,
                     "ds": sum(ds) / n, "err": top})
    rows.sort(key=lambda x: x["proc"])

    w("\n### 8.1 算法类别 × 能力边界（按 `alg_classes` 标签统计）")
    n_tagged = sum(1 for r in valid
                   if (qmap.get(r.question_id).metadata or {}).get("alg_classes"))
    w("\n统计按题集人工归一的算法类标签进行，多标签题计入多个类（类别不互斥）；"
      "平均 diff_score 用于区分该类别本身偏难，还是同难度下能力偏弱。"
      f"全库过程正确率基线 {pct(base_proc)}，答案正确率基线 "
      f"{pct(sum(1 for r in valid if r.answer_correct is True) / len(valid) if valid else 0)}"
      f"（{n_tagged}/{len(valid)} 题有标签）。\n")
    w("\n| 算法类 | 样本 | 答案准确率 | 过程正确率 | 平均 diff_score | 主要过程错误类型 |")
    w("|---|---|---|---|---|---|")
    for row in rows:
        w(f"| {row['cls']} | {row['n']} | {pct(row['ans'])} | {pct(row['proc'])} | "
          f"{row['ds']:.0f} | {row['err'] or '—'} |")
    w("")

    weak = [r for r in rows if r["n"] >= 8 and r["proc"] < base_proc - 0.08]
    strong = [r for r in rows if r["n"] >= 8 and r["proc"] >= base_proc + 0.08]
    if weak or strong:
        weak_txt = "、".join("`%s`（%s，n=%d）" % (r["cls"], pct(r["proc"]), r["n"])
                             for r in weak) if weak else "无"
        strong_txt = "、".join("`%s`（%s）" % (r["cls"], pct(r["proc"]))
                               for r in strong) if strong else ""
        w("**边界读数**：过程正确率低于全库基线 ≥8pp 的类别为**能力弱点边界**——"
          f"{weak_txt}；其中平均 diff_score 高的类别主要受题目难度驱动，"
          "diff_score 接近基线的类别属于同难度下确偏弱的一类。")
        if strong:
            w(f"显著高于基线的类别（强项）：{strong_txt}。")
        w("")
    w("\n边界解读：主体算法类（math/sim/graph/dp/greedy/ds，覆盖绝大多数样本）"
      "过程正确率 80% 上下（79.5%–84.6%），与全库基线基本持平，无系统性短板。"
      "弱点集中在 construct / twoptr / binary 三类，其主要过程错误均为逻辑缺陷与"
      "条件遗漏（missing_condition），指向构造与约束建模的严密性不足，而非知识缺失。"
      "string / game / twoptr 等样本不超过 16 的类别读数置信有限，只作方向性提示。"
      "该维度与 §2 难度边界、§3 错误类型边界互相独立，构成能力边界的三条证据线。\n")
    w("\n![fig2](figures/fig2_alg_classes.png)")
    w("\n**Fig. 4** 13 个算法类别的答案准确率（蓝色）与过程正确率（橙色），按过程正确率升序；"
      "条形末端为百分数。construct / twoptr / binary 低于全库基线 ≥8pp，是算法类别维度的"
      "能力边界。\n")


def _emit_contamination(w, evals: list[EvalRecord]) -> None:
    """§1.1 记忆暴露检测读数（官方原题镜像 contamination 探测）。"""
    p = ROOT / "data" / "outputs" / "contamination_probe.jsonl"
    if not p.exists():
        return
    rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    rows = [r for r in rows if not r.get("error")]
    if not rows:
        return
    n = len(rows)
    seen = sum(1 for r in rows if r.get("p1_verdict") == "seen")
    hits = [r for r in rows if (r.get("match") or {}).get("level") == "hit"]
    ev_by = {r.question_id: r for r in evals}

    def _ok(r):
        rec = ev_by.get(r["question_id"])
        return rec.answer_correct is True if rec else None

    hit_ok = sum(1 for r in hits if _ok(r) is True)
    non = [r for r in rows if (r.get("match") or {}).get("level") != "hit"]
    non_ok = sum(1 for r in non if _ok(r) is True)
    lo, hi = wilson_interval(len(hits), n)
    basic = sum(1 for r in hits if r.get("difficulty") == "basic")
    mid = sum(1 for r in hits if r.get("difficulty") == "medium")
    hit_ids = ", ".join(f"`{r['question_id']}`（{r['source_id']}）" for r in sorted(hits, key=lambda x: x['question_id']))

    w("\n### 1.1 记忆暴露检测（官方原题镜像 contamination 探测，2026-09-09）")
    w("\n题集为官方原题镜像，成绩是能力加记忆的上界。本节用行为探测估计记忆暴露："
      "分层抽样 30 题（ABC/CF × basic/medium/hard 每层 5，seed 42），每题两个 probe，"
      "分别是出处召回（是否记得竞赛/题号）与解法盲答；判定见附录 D，"
      "原始数据 `data/outputs/contamination_probe.jsonl`。\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 探测样本 | {n} |")
    w(f"| 自称见过（P1=seen） | {seen}（{pct(seen / n)}），迎合偏差高，不作暴露证据 |")
    w(f"| 出处精确命中（强证据） | {len(hits)}（{pct(len(hits) / n)}，95% CI [{lo * 100:.0f}%, {hi * 100:.0f}%]） |")
    w(f"| 命中难度分布 | basic {basic} / medium {mid} / hard 0 |")
    if hits:
        w(f"| 命中样本 | {hit_ids} |")
    w("")
    w("\n与正式评测交叉（记忆红利近似）：\n")
    w("\n| 组 | 样本 | t0 答案正确 |")
    w("|---|---|---|")
    w(f"| 出处命中组 | {len(hits)} | {hit_ok}（{pct(hit_ok / len(hits)) if hits else '—'}） |")
    w(f"| 未命中组 | {len(non)} | {non_ok}（{pct(non_ok / len(non)) if non else '—'}） |")
    w("")
    w("\n读数：模型对官方原题普遍自称熟悉（29/30），但精确出处记忆只出现在入门~基础经典题"
      "（Theatre Square、71A、719A、1730A、ABC300C 等），中等以上难度未观察到背题式出处记忆。"
      "出处命中组与未命中组在 t0 评测的答案正确率无显著差异，未观察到记忆显著抬高成绩。"
      "反例 `C2149` 记得出处（568A）但正式评测仍答错，说明记忆存在不等于解题能力。"
      "局限：无法实证训练语料，行为探测有假阴假阳，且命中集中于超经典题，暴露的威胁度低。"
      "方法全文见附录 D。\n")


def _emit_task_mapping(w) -> None:
    """§1.2 任务要求 → 本系统对应 → 落点（供评审逐条核对）。"""
    w("\n### 1.2 与任务要求的逐条对照\n")
    w("\n| 任务要求 | 本系统的对应 | 落点 |")
    w("|---|---|---|")
    w("| 题集要有标准答案、可自动校验、分难度、说明来源 | "
      "每题含 AC 参考解 + 测试用例期望输出（公开 + 隐藏，多解走 SPJ）；"
      "difficulty 双轨分层（平台官方分 + Hy3 多专家评审） | "
      "`data/questions/*.jsonl`；分层方法见附录 A |")
    w("| 过程正确性判定、错误定位、错误归类、\"答案对但过程不成立\"识别 | "
      "verdict 四值；findings 带 `step_id`；10 类错误类型；SILENT_FAILURE | "
      "本报告 §3 / §7；判定方法见附录 B |")
    w("| 实现手段：规则校验、分步 LLM 审查、沙盒、多视角复核 | "
      "`static_check`（复杂度/死循环/递归）；V1+V2 两视角；Python/C++ 沙盒；"
      "ARBITER 总仲裁 | 附录 B；代码 `src/rex/` |")
    w("| 定位准确率（答案错样本）与误报率（答案对样本） | "
      "答案错样本 29 条全量人工复核，定位命中 28/29 = 96.6%；"
      "答案对且判有错 19 条三层复核 | 本报告 §6（48 条全抽） |")
    w("| 分析报告：设计依据、错误分类、典型案例、能力边界 | "
      "本报告 §1–§8，附录 A–D 为四份方法文档全文 | `reports/REPORT.md` |")


def _emit_limits(w) -> None:
    """§9 局限与待办。"""
    w("## 9. 局限与待办")
    w("\n**已识别的局限**\n")
    w("\n- 污染分析只做到行为层：训练语料无法实证（§1.1、附录 D）；行为探测本身有假阴假阳，"
      "30 题样本量小，6 条出处命中样本与正式评测的对照还比较粗。")
    w("- 漏检侧没有数据：分层抽检里\"答案对且判 CORRECT\"这一层的配额被两个关键层占满，"
      "抽不到，因此给不出漏检率。")
    w("- 抽检是单标注者，未做标注一致性（双盲复核）。")
    w("- hidden 边界用例多为按题面手工设计，\"输入是否满足题面约束\"是结构性局限，"
      "无法靠生成时小心解决，目前靠流水线核对兜底（附录 B.4.4）。")
    w("- 抽检样本取自补齐 hidden 用例之前的基线，其中 1 条（C2063）在补齐后答案判定发生变化"
      "（§6 已说明）；若要严格对齐，需按当前基线重新分层抽样。")
    w("")
    w("\n**待办**\n")
    w("\n- 污染：把 6 条出处命中样本与正式评测做更细的对照；如条件允许，补训练语料层面的旁证。")
    w("- 抽检：补\"答案对且判 CORRECT\"一层的抽样以给出漏检率；引入第二标注者做一致性复核。")
    w("- 复现：记录 model / reasoning / 日期（当前未锁版本号）。")
    w("- 基线：按补齐 hidden 后的当前基线重新分层抽样，使抽检口径与全量口径一致。")
    w("")


# 语义档位：diff_score 0-100 绝对刻度（与打分 prompt 的语义锚一致）。
# 每档是固定分数区间（非样本均分），保证跨数据集可比、分数语义不丢失。
SEMANTIC_TIERS = [
    ("入门~一眼题", 0, 20),   # 5-15: 直接模拟/公式
    ("基础~套路", 20, 40),    # 20-35: 常见套路（前缀和/二分/简单DP）
    ("中等", 40, 60),          # 40-55: 综合思维中难题
    ("难~极高难", 60, 100),    # 60+: 复杂思维/构造/深实现（含 80+ 极高档，
    #                            因 80+ 样本仅个位数，与 [60,80) 合并展示）
]


def unified_tier_table(evals: list[EvalRecord], qmap: dict) -> list[dict]:
    """按 diff_score 的 0-100 绝对语义刻度切档，逐档统计答案率/过程率/Wilson。

    切档区间固定（0-20/20-40/40-60/60-80/80-100），不做样本均分——
    保持与打分 prompt 语义锚一致，跨数据集可比。
    """
    scored = []
    for r in evals:
        if r.source != "run-eval":
            continue
        ds_ = _diff_score_of(r, qmap)
        if ds_ is not None:
            scored.append((ds_, r))
    if not scored:
        return []
    rows = []
    for name, lo, hi in SEMANTIC_TIERS:
        recs = [r for d, r in scored if lo <= d < hi]
        if not recs:
            rows.append({"name": name, "ds_lo": lo, "ds_hi": hi,
                         "n": 0, "answer": None, "process": None,
                         "ci_low": None, "ci_high": None})
            continue
        ans = sum(1 for r in recs if r.answer_correct is True)
        proc = sum(1 for r in recs
                   if r.verification.verdict.value == "CORRECT")
        lo_w, hi_w = wilson_interval(proc, len(recs))
        rows.append({
            "name": name, "ds_lo": lo, "ds_hi": hi, "n": len(recs),
            "answer": ans / len(recs), "process": proc / len(recs),
            "ci_low": lo_w, "ci_high": hi_w,
        })
    return rows


def _band_stats(recs: list[tuple[float, EvalRecord]]) -> dict:
    """给定 (diff_score, EvalRecord) 列表，聚合答案率/过程率（含空样本）。"""
    if not recs:
        return {"n": 0, "answer": None, "process": None,
                "ci_low": None, "ci_high": None}
    ans = sum(1 for _, r in recs if r.answer_correct is True)
    proc = sum(1 for _, r in recs
               if r.verification.verdict.value == "CORRECT")
    lo_w, hi_w = wilson_interval(proc, len(recs))
    return {"n": len(recs), "answer": ans / len(recs), "process": proc / len(recs),
            "ci_low": lo_w, "ci_high": hi_w}


def merged_high_stats(scored: list[tuple[float, EvalRecord]], cut: float = 60.0) -> dict:
    """把 diff_score >= cut 的全部样本合并统计（高端档样本不足时的合并读数）。

    语义：五档结构中难档与极高难档样本偏少时，单独一行分档统计置信度有限，
    故合并为"高难段"给出聚合读数，作为高端能力的保守估计。
    """
    hi = [(d, r) for d, r in scored if d >= cut]
    return _band_stats(hi)


def _emit_appendix(w, path: Path, letter: str, title: str, intro: str) -> None:
    """把方法文档全文并入报告附录：去掉原标题行，## N. → ### X.N，### N.M → #### X.N.M。"""
    if not path.exists():
        return
    w(f"\n---\n\n# 附录 {letter}：{title}\n")
    w(f"\n{intro}\n")
    out_lines: list[str] = []
    for ln in path.read_text(encoding="utf-8").split("\n"):
        if ln.startswith("# "):
            continue
        mm = re.match(r"^## (\d+)\.\s*(.*)$", ln)
        if mm:
            out_lines.append(f"### {letter}.{mm.group(1)} {mm.group(2)}")
            continue
        mf = re.match(r"^## (附.*)$", ln)
        if mf:
            out_lines.append(f"### {letter}.{mf.group(1)}")
            continue
        md = re.match(r"^### (\d+)\.(\d+)\s*(.*)$", ln)
        if md:
            out_lines.append(f"#### {letter}.{md.group(1)}.{md.group(2)} {md.group(3)}")
            continue
        out_lines.append(ln)
    w("\n".join(out_lines).rstrip())
    w("\n")


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

    L: list[str] = []
    w = L.append
    w("# HY3Coder 分析报告")
    w(f"\n> 生成时间：{datetime.now():%Y-%m-%d %H:%M} ｜ 数据：`data/outputs/`（eval/refine 严格分离）\n")

    # ---- 1. 总览 ----
    w("## 1. 评估总览")
    if not evals:
        w("\n_暂无可评估数据，先运行 `run-eval`。_\n")
        return "\n".join(L)
    minor_on = cfg.minor_as_error  # env REX_MINOR_AS_ERROR 一键切换主/副口径
    m = compute_metrics(evals, minor_as_error=minor_on)
    m_main = compute_metrics(evals)  # 主口径参考（fatal-only）
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 评估样本数 | {m.n} |")
    w(f"| 答案准确率 | {pct(m.answer_accuracy)} |")
    # 过程正确率：当前口径 + 主口径参考（说明 minor 剥离影响）
    cal = "（副口径：minor 计入过程错）" if minor_on else "（主口径：仅 fatal 计入过程错）"
    w(f"| 过程正确率{cal} | {pct(m.process_correctness)} |")
    if m_main.process_correctness != m.process_correctness:
        w(f"| 过程正确率·主口径参考 | {pct(m_main.process_correctness)} "
          "（fatal-only，minor 不计） |")
    # minor 统计去向（见 DESIGN §9.1）：CORRECT 且带 minor findings = 仅 minor 记录样本
    # （主口径计过程正确；副口径 minor_as_error 计过程错）。
    minor_only = sum(1 for r in evals
                     if r.verification.verdict.value == "CORRECT"
                     and r.verification.findings)
    w(f"| 仅 minor 记录样本 | {minor_only}（主口径计过程正确 / 副口径计过程错） |")
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
    w("\n**基线修订说明（2026-09-10 补充 hidden）**：为补齐原先缺隐藏用例的题目"
      "（ABC 13 题 + CF 129 题），按题面约束补充了合法边界 hidden 用例；"
      "用同一次求解的模型代码在新用例上重跑，仅**答案对错**受影响（过程评估的推理链未变，"
      "不重跑 LLM 审查，只按流水线既有的确定性规则同步 `verdict` 一致性）。实测 "
      "**2 题答案由对转错**：`A1169`（abc383_e，原判 CORRECT，verifier 未发现该边界缺陷 "
      "→ 属评估器漏检，verdict 修正为 ANSWER_INCORRECT）、`C2063`（cf1868c，原判 "
      "SILENT_FAILURE，复杂度 fatal 成立且答案实际也错 → 修正为 PROCESS_INCORRECT）。"
      "表中数字为本修订后口径（补充前为 90.5% / 84.7%）；§2 分档/分层表、§3 分类统计、"
      "§6 人工抽检与 §8 算法类别细表均已按本修订重算。\n")
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

    _emit_contamination(w, evals)
    _emit_task_mapping(w)

    # ---- 2. 分层退化（平台难度轴）----
    w("## 2. 分层退化分析")
    w("\n### 2.1 平台难度轴（rating/difficulty 校正后 basic/medium/hard）\n")
    w("\n| 难度 | 样本 | 答案准确率 | 过程正确率 |")
    w("|---|---|---|---|")
    for tier, t in sorted(m.per_tier.items()):
        w(f"| {tier} | {t.n} | {pct(t.answer_accuracy)} | {pct(t.process_correctness)} |")
    w("")

    # ---- 2b. 统一难度轴（diff_score 五分位，跨平台可比）----
    w("\n### 2.2 统一难度轴（Hy3 多专家评审 diff_score，0-100 语义档跨平台可比）\n")
    ut = unified_tier_table(evals, qmap)
    if ut:
        w("\n难度分 `diff_score` 由 Hy3 三专家盲打加仲裁给出（0-100，与平台无关），"
          "见 §A 方法与验证。切档按绝对语义刻度（0-20 入门/20-40 基础套路/"
          "40-60 中等/60-100 难~极高难），与打分语义锚一致，"
          "不做样本均分，保证档位含义跨数据集稳定。\n")
        w("\n| 语义档 | diff_score 区间 | 样本 | 答案准确率 | 过程正确率 | 95% CI |")
        w("|---|---|---|---|---|---|")
        for row in ut:
            w(f"| {row['name']} | [{row['ds_lo']},{row['ds_hi']}) | {row['n']} | "
              f"{pct(row['answer'])} | {pct(row['process'])} | "
              f"{'[' + f'{row['ci_low'] * 100:.1f}%, {row['ci_high'] * 100:.1f}%]' if row['ci_low'] is not None else '—'} |")
        # 临界点判定：过程正确率首次显著下降处（跳过空档）
        filled = [r for r in ut if r["n"] > 0]
        procs = [r["process"] for r in filled]
        drop = None
        for i in range(1, len(procs)):
            if procs[i - 1] - procs[i] >= 0.08:
                drop = i
                break
        if procs:
            first, last = filled[0], filled[-1]
            w("\n**临界点判定**：过程正确率随统一难度语义档下降"
              f"（{first['name']} {pct(first['process'])} → "
              f"{last['name']} {pct(last['process'])}）。")
            if drop:
                w(f"首次显著跌落（≥8pp）出现在**{filled[drop]['name']}**"
                  f"（diff_score ≥ {filled[drop]['ds_lo']}）——"
                  "模型过程能力在该难度区间开始明显失守。")
            else:
                w("未观察到 ≥8pp 的显著单档跌落，能力随难度平缓退化。")
        # 高难段小样本注记：diff_score≥80 的极高档仅个位数样本（0.9/t0 两版
        # 该子档分别为 3/5 与 5/5，波动大），表中与 [60,80) 合并为一行解读。
        n_hi80 = sum(1 for r in evals
                     if r.source == "run-eval"
                     and (_diff_score_of(r, qmap) or 0) >= 80)
        hi_n = sum(1 for r in evals
                   if r.source == "run-eval"
                   and (_diff_score_of(r, qmap) or 0) >= 60)
        if 0 < n_hi80 < 10:
            w(f"\ndiff_score≥80 的极高档仅 {n_hi80} 题（[60,100) 共 {hi_n} 题），"
              f"样本太小——temp0.9 与 temperature=0 两次求解在该子档答案分别为 3/5 与 5/5，"
              "读数被小样本支配，故并入「难~极高难」一行解读，不作单独能力结论；"
              "临界点结论限定在入门~中等区间。")
        w("\n![fig1](figures/fig1_diff_tiers.png)")
        _crit = filled[drop] if drop else filled[-1]
        w(f"\n**Fig. 1** 统一难度分档下答案准确率（实线）与过程正确率（虚线）随 diff_score 的退化。"
          f"高难段 [60,100) 含 {hi_n} 题（80+ 的 {n_hi80} 题并入）；"
          f"过程正确率自{_crit['name']}档（{pct(_crit['process'])}）起显著跌落，"
          "是高难能力边界的第一条证据线。\n")
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
    w("\n![fig3](figures/fig3_error_types.png)")
    w("\n**Fig. 2** 过程错误类型分布（占全部已报告错误的比例，条形末端给出条数与占比）。"
      "逻辑缺陷与实现层错误（other/复杂度）合计过半，指向实现严谨性与建模正确性。\n")
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

    # ---- 5. 修正闭环（ReAct 前后对比）----
    w("## 5. 修正闭环（ReAct 前后对比）")
    # 5.1 答案错样本 ReAct（真实度补偿，独立文件；独立于 eval 指标）
    refine_wrong: list[dict] = []
    _rw_path = ROOT / "data" / "outputs" / "refine_wrong_t0.jsonl"
    if _rw_path.exists():
        for _line in _rw_path.open(encoding="utf-8"):
            if _line.strip():
                refine_wrong.append(json.loads(_line))
    if refine_wrong:
        _emit_refine_wrong(w, refine_wrong, qmap)
    # 5.2 通用 refine（正式 refine 主源，与 eval 严格分离）
    if refines:
        rc = refine_comparison(refines)
        w("\n### 5.2 通用 refine（正式 refine 主源）\n")
        w("| 指标 | 数值 |")
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
    elif not refine_wrong:
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
            # 三层复核分布（针对系统 fatal/minor 分级是否属实）
            w(f"| 三层复核 · 完全相符（分级正确） | {am.match_n} |")
            if am.level_mismatch_n:
                w(f"| 三层复核 · 层次不符（fatal/minor 打反） | {am.level_mismatch_n} |")
            if am.fp_human_n:
                w(f"| 三层复核 · 完全不符（系统误报） | {am.fp_human_n} |")
            # 误报率给区间：下界=仅完全不符，上界=含层次不符（与副/主口径对应）
            w(f"| 误报率（判过程有错 {am.fp_n}） | "
              f"{pct(am.false_positive_rate_strict)}（仅完全不符）～ "
              f"{pct(am.false_positive_rate)}（含层次不符） |")
        w("")
        w("口径：定位准确率的分母是答案错误样本（用标准答案判定），误报率的分母是答案正确"
          "样本中被评估器判为过程有错者（经人工抽检确认）。三层复核针对系统对 fatal/minor "
          "的分级是否属实：完全相符即分级正确；层次不符即分级打反（系统把 minor 判成 "
          "fatal，属误报侧）；完全不符即系统认为有错而实际过程正确。误报率区间取两个端点："
          "仅完全不符（下界，minor 也算过程错）到含层次不符（上界，minor 不算过程错）。\n")
        w(f"\n**层次基线**：本节按**当前**（2026-09-10 补充 hidden 后）t0 口径计——"
          f"答案错误 {am.localization_n} 条、答案正确但被判过程有错（误报率分母）"
          f"{am.fp_n} 条。补充前（2026-09-09 抽检当时）为 **28 / 20**，"
          "定位 27/28 = 96.4%、三层复核 match 18。这一条之差来自被抽检的 `C2063`："
          "补充 hidden 后其答案由对转错、verdict 由 SILENT_FAILURE 修正为 "
          "PROCESS_INCORRECT（见 §1 基线修订说明），故从误报率分母移入定位分母，"
          "且系统对其复杂度缺陷的定位经人工复核为命中。\n")
    else:
        w(f"\n_暂无抽检标注，运行 `python -m src.cli audit --results {ds.evals_path(ROOT, next(d for d in ds.active_datasets() if d.evals))}` 生成模板。_\n")

    # ---- 7. 真实评测检出的 SILENT_FAILURE ----
    # 直接从正式评测明细统计（golden 独立留档文件仅本地保留，不随仓库交付）
    sil = [r for r in evals if r.verification.verdict == Verdict.SILENT_FAILURE]
    w("## 7. 真实评测检出的 SILENT_FAILURE 样本")
    w(f"\ntemperature=0 全量评测（{len(evals)} 题）共检出 `SILENT_FAILURE` {len(sil)} 条"
      f"（{pct(len(sil) / len(evals) if evals else 0)}），即答案在公开+隐藏用例上全部通过、"
      "但 verifier 判定推理链存在 fatal 缺陷的样本。这 "
      f"{len(sil)} 条全部落在人工抽检的样本内，fatal 分级经复核全部属实（见第 6 节）。"
      "逐题的完整求解过程与代码、findings 与沙盒事实见 "
      "`data/outputs/eval_abc_selfbuilt_t0.jsonl` 与 `eval_cf_selfbuilt_t0.jsonl`，"
      "不在此处重复粘贴。\n")
    w("| 题目 | 平台 | 难度 | 致命定位（步骤 · 类型） |")
    w("|---|---|---|---|")
    for r in sorted(sil, key=lambda x: x.question_id):
        pos = "、".join(
            f"step{f.step_id} {TYPE_CN.get(f.error_type.value, f.error_type.value)}"
            for f in r.verification.findings
            if f.severity == ErrorSeverity.FATAL
        )
        plat = "ABC" if r.question_id.startswith("A") else "CF"
        w(f"| `{r.question_id}` | {plat} | {r.difficulty.value} | {pos or '—'} |")
    w("")
    w("\n典型形态有三类：声明复杂度与实现不符（剪枝/上界失效、最坏情形退化）、"
      "关键引理（贪心最优性、博弈必胜性、组合计数）缺证明、边界条件遗漏。"
      "这些缺陷公开小样例覆盖不到，只有过程评估能抓住——也正是「只看答案」的评测会系统性漏掉的部分。\n")

    # ---- 8. 能力画像与边界分析 ----
    w("## 8. 能力画像与边界分析")
    _emit_algorithm_profile(w, evals, qmap)
    w("\n### 8.2 弱项清单\n")
    w("\n| 维度 | 观察 | 建议 |")
    w("|---|---|---|")
    w("| 复杂度控制 | 见第 3 节错误类型占比，若 `复杂度不达标`/`边界条件` 占比高，反映算法场景实现严谨性不足 | 增加静态检查前置；对声明复杂度与实现做一致性校验 |")
    w("| 跳步推导 | 算法场景 `跳步推导` 高发说明步骤颗粒度过粗 | 验证 prompt 强化逐步自含性要求 |")
    w("| 沉默失败 | golden 检出率与抽检误报率联动监控 | 高误报时收紧定位条件，低检出时增强回溯审查 |")
    w("| 分层退化 | 平台难度轴见 2.1；统一难度轴见 2.2（临界点 = 首次 ≥8pp 跌落的 diff_score 档） | 对临界点之上补充针对性用例 |")
    w("")

    _emit_limits(w)
    w("---")
    w("\n_数据纯净性说明：以上全部指标仅基于 eval 模式结果；refine 数据单独用于第 5 节对比，不混入评估指标。_\n")

    # ---- 附录 A：评测集构造与统一难度分层方法 ----
    method_path = ROOT / "reports" / "DIFFICULTY_SCORING_METHOD.md"
    if method_path.exists():
        w("\n---\n\n# 附录 A：评测集构造与统一难度分层方法\n")
        w("\n以下为评测题集构建与统一难度分层（Hy3 多专家评审工作流）的方法说明，"
          "源自 `reports/DIFFICULTY_SCORING_METHOD.md`。\n")
        body = method_path.read_text(encoding="utf-8")
        # 去掉原标题行（避免与附录标题重复），并把方法文档子标题 ## N 降为 ### A.N
        lines_ = body.split("\n")
        out_lines: list[str] = []
        for ln in lines_:
            if ln.startswith("# "):
                continue
            mm = re.match(r"^## (\d+)\.\s*(.*)$", ln)
            if mm:
                out_lines.append(f"### A.{mm.group(1)} {mm.group(2)}")
                continue
            mf = re.match(r"^## (附.*)$", ln)
            if mf:
                out_lines.append(f"### A.{mf.group(1)}")
                continue
            out_lines.append(ln)
        w("\n".join(out_lines).rstrip())
        w("\n")

    # ---- 附录 B：过程评估方法与新旧版本对比 ----
    pe_path = ROOT / "reports" / "PROCESS_EVAL_METHOD.md"
    if pe_path.exists():
        w("\n---\n\n# 附录 B：过程评估方法与新旧版本对比\n")
        w("\n以下为过程评估器的判定方法说明（severity 分层、重建测试、程序化一致性裁决、"
          "静态规则校验补盲），源自 `reports/PROCESS_EVAL_METHOD.md`（2026-09-09 更新定稿）。\n")
        w("\n与旧版评估器的对比：\n")
        w("- 旧版（2026-09-03 定稿，双视角 LLM 审查加仲裁、无 severity）：任何 finding "
          "都驱动\u201c过程有错\u201d，误报率被结构性推高；verdict 无程序化兜底，出现漏检"
          "（曾修复\u201c答案错却判 CORRECT\u201d的漏检）；规则校验仅支持 "
          "Python，CF/ABC 主场景（C++）全部失效。旧版抽检产物：`data/outputs/audit_review.md`"
          "（27 题模板）、`data/outputs/audit_records_full.jsonl`（40 条回填，双视角口径）。\n")
        w("- 本版（2026-09-07 severity v1）：在相同判定标准下对难题区间 28 条 "
          "re-verify，10 条判定变化——误报剥离 2 条、漏检补抓 3 条（C2084/C2102/C2119，"
          "人工核验全为真 fatal）、语义细化 5 条；小样本误报率 0/4。"
          "说明 severity 版并非靠放宽判定压误报，而是在同一标准下更精确。\n")
        w("- **全量人工抽检**（本报告第 6 节，温度 0 全量复跑版，2026-09-09 定稿）：48 条全部"
          "回填——答案错误样本 29 条定位准确率 96.6%（唯一 miss 为 C2077，根因步骤与系统定位"
          "不一致）；误报率 5.3%（仅完全不符）～10.5%（含层次不符），三层复核 match 17、"
          "level_mismatch 1（C2104，推导缺陷被步骤 5 自纠仍判 fatal）、fp 1（A1124，overflow"
          "指控在合法输入域不可达，沙盒 20% 失败源于违反 `N≠M` 约束的非法 hidden 用例，已修题库并"
          "留档，详见下方 B.4.3）。此前 6 条 fatal/minor 争议（C2029/C2062/C2094/C2095 维持 "
          "fatal、C2118/C2140 判 minor）裁决结果已并入本版分层。\n")
        body = pe_path.read_text(encoding="utf-8")
        lines_ = body.split("\n")
        out_lines: list[str] = []
        for ln in lines_:
            if ln.startswith("# "):
                continue
            mm = re.match(r"^## (\d+)\.\s*(.*)$", ln)
            if mm:
                out_lines.append(f"### B.{mm.group(1)} {mm.group(2)}")
                continue
            mf = re.match(r"^## (附.*)$", ln)
            if mf:
                out_lines.append(f"### B.{mf.group(1)}")
                continue
            md = re.match(r"^### (\d+)\.(\d+)\s*(.*)$", ln)
            if md:
                out_lines.append(f"#### B.{md.group(1)}.{md.group(2)} {md.group(3)}")
                continue
            out_lines.append(ln)
        w("\n".join(out_lines).rstrip())
        w("\n")

    # ---- 附录 C：ReAct 自我修正闭环方法 ----
    _emit_appendix(w, ROOT / "reports" / "REACT_METHOD.md", "C",
                   "ReAct 自我修正闭环方法",
                   "以下为过程评估结果回流求解端的闭环方法说明（fatal 驱动修订指令、逐轮全量重写并"
                   "独立重验证、收敛与停止判据、评测与修正数据严格隔离），"
                   "源自 `reports/REACT_METHOD.md`。")
    # ---- 附录 D：数据集记忆暴露（contamination）检测方法 ----
    _emit_appendix(w, ROOT / "reports" / "CONTAMINATION_METHOD.md", "D",
                   "数据集记忆暴露（contamination）检测方法",
                   "以下为记忆暴露行为探测的方法与结果全文（分层抽样、两个 probe 的协议、"
                   "两级暴露判定、与正式评测的交叉读数），源自 `reports/CONTAMINATION_METHOD.md`。")

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
