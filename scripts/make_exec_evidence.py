"""生成「逐用例核验证据」markdown：AI 代码 vs 期望输出 vs 实际输出。

用法:
    python scripts/make_exec_evidence.py \
        --records data/outputs/eval_selfbuilt_hard.jsonl \
        --questions data/questions/abc_selfbuilt.jsonl \
        --pick data/outputs/audit_records.jsonl \
        --out data/outputs/audit_evidence.md

对每题：
- 列出 AI 提交代码（Python）；
- 逐条运行公开+隐藏测试用例，给出【期望输出 vs AI 实际输出】（隐藏用例也完整显示，
  供人工核验——这些是人工抽检证据，不进入任何训练/公开产物）；
- 附题目参考解（reference_solution）供对照；
- 附系统错误定位 findings。

目的：让用户能确认「系统说 AI 第 N 步错了」是否与实际用例失败一致。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.executor.judge import run_checker  # noqa: E402
from rex.executor.sandbox import detect_language, run_code  # noqa: E402

TYPE_CN = {
    "misread": "题意误读", "concept": "概念理解错误", "calculation": "计算错误",
    "missing_condition": "条件遗漏", "jump": "跳步推导", "format": "格式不符",
    "logic": "逻辑缺陷", "boundary": "边界条件", "complexity": "复杂度不达标", "other": "其他",
}


def _clean(s: str, limit: int | None = None) -> str:
    s = (s or "").replace("|", "｜").replace("\r", "")
    if limit and len(s) > limit:
        s = s[:limit] + "…（截断）"
    return s


def run_one(code: str, stdin: str, expected: str, hidden: bool,
            judge: str, checker_code: str | None, checker_language: str,
            timeout: float = 8.0) -> dict:
    """跑单个用例，返回对比结果（隐藏用例也返回期望输出，供人工核验）。"""
    res = run_code(code, stdin=stdin, timeout=timeout,
                   language=detect_language(code))
    if res.error or res.timed_out:
        return {
            "hidden": hidden, "input": stdin, "expected": expected,
            "actual": (res.stderr or res.error or "")[:600],
            "pass": False, "note": "运行错误/超时" if res.error else "超时",
        }
    got = res.stdout
    if judge == "special":
        ok, msg = run_checker(checker_code or "", checker_language, stdin, got, timeout=15.0)
        return {
            "hidden": hidden, "input": stdin, "expected": "(SPJ，无唯一文本)", "actual": got,
            "pass": ok, "note": msg[:120],
        }
    # exact：文本匹配（含浮点容差，与 executor.tests._text_match 一致）
    def _text_match(g, e) -> bool:
        gl = [ln.strip() for ln in g.rstrip().split("\n")]
        el = [ln.strip() for ln in e.rstrip().split("\n")]
        if len(gl) != len(el):
            return False
        for a, b in zip(gl, el):
            if a == b:
                continue
            try:
                fa, fb = float(a), float(b)
            except ValueError:
                return False
            if abs(fa - fb) > 1e-5 * max(1.0, abs(fb), abs(fa)):
                return False
        return True
    ok = _text_match(got, expected)
    return {"hidden": hidden, "input": stdin, "expected": expected, "actual": got,
            "pass": ok, "note": ""}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--pick", type=Path, default=None,
                    help="audit_records.jsonl：只对其中题号生成证据（默认全部记录）")
    ap.add_argument("--out", type=Path, default=Path("data/outputs/audit_evidence.md"))
    args = ap.parse_args()

    evals = [json.loads(l) for l in args.records.open(encoding="utf-8") if l.strip()]
    qmap = {q["id"]: q for q in
            (json.loads(l) for l in args.questions.open(encoding="utf-8") if l.strip())}
    pick_ids = None
    if args.pick and args.pick.exists():
        pick_ids = {json.loads(l)["question_id"] for l in
                    args.pick.open(encoding="utf-8") if l.strip()}

    L: list[str] = []
    w = L.append
    w("# 逐用例核验证据（人工抽检配套）\n")
    w("> 用途：每题给出「AI 提交代码」在每个测试用例（含**隐藏**）上的"
      "【期望输出 vs AI 实际输出】，并附参考解与系统错误定位。\n")
    w("> **请结合此文档核验 `audit_review.md` 中的判定**：若 AI 在隐藏用例上输出与期望不符，"
      "说明系统定位到的那一步错误是真实的；若全部用例通过但系统仍判过程有错，需判断是否为误报。\n")
    w("> ⚠️ 本文档含隐藏用例期望输出，仅用于人工抽检核验，勿并入公开交付/训练语料。\n")

    total_cases = 0
    failed_cases = 0
    for r in sorted(evals, key=lambda x: x["question_id"]):
        qid = r["question_id"]
        if pick_ids is not None and qid not in pick_ids:
            continue
        q = qmap.get(qid, {})
        code = (r["answer"].get("code") or "").strip()
        tcs = q.get("test_cases") or []
        v = r["verification"]
        title = q.get("title", qid)
        w(f"---\n\n## `{qid}` · {_clean(title, 80)}")
        w(f"\n**系统判定**：{v.get('verdict')}（置信 {v.get('confidence')}）｜"
          f"答案对错：{r.get('answer_correct')}｜用例通过率：{r.get('test_pass_rate')}")
        if not code:
            w("\n_（无 AI 代码，跳过）_")
            continue
        # 系统错误定位
        findings = v.get("findings") or []
        if findings:
            w("\n**系统错误定位**：")
            for f in findings:
                w(f"- 第 {f['step_id']} 步 · {TYPE_CN.get(f['error_type'], f['error_type'])}："
                  f"{_clean(f['detail'], 200)}")
        else:
            w("\n**系统错误定位**：无")
        # 用例逐个跑
        w(f"\n**逐用例执行（共 {len(tcs)}，隐藏 {sum(1 for t in tcs if t.get('hidden'))}）**：\n")
        if not tcs:
            w("_（无用例）_")
        for i, tc in enumerate(tcs, 1):
            res = run_one(code, tc.get("input", ""), tc.get("output", ""),
                          bool(tc.get("hidden")), q.get("judge", "exact"),
                          q.get("checker_code"), q.get("checker_language", "python"))
            total_cases += 1
            mark = "✅" if res["pass"] else "❌"
            hid = "隐藏" if res["hidden"] else "公开"
            failed_cases += (0 if res["pass"] else 1)
            note = f"（{_clean(res['note'], 60)}）" if res["note"] else ""
            w(f"**用例 {i}（{hid}）**{mark}{note}")
            w(f"- 输入：\n```\n{_clean(res['input'], 300)}\n```")
            w(f"- 期望输出：\n```\n{_clean(res['expected'], 200)}\n```")
            w(f"- AI 实际输出：\n```\n{_clean(res['actual'], 200)}\n```")
        # 参考解
        ref = (q.get("reference_solution") or "").strip()
        if ref:
            lang = "cpp" if "#include" in ref or "using namespace" in ref else "python"
            w(f"\n**参考解（reference_solution，{lang}）**：")
            w(f"```{lang}\n{_clean(ref, 2400)}\n```")
        else:
            w("\n**参考解**：无")
        w("\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L), encoding="utf-8")
    print(f"evidence written -> {args.out}（用例 {total_cases}，失败 {failed_cases}）")


if __name__ == "__main__":
    main()
