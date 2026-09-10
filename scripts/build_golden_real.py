"""构建 data/golden/golden_real_algorithm.jsonl —— 真实评测中检出的 SILENT_FAILURE 样本库。

样本直接来自正式评测明细：flaw_answer 即该次求解的真实输出（含代码），
findings 来自 verifier 的实际定位，construction_note 记录来源文件/时间戳/沙盒事实。
只选 `verdict == SILENT_FAILURE` 的记录（答案在公开+隐藏用例上全过、但推理链有 fatal 缺陷），
因此在同一批评测数据上重建即可得到与报告 §7 一致的结果。

用法：
    python scripts/build_golden_real.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.models import GoldenSample, QuestionItem  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QUESTION_FILES = (
    ROOT / "data" / "questions" / "abc_selfbuilt.jsonl",
    ROOT / "data" / "questions" / "cf_selfbuilt.jsonl",
)
EVAL_FILES = (
    ROOT / "data" / "outputs" / "eval_abc_selfbuilt_t0.jsonl",
    ROOT / "data" / "outputs" / "eval_cf_selfbuilt_t0.jsonl",
)
OUT = ROOT / "data" / "golden" / "golden_real_algorithm.jsonl"


def _flaw_type(verification: dict) -> str:
    """取首个 fatal finding 的错误类型；无 fatal 时退回首个 finding。"""
    findings = verification.get("findings") or []
    for f in findings:
        if f.get("severity", "fatal") == "fatal":
            return f.get("error_type") or "other"
    return (findings[0].get("error_type") if findings else None) or "other"


def _note(source: str, rec: dict, verification: dict) -> str:
    detail = "; ".join(
        f"step{f.get('step_id')}[{f.get('error_type')}] {f.get('detail', '')[:160]}"
        for f in (verification.get("findings") or [])
    )[:600]
    return (
        f"真实评测检出：{rec.get('created_at')} · 来源 {source} · "
        f"沙盒通过率 {rec.get('test_pass_rate')} · answer_correct=True · "
        f"verifier={verification.get('verdict')} · 缺陷定位: {detail}"
    )


def main() -> None:
    qmap: dict[str, QuestionItem] = {}
    for qf in QUESTION_FILES:
        if not qf.exists():
            continue
        for line in qf.open(encoding="utf-8"):
            if line.strip():
                q = json.loads(line)
                qmap[q["id"]] = QuestionItem.model_validate(q)

    rows: list[GoldenSample] = []
    for ef in EVAL_FILES:
        if not ef.exists():
            print(f"[skip] eval 文件缺失：{ef.name}")
            continue
        for line in ef.open(encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            verification = rec.get("verification") or {}
            if verification.get("verdict") != "SILENT_FAILURE":
                continue
            q = qmap.get(rec["question_id"])
            if q is None:
                print(f"[skip] {rec['question_id']}: 题集里找不到题目")
                continue
            rows.append(GoldenSample(
                question=q,
                flaw_answer=rec["answer"],
                flaw_type=_flaw_type(verification),
                construction_note=_note(ef.name, rec, verification),
            ))

    rows.sort(key=lambda s: s.question.id)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for s in rows:
            fh.write(s.model_dump_json() + "\n")
    print(f"written {len(rows)} -> {OUT}")
    for s in rows:
        print("-", s.question.id, s.question.source_id, s.flaw_type)


if __name__ == "__main__":
    main()
