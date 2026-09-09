"""解析用户填写的审查 md，回填为 audit_records.jsonl（AuditRecord 兼容）。

用法:
    python scripts/audit_review_parse.py \
        --review data/outputs/audit_review.md \
        --out data/outputs/audit_records.jsonl

从 md 中逐题解析以下填空：
  - 人工判定（verdict_human）
  - 真实错误起始步骤（error_step_id）
  - 错误类型（error_type_human）
  - 是否误报（is_false_positive）
  - 备注（note）
未填写的字段保持 None。输出可被 AuditRecord.model_validate_json 读回，
供 make_report.py §6 / audit_metrics 计算定位准确率与误报率。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VERDICT_SET = {"CORRECT", "PROCESS_INCORRECT", "ANSWER_INCORRECT", "SILENT_FAILURE"}
ERROR_TYPE_SET = {
    "misread", "concept", "calculation", "missing_condition", "jump",
    "format", "logic", "boundary", "complexity", "other",
}


def _clean(val: str) -> str:
    return re.sub(r"\s+", " ", val or "").strip(" ｜|[]")


def parse_review(text: str) -> dict[str, dict]:
    """返回 {question_id: {verdict_human, error_step_id, error_type_human, is_false_positive, note}}"""
    # 按题分隔：每个区块以 '## [n/N] `QID`' 开头，含 '### 【请填写】' 区域
    blocks = re.split(r"(?m)^## \[\d+/\d+\] ", text)
    out: dict[str, dict] = {}
    for blk in blocks[1:]:
        m = re.match(r"`([A-Za-z0-9]+)`", blk)
        if not m:
            continue
        qid = m.group(1)
        # 定位填写区（第一个 ### 【请填写】 之后）
        fill = re.search(r"### 【请填写】\s*(.*)$", blk, flags=re.S)
        if not fill:
            out[qid] = {}
            continue
        body = fill.group(1)
        rec: dict = {
            "verdict_human": None,
            "error_step_id": None,
            "error_type_human": None,
            "is_false_positive": None,
            "note": "",
        }
        # 人工判定：冒号后到行尾
        m_v = re.search(r"人工判定[：:]\s*\[([^\]]*)\]", body)
        if m_v:
            v = _clean(m_v.group(1))
            if v in VERDICT_SET:
                rec["verdict_human"] = v
        # 错误步骤
        m_s = re.search(r"错误起始步骤[：:]\s*\[([^\]]*)\]", body)
        if m_s:
            s = _clean(m_s.group(1))
            if s.isdigit():
                rec["error_step_id"] = int(s)
        # 错误类型
        m_t = re.search(r"错误类型[：:]\s*\[([^\]]*)\]", body)
        if m_t:
            t = _clean(m_t.group(1))
            if t in ERROR_TYPE_SET:
                rec["error_type_human"] = t
        # 是否误报
        m_f = re.search(r"是否误报[：:]\s*\[([^\]]*)\]", body)
        if m_f:
            f = _clean(m_f.group(1))
            if f == "是":
                rec["is_false_positive"] = True
            elif f == "否":
                rec["is_false_positive"] = False
        # 备注：'备注：' 后直到下一个 '-  ' 或区块结束
        m_n = re.search(r"备注[：:]\s*(.*?)(?=\n\s*\n|\Z)", body, flags=re.S)
        if m_n:
            note = m_n.group(1).strip(" \n- ")
            if note and note != "（无）":
                rec["note"] = note[:500]
        out[qid] = rec
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", type=Path, required=True, help="填写的审查 md")
    ap.add_argument("--out", type=Path, default=Path("data/outputs/audit_records.jsonl"))
    args = ap.parse_args()
    text = args.review.read_text(encoding="utf-8")
    parsed = parse_review(text)
    if not parsed:
        raise SystemExit("未解析到任何题目块")
    rows = []
    n_done = 0
    for qid in sorted(parsed):
        r = parsed[qid]
        rec = {
            "question_id": qid,
            "verdict_human": r.get("verdict_human"),
            "error_step_id": r.get("error_step_id"),
            "error_type_human": r.get("error_type_human"),
            "is_false_positive": r.get("is_false_positive"),
            "note": r.get("note", ""),
            "audited_by": "",
            "audited_at": None,
        }
        if rec["verdict_human"]:
            n_done += 1
        rows.append(rec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"解析 {len(rows)} 题，已人工判定 {n_done} → {args.out}")
    if n_done < len(rows):
        print("提示：仍有题目未填人工判定（verdict_human=None）。")


if __name__ == "__main__":
    main()
