# -*- coding: utf-8 -*-
"""针对「答案错误样本」的 ReAct 修正测试（真实度补偿版）。

与纯文本 refine 的区别：每一轮除了把 verifier 审查文本（findings）转为修订指令，
还把**非隐藏样例的沙盒执行结果**（输入 / 期望输出 / 实际输出）作为客观观察喂给
求解端（revise prompt）与验证端（execution_feedback），补偿 refine 无沙盒的空洞。

输入：temperature=0 eval 记录中 answer_correct=False 的全部题（t0 文件）。
输出：data/outputs/refine_wrong_t0.jsonl（每行含 initial/轮次/final + 每轮沙盒事实，
      供报告按难度/错误类型/平台标签分析）。

用法：
    python scripts/run_refine_wrong_t0.py --ids A1052 C2075      # smoke
    python scripts/run_refine_wrong_t0.py                        # 全量 34 题（resume）
    python scripts/run_refine_wrong_t0.py --max-rounds 3 --out data/outputs/refine_wrong_t0.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex.config import Config  # noqa: E402
from rex.executor.sandbox import detect_language, run_code  # noqa: E402
from rex.executor.judge import run_checker  # noqa: E402
from rex.executor.tests import _text_match  # noqa: E402
from rex.executor.static_check import check_static, static_evidence_block  # noqa: E402
from rex.models import (  # noqa: E402
    Answer, ErrorSeverity, ErrorType, QuestionItem, RefineFeedback,
    TestCase, Verdict,
)
from rex.refine.prompts import findings_to_feedback  # noqa: E402
from rex.solver.agent import SolverAgent  # noqa: E402
from rex.verifier.agent import VerifierAgent  # noqa: E402

_PUBLIC_CAP = 900    # 失败用例输入文本截断（字符）
_OUT_CAP = 300       # 输出/期望截断


def load_questions() -> dict[str, dict]:
    qmap: dict[str, dict] = {}
    for f in (ROOT / "data" / "questions" / "abc_selfbuilt.jsonl",
              ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"):
        for line in f.open(encoding="utf-8"):
            if line.strip():
                q = json.loads(line)
                qmap[q["id"]] = q
    return qmap


def load_wrong_evals() -> list[dict]:
    rows = []
    for f in ("eval_selfbuilt_all_t0.jsonl", "eval_cf_all_t0.jsonl"):
        p = ROOT / "data" / "outputs" / f
        for line in p.open(encoding="utf-8"):
            if line.strip():
                o = json.loads(line)
                if o.get("answer_correct") is False:
                    rows.append(o)
    return rows


def _run_error_detail(res) -> str:
    """编译/运行错误诊断：提取完整 stderr 中含 `error` 的行。

    之前只用 res.error[:200]（编译器诊断常被截断在模板堆栈开头），模型看不到
    真正的错误行（如 `shadows a parameter`、`no match for 'operator<'`），
    导致连可一行修复的编译错误也反复修不好。这里改为给最有用的诊断行。
    """
    if not res.error:
        return ""
    lines = [ln.strip() for ln in (res.stderr or "").splitlines() if ln.strip()]
    err_lines = [ln[:240] for ln in lines if "error" in ln.lower()][:6]
    if err_lines:
        return "(运行错误) " + " | ".join(err_lines)
    return f"(运行错误) {res.error[:300]}"


def run_single_case(code: str, q: dict, tc: dict) -> tuple[bool, str]:
    """返回 (通过?, 输出文本或错误说明)。special 走 checker。"""
    lang = detect_language(code) if code else "python"
    res = run_code(code, stdin=tc["input"], timeout=15, language=lang)
    if res.error:
        return False, _run_error_detail(res)
    if q.get("judge", "exact") == "special":
        try:
            ok, msg = run_checker(q.get("checker_code"), q.get("checker_language", "python"),
                                  tc["input"], res.stdout, timeout=20)
        except Exception as e:  # noqa: BLE001
            return False, f"(checker 异常) {e}"
        return bool(ok), res.stdout[:300]
    return _text_match(res.stdout, tc.get("output", "")), res.stdout[:300]


def build_exec_feedback(code: str, q: dict) -> tuple[str | None, float, list[dict]]:
    """非隐藏（public）用例执行反馈文本。返回 (feedback_text, public_pass_rate, failures)。"""
    cases = [t for t in q.get("test_cases", []) if not t.get("hidden")]
    if not cases:
        return None, 0.0, []
    passed, failures = 0, []
    for i, tc in enumerate(cases, 1):
        ok, detail = run_single_case(code, q, tc)
        if ok:
            passed += 1
        else:
            inp = tc["input"][:_PUBLIC_CAP]
            exp = tc.get("output", "") if q.get("judge", "exact") != "special" else "(SPJ)"
            failures.append({"idx": i, "input": inp, "expected": exp[:_OUT_CAP],
                             "got": detail})
    if not failures:
        return f"公开样例执行（客观事实）：{passed}/{len(cases)} 全部通过。", 1.0, []
    lines = [f"公开样例执行（客观事实）：{passed}/{len(cases)} 通过，失败 {len(failures)} 个："]
    for f in failures[:8]:
        lines.append(f"· 用例{f['idx']} 输入：{f['input']!r}")
        lines.append(f"  期望输出：{f['expected']!r}  你的输出：{f['got']!r}")
    if len(failures) > 8:
        lines.append(f"（其余 {len(failures)-8} 个失败省略）")
    return "\n".join(lines), passed / len(cases), failures


def exec_feedback_for_verifier(feedback_text: str | None, rate: float) -> str | None:
    """喂给 verifier 的 execution_feedback（事实性文本）。"""
    if feedback_text is None:
        return None
    if rate >= 1.0:
        return f"公开样例执行全部通过（{feedback_text}）"
    return feedback_text


def strip_minor_only(v):
    """refine 语义：无 fatal 且非 CORRECT → 归一 CORRECT（只记录不驱动）。"""
    if not v.findings:
        return v
    has_fatal = any(getattr(f, "severity", None) == "fatal" for f in v.findings)
    if not has_fatal and v.verdict in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
        v.verdict = Verdict.CORRECT
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None, help="只跑指定题（smoke）")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--out", default="refine_wrong_t0.jsonl")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    from rex.hy3_client import Hy3Client
    client = Hy3Client(api_key=cfg.hy3_api_key, base_url=cfg.hy3_base_url,
                       model=cfg.hy3_model, reasoning_effort=cfg.hy3_reasoning_effort,
                       temperature=getattr(cfg, "temperature", 0.0) or 0.0,
                       max_retries=cfg.max_retries, timeout=cfg.timeout)
    solver = SolverAgent(client)
    verifier = VerifierAgent(client)

    qmap = load_questions()
    wrong = load_wrong_evals()
    if args.ids:
        wrong = [o for o in wrong if o["question_id"] in args.ids]
    print(f"待跑 {len(wrong)} 题（answer_correct=False）", flush=True)

    out = ROOT / "data" / "outputs" / args.out
    done = set()
    if not args.no_resume and out.exists():
        for line in out.open(encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["question_id"])
    print(f"已有 {len(done)} 题（resume）", flush=True)

    fh = out.open("a", encoding="utf-8")
    for o in wrong:
        qid = o["question_id"]
        if qid in done:
            print(f"- {qid} 已存在，跳过", flush=True)
            continue
        q = qmap.get(qid)
        if q is None:
            print(f"- {qid} 找不到题目，跳过", flush=True)
            continue
        t0 = time.time()
        try:
            rec = refine_one(client, solver, verifier, q, o, args.max_rounds)
        except Exception as e:  # noqa: BLE001
            print(f"- {qid} FAILED: {e}", flush=True)
            rec = {"question_id": qid, "error": str(e)[:500], "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        tag = "converged" if rec.get("converged") else "NOT-converged"
        print(f"- {qid} done rounds={rec.get('rounds_used')} {tag} "
              f"final_ans={rec.get('final', {}).get('answer_correct')} "
              f"({time.time()-t0:.0f}s)", flush=True)
    fh.close()
    print("写盘完成", out)


def refine_one(client, solver, verifier, q: dict, o: dict, max_rounds: int) -> dict:
    question = QuestionItem.model_validate(q)
    initial_answer = Answer.model_validate(o["answer"])
    initial_v = o["verification"]
    # 静态证据（无模型调用，补充规则诊断）
    static = check_static(question, initial_answer)
    static_text = static_evidence_block(static)
    # 初始执行反馈（公开用例）
    exec_txt0, pub0, _ = build_exec_feedback(initial_answer.code or "", q)
    cost0 = client.call_count
    rounds = []
    cur_ans, cur_v = initial_answer, None
    exec_txt, pub_rate = exec_txt0, pub0

    for r in range(1, max_rounds + 1):
        # 1) 审查文本 → 修订指令
        prev_v_obj = None
        if cur_v is None:
            # initial：把 eval 的 verification 转成模型对象以便 findings_to_feedback
            from rex.models import VerificationResult, ErrorFinding
            prev_v_obj = VerificationResult.model_validate(initial_v)
        else:
            prev_v_obj = cur_v
        feedbacks = findings_to_feedback(prev_v_obj)
        # 2) 真实度补偿：非隐藏样例执行结果（输入/期望/实际输出）作为客观观察
        if exec_txt:
            feedbacks.append(RefineFeedback(
                step_id=None, error_type=ErrorType.OTHER,
                instruction=(f"【公开样例执行反馈（客观事实，来自沙盒运行你的代码）】\n{exec_txt}\n"
                             "请结合失败用例修正代码与相关步骤，确保重新输出的完整过程能通过上述公开样例；"
                             "若你认为期望输出本身有歧义，请在推导中说明依据。"),
                evidence="沙盒执行公开（非隐藏）样例的客观比对结果",
            ))
        # 3) revise
        revised = solver.revise(question, cur_ans, feedbacks)
        # 4) 重验：静态 + 公开样例执行反馈
        st2 = check_static(question, revised)
        exec_txt2, pub2, fails2 = build_exec_feedback(revised.code or "", q)
        v = verifier.verify(question, revised,
                            static_evidence=static_evidence_block(st2),
                            execution_feedback=exec_feedback_for_verifier(exec_txt2, pub2))
        v = strip_minor_only(v)
        cost_now = client.call_count
        rounds.append({
            "round_no": r,
            "feedbacks": [fb.model_dump() for fb in feedbacks],
            "revised_answer": revised.model_dump(),
            "verification": v.model_dump(),
            "public_pass_rate": pub2,
            "public_failures": fails2[:8],
            "exec_feedback": exec_txt2,
            "cost_calls": cost_now - cost0,
        })
        cur_ans, cur_v = revised, v
        exec_txt, pub_rate = exec_txt2, pub2
        cost0 = cost_now
        if v.verdict == Verdict.CORRECT:
            break

    # 终局沙盒事实（全部用例含 hidden，供报告标签分析）
    full_correct, full_pass, full_err = eval_final(question, cur_ans.code or "")
    final_v = cur_v.model_dump() if cur_v is not None else None
    return {
        "question_id": o["question_id"],
        "difficulty": o.get("difficulty"),
        "eval_verdict": initial_v.get("verdict"),
        "eval_answer_correct": False,
        "initial_error_type": _first_error_type(initial_v),
        "rounds_used": len(rounds),
        "converged": bool(final_v and final_v["verdict"] == "CORRECT"),
        "final_verdict": (final_v or {}).get("verdict"),
        "initial_public_pass": pub0,
        "rounds": rounds,
        "final": {
            "verification": final_v,
            "public_pass_rate": pub_rate,
            "full_pass_rate": full_pass,
            "answer_correct": full_correct,
            "full_error": (full_err or "")[:200],
        },
        "cost_calls": client.call_count,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def eval_final(q: QuestionItem, code: str) -> tuple[bool, float, str | None]:
    """全量用例（含 hidden）沙盒判定——终局答案正确性（报告标签分析用）。"""
    from rex.executor.tests import run_test_cases
    from rex.models import TestCase
    if not code:
        return False, 0.0, "no code"
    tcs = [TestCase.model_validate(t) for t in q.test_cases]
    res = run_test_cases(code, tcs, timeout=15, language=detect_language(code),
                         judge=q.judge, checker_code=q.checker_code,
                         checker_language=q.checker_language)
    return (res.pass_rate == 1.0 and not res.error), res.pass_rate, res.error


def _first_error_type(v: dict) -> str | None:
    for f in (v or {}).get("findings", []):
        if f.get("severity") == "fatal":
            return f.get("error_type")
    return None


if __name__ == "__main__":
    main()
