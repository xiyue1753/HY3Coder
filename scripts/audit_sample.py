"""人工抽检工具：从评估结果中按「答案正确性 × 判定」分层抽样生成标注模板。

用法:
    python scripts/audit_sample.py --results data/outputs/eval_selfbuilt_hard.jsonl \
        --questions data/questions/abc_selfbuilt.jsonl \
        --sample 35 --out data/outputs/audit_records.jsonl

模板每行一个 AuditRecord（question_id 预填 + 附系统上下文便于人工判断）：
    - verdict_human   : 人工判定（CORRECT/PROCESS_INCORRECT/ANSWER_INCORRECT/SILENT_FAILURE）
    - error_step_id   : 真实错误起始步骤（无则留 null）
    - error_type_human: 真实错误类型（与 ErrorType 枚举一致）
    - is_false_positive: 系统判错但实际正确 → true
    - note            : 说明

生成后可用 --check 校验回填结果是否完整：
    python scripts/audit_sample.py --check data/outputs/audit_records.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.datasets.sampling import audit_records_sample  # noqa: E402
from rex.models import AuditRecord, EvalRecord  # noqa: E402


def load_records(path: Path) -> list[EvalRecord]:
    with path.open(encoding="utf-8") as f:
        return [EvalRecord.model_validate_json(line) for line in f if line.strip()]


def load_questions(path: Path) -> dict[str, dict]:
    qmap: dict[str, dict] = {}
    if path and path.exists():
        for line in path.open(encoding="utf-8"):
            if line.strip():
                q = json.loads(line)
                qmap[q["id"]] = q
    return qmap


def build_template(records: list[EvalRecord], qmap: dict[str, dict],
                   n: int, seed: int = 42) -> list[dict]:
    picked = audit_records_sample(records, n, seed=seed)
    return [_template_for(r, qmap) for r in picked]


def _template_for(r: EvalRecord, qmap: dict[str, dict]) -> dict:
    """构造带系统上下文的人工标注模板（含题目/判定/过程摘要/错误定位）。"""
    q = qmap.get(r.question_id, {})
    v = r.verification
    # 只保留精简上下文，避免模板过大
    steps_short = []
    for s in r.answer.steps:
        content = s.content
        if s.kind == "implement" and r.answer.code:
            content = r.answer.code
        steps_short.append({
            "id": s.id, "kind": s.kind,
            "content": content[:1200],
            "conclusion": s.conclusion[:300],
        })
    findings = [{
        "step_id": f.step_id, "error_type": f.error_type.value,
        "detail": f.detail[:300], "evidence": f.evidence[:400],
    } for f in v.findings]
    return {
        "question_id": r.question_id,
        # 系统判定上下文（供人工对照，不作为最终标注）
        "sys_context": {
            "title": q.get("title", ""),
            "source": q.get("source", r.scene),
            "prompt": q.get("prompt", "")[:2000],
            "difficulty": r.difficulty.value,
            "sys_verdict": v.verdict.value,
            "sys_confidence": round(v.confidence, 2),
            "arbiter": v.arbiter,
            "answer_correct": r.answer_correct,
            "test_pass_rate": r.test_pass_rate,
            "static_check": r.static_check or {},
            "steps": steps_short,
            "findings": findings,
            "final_answer": r.answer.final_answer[:500],
        },
        # 人工回填字段（初始为空）
        "verdict_human": None,
        "error_step_id": None,
        "error_type_human": None,
        "is_false_positive": None,
        "note": "",
        "audited_by": "",
        "audited_at": None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, help="eval 结果 jsonl 文件")
    ap.add_argument("--questions", type=Path, help="题目池 jsonl（附题面上下文）")
    ap.add_argument("--sample", type=int, default=35, help="抽样数量")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, help="标注模板输出路径")
    ap.add_argument("--check", type=Path, help="校验已回填的标注文件")
    args = ap.parse_args()

    if args.check:
        ok = True
        with args.check.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = AuditRecord.model_validate_json(line)
                if rec.verdict_human is None:
                    print(f"行 {i} 未回填 verdict_human: {rec.question_id}")
                    ok = False
        print("标注校验通过" if ok else "存在未完成标注")
        sys.exit(0 if ok else 1)

    if not args.results or not args.out:
        ap.error("需要 --results 与 --out（或使用 --check）")
    records = load_records(args.results)
    if not records:
        print("[fatal] 结果文件为空", file=sys.stderr)
        sys.exit(1)
    qmap = load_questions(args.questions)
    template = build_template(records, qmap, args.sample, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for t in template:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"生成标注模板 {len(template)} 条 → {args.out}")
    print("请人工回填 verdict_human / error_step_id / is_false_positive 后运行 --check 校验")


if __name__ == "__main__":
    main()
