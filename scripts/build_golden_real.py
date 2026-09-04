"""构建 data/golden/golden_real_algorithm.jsonl —— 真实评测中检出的 SILENT_FAILURE 样本。

与 golden_algorithm.jsonl（人工合成陷阱）不同：本库样本来自真实 Hy3 评测，
flaw_answer 即当时模型真实输出（含 code），findings 来自 verifier 实际定位。
每个样本完整记录来源文件/时间戳、陷阱过程、沙盒结果、缺陷定位，便于审计与续补。

用法：
    python scripts/_build_real_golden.py
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.models import GoldenSample, QuestionItem  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QFILE = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"
OUT = ROOT / "data" / "golden" / "golden_real_algorithm.jsonl"

# 目标：qid -> 来源 eval 文件（同题多份记录取 all）
TARGETS = {"A1042": "eval_selfbuilt_all.jsonl", "A1148": "eval_selfbuilt_all.jsonl"}


def main() -> None:
    # 读题目
    qmap = {}
    for l in QFILE.open(encoding="utf-8"):
        if l.strip():
            q = json.loads(l)
            qmap[q["id"]] = QuestionItem.model_validate(q)
    # 读 eval 记录
    recs = {}
    src = ROOT / "data" / "outputs"
    for f in (src / "eval_selfbuilt_all.jsonl").open(encoding="utf-8"):
        if f.strip():
            r = json.loads(f)
            if r.get("question_id") in TARGETS:
                recs[r["question_id"]] = r

    rows = []
    for qid in ("A1042", "A1148"):
        q = qmap.get(qid)
        r = recs.get(qid)
        if q is None or r is None:
            print(f"[skip] {qid}: 题目/记录缺失 q={q is not None} r={r is not None}")
            continue
        v = r["verification"]
        # 真实模型输出 = flaw_answer
        sample = GoldenSample(
            question=q,
            flaw_answer=r["answer"],
            flaw_type=(v["findings"][0]["error_type"] if v.get("findings") else "other"),
            construction_note=(
                f"真实评测检出：{r.get('created_at')} · 来源 eval_selfbuilt_all.jsonl · "
                f"沙盒通过率 {r.get('test_pass_rate')} · answer_correct=True · "
                f"verifier={v.get('verdict')} · 缺陷定位: "
                + "; ".join(
                    f"step{f.get('step_id')}[{f.get('error_type')}] {f.get('detail', '')[:160]}"
                    for f in (v.get('findings') or []))[:600]
            ),
        )
        rows.append(sample)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for s in rows:
            fh.write(s.model_dump_json() + "\n")
    print(f"written {len(rows)} -> {OUT}")
    for s in rows:
        print("-", s.question.id, s.question.source_id, s.flaw_type)


if __name__ == "__main__":
    main()
