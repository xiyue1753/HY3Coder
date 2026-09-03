"""生成人工抽检标注工作簿（自包含 HTML，可直接浏览器打开对照标注）。

用法:
    python scripts/make_audit_workbook.py \
        --records data/outputs/audit_records.jsonl \
        --out reports/audit_workbook.html

页面内容：
- 顶部：抽检样本分层分布 + 操作说明
- 每题一卡片：题目、系统判定（verdict/confidence/arbiter）、沙盒结果（answer_correct/test_pass_rate）、
  静态校验标记、分步过程（可展开）、错误定位 findings
- 标注表单：人工判定下拉、真实错误步骤、错误类型、是否误报、备注
  点击「保存」把标注存到浏览器 localStorage；点击「导出」下载 audit_records.jsonl（人工回填后的）
"""
from __future__ import annotations

import argparse
import html
import json
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
VERDICTS = ["CORRECT", "PROCESS_INCORRECT", "ANSWER_INCORRECT", "SILENT_FAILURE"]


def _esc(s: str) -> str:
    return html.escape(s or "")


def _verdict_badge(v: str, ans: bool | None) -> str:
    color = {"CORRECT": "#0a7d33", "PROCESS_INCORRECT": "#b26a00",
             "ANSWER_INCORRECT": "#c62828", "SILENT_FAILURE": "#6a1b9a",
             "FAILED": "#666"}.get(v, "#666")
    ans_tag = {True: "答案对", False: "答案错", None: "答案未知"}.get(ans, "答案未知")
    return (f'<span class="badge" style="background:{color}">{_esc(v)}</span>'
            f'<span class="badge2">{ans_tag}</span>')


def _finding_html(f: dict) -> str:
    return (f'<li><b>第{f["step_id"]}步 · {TYPE_CN.get(f["error_type"], f["error_type"])}</b>'
            f'<div class="muted">{_esc(f["detail"])}</div>'
            f'<details><summary>判定依据</summary><div class="muted">{_esc(f["evidence"])}</div></details></li>')


def _steps_html(steps: list[dict]) -> str:
    parts = []
    for s in steps:
        kind = KIND_CN.get(s["kind"], s["kind"])
        body = _esc(s["content"])
        concl = _esc(s["conclusion"])
        parts.append(
            f'<div class="step"><div class="step-head">{kind} <span class="muted">'
            f'第 {s["id"]} 步</span></div>'
            f'<pre>{body}</pre>'
            f'<div class="concl">结论：{concl}</div></div>')
    return "\n".join(parts)


def _card(idx: int, rec: dict) -> str:
    qid = rec["question_id"]
    sc = rec["sys_context"]
    title = _esc(sc.get("title", qid))
    source = _esc(sc.get("source", ""))
    prompt = _esc(sc.get("prompt", ""))
    static = sc.get("static_check") or {}
    flags = []
    if static.get("loop_risk"):
        flags.append("死循环风险")
    if static.get("recursion_risk"):
        flags.append("递归无终止风险")
    if static.get("mismatch"):
        flags.append("复杂度声明不一致")
    flags_html = ("".join(f'<span class="flag">{f}</span>' for f in flags)
                  if flags else '<span class="muted">—</span>')
    findings = sc.get("findings") or []
    findings_html = (
        '<div class="findings"><h4>错误定位（系统 findings）</h4><ul>' +
        "".join(_finding_html(f) for f in findings) + "</ul></div>"
    ) if findings else ""
    steps = sc.get("steps") or []
    steps_html = (f'<details class="steps-details"><summary>查看 AI 解题过程'
                  f'（{len(steps)} 步）</summary>{_steps_html(steps)}</details>'
                  if steps else "")
    row_id = f"row-{qid}"
    sel_opts = "".join(
        f'<option value="{v}">{v}</option>' for v in VERDICTS)
    type_opts = "".join(
        f'<option value="{k}">{v}</option>' for k, v in sorted(TYPE_CN.items()))
    return f"""
    <div class="card" id="{row_id}" data-qid="{qid}">
      <div class="card-head">
        <span class="qno">{idx}</span>
        <div>
          <div class="title">{title} <span class="mono muted">{qid}</span></div>
          <div class="muted">{source} · 系统判定 {_verdict_badge(sc.get('sys_verdict', ''), sc.get('answer_correct'))}
              置信度 {sc.get('sys_confidence', '—')} · 仲裁 {sc.get('arbiter', '—')}
              · 用例通过率 {sc.get('test_pass_rate', '—')} {flags_html}</div>
        </div>
        <div class="status" id="st-{qid}">待标注</div>
      </div>
      <details class="q-details"><summary>题目</summary><div class="prompt">{prompt}</div></details>
      {steps_html}
      {findings_html}
      <div class="audit-form">
        <h4>人工标注</h4>
        <div class="form-grid">
          <label>人工判定
            <select class="in-verdict" data-qid="{qid}">
              <option value="">— 选择 —</option>{sel_opts}
            </select></label>
          <label>真实错误起始步骤
            <input class="in-step" data-qid="{qid}" type="number" min="0" placeholder="如 3，无错留空"></label>
          <label>错误类型
            <select class="in-etype" data-qid="{qid}">
              <option value="">— 选择 —</option>{type_opts}
            </select></label>
          <label>系统误报？
            <select class="in-fp" data-qid="{qid}">
              <option value="">— 选择 —</option>
              <option value="false">否（系统判定合理）</option>
              <option value="true">是（系统误报）</option>
            </select></label>
          <label class="full">备注
            <textarea class="in-note" data-qid="{qid}" rows="2"></textarea></label>
        </div>
        <button class="btn-save" data-qid="{qid}">保存本题标注</button>
        <span class="saved-hint" id="hint-{qid}"></span>
      </div>
    </div>"""


def build(records: list[dict]) -> str:
    cards = "\n".join(_card(i + 1, r) for i, r in enumerate(records))
    # 分层分布
    buckets: dict[str, int] = {}
    for r in records:
        sc = r["sys_context"]
        v = sc.get("sys_verdict")
        ans = sc.get("answer_correct")
        if ans is True and v in ("PROCESS_INCORRECT", "SILENT_FAILURE"):
            key = "答案对 + 过程判错（误报率分母，需确认是否误报）"
        elif ans is False and v in ("PROCESS_INCORRECT", "SILENT_FAILURE"):
            key = "答案错 + 过程判错（定位准确率核心层）"
        elif ans is False:
            key = "答案错 + 判答案错（定位补充层）"
        else:
            key = "答案对 + CORRECT（对照组）"
        buckets[key] = buckets.get(key, 0) + 1
    dist = "".join(f'<div class="dist-row"><span>{_esc(k)}</span><b>{v} 题</b></div>'
                   for k, v in sorted(buckets.items()))
    payload = json.dumps(records, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>人工抽检标注工作簿</title>
<style>
  body {{ font-family: -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
         margin:0; background:#f6f7f9; color:#1a1a1a; }}
  header {{ position:sticky; top:0; background:#fff; padding:14px 28px;
           box-shadow:0 1px 4px rgba(0,0,0,.08); z-index:5;
           display:flex; justify-content:space-between; align-items:center; }}
  header h1 {{ font-size:18px; margin:0; }}
  .wrap {{ max-width:980px; margin:20px auto; padding:0 20px; }}
  .summary {{ background:#fff; border:1px solid #e2e5ea; border-radius:10px;
              padding:16px 20px; margin-bottom:18px; }}
  .dist-row {{ display:flex; justify-content:space-between; padding:4px 0; }}
  .card {{ background:#fff; border:1px solid #e2e5ea; border-radius:10px;
           padding:16px 20px; margin-bottom:16px; }}
  .card-head {{ display:flex; gap:12px; align-items:flex-start; }}
  .qno {{ background:#1a73e8; color:#fff; border-radius:6px; min-width:28px;
          text-align:center; padding:4px 0; font-weight:600; }}
  .title {{ font-weight:600; font-size:15px; }}
  .muted {{ color:#6b7280; font-size:12px; }}
  .mono {{ font-family:Consolas,monospace; }}
  .badge {{ color:#fff; padding:2px 8px; border-radius:10px; font-size:12px;
            margin-right:6px; }}
  .badge2 {{ background:#eef0f3; padding:2px 8px; border-radius:10px; font-size:12px; }}
  .flag {{ background:#fff3cd; color:#7a5b00; border-radius:8px; padding:1px 8px;
           font-size:11px; margin-left:6px; }}
  details {{ border:1px solid #e2e5ea; border-radius:8px; padding:10px 14px; margin-top:10px; }}
  summary {{ cursor:pointer; font-weight:500; font-size:13px; }}
  .prompt {{ white-space:pre-wrap; font-size:13px; margin-top:8px; line-height:1.6;
             max-height:260px; overflow:auto; }}
  .step {{ border-left:3px solid #d1d9e6; padding-left:10px; margin:8px 0; }}
  .step-head {{ font-size:12px; color:#333; font-weight:500; }}
  pre {{ white-space:pre-wrap; background:#f8f9fb; border-radius:6px; padding:10px;
         font-size:12px; line-height:1.5; max-height:320px; overflow:auto; }}
  .concl {{ font-size:12px; color:#2b5797; margin-top:4px; }}
  .findings ul {{ margin:6px 0 0; padding-left:18px; }}
  .findings li {{ font-size:13px; margin:6px 0; }}
  .audit-form {{ background:#f8f9fb; border-radius:8px; padding:12px 14px; margin-top:12px; }}
  .audit-form h4 {{ margin:0 0 10px; font-size:13px; }}
  .form-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px 16px; }}
  label {{ font-size:12px; color:#444; display:flex; flex-direction:column; gap:4px; }}
  label.full {{ grid-column:1 / -1; }}
  select, input, textarea {{ border:1px solid #ccd2da; border-radius:6px;
              padding:6px 8px; font-size:13px; font-family:inherit; }}
  .btn-save {{ margin-top:10px; background:#1a73e8; color:#fff; border:none;
              padding:8px 18px; border-radius:6px; cursor:pointer; font-size:13px; }}
  .btn-save:hover {{ background:#1765c1; }}
  .saved-hint {{ margin-left:10px; font-size:12px; color:#0a7d33; }}
  .status {{ margin-left:auto; font-size:12px; padding:4px 10px; border-radius:12px;
             background:#eef0f3; white-space:nowrap; }}
  .status.done {{ background:#e6f4ea; color:#0a7d33; }}
  .export {{ background:#188038; }}
  .toolbar {{ display:flex; gap:10px; align-items:center; }}
  .toolbar button {{ border:none; border-radius:6px; padding:8px 16px; cursor:pointer;
                     color:#fff; font-size:13px; }}
</style></head><body>
<header>
  <h1>人工抽检标注工作簿（{len(records)} 题）</h1>
  <div class="toolbar">
    <button class="export" onclick="exportAudits()">导出标注 JSONL</button>
  </div>
</header>
<div class="wrap">
  <div class="summary">
    <h3 style="margin:0 0 8px;font-size:14px">抽检样本分层（对齐任务书 P4 两套分母）</h3>
    {dist}
    <div class="muted" style="margin-top:8px">
      操作：对每题对照「AI 过程 + 系统判定 + 错误定位」给出真实结论；
      完成全部后点右上角「导出标注 JSONL」，覆盖 <span class="mono">data/outputs/audit_records.jsonl</span>。
      中途标注保存在本浏览器 localStorage，刷新不丢。
    </div>
  </div>
  {cards}
</div>
<script>
const RECORDS = {payload};
const KEY = "audit_workbook_v1";
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch(e) {{}}

function fillForm(qid) {{
  const s = saved[qid] || {{}};
  if (s.verdict_human) document.querySelector(`.in-verdict[data-qid="${{qid}}"]`).value = s.verdict_human;
  if (s.error_step_id != null) document.querySelector(`.in-step[data-qid="${{qid}}"]`).value = s.error_step_id;
  if (s.error_type_human) document.querySelector(`.in-etype[data-qid="${{qid}}"]`).value = s.error_type_human;
  if (s.is_false_positive != null) document.querySelector(`.in-fp[data-qid="${{qid}}"]`).value = String(s.is_false_positive);
  if (s.note) document.querySelector(`.in-note[data-qid="${{qid}}"]`).value = s.note;
  markStatus(qid);
}}
function markStatus(qid) {{
  const s = saved[qid];
  const el = document.getElementById('st-' + qid);
  if (s && s.verdict_human) {{ el.textContent = '已标注'; el.className = 'status done'; }}
}}
document.querySelectorAll('.btn-save').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const qid = btn.dataset.qid;
    const rec = RECORDS.find(r => r.question_id === qid);
    const verdict = document.querySelector(`.in-verdict[data-qid="${{qid}}"]`).value;
    const stepVal = document.querySelector(`.in-step[data-qid="${{qid}}"]`).value;
    const etype = document.querySelector(`.in-etype[data-qid="${{qid}}"]`).value;
    const fpVal = document.querySelector(`.in-fp[data-qid="${{qid}}"]`).value;
    const note = document.querySelector(`.in-note[data-qid="${{qid}}"]`).value;
    saved[qid] = {{
      question_id: qid,
      verdict_human: verdict || null,
      error_step_id: stepVal === '' ? null : Number(stepVal),
      error_type_human: etype || null,
      is_false_positive: fpVal === '' ? null : (fpVal === 'true'),
      note: note,
      audited_by: '',
      audited_at: new Date().toISOString(),
    }};
    localStorage.setItem(KEY, JSON.stringify(saved));
    markStatus(qid);
    const hint = document.getElementById('hint-' + qid);
    hint.textContent = '✓ 已保存';
    setTimeout(() => hint.textContent = '', 1800);
  }});
}});
function exportAudits() {{
  const nDone = RECORDS.filter(r => saved[r.question_id] && saved[r.question_id].verdict_human).length;
  const out = RECORDS.map(r => {{
    const s = saved[r.question_id] || {{}};
    return {{
      question_id: r.question_id,
      verdict_human: s.verdict_human || null,
      error_step_id: s.error_step_id ?? null,
      error_type_human: s.error_type_human || null,
      is_false_positive: s.is_false_positive ?? null,
      note: s.note || '',
      audited_by: s.audited_by || '',
      audited_at: s.audited_at || null,
    }};
  }});
  const blob = new Blob([out.map(o => JSON.stringify(o)).join('\\n')], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'audit_records.jsonl';
  a.click();
  alert(`已导出 ${{out.length}} 条（已标注 ${{nDone}}）。请用下载文件覆盖 data/outputs/audit_records.jsonl`);
}}
RECORDS.forEach(r => fillForm(r.question_id));
</script>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True, help="audit_records.jsonl（模板）")
    ap.add_argument("--out", type=Path, default=Path("reports/audit_workbook.html"))
    args = ap.parse_args()
    records = [json.loads(l) for l in args.records.open(encoding="utf-8") if l.strip()]
    if not records:
        raise SystemExit("模板为空，请先生成 audit_records.jsonl")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(records), encoding="utf-8")
    print(f"workbook written -> {args.out}")


if __name__ == "__main__":
    main()
