# -*- coding: utf-8 -*-
"""生成 REPORT 的科研级统计图（与报告同源数据、同口径）。

规范（paper-figure）：Times New Roman 统一字体；无图内标题；clean axes
（隐藏上/右边框、ticks 向外）；300 dpi；同一组序列跨图用同一颜色
（答案率 #0072B2 / 过程率 #E69F00）；柱状图在柱上/末端标数值；折线图用
不同 marker/linestyle 与图例区分；标签不重叠。

用法：
    python scripts/make_report_figs.py          # 全量生成
    python scripts/make_report_figs.py --only fig1   # 只出某张
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex.metrics.compute import compute_metrics  # noqa: E402

# ---- 全局科研风格 ----
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.edgecolor": "black",
    "axes.linewidth": 0.8,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

ANS_C = "#0072B2"   # 答案准确率
PROC_C = "#E69F00"  # 过程正确率
FIG_DIR = ROOT / "reports" / "figures"
TYPE_CN = {
    "logic": "logic", "other": "other", "complexity": "complexity",
    "concept": "concept", "calculation": "calculation",
    "missing_condition": "missing condition", "jump": "jump",
    "boundary": "boundary", "misread": "misread", "format": "format",
}


def _style_ax(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(direction="out", length=3, colors="black")


def _load():
    qmap = {}
    for f in ("abc_selfbuilt.jsonl", "cf_selfbuilt.jsonl"):
        for line in (ROOT / "data" / "questions" / f).open(encoding="utf-8"):
            if line.strip():
                q = json.loads(line)
                qmap[q["id"]] = q
    evs = []
    for f in ("eval_abc_selfbuilt_t0.jsonl", "eval_cf_selfbuilt_t0.jsonl"):
        for line in (ROOT / "data" / "outputs" / f).open(encoding="utf-8"):
            if line.strip():
                evs.append(json.loads(line))
    refine = []
    p = ROOT / "data" / "outputs" / "refine_wrong_t0.jsonl"
    if p.exists():
        for line in p.open(encoding="utf-8"):
            if line.strip():
                refine.append(json.loads(line))
    return qmap, evs, refine


def _diff_tier_stats(evs, qmap):
    """统一难度档 [0,20)[20,40)[40,60)[60,100) 答案/过程率。"""
    bands = [("Intro\n(n=79)", 0, 20), ("Basic\n(n=171)", 20, 40),
             ("Mid\n(n=74)", 40, 60), ("Hard\n(n=35)", 60, 100)]
    out = []
    for name, lo, hi in bands:
        recs = []
        for o in evs:
            q = qmap.get(o["question_id"])
            ds = (q.get("metadata") or {}).get("diff_score") if q else None
            if ds is not None and lo <= ds < hi:
                recs.append(o)
        ans = sum(1 for r in recs if r.get("answer_correct") is True) / len(recs) if recs else 0
        proc = sum(1 for r in recs
                   if (r.get("verification") or {}).get("verdict") == "CORRECT") / len(recs) if recs else 0
        out.append((name.split("\n")[0], ans, proc, len(recs)))
    return out


def _alg_class_stats(evs, qmap):
    by = {}
    for o in evs:
        q = qmap.get(o["question_id"])
        tags = ((q.get("metadata") or {}).get("alg_classes") or []) if q else []
        for t in tags:
            by.setdefault(t, []).append(o)
    rows = []
    for cls, recs in by.items():
        n = len(recs)
        rows.append((cls, n,
                     sum(1 for r in recs if r.get("answer_correct") is True) / n,
                     sum(1 for r in recs if (r.get("verification") or {}).get("verdict") == "CORRECT") / n))
    rows.sort(key=lambda x: x[3])
    return rows


def fig1(evs, qmap):
    data = _diff_tier_stats(evs, qmap)
    names = [d[0] for d in data]
    n_txt = [d[3] for d in data]
    ans = [d[1] * 100 for d in data]
    proc = [d[2] * 100 for d in data]
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    x = range(len(names))
    ax.plot(x, ans, "-o", color=ANS_C, lw=1.6, ms=4, label="Answer accuracy")
    ax.plot(x, proc, "--s", color=PROC_C, lw=1.6, ms=4, label="Process correctness")
    for xi, (a, p, nn) in enumerate(zip(ans, proc, n_txt)):
        ax.annotate(f"{a:.1f}%", (xi, a), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color=ANS_C)
        ax.annotate(f"{p:.1f}%", (xi, p), textcoords="offset points", xytext=(0, -13),
                    ha="center", fontsize=8, color=PROC_C)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{n}\n(n={nn})" for n, nn in zip(names, n_txt)])
    ax.set_ylim(50, 105)
    ax.set_ylabel("Correctness (%)")
    ax.legend(loc="lower left", frameon=False)
    _style_ax(ax)
    fig.savefig(FIG_DIR / "fig1_diff_tiers.png")
    plt.close(fig)


def fig2(evs, qmap):
    rows = _alg_class_stats(evs, qmap)
    names = [r[0] for r in rows]
    n = [r[1] for r in rows]
    ans = [r[2] * 100 for r in rows]
    proc = [r[3] * 100 for r in rows]
    y = range(len(names))
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    h = 0.34
    b1 = ax.barh([i + h / 2 for i in y], ans, height=h, color=ANS_C, label="Answer accuracy")
    b2 = ax.barh([i - h / 2 for i in y], proc, height=h, color=PROC_C, label="Process correctness")
    for rect, v, lab in [(r2, v2, 0) for r2, v2 in zip(b2, proc)] + \
                        [(r1, v1, 1) for r1, v1 in zip(b1, ans)]:
        ax.text(v + 1.0, rect.get_y() + rect.get_height() / 2, f"{v:.0f}%",
                va="center", fontsize=7.5)
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{nm} (n={nn})" for nm, nn in zip(names, n)])
    ax.set_xlim(0, 110)
    ax.set_xlabel("Correctness (%)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.06),
              ncol=2, frameon=False)
    _style_ax(ax)
    fig.savefig(FIG_DIR / "fig2_alg_classes.png")
    plt.close(fig)


def fig3(evs):
    m = compute_metrics(_as_records(evs))
    dist = sorted(m.error_type_dist.items(), key=lambda x: -x[1])
    total = sum(v for _, v in dist)
    labels = [TYPE_CN.get(k, k) for k, _ in dist]
    vals = [v / total * 100 for _, v in dist]
    counts = [v for _, v in dist]
    y = range(len(labels))
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    bars = ax.barh(list(y), vals, color="#0072B2")
    for rect, v, c in zip(bars, vals, counts):
        ax.text(v + 0.8, rect.get_y() + rect.get_height() / 2,
                f"{v:.1f}%  (n={c})", va="center", fontsize=7.5)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(vals) * 1.35)
    ax.set_xlabel("Share of reported errors (%)")
    _style_ax(ax)
    fig.savefig(FIG_DIR / "fig3_error_types.png")
    plt.close(fig)


def fig4(refine):
    ok = [r for r in refine if not r.get("error") and (r.get("final") or {}).get("answer_correct") is True]
    conv = [r for r in refine if not r.get("error") and r.get("converged")]
    conv_ok = sum(1 for r in conv if (r.get("final") or {}).get("answer_correct") is True)
    conv_no = len(conv) - conv_ok
    noconv = [r for r in refine if not r.get("error") and not r.get("converged")]
    nc_ok = sum(1 for r in noconv if (r.get("final") or {}).get("answer_correct") is True)
    nc_no = len(noconv) - nc_ok
    cats = ["Converged\n& correct", "Converged\n& wrong", "Not converged\n& correct",
            "Not converged\n& wrong"]
    vals = [conv_ok, conv_no, nc_ok, nc_no]
    colors = ["#0072B2", "#D55E00", "#56B4E9", "#999999"]
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    bars = ax.bar(cats, vals, color=colors, width=0.62)
    for rect, v in zip(bars, vals):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 0.3, str(v),
                ha="center", fontsize=9)
    ax.set_ylim(0, max(vals) * 1.32)
    ax.set_ylabel(f"Questions (n = {sum(vals)})")
    _style_ax(ax)
    fig.savefig(FIG_DIR / "fig4_refine_outcome.png")
    plt.close(fig)


def _as_records(evs):
    from rex.models import EvalRecord
    return [EvalRecord.model_validate(o) for o in evs]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="fig1/fig2/fig3/fig4")
    args = ap.parse_args()
    FIG_DIR.mkdir(exist_ok=True)
    qmap, evs, refine = _load()
    jobs = {"fig1": lambda: fig1(evs, qmap),
            "fig2": lambda: fig2(evs, qmap),
            "fig3": lambda: fig3(evs),
            "fig4": lambda: fig4(refine)}
    keys = [args.only] if args.only else list(jobs)
    for k in keys:
        jobs[k]()
        print("fig saved:", FIG_DIR / ("fig" + k[3:] + ".png"))
    print("done")


if __name__ == "__main__":
    main()
