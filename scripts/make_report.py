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
    w("\n> 对象：temperature=0 正式评测中 `answer_correct=False` 的全部题（34 题）。"
      "与纯文本 refine 不同，每轮反馈 = verifier 审查文本（findings→修订指令，仅 fatal 驱动）"
      "＋**非隐藏样例沙盒执行结果**（失败用例的输入/期望输出/实际输出），作为客观观察补偿"
      "refine 无沙盒的真实度；重验证以 `execution_feedback` 喂给双视角与 ARBITER"
      "（公开样例失败时不得判 CORRECT）。终局以**全部用例（含 hidden）**沙盒复核答案真值。"
      "记录与复现：`data/outputs/refine_wrong_t0.jsonl`、`scripts/run_refine_wrong_t0.py`。\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 修正样本数（全部答案错） | {n} |")
    w(f"| 文本收敛（verdict → CORRECT） | {conv}（{pct(conv / n)}） |")
    w(f"| 最终答案修对（全量含 hidden 沙盒） | {ans_ok}（{pct(ans_ok / n)}） |")
    w("")
    w("**文本收敛 × 沙盒真值四象限**（真收敛 / 边界样本的分界线）：\n")
    w("\n| | 最终答案修对 | 最终仍错 |")
    w("|---|---|---|")
    w(f"| 文本收敛 | {q1}（真收敛） | {q2}（假收敛：hidden 缺陷仍在） |")
    w(f"| 未文本收敛 | {q3}（修对但评估器未认可） | {q4}（未改善） |")
    w("")

    plat = defaultdict(list)
    for r in done:
        plat["ABC" if r.get("question_id", "").startswith("A") else "CF"].append(r)
    w("**按平台**：\n")
    w("\n| 子集 | 样本 | 文本收敛 | 最终修对 |")
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
    w("**按难度**：\n")
    w("\n| 难度 | 样本 | 文本收敛 | 最终修对 |")
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
    w("**修正轮次分布**：" + "，".join(f"{k} 轮 {v} 题" for k, v in sorted(rc.items())) + "\n")

    w("\n> 读数口径：文本收敛与沙盒真值一致才是完全成功；"
      f"{q2} 题文本收敛但 hidden 仍错（假收敛）反映「评估器只能看到公开用例」的固有边界；"
      f"{q3} 题沙盒已修对但评估器未判收敛，是定位/接受滞后的另一侧证据。"
      "该节同时是过程评估定位质量的下游观察面——修正能否收敛、收敛是否对应真值修正，"
      "与第 6 节定位准确率相互印证。\n")

    w("\n**过程性修正记录（2026-09-09）**\n")
    w("- **编译错误反馈管道缺陷与修复**：首轮实现把运行/编译错误截断到 200 字符，"
      "编译器真正的诊断行（如 `shadows a parameter`、`no match for 'operator<'`）被丢在"
      "模板堆栈之外，模型只见 `error: declaration` 无法定位 → C2070/C2082 连续三轮修不好"
      "同一编译错误。本地手动编译确认沙盒判定正确（代码确不可编译）。修复为从完整 stderr"
      "提取含 `error` 的诊断行后，两题均**首轮收敛且最终全量通过**。此记录说明：给求解端的"
      "执行反馈必须保留原始诊断，截断会结构性削弱「真实度补偿」。\n")
    w("- **三轮未收敛样本人工校验**（8 题，逐条核对每轮 findings 与沙盒事实，未发现评估器误报）：\n")
    w("  - 修正能力不足（终局仍错 3 题）：`C2049`（组合计数公式三轮反复换仍错、自测虚报）、"
      "`C2085`（只删最右 vs 删任意位置、输出索引 vs 计数等概念反复错）、"
      "`C2121`（DP 截断/最短结尾维护反复错）。\n")
    w("  - 评估器正确坚持、缺陷真实但公开用例覆盖不到（5 题，终局沙盒虽过不等于满足约束）："
      "`A1071`（代码主循环每轮全表重建、最坏 O(N²)，N=1e6 必 TLE，人工抽查终版代码属实）、"
      "`C2060`（p,q 范围 ±1e18 下小范围枚举无保证、最坏复杂度 4e9 必超时）、"
      "`C2143`（分段公式存在边界反例）、`C2145`（贪心正确性引理被可验证反例击破）、"
      "`C2149`（扫描上界不足，isp[1] 曾误把 1 当素数）。"
      "这类缺陷公开小样例永远触发不了，恰说明过程评估的文本审查不可被沙盒替代。\n")


def _diff_score_of(r: EvalRecord, qmap: dict) -> float | None:
    q = qmap.get(r.question_id)
    if q is None:
        return None
    return (q.metadata or {}).get("diff_score")


def _platform_of(rid: str, qmap: dict) -> str:
    q = qmap.get(rid)
    sid = (q.source_id or "") if q else ""
    return "ABC" if sid.startswith("abc") else "CF"


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
    w("\n> 题集为官方原题镜像，成绩是「能力＋记忆」的上界。本文用行为探测估计记忆暴露："
      "分层抽样 30 题（ABC/CF × basic/medium/hard 每层 5，seed 42），每题两个 probe——"
      "出处召回（是否记得竞赛/题号）＋解法盲答；判定见 `reports/CONTAMINATION_METHOD.md`，"
      "原始数据 `data/outputs/contamination_probe.jsonl`。\n")
    w("\n| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 探测样本 | {n} |")
    w(f"| 自称见过（P1=seen） | {seen}（{pct(seen / n)}）——迎合偏差高，不作暴露证据 |")
    w(f"| 出处精确命中（强证据） | {len(hits)}（{pct(len(hits) / n)}，95% CI [{lo * 100:.0f}%, {hi * 100:.0f}%]） |")
    w(f"| 命中难度分布 | basic {basic} / medium {mid} / hard 0 |")
    if hits:
        w(f"| 命中样本 | {hit_ids} |")
    w("")
    w("**与正式评测交叉（记忆红利近似）**：\n")
    w("\n| 组 | 样本 | t0 答案正确 |")
    w("|---|---|---|")
    w(f"| 出处命中组 | {len(hits)} | {hit_ok}（{pct(hit_ok / len(hits)) if hits else '—'}） |")
    w(f"| 未命中组 | {len(non)} | {non_ok}（{pct(non_ok / len(non)) if non else '—'}） |")
    w("")
    w("\n> 读数口径：① 模型对官方原题普遍自称熟悉（29/30），但精确出处记忆仅出现在"
      "**入门~基础经典题**（Theatre Square、71A、719A、1730A、ABC300C 等），中等以上难度"
      "未观察到背题式出处记忆；② 出处命中组与未命中组在 t0 评测的答案正确率无显著差异，"
      "未观察到记忆显著抬高成绩；③ 反例 `C2149` 记得出处（568A）但正式评测仍答错——"
      "记忆存在不等于解题能力；④ 局限：无法实证训练语料、行为探测有假阴假阳、命中集中于"
      "超经典题所以暴露的“危险度”低。方法全文见 `reports/CONTAMINATION_METHOD.md`。\n")


# 语义档位：diff_score 0-100 绝对刻度（与打分 prompt 的语义锚一致）。
# 每档是固定分数区间（非样本均分），保证跨数据集可比、分数语义不丢失。
SEMANTIC_TIERS = [
    ("入门~一眼题", 0, 20),   # 5-15: 直接模拟/公式
    ("基础~套路", 20, 40),    # 20-35: 常见套路（前缀和/二分/简单DP）
    ("中等", 40, 60),          # 40-55: 综合思维中难题
    ("难", 60, 80),            # 60-75: 复杂思维/构造/深实现
    ("极高难", 80, 100),       # 80+: 罕见思维模型
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
        w("\n> 难度分 `diff_score` 由 Hy3 三专家盲打+仲裁给出（0-100，与平台无关），"
          "见 §A 方法与验证。切档按**绝对语义刻度**（0-20 入门/20-40 基础套路/"
          "40-60 中等/60-80 难/80-100 极高难），与打分语义锚一致——"
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
        # 高端样本不足声明：难档/极高难档样本少时合并叙述（保留五档结构，
        # 高难两档合计作为保守聚合读数，避免单档小样本夸大/缩小结论）
        hi_lo = ut[3]["n"] if len(ut) > 3 else 0   # [60,80)
        hi_hi = ut[4]["n"] if len(ut) > 4 else 0   # [80,100)
        if hi_lo + hi_hi < 60:
            scored_hi = []
            for r in evals:
                if r.source != "run-eval":
                    continue
                ds_ = _diff_score_of(r, qmap)
                if ds_ is not None and ds_ >= 60:
                    scored_hi.append((ds_, r))
            mh = merged_high_stats(scored_hi, cut=60.0)
            hi_txt = (f"{pct(mh['answer'])} / {pct(mh['process'])}"
                      if mh["n"] else "— / —")
            w(f"\n> **高难档合并说明**：五档结构中「难」（[60,80)）仅 {hi_lo} 题、"
              f"「极高难」（[80,100]）仅 {hi_hi} 题——高端两档样本不足，" 
              "单档统计置信度有限。合并为**高难段（[60,100]，共 "
              f"{mh['n']} 题）**读数：答案/过程正确率 {hi_txt}"
              "，作为高端能力的保守聚合估计；临界点分析结论限定在入门~中等区间，"
              "后续可继续补入高 rating 题扩充。")
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
        w("> 口径说明：定位准确率分母为「答案错误」样本（用标准答案判定）；"
          "误报率分母为「答案正确」样本中被评估器判过程有错者（经人工抽检确认）。"
          "三层复核针对系统 fatal/minor 分级是否属实：完全相符=分级正确；"
          "层次不符=分级打反（系统把 minor 判 fatal，属误报侧）；完全不符=系统说有错但"
          "实际过程正确。误报率区间=仅完全不符（下界，minor 也算过程错）～ 含层次不符"
          "（上界，minor 不算过程错）。\n")
    else:
        w(f"\n_暂无抽检标注，运行 `python -m src.cli audit --results {ds.evals_path(ROOT, next(d for d in ds.active_datasets() if d.evals))}` 生成模板。_\n")

    # ---- 7. Golden ----
    # 真实评测检出库（独立文件，见注册中心 golden_real_path）
    golden_real = (load_jsonl(ds.golden_real_path(ROOT), GoldenSample)
                   if ds.golden_real_path(ROOT).exists() else [])
    w("## 7. 真实评测检出的 SILENT_FAILURE 样本留档")
    w(f"\n> 真实 Hy3 评测中 verifier 检出 `SILENT_FAILURE`（{len(golden_real)} 条：答案正确但过程"
      "存在根本缺陷）的样本留档。每条含题目源（contest）、检测时间、定位缺陷与步骤、沙盒通过率；"
      "flaw_answer 为当时模型的真实求解输出（含代码），非人工编造。"
      "检出计数已计入第 1 节判定分布，本节供逐条核验。\n")
    if golden_real:
        for g in golden_real:
            q = g.question
            src_id = q.source_id or "—"
            w(f"- **`{q.id}`**（{q.source} · `{src_id}` · {q.difficulty.value}）")
            w(f"  - 题面：{q.prompt[:160].strip()}…")
            w(f"  - 缺陷类型：{TYPE_CN.get(g.flaw_type.value, g.flaw_type.value)}")
            w(f"  - 来源说明：{g.construction_note}")
            w(f"  - 陷阱步骤数：{len(g.flaw_answer.steps)}（含代码 "
              f"{'✓' if g.flaw_answer.code else '✗'}）")
        w("")
    else:
        w("\n_暂无真实检出的 SILENT_FAILURE 留档。_\n")

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
        w("\n> 过程评估器的判定方法（severity 分层 + 重建测试 + 程序化一致性裁决 + "
          "静态规则校验补盲）全文如下（源自 `reports/PROCESS_EVAL_METHOD.md`，2026-09-09 更新定稿）。\n")
        w("\n**与旧版评估器的对比（增强说服力的关键证据）**：\n")
        w("- **旧版**（2026-09-03 定稿，双视角 LLM 审查 + 仲裁、无 severity）：任何 finding "
          "都驱动“过程有错” → 误报率被结构性推高；verdict 无程序化兜底 → 出现漏检"
          "（曾修复“答案错却判 CORRECT”，见 `docs/IMPL_LOG.md` hard-eval 任务）；规则校验仅支持 "
          "Python，CF/ABC 主场景（C++）全部失效。旧版抽检产物：`data/outputs/audit_review.md`"
          "（27 题模板）、`data/outputs/audit_records_full.jsonl`（40 条回填，双视角口径）。\n")
        w("- **本版**（2026-09-07 severity v1）：在**同一判定标准**下对难题区间 28 条 "
          "re-verify，10 条判定变化——误报剥离 2 条、漏检补抓 3 条（C2084/C2102/C2119，"
          "人工核验全为真 fatal）、语义细化 5 条；小样本误报率 **0/4**。证明 severity 版"
          "不是靠放宽判定压误报，而是同一标准下更精准。\n")
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
