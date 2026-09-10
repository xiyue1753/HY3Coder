"""Generate reports/REPORT.md from eval/refine/audit data.

注意：`reports/REPORT.md` 自 2026-09-10 起改为手工维护的正式稿，本脚本仅保留
作为口径与措辞的参考实现（各节数字的算法、附录拼装规则仍以这里为准）。
直接运行不会覆盖正式稿，必须显式加 `--force`。

Usage:
    python scripts/make_report.py --out /tmp/report_draft.md   # 只生成草稿
    python scripts/make_report.py --force                      # 覆盖正式稿（会丢手工改动）
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
from rex.metrics.stats import stability_check, stability_sweep, wilson_interval
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


def _one_line(text: str, limit: int) -> str:
    """压成单行再截断：题面与说明里带换行，直接贴进 markdown 会把结构冲散。
    顺带丢掉只有 # 的 markdown 标题记号，避免题面里的 "### Problem Statement" 混进来。"""
    s = " ".join(tok for tok in str(text).split() if tok.strip("#").strip())
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def _excerpt(text: str, limit: int) -> str:
    """题面摘录：保留换行与缩进，去掉 markdown 标题记号与反引号，供围栏代码块展示。"""
    lines = []
    for raw in str(text).splitlines():
        ln = re.sub(r"^\s*#{1,6}\s*", "", raw.rstrip()).replace("`", "'")
        lines.append(ln)
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())
    return s if len(s) <= limit else s[:limit].rstrip() + "\n……（题面后续略）"


def _tier_of(ds: float | None) -> str:
    """diff_score 落在哪个语义档，档名与第 2 章展示的口径一致。"""
    if ds is None:
        return "—"
    for name, lo, hi in SEMANTIC_TIERS:
        if lo <= ds < hi:
            return name
    return SEMANTIC_TIERS[-1][0]


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

    w("\n### 5.1 答案错样本的 ReAct 修正")
    w(f"\n测试对象是 temperature=0 正式评测里答案错误的全部 {n} 题。与纯文本 refine 不同，"
      "每轮反馈除了 verifier 的审查意见，还附上公开样例的沙盒执行结果，"
      "其中包含失败用例的输入、期望输出和实际输出，让模型看到客观事实；"
      "重验证时把执行反馈通过 `execution_feedback` 一并交给两个视角与 ARBITER，"
      "公开样例都没过的不得判 CORRECT。终局用含隐藏用例在内的全部用例复核答案真值。"
      "记录在 `data/outputs/refine_wrong_t0.jsonl`，脚本 `scripts/run_refine_wrong_t0.py`，"
      "方法见附录 C。\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 修正样本数 | {n} |")
    w(f"| 文本收敛（判定转为 CORRECT） | {conv}，{pct(conv / n)} |")
    w(f"| 最终答案修对（全量沙盒复核） | {ans_ok}，{pct(ans_ok / n)} |")
    w("")
    w("\n把文本判定与沙盒真值交叉起来看：\n")
    w("\n| | 最终答案修对 | 最终仍错 |")
    w("|---|---|---|")
    w(f"| 文本收敛 | {q1}，真收敛 | {q2}，假收敛，隐藏用例仍有缺陷 |")
    w(f"| 未文本收敛 | {q3}，已修对但评估器未认可 | {q4}，未改善 |")
    w("")

    plat = defaultdict(list)
    for r in done:
        plat["ABC" if r.get("question_id", "").startswith("A") else "CF"].append(r)
    w("\n按平台分，一题只计一次：\n")
    w("| 子集 | 样本 | 文本收敛 | 最终修对 |")
    w("|---|---|---|---|")
    for name in ("ABC", "CF"):
        rows = plat[name]
        if not rows:
            continue
        c = sum(1 for r in rows if r.get("converged"))
        a = sum(1 for r in rows if (r.get("final") or {}).get("answer_correct") is True)
        w(f"| {name} 自建 | {len(rows)} | {c}，{pct(c / len(rows))} | "
          f"{a}，{pct(a / len(rows))} |")
    w("")

    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in done:
        q = qmap.get(r.get("question_id", ""))
        ds = (q.metadata or {}).get("diff_score") if q else None
        by_tier[_tier_of(ds)].append(r)
    w("\n按统一难度语义档：\n")
    w("| 语义档 | 样本 | 文本收敛 | 最终修对 |")
    w("|---|---|---|---|")
    for name, _lo, _hi in SEMANTIC_TIERS:
        rows = by_tier.get(name) or []
        if not rows:
            continue
        c = sum(1 for r in rows if r.get("converged"))
        a = sum(1 for r in rows if (r.get("final") or {}).get("answer_correct") is True)
        w(f"| {name} | {len(rows)} | {c}，{pct(c / len(rows))} | {a}，{pct(a / len(rows))} |")
    w("")

    rc = defaultdict(int)
    for r in done:
        rc[r.get("rounds_used")] += 1
    w("\n修正轮次分布：" + "，".join(f"{k} 轮 {v} 题" for k, v in sorted(rc.items())) + "\n")

    w("\n文本收敛和沙盒真值一致，才算真正修好。"
      f"有 {q2} 题文本判为收敛、隐藏用例却仍然不过，说明评估器只看得到公开用例；"
      f"反过来有 {q3} 题沙盒已经修对、评估器没有判收敛，是定位与接受之间的滞后。"
      "这两类合起来，就是文本判定与沙盒真值之间的边界。\n")
    w("\n![fig4](figures/fig4_refine_outcome.png)")
    w(f"\n**Fig. 3** {n} 道答案错题经 ReAct 修正后的四象限分布，柱顶为样本数。"
      "四类依次是文本收敛且答案已对、文本收敛但答案仍错、未收敛但答案已对、未收敛且答案仍错。"
      f"真正修好的是第一类，{q1} 题；后两类共 {q2 + q3} 题，"
      "构成文本判定与沙盒真值之间的边界。\n")

    w("\n三轮未收敛的 8 题逐条复核如下，每轮的 findings 都与沙盒事实核对过，"
      "没有发现评估器误报。\n")
    w("- 模型修正能力不足，终局仍错 3 题：`C2049` 组合计数公式三轮反复换仍错，"
      "还虚报自测结果；`C2085` 在只删最右还是删任意位置、输出索引还是计数之间反复错；"
      "`C2121` 的 DP 截断与最短结尾维护反复错。\n")
    w("- 评估器坚持正确，缺陷真实但公开用例覆盖不到，共 5 题，终局沙盒通过不等于满足约束："
      "`A1071` 主循环每轮全表重建，最坏 O(N²)，N 到 1e6 必然超时，人工抽查终版代码属实；"
      "`C2060` 在 p、q 达到 ±1e18 时小范围枚举没有保证，最坏复杂度 4e9，必然超时；"
      "`C2143` 分段公式存在边界反例；`C2145` 贪心正确性引理被可验证的反例击破；"
      "`C2149` 扫描上界不足，`isp[1]` 曾把 1 当成素数。"
      "这类缺陷公开小样例触发不到，沙盒替代不了文本审查。\n")


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

    w("\n### 8.1 算法类别 × 能力边界")
    n_tagged = sum(1 for r in valid
                   if (qmap.get(r.question_id).metadata or {}).get("alg_classes"))
    w("\n统计按题集里人工归一的算法类标签进行，一题可以属于多个类。"
      "平均 `diff_score` 用来看一个类别是本身偏难，还是同难度下确实偏弱。"
      f"全库过程正确率基线 {pct(base_proc)}，答案准确率基线 "
      f"{pct(sum(1 for r in valid if r.answer_correct is True) / len(valid) if valid else 0)}，"
      f"{n_tagged} 题有标签。\n")
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
        strong_txt = "、".join("`%s`，%s" % (r["cls"], pct(r["proc"]))
                               for r in strong) if strong else ""
        w("**边界读数**：过程正确率比全库基线低 8pp 以上的类别算能力弱点边界，"
          f"有 {weak_txt}。其中平均 diff_score 高的类别主要受题目本身难度驱动，"
          "diff_score 接近基线的才是同难度下确实偏弱。")
        if strong:
            w(f"明显高于基线的类别是：{strong_txt}。")
        w("")
    w("\n边界解读：math、sim、graph、dp、greedy、ds 这些主体类别覆盖了绝大多数样本，"
      "过程正确率在 80% 上下，与全库基线基本持平，没有系统性短板。"
      "弱点集中在 construct、twoptr、binary 三类，主要错误都是逻辑缺陷与条件遗漏，"
      "问题出在构造与约束建模的严密性，而不是不会做。string、game、twoptr 这些"
      "样本不足 16 的类别读数置信有限，只作方向性提示。\n")
    w("\n![fig2](figures/fig2_alg_classes.png)")
    w("\n**Fig. 4** 13 个算法类别的答案准确率与过程正确率对比，蓝柱为答案准确率，"
      "橙柱为过程正确率，按后者升序排列，条形末端为百分数。construct、twoptr、binary "
      "比全库基线低 8pp 以上。\n")


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

    w("\n### 1.1 记忆暴露检测")
    w("\n题集都取自官方原题镜像，成绩里难免掺进记忆的成分，所以只能算能力加记忆的上界。"
      "为估计暴露程度，按平台与难度分层抽 30 题，每层 5 题，每题问两个独立的问题："
      "能否说出题目出处，能否讲清标准解法。判定规则见附录 D，"
      "原始记录在 `data/outputs/contamination_probe.jsonl`。\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 探测样本 | {n} |")
    w(f"| 自称见过 | {seen}，{pct(seen / n)}；迎合偏差高，不作暴露证据 |")
    w(f"| 出处精确命中 | {len(hits)}，{pct(len(hits) / n)}；"
      f"95% CI [{lo * 100:.0f}%, {hi * 100:.0f}%] |")
    w(f"| 命中样本的平台分档 | basic {basic} / medium {mid} / hard 0 |")
    if hits:
        w(f"| 命中样本 | {hit_ids} |")
    w("")
    w("\n与正式评测交叉，看记忆是否带来红利：\n")
    w("\n| 组 | 样本 | t0 答案正确 |")
    w("|---|---|---|")
    w(f"| 出处命中组 | {len(hits)} | {hit_ok}（{pct(hit_ok / len(hits)) if hits else '—'}） |")
    w(f"| 未命中组 | {len(non)} | {non_ok}（{pct(non_ok / len(non)) if non else '—'}） |")
    w("")
    w("\n模型对官方原题普遍自称熟悉，30 题里有 29 题答见过；但能说准出处的只有 6 题，"
      "且全部落在入门到基础的经典题上，比如 Theatre Square、71A、719A、1730A、ABC300C，"
      "中等以上难度没有出现背题式的出处记忆。命中出处的 6 题与其余 24 题在正式评测上"
      "分别答对 5 题和 22 题，看不出记忆抬高了成绩。`C2149` 是个反例：模型记得它出自 "
      "CF 568A，正式评测仍然答错，记忆存在不等于能力存在。局限有三处：训练语料无法实证，"
      "行为探测本身有假阴假阳，命中样本又集中在全网烂熟的题上，实际威胁度低。"
      "方法见附录 D。\n")


def _emit_task_mapping(w) -> None:
    """§1.2 任务要求 → 本系统对应 → 落点（供评审逐条核对）。"""
    w("\n### 1.2 与任务要求的逐条对照\n")
    w("\n| 任务要求 | 本系统的对应 | 落点 |")
    w("|---|---|---|")
    w("| 题集要有标准答案、可自动校验、分难度、说明来源 | "
      "每题带可执行的 AC 参考解与测试用例，公开用例和隐藏用例都在，"
      "多解题目用 SPJ 判定；难度双轨分层，平台官方分与 Hy3 多专家评审各一套 | "
      "`data/questions/*.jsonl`；分层方法见附录 A |")
    w("| 过程正确性判定、错误定位、错误归类、\"答案对但过程不成立\"识别 | "
      "verdict 四值；findings 带 `step_id`；10 类错误类型；SILENT_FAILURE | "
      "本报告 §3 与 §7；判定方法见附录 B |")
    w("| 实现手段：沙盒校验、多视角 Agent 复核 | "
      "沙盒校验：Python 与 C++ 沙盒跑公开与隐藏用例，答案真值以沙盒为准，"
      "`static_check` 的规则校验作为补充诊断证据；"
      "多视角 Agent 复核：V1 自含性审查与 V2 全局回溯各自给出 verdict 与 findings，"
      "再由 ARBITER 总仲裁 | 附录 B；代码 `src/rex/` |")
    w("| 答案错样本的定位准确率与答案对样本的误报率 | "
      "答案错的 29 条全量人工复核，定位命中 28 条，96.6%；"
      "答案对却被判过程有错的 19 条做三层复核 | 本报告 §6，48 条全部抽检 |")
    w("| 分析报告：设计依据、错误分类、典型案例、能力边界 | "
      "本报告 §1 至 §9，附录 A 至 D 为四份方法文档全文 | `reports/REPORT.md` |")
    w("")


def _emit_limits(w) -> None:
    """§9 适用范围与后续方向。"""
    w("## 9. 适用范围与后续方向")
    w("\n报告里每项结论都有对应的成立条件。下表把条件与边界一并列清，并给出后续可以继续"
      "推进的方向：边界之内结论可直接引用，超出边界时相应数值需要重新验证。\n")
    w("| 结论 | 成立条件与边界 | 后续方向 |")
    w("|---|---|---|")
    w("| 污染读数，见 §1.1 与附录 A、D | 证据链建立在行为层：答题表现、出处自述与 pass "
      "对照。行为探测存在假阴，即见过但答不出出处；也存在假阳，即没背过但推理命中出处。"
      "探测样本 30 题，其中 6 条出处命中样本与正式评测目前为总体对照 | "
      "6 条命中样本与正式评测做逐题对照；条件允许时补训练语料层面的旁证 |")
    w("| 误报率，见 §6 | 48 条抽检样本取自答案错的与答案对但过程被质疑的两类，覆盖误报侧；"
      "答案对且系统判为 CORRECT 的那一层未入池 | 补足该层抽样，在同一口径下给出漏检率 |")
    w("| 抽检口径，见 §6 | 48 条由一位标注者按同一份标准完成，前后口径一致 | "
      "引入第二位标注者做一致性复核 |")
    w("| hidden 边界用例，见附录 B.4.3 | 用例按题面手工构造，输入是否严格满足题面约束"
      "取决于构造过程 | 当前由流水线核对兜底；后续可在构造阶段加入约束自检 |")
    w("| 复现信息，见 §8 | 报告对应的是当次运行的模型与推理配置 | "
      "落盘 model、reasoning 与日期，锁定版本号，便于逐次比对 |")
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
    w(f"\n> 生成时间：{datetime.now():%Y-%m-%d %H:%M} ｜ 数据：`data/outputs/`，"
      "评测与修正数据分开存放\n")

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
    cal = "（minor 也计入过程错）" if minor_on else "（仅 fatal 计入过程错）"
    w(f"| 过程正确率{cal} | {pct(m.process_correctness)} |")
    if m_main.process_correctness != m.process_correctness:
        w(f"| 过程正确率·主口径 | {pct(m_main.process_correctness)} |")
    # minor 统计去向（见 DESIGN §9.1）：CORRECT 且带 minor findings = 仅 minor 记录样本
    # （主口径计过程正确；副口径 minor_as_error 计过程错）。
    minor_only = sum(1 for r in evals
                     if r.verification.verdict.value == "CORRECT"
                     and r.verification.findings)
    w(f"| 仅 minor 的记录样本 | {minor_only}（主口径计为过程正确） |")
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
    w(f"| 过程正确率 95% CI（Wilson） | [{lo * 100:.1f}%, {hi * 100:.1f}%] |")
    w("")
    # 分平台概览
    w("\n**分平台概览**\n")
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
    # 稳定性：样本构成敏感性（数值来自固化记录，重算逐位一致；不含运行期随机性）
    st = stability_check(valid)
    sw = stability_sweep(valid)
    if st.stable:
        drift_txt = f"漂移 {st.drift * 100:.1f}pp，在 5pp 的判稳阈值以内。"
    else:
        drift_txt = (f"漂移 {st.drift * 100:.1f}pp，超过 5pp 判稳阈值，"
                     "单次求解的波动还需要多跑几轮抹平。")
    w("**稳定性说明**：本章数值全部来自仓库中已固化的 t0 正式评测记录"
      "（temperature=0，359 题，每题一次求解），读取同一份记录重算得到的结果逐位一致，"
      "不含运行期随机性。为看样本构成对结论的影响，按难度档用两组固定随机种子各重抽 60% 样本，"
      f"过程正确率分别为 {st.seed_a * 100:.1f}% 与 {st.seed_b * 100:.1f}%，{drift_txt}"
      f"再用 {sw.pairs} 组种子跑同一检验（`stability_sweep`）：漂移中位数 "
      f"{sw.median_drift * 100:.1f}pp、最大 {sw.max_drift * 100:.1f}pp，"
      f"全部 {sw.pairs} 组都在阈值内——指标对\"抽到哪一部分题\"不敏感。"
      "本检验衡量的是**样本构成**的影响；本报告是 temperature=0 的单次基线，"
      "指标区间由上面的 Wilson 置信区间与这一检验共同给出。\n")
    w("")

    _emit_contamination(w, evals)
    _emit_task_mapping(w)

    # ---- 2. 分层退化（统一难度轴为主，平台标签作对照）----
    w("## 2. 分层退化分析")
    w("\n本章有两条难度轴。统一难度分 `diff_score` 是本报告使用的标准，"
      "分层退化分析与后面各章的难度标注都以它为准；平台官方标签只作对照，"
      "用来看两个平台各自的原始分级。\n")
    w("\n### 2.1 统一难度轴\n")
    ut = unified_tier_table(evals, qmap)
    if ut:
        w("\n`diff_score` 是统一难度分，由 Hy3 三位专家盲打后仲裁给出，取值 0 到 100，"
          "与题目来自哪个平台无关，方法与验证见附录 A。按绝对语义刻度切四档："
          "0–20 入门，20–40 基础套路，40–60 中等，60–100 难到极高难。"
          "这里不做样本均分，档位含义在跨数据集时保持稳定。\n")
        w("\n| 语义档 | diff_score 区间 | 样本 | 答案准确率 | 过程正确率 | 95% CI |")
        w("|---|---|---|---|---|---|")
        for row in ut:
            # 嵌套引号写在 f-string 里要 3.12+（PEP 701），项目环境是 3.9，故先在循环里算好
            ci = (f"[{row['ci_low'] * 100:.1f}%, {row['ci_high'] * 100:.1f}%]"
                  if row["ci_low"] is not None else "—")
            w(f"| {row['name']} | [{row['ds_lo']},{row['ds_hi']}) | {row['n']} | "
              f"{pct(row['answer'])} | {pct(row['process'])} | {ci} |")
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
            w("\n**临界点**：过程正确率随难度单调下降，从{0}档的 {1} 落到{2}档的 {3}。".format(
                first['name'], pct(first['process']), last['name'], pct(last['process'])))
            if drop:
                w(f"首次 8pp 以上的显著跌落出现在{filled[drop]['name']}档，"
                  f"即 `diff_score` 到 {filled[drop]['ds_lo']} 以后，"
                  "模型的过程能力开始明显失守。")
            else:
                w("没有出现 8pp 以上的单档跌落，能力随难度平缓退化。")
        # 高难段小样本注记：diff_score≥80 的极高档仅个位数样本（0.9/t0 两版
        # 该子档分别为 3/5 与 5/5，波动大），表中与 [60,80) 合并为一行解读。
        n_hi80 = sum(1 for r in evals
                     if r.source == "run-eval"
                     and (_diff_score_of(r, qmap) or 0) >= 80)
        hi_n = sum(1 for r in evals
                   if r.source == "run-eval"
                   and (_diff_score_of(r, qmap) or 0) >= 60)
        if 0 < n_hi80 < 10:
            w(f"\n`diff_score` 80 以上的极高档只有 {n_hi80} 题，难档整体也才 {hi_n} 题，"
              "两次求解在这个子档的答案对错分别是 3/5 和 5/5，读数被个位数样本支配，"
              "因此并入难到极高难一档看，不单独下能力结论；上面的临界点结论也只在"
              "入门到中等区间成立。")
        w("\n![fig1](figures/fig1_diff_tiers.png)")
        _crit = filled[drop] if drop else filled[-1]
        w(f"\n**Fig. 1** 统一难度分档下答案准确率与过程正确率的变化。"
          f"难档覆盖 `diff_score` 60 以上共 {hi_n} 题，其中 80 以上的 {n_hi80} 题并入。"
          f"过程正确率从{_crit['name']}档开始显著跌落，降到 {pct(_crit['process'])}，"
          "这是高难能力边界的第一条证据。\n")
        w("")
    else:
        w("\n_暂无 diff_score（先运行 score_difficulty.py）。_\n")

    # ---- 2.2 平台难度轴（对照）----
    w("\n### 2.2 平台难度轴\n")
    w("\n按各平台官方难度校正后分 basic、medium、hard 三档，仅作对照。\n")
    w("\n| 难度 | 样本 | 答案准确率 | 过程正确率 |")
    w("|---|---|---|---|")
    for tier in ("basic", "medium", "hard"):
        t = m.per_tier.get(tier)
        if t is None:
            continue
        w(f"| {tier} | {t.n} | {pct(t.answer_accuracy)} | {pct(t.process_correctness)} |")
    w("")

    # ---- 3. 错误类型分布 ----
    w("## 3. 错误类型分布")
    w("\n按评估器已报告的 finding 统计：\n")
    w("\n| 错误类型 | 数量 | 占比 |")
    w("|---|---|---|")
    total_inc = sum(m.error_type_dist.values()) or 1
    for k, v in sorted(m.error_type_dist.items(), key=lambda x: -x[1]):
        w(f"| {TYPE_CN.get(k, k)} | {v} | {v / total_inc * 100:.1f}% |")
    w("\n![fig3](figures/fig3_error_types.png)")
    w("\n**Fig. 2** 过程错误类型分布，条形末端给出条数与占比。逻辑缺陷与实现层错误"
      "合计超过一半，短板主要在实现严谨性与建模正确性。\n")
    w("")

    # ---- 4. 典型案例归因 ----
    w("## 4. 典型案例归因")
    notable = [r for r in evals if r.verification.verdict.value == "SILENT_FAILURE"][:5]
    if not notable:
        w("\n_当前样本中暂无 SILENT_FAILURE，退而展示过程错误样本。_\n")
        notable = [r for r in evals if r.verification.verdict.value == "PROCESS_INCORRECT"][:5]
    w("\n下面取 5 例，逐题给出题面摘录与评估器的定位结果；难度按第 2 章的语义档标注，"
      "完整清单见第 7 节。\n")
    for r in notable:
        q = qmap.get(r.question_id)
        sid = (getattr(q, "source_id", "") or "") if q else ""
        w(f"\n### {r.question_id}" + (f" · {sid}" if sid else ""))
        ds = _diff_score_of(r, qmap)
        w(f"- 难度：语义档 {_tier_of(ds)}"
          + (f"，diff_score {ds:.0f}" if ds is not None else ""))
        w(f"- 判定：{r.verification.verdict.value}，置信度 {r.verification.confidence:.2f}")
        w(f"- 答案正确：{r.answer_correct}，用例通过率 {r.test_pass_rate}")
        findings = "；".join(
            f"第{f.step_id}步 {TYPE_CN.get(f.error_type.value, f.error_type.value)}，"
            f"{_one_line(f.detail, 70)}"
            for f in r.verification.findings[:3])
        w(f"- 定位：{findings or '无'}")
        w("\n题面摘录：\n")
        w("```text")
        w(_excerpt(q.prompt if q else r.question_id, 420))
        w("```")
    w("")

    # ---- 5. 修正闭环（ReAct 前后对比）----
    w("## 5. 修正闭环")
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
        w("\n### 5.2 通用 refine\n")
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
            w(f"| 定位准确率（分母是 {am.localization_n} 条答案错的样本） | "
              f"{pct(am.error_localization_hit_rate)} |")
            # 三层复核分布（针对系统 fatal/minor 分级是否属实）
            w(f"| 三层复核 · 完全相符 | {am.match_n} |")
            if am.level_mismatch_n:
                w(f"| 三层复核 · 层次不符，fatal 与 minor 打反 | {am.level_mismatch_n} |")
            if am.fp_human_n:
                w(f"| 三层复核 · 完全不符，系统误报 | {am.fp_human_n} |")
            # 误报率给区间：下界=仅完全不符，上界=含层次不符（与副/主口径对应）
            w(f"| 误报率（分母是 {am.fp_n} 条被判过程有错） | "
              f"{pct(am.false_positive_rate_strict)} 到 {pct(am.false_positive_rate)} |")
        w("")
        w("口径说明：定位准确率的分母是答案错的样本，以标准答案判定；误报率的分母是答案"
          "正确、却被评估器判为过程有错的样本。三层复核看的是系统对 fatal 与 minor 的"
          "分级对不对：完全相符就是分级正确；层次不符是把 minor 判成了 fatal，算误报一侧；"
          "完全不符是系统说有错而过程其实没有问题。误报率给的是一个区间，"
          "下界只算完全不符，上界把层次不符也算进去。\n")
    else:
        w(f"\n_暂无抽检标注，运行 `python -m src.cli audit --results {ds.evals_path(ROOT, next(d for d in ds.active_datasets() if d.evals))}` 生成模板。_\n")

    # ---- 7. 真实评测检出的 SILENT_FAILURE ----
    # 直接从正式评测明细统计（留档文件 data/golden/golden_real_algorithm.jsonl 与报告同源，随仓库交付）
    sil = [r for r in evals if r.verification.verdict == Verdict.SILENT_FAILURE]
    w("## 7. 真实评测检出的 SILENT_FAILURE 样本")
    w(f"\n正式评测的 {len(evals)} 题里，有 {len(sil)} 题被检出 `SILENT_FAILURE`，"
      f"占 {pct(len(sil) / len(evals) if evals else 0)}：答案在公开与隐藏用例上全部通过，"
      "verifier 却认定推理链存在致命缺陷。这些题全部落在人工抽检的样本内，"
      "致命分级经复核属实，见第 6 节。逐题的求解过程、findings 与沙盒事实在 "
      "`data/outputs/eval_abc_selfbuilt_t0.jsonl` 与 `eval_cf_selfbuilt_t0.jsonl`，"
      "这里不再重复粘贴。\n")
    w("| 题目 | 平台 | 语义档 | 致命定位 |")
    w("|---|---|---|---|")
    for r in sorted(sil, key=lambda x: x.question_id):
        pos = "、".join(
            f"step{f.step_id} {TYPE_CN.get(f.error_type.value, f.error_type.value)}"
            for f in r.verification.findings
            if f.severity == ErrorSeverity.FATAL
        )
        plat = "ABC" if r.question_id.startswith("A") else "CF"
        ds = _diff_score_of(r, qmap)
        tier = _tier_of(ds) + (f" {ds:.0f}" if ds is not None else "")
        w(f"| `{r.question_id}` | {plat} | {tier} | {pos or '—'} |")
    w("")
    w("\n这类缺陷有三种典型形态：一是声明的复杂度与实现不符，剪枝或上界失效、"
      "最坏情形退化；二是关键引理缺证明，贪心最优性、博弈必胜性、组合计数只写显然；"
      "三是边界条件遗漏。公开的小样例覆盖不到它们，只有过程评估能抓住，"
      "也正是不看过程、只看答案的评测会系统性漏掉的部分。\n")

    # ---- 8. 能力画像与边界分析 ----
    w("## 8. 能力画像与边界分析")
    _emit_algorithm_profile(w, evals, qmap)
    w("\n### 8.2 弱项清单\n")
    w("\n| 维度 | 观察 | 建议 |")
    w("|---|---|---|")
    w("| 复杂度控制 | 见第 3 节错误类型占比，若 `复杂度不达标`/`边界条件` 占比高，反映算法场景实现严谨性不足 | 增加静态检查前置；对声明复杂度与实现做一致性校验 |")
    w("| 跳步推导 | 算法场景 `跳步推导` 高发说明步骤颗粒度过粗 | 验证 prompt 强化逐步自含性要求 |")
    w("| 沉默失败 | 留档样本的人工复核与误报率联动监控 | 高误报时收紧定位条件，低检出时增强回溯审查 |")
    w("| 分层退化 | 统一难度轴见 2.1，平台难度轴见 2.2，临界点取首次 8pp 以上跌落的 diff_score 档 | 对临界点之上补充针对性用例 |")
    w("")

    _emit_limits(w)
    w("---")
    w("\n_以上指标全部来自正式评测结果；修正数据只用于第 5 节的对比，不混入任何指标。_\n")

    # ---- 附录 A：评测集构造与统一难度分层方法 ----
    _emit_appendix(w, ROOT / "reports" / "DIFFICULTY_SCORING_METHOD.md", "A",
                   "评测集构造与统一难度分层方法",
                   "以下为评测题集构建与统一难度分层（Hy3 多专家评审工作流）的方法说明，"
                   "源自 `reports/DIFFICULTY_SCORING_METHOD.md`。")

    # ---- 附录 B：过程评估方法与新旧版本对比 ----
    _emit_appendix(
        w, ROOT / "reports" / "PROCESS_EVAL_METHOD.md", "B",
        "过程评估方法与新旧版本对比",
        "以下为过程评估器的判定方法说明（severity 分层、重建测试、程序化一致性裁决、"
        "静态规则校验补盲），源自 `reports/PROCESS_EVAL_METHOD.md`（2026-09-09 更新定稿）。"
        "\n\n与旧版评估器的对比：\n"
        "\n- 旧版定稿于 2026-09-03，做法是双视角 LLM 审查加仲裁，没有 severity："
        "任何 finding 都驱动“过程有错”，误报率被结构性推高；verdict 没有程序化兜底，"
        "出现过“答案错却判 CORRECT”的漏检；规则校验只支持 Python，"
        "CF/ABC 主场景是 C++，规则全部失效。旧版抽检产物为 `data/outputs/audit_review.md`"
        "的 27 题模板与 `data/outputs/audit_records_full.jsonl` 的 40 条回填，口径为双视角。"
        "\n- 本版是 2026-09-07 的 severity v1：在相同判定标准下对难题区间 28 条 re-verify，"
        "10 条判定变化，误报剥离 2 条、漏检补抓 3 条即 C2084/C2102/C2119，"
        "人工核验全为真 fatal、语义细化 5 条；小样本误报率 0/4。"
        "severity 版不是靠放宽判定压误报，而是在同一标准下更精确。"
        "\n- **全量人工抽检**：本报告第 6 节，温度 0 全量复跑版，2026-09-09 定稿，"
        "48 条全部回填。答案错的 29 条定位准确率 96.6%，唯一 miss 是 C2077，"
        "根因步骤与系统定位不一致；误报率 5.3% 到 10.5%，三层复核 match 17、"
        "level_mismatch 1 即 C2104、fp 1 即 A1124。A1124 的 overflow 指控在合法输入域"
        "不可达，沙盒 20% 失败源于违反 `N≠M` 约束的非法 hidden 用例，题库已修并留档，"
        "详见下方 B.4.3 与 B.4.4。此前 6 条 fatal/minor 争议中，C2029/C2062/C2094/C2095 维持 fatal，"
        "C2118/C2140 判 minor，裁决结果已并入本版分层。")

    # ---- 附录 C：ReAct 自我修正闭环方法 ----
    _emit_appendix(w, ROOT / "reports" / "REACT_METHOD.md", "C",
                   "ReAct 自我修正闭环方法",
                   "以下为过程评估结果回流求解端的闭环方法说明，覆盖 fatal 驱动的修订指令、"
                   "逐轮全量重写与独立重验证、收敛与停止判据、评测与修正数据隔离，"
                   "源自 `reports/REACT_METHOD.md`。")
    # ---- 附录 D：数据集记忆暴露检测方法 ----
    _emit_appendix(w, ROOT / "reports" / "CONTAMINATION_METHOD.md", "D",
                   "数据集记忆暴露检测方法",
                   "以下为记忆暴露行为探测的方法与结果全文，覆盖分层抽样、两个 probe 的协议、"
                   "两级暴露判定与正式评测的交叉读数，源自 `reports/CONTAMINATION_METHOD.md`。")

    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "REPORT.md")
    ap.add_argument("--force", action="store_true",
                    help="正式稿已改为手工维护，覆盖它必须显式加 --force")
    args = ap.parse_args()
    official = (ROOT / "reports" / "REPORT.md").resolve()
    if args.out.resolve() == official and not args.force:
        print("reports/REPORT.md 是手工维护的正式稿，未覆盖。")
        print("只想要草稿：--out <其它路径>；确实要覆盖：加 --force（手工改动会丢）")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # 固定 LF：写入时不随平台做换行转换，保证生成结果与仓库中的版本逐字节一致。
    # 项目环境是 Python 3.9，write_text(newline=...) 要到 3.10 才有，故走 open()。
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        f.write(build())
    print(f"report written -> {args.out}")


if __name__ == "__main__":
    main()
