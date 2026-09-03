"""生成自建 hard 60 题评测结果展示页（自包含 HTML）。

用法:
    python scripts/make_selfbuilt_report_html.py \
        --records data/outputs/eval_selfbuilt_hard.jsonl \
        --questions data/questions/abc_selfbuilt.jsonl \
        --out reports/selfbuilt_hard_report.html

页面内容：总览指标卡、verdict 分布、答案×判定交叉表、60 题表格
（含题号/题名/来源/判定/答案/通过率/置信度/错误类型），点行展开单题详情
（题目/过程/沙盒结果/错误定位）。
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
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
VCOLOR = {"CORRECT": "#0a7d33", "PROCESS_INCORRECT": "#b26a00",
          "ANSWER_INCORRECT": "#c62828", "SILENT_FAILURE": "#6a1b9a", "FAILED": "#666"}


def _esc(s: str) -> str:
    return html.escape(s or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, default=None,
                    help="data/outputs/exec_evidence.json（逐用例 期望 vs 实际 输出对照）")
    ap.add_argument("--out", type=Path, default=Path("reports/selfbuilt_hard_report.html"))
    args = ap.parse_args()

    evals = [json.loads(l) for l in args.records.open(encoding="utf-8") if l.strip()]
    qmap = {q["id"]: q for q in
            (json.loads(l) for l in args.questions.open(encoding="utf-8") if l.strip())}
    evidence = {}
    if args.evidence and args.evidence.exists():
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    n = len(evals)
    valid = [r for r in evals if r["verification"]["verdict"] != "FAILED"]
    ans_ok = sum(1 for r in valid if r.get("answer_correct") is True)
    proc_ok = sum(1 for r in valid if r["verification"]["verdict"] == "CORRECT")
    vd = Counter(r["verification"]["verdict"] for r in evals)
    # 交叉表
    cross = Counter((r.get("answer_correct"), r["verification"]["verdict"]) for r in evals)
    vc = lambda v: VCOLOR.get(v, "#666")  # noqa: E731

    rows = []
    for i, r in enumerate(sorted(evals, key=lambda x: x["question_id"])):
        q = qmap.get(r["question_id"], {})
        v = r["verification"]
        findings = v.get("findings") or []
        errs = "、".join(dict.fromkeys(TYPE_CN.get(f["error_type"], f["error_type"])
                                       for f in findings)) or "—"
        ans_tag = {True: "✅", False: "❌", None: "—"}.get(r.get("answer_correct"), "—")
        steps = r["answer"].get("steps") or []
        step_html = []
        for s in steps:
            content = s.get("content", "")
            step_html.append(
                f'<div class="step"><b>{KIND_CN.get(s["kind"], s["kind"])} · 第{s["id"]}步</b>'
                f'<pre>{_esc(content)}</pre>'
                f'<div class="muted">结论：{_esc(s.get("conclusion", ""))}</div></div>')
        finding_html = ("<ul>" + "".join(
            f'<li><b>第{f["step_id"]}步 · {TYPE_CN.get(f["error_type"], f["error_type"])}</b>'
            f'<div>{_esc(f["detail"])}</div>'
            f'<details><summary>依据</summary><div class="muted">{_esc(f["evidence"])}</div></details></li>'
            for f in findings) + "</ul>") if findings else "<div class='muted'>无错误定位（CORRECT）</div>"
        exec_note = ""
        if r.get("error"):
            exec_note = f"<div class='muted'>运行异常：{_esc(r['error'])}</div>"
        # ---- 逐用例证据（期望 vs 实际输出） ----
        ev = evidence.get(r["question_id"])
        case_html = ""
        ref_html = ""
        if ev:
            case_rows = []
            for ci, c in enumerate(ev.get("cases", []), 1):
                hid = "隐藏" if c.get("hid") else "公开"
                mark = "✅" if c.get("pass") else "❌"
                color = "#0a7d33" if c.get("pass") else "#c62828"
                note = f"<div class='muted'>{_esc(c.get('note', ''))}</div>" if c.get("note") else ""
                case_rows.append(
                    f'<tr style="border-left:4px solid {color}">'
                    f"<td class='mono'>{ci}</td><td>{hid}</td><td>{mark}</td>"
                    f"<td><pre class='sm'>{_esc(c.get('input', ''))}</pre></td>"
                    f"<td><pre class='sm'>{_esc(c.get('expected', ''))}</pre></td>"
                    f"<td><pre class='sm'>{_esc(c.get('actual', ''))}</pre></td></tr>")
            case_html = f"""<h4>逐用例执行对照（AI 实际输出 vs 期望输出）
                <span class="muted" style="font-weight:normal">—— 用于人工核验错误定位是否属实</span></h4>
                <div style="overflow-x:auto"><table class="ev"><thead><tr>
                <th>#</th><th>类型</th><th>结果</th><th>输入</th><th>期望输出</th><th>AI 实际输出</th>
                </tr></thead><tbody>{''.join(case_rows)}</tbody></table></div>"""
            ref = ev.get("ref") or ""
            if ref:
                lang = "cpp" if "#include" in ref or "using namespace" in ref else "python"
                ref_html = (f"<h4>参考解（标准答案）</h4><pre style='max-height:260px'>"
                            f"{_esc(ref)}</pre>")
        rows.append(f"""
        <tr>
          <td class="mono">{r['question_id']}</td>
          <td>{_esc(q.get('title', '—'))}</td>
          <td class="mono muted">{_esc(q.get('source_id', q.get('source', '')))}</td>
          <td><span class="badge" style="background:{vc(v['verdict'])}">{v['verdict']}</span></td>
          <td>{ans_tag}</td>
          <td class="mono">{r.get('test_pass_rate', '—')}</td>
          <td class="mono">{v.get('confidence', '—')}</td>
          <td>{_esc(errs)}</td>
          <td class="expander">▸</td>
        </tr>
        <tr class="detail-row">
          <td colspan="9">
            <details open>
              <summary>题目 · 过程 · 判定依据</summary>
              <div class="prompt">{_esc(q.get('prompt', ''))}</div>
              {exec_note}
              {case_html}
              {ref_html}
              <h4>AI 解题过程（{len(steps)} 步）</h4>
              {''.join(step_html)}
              <h4>最终答案</h4>
              <pre>{_esc(r['answer'].get('final_answer', ''))}</pre>
              <h4>错误定位（findings）</h4>
              {finding_html}
            </details>
          </td>
        </tr>""")

    acc = ans_ok / len(valid) if valid else 0.0
    pcc = proc_ok / len(valid) if valid else 0.0
    html_out = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>自建算法 hard 评测结果（{n} 题）</title>
<style>
body {{ font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif; margin:0;
       background:#f6f7f9; color:#1a1a1a; }}
header {{ background:#fff; padding:16px 28px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
h1 {{ margin:0; font-size:20px; }}
.sub {{ color:#6b7280; font-size:12px; margin-top:4px; }}
.wrap {{ max-width:1100px; margin:20px auto; padding:0 20px; }}
.cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:18px; }}
.kpi {{ background:#fff; border:1px solid #e2e5ea; border-radius:10px; padding:14px 18px; }}
.kpi .v {{ font-size:26px; font-weight:700; }}
.kpi .l {{ font-size:12px; color:#6b7280; margin-top:2px; }}
.panel {{ background:#fff; border:1px solid #e2e5ea; border-radius:10px;
          padding:16px 20px; margin-bottom:18px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th {{ text-align:left; background:#f1f3f6; padding:8px; font-size:12px; }}
td {{ padding:8px; border-bottom:1px solid #edf0f3; vertical-align:top; }}
tr.detail-row td {{ background:#fafbfd; padding:0 12px 12px; }}
tr.detail-row details {{ border-top:1px dashed #dbe1e8; padding-top:8px; }}
tr.detail-row[hidden] {{ display:none; }}
.badge {{ color:#fff; padding:2px 8px; border-radius:10px; font-size:11px; }}
.mono {{ font-family:Consolas,monospace; }}
.muted {{ color:#6b7280; font-size:12px; }}
.expander {{ cursor:pointer; text-align:center; color:#1a73e8; font-size:16px; }}
.step {{ border-left:3px solid #d1d9e6; padding-left:10px; margin:8px 0; }}
pre {{ white-space:pre-wrap; background:#f8f9fb; border-radius:6px; padding:10px;
      font-size:12px; line-height:1.5; max-height:300px; overflow:auto; }}
pre.sm {{ margin:2px 0; padding:4px 6px; font-size:11px; max-height:160px; }}
table.ev {{ border-collapse:collapse; width:100%; font-size:11px; background:#fdfefe; }}
table.ev th {{ background:#eef1f5; padding:5px 8px; font-size:11px; }}
table.ev td {{ padding:4px 8px; border:1px solid #e5e9ef; }}
table.ev pre {{ margin:0; }}
.prompt {{ white-space:pre-wrap; background:#fff8e6; border-radius:6px; padding:10px;
          font-size:13px; line-height:1.6; }}
h4 {{ margin:14px 0 6px; font-size:13px; }}
ul {{ padding-left:18px; }}
.dist {{ display:flex; gap:10px; flex-wrap:wrap; }}
.dist span {{ background:#eef0f3; border-radius:12px; padding:4px 12px; font-size:12px; }}
.filter-bar {{ margin-bottom:12px; }}
.filter-bar button {{ border:1px solid #ccd2da; background:#fff; border-radius:14px;
        padding:4px 12px; margin-right:6px; cursor:pointer; font-size:12px; }}
.filter-bar button.on {{ background:#1a73e8; color:#fff; border-color:#1a73e8; }}
</style></head><body>
<header>
  <h1>自建算法题集 · hard 档评测结果</h1>
  <div class="sub">数据：data/outputs/eval_selfbuilt_hard.jsonl（60/60 hard，真实 Hy3 评测）｜
    生成：{datetime.now():%Y-%m-%d %H:%M}</div>
</header>
<div class="wrap">
  <div class="cards">
    <div class="kpi"><div class="v">{acc*100:.1f}%</div><div class="l">答案准确率（{ans_ok}/{len(valid)}）</div></div>
    <div class="kpi"><div class="v">{pcc*100:.1f}%</div><div class="l">过程正确率（CORRECT {proc_ok}/{len(valid)}）</div></div>
    <div class="kpi"><div class="v">{vd.get('ANSWER_INCORRECT',0)+vd.get('PROCESS_INCORRECT',0)}</div><div class="l">过程/答案错误样本（可修正）</div></div>
  </div>
  <div class="panel">
    <h3 style="margin:0 0 8px;font-size:14px">判定分布</h3>
    <div class="dist">{''.join(f'<span style="background:{vc(k)}22;color:{vc(k)}"><b>{k}: {v}</b></span>'
                              for k, v in vd.items())}</div>
    <h3 style="margin:16px 0 8px;font-size:14px">答案正确性 × 判定（交叉统计，验证评估器自洽）</h3>
    <table><thead><tr><th>答案正确</th><th>判定</th><th>样本</th><th>含义</th></tr></thead><tbody>
    {''.join(f'<tr><td>{ {"True":"✅ 对","False":"❌ 错","None":"— 未知"}.get(str(k[0]) if k[0] is not None else "None", "—") }</td>'
             f'<td>{k[1]}</td><td>{v}</td>'
             f'<td class="muted">{ {("False","ANSWER_INCORRECT"):"系统正确降级（预期行为）",
                                    ("True","CORRECT"):"均正确",
                                    ("True","PROCESS_INCORRECT"):"沉默失败候选——答案对但过程判错，需人工核验",
                                    ("False","PROCESS_INCORRECT"):"答案错且过程错"}.get((str(k[0]),k[1]), "其它") }</td></tr>'
             for k, v in sorted(cross.items(), key=lambda x: -x[1]))}
    </tbody></table>
  </div>
  <div class="panel">
    <h3 style="margin:0 0 8px;font-size:14px">60 题明细（点击 ▸ 展开详情）</h3>
    <div class="filter-bar" id="filters">
      <button data-f="" class="on">全部 ({n})</button>
      <button data-f="CORRECT">CORRECT</button>
      <button data-f="PROCESS_INCORRECT">PROCESS_INCORRECT</button>
      <button data-f="ANSWER_INCORRECT">ANSWER_INCORRECT</button>
      <button data-f="SILENT">SILENT_FAILURE</button>
    </div>
    <table id="tbl"><thead><tr>
      <th>题号</th><th>题名</th><th>来源</th><th>判定</th><th>答案</th>
      <th>通过率</th><th>置信度</th><th>错误类型</th><th></th>
    </tr></thead><tbody>{''.join(rows)}</tbody></table>
  </div>
</div>
<script>
const badge = document.querySelectorAll('.expander');
badge.forEach(b => b.addEventListener('click', () => {{
  const tr = b.closest('tr').nextElementSibling;
  tr.hidden = !tr.hidden;
  b.textContent = tr.hidden ? '▸' : '▾';
}}));
const fbtns = document.querySelectorAll('#filters button');
fbtns.forEach(btn => btn.addEventListener('click', () => {{
  fbtns.forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  const f = btn.dataset.f;
  document.querySelectorAll('#tbl tbody tr').forEach(tr => {{
    const isMain = !tr.classList.contains('detail-row');
    if (!isMain) {{ tr.hidden = true; return; }}
    const v = tr.children[3].textContent.trim();
    tr.hidden = !(f === '' || (f === 'SILENT' ? v === 'SILENT_FAILURE' : v === f));
  }});
}}));
</script>
</body></html>"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_out, encoding="utf-8")
    print(f"report written -> {args.out}（{n} 题）")


if __name__ == "__main__":
    main()
