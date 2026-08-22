"""人工抽检工具：从评估结果中分层抽样生成标注模板，供人工回填。

用法:
    python scripts/audit_sample.py --results data/outputs/eval_results.jsonl \
        --sample 30 --out data/outputs/audit_records.jsonl

标注模板每行一个 AuditRecord（question_id 预填，其余字段留空由人填写）：
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

from rex.datasets.sampling import stratified_sample  # noqa: E402
from rex.models import AuditRecord, EvalRecord  # noqa: E402


def load_records(path: Path) -> list[EvalRecord]:
    with path.open(encoding="utf-8") as f:
        return [EvalRecord.model_validate_json(line) for line in f if line.strip()]


def build_template(records: list[EvalRecord], n: int, seed: int = 42) -> list[AuditRecord]:
    picked = stratified_sample(
        records, "algorithm" if records[0].scene == "algorithm" else "math",
        str(n), seed=seed,
    ) if records else []
    return [AuditRecord(question_id=r.question_id) for r in picked]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, help="eval 结果 jsonl 文件")
    ap.add_argument("--sample", type=int, default=30, help="抽样数量")
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
    template = build_template(records, args.sample)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in template:
            f.write(r.model_dump_json() + "\n")
    print(f"生成标注模板 {len(template)} 条 → {args.out}")
    print("请人工回填 verdict_human / error_step_id / is_false_positive 后运行 --check 校验")


if __name__ == "__main__":
    main()
