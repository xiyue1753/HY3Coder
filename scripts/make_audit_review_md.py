"""生成人工审查 markdown 文档（供用户在文本编辑器里逐题填写）。

用法:
    python scripts/make_audit_review_md.py \
        --records data/outputs/audit_records.jsonl \
        --out data/outputs/audit_review.md

文档每题结构：
    ### [1/35] A1013 · abc277_e（PROCESS_INCORRECT · 答案对）
    - 题目/解题过程/系统判定/错误定位摘要
    - 请人工填写区域：
      * 人工判定：[  ]
      * 真实错误起始步骤：[  ]
      * 错误类型：[  ]
      * 是否误报：[  ]（是/否/不确定）
      * 备注：____

用户填写后，运行 scripts/audit_review_parse.py 把填写内容回填为
data/outputs/audit_records.jsonl（AuditRecord 格式）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

TYPE_CN = {
    "misread": "题意误读", "concept": "概念理解错误", "calculation": "计算错误",
    "missing_condition": "条件遗漏", "jump": "跳步推导", "format": "格式不符",
    "logic": "逻辑缺陷", "boundary": "边界条件", "complexity": "复杂度不达标", "other": "其他",
}
KIND_CN = {
    "understand": "① 题意理解", "approach": "② 思路设计", "complexity": "③ 复杂度分析",
    "implement": "④ 代码实现", "selftest": "⑤ 自测验证",
    "derive": "推导", "calc": "计算", "check": "检验",
}


def _strip_md(s: str, limit: int | None = None) -> str:
    """清洗文本避免 markdown 语法污染；可选截断。"""
    # 去掉代码块标记行（题目/结论文本里一般没有，但保守处理）
    s = re.sub(r"```|~~~", "", s or "")
    s = s.replace("|", "｜").replace("\r", "")
    if limit and len(s) > limit:
        s = s[:limit] + "…（截断）"
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/outputs/audit_review.md"))
    args = ap.parse_args()

    records = [json.loads(l) for l in args.records.open(encoding="utf-8") if l.strip()]
    if not records:
        raise SystemExit("模板为空")
    L: list[str] = []
    w = L.append
    w("# 人工审查记录（过程评估 · 有效性抽检）\n")
    w("> 请逐题阅读后填写。只需改每节【请填写】部分，`[ ]` 内填入内容。完成后通知 AI 读取回填。\n")
    w("## 填写说明\n")
    w("1. **人工判定**：`CORRECT`（过程与答案都对）/ `PROCESS_INCORRECT`（过程有错，答案可能对也可能错）"
      "/ `ANSWER_INCORRECT`（最终答案错）/ `SILENT_FAILURE`（答案对但过程不成立）。")
    w("2. **真实错误起始步骤**：若系统判定过程有错，请指出你认为 AI 真正开始出错的是第几步（1 起）；无错留空。")
    w("3. **错误类型**：`misread`题意误读 / `concept`概念错误 / `calculation`计算错误 / "
      "`missing_condition`条件遗漏 / `jump`跳步 / `logic`逻辑缺陷 / `boundary`边界 / `complexity`复杂度 / `other`。")
    w("4. **是否误报**：系统判了过程有错，但你认为实际解题过程并无问题 → 填 `是`（误报）；系统判断合理 → `否`；不确定 → 留空。\n")

    for i, r in enumerate(records, 1):
        qid = r["question_id"]
        sc = r["sys_context"]
        verdict = sc.get("sys_verdict", "?")
        ans = sc.get("answer_correct")
        ans_tag = {True: "答案对", False: "答案错", None: "答案未知"}.get(ans, "答案未知")
        title = sc.get("title", qid)
        source = sc.get("source_id", sc.get("source", ""))
        w(f"---\n\n## [{i}/{len(records)}] `{qid}` · {title}（{source}）")
        w(f"\n**系统判定**：{verdict}（置信度 {sc.get('sys_confidence', '—')}，仲裁 {sc.get('arbiter', '—')}）"
          f"｜{ans_tag}｜用例通过率 {sc.get('test_pass_rate', '—')}\n")
        # 题目
        w(f"\n**题目**：\n```\n{_strip_md(sc.get('prompt', ''), 1500)}\n```\n")
        # 静态校验
        st = sc.get("static_check") or {}
        flags = []
        if st.get("loop_risk"):
            flags.append("死循环风险")
        if st.get("recursion_risk"):
            flags.append("递归无终止")
        if st.get("mismatch"):
            flags.append("复杂度声明不一致")
        if flags:
            w(f"**静态校验提示**：{'、'.join(flags)}\n")
        # 解题过程
        w("\n**AI 解题过程**：")
        for s in (sc.get("steps") or []):
            kind = KIND_CN.get(s["kind"], s["kind"])
            content = s.get("content", "")
            is_code = s["kind"] == "implement"
            fence = "```python" if is_code else "```"
            if content.strip():
                w(f"\n- **{kind}（第 {s['id']} 步）**：{fence}\n{_strip_md(content, 900 if not is_code else 1400)}\n```")
            if s.get("conclusion"):
                w(f"  - _结论：{_strip_md(s['conclusion'], 200)}_")
        # 系统 findings
        findings = sc.get("findings") or []
        if findings:
            w("\n**系统错误定位 findings**：")
            for f in findings:
                w(f"- 第 {f['step_id']} 步 · {TYPE_CN.get(f['error_type'], f['error_type'])}："
                  f"{_strip_md(f['detail'], 300)}")
        else:
            w("\n**系统错误定位 findings**：无（判定为正确）")
        # 填写区
        w("\n### 【请填写】")
        w(f"- 人工判定：[ ]（CORRECT / PROCESS_INCORRECT / ANSWER_INCORRECT / SILENT_FAILURE）")
        w(f"- 真实错误起始步骤：[ ]（数字，从第 1 步起；无错留空）")
        w(f"- 错误类型：[ ]（{', '.join(TYPE_CN.keys())}）")
        w(f"- 是否误报：[ ]（是 / 否 / 不确定）")
        w(f"- 备注：")
        w(f"\n    \n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L), encoding="utf-8")
    print(f"audit review written -> {args.out}（{len(records)} 题）")


if __name__ == "__main__":
    main()
