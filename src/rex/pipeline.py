"""Batch pipeline: eval (once, no feedback) and refine (ReAct loop) modes.

Data purity:
  - eval:   question → solve → execute → verify, one pass. Verifier feedback
            is NEVER routed back. Metrics are computed on eval data only.
  - refine: question → solve → verify → [feedback → revise → re-verify] ≤N
            rounds. Rounds are recorded separately; never mixed into eval
            metrics.

Both modes support checkpoint resume: completed question_ids are skipped,
each record is appended to a JSONL output file as it finishes.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable

from rex.config import Config
from rex.executor.tests import run_test_cases
from rex.hy3_client import Hy3Client
from rex.models import (
    Answer,
    ErrorFinding,
    ErrorSeverity,
    ErrorType,
    EvalRecord,
    QuestionItem,
    RefineRecord,
    Step,
    VerificationResult,
    Verdict,
)
from rex.refine.agent import Refiner
from rex.solver.agent import SolverAgent
from rex.verifier.agent import VerifierAgent

log = logging.getLogger(__name__)

_WS_NORM_RE = re.compile(r"\s+")
# LaTeX 排版命令（无参数）——移除它们不影响语义
_LATEX_NOARG = re.compile(
    r"\\\\(?:left|right|displaystyle|textstyle|large|Large|big|Big|bigg|Bigg|quad|qquad)"
)

# 用于匹配 \frac{a}{b}、\sqrt{n}、\boxed{...}、\text{...} 等带花括号参数的 LaTeX 结构
_LATEX_GROUP = re.compile(r"\\(frac|dfrac|tfrac|sqrt|boxed|text|cfrac)\{")

# 简单符号映射（去除空白后再比对，故先映射为等宽文本）
_LATEX_SYM = {
    r"\cdot": "*", r"\times": "*", r"\times": "*",
    r"\div": "/", r"\pm": "+-", r"\mp": "-+",
    r"\pi": "pi", r"\infty": "inf", r"\leq": "<=", r"\leqq": "<=",
    r"\geq": ">=", r"\geqq": ">=", r"\ne": "!=", r"\neq": "!=",
    r"\approx": "~", r"\times": "*", r"\dots": "...", r"\ldots": "...",
}


_FRAC_SIMPLE_RE = re.compile(r"^[0-9a-z√.]+$")


def _emit(progress, phase: str, payload=None, message: str | None = None) -> None:
    """阶段回调兼容层：`progress(phase, payload[, message])`。

    老回调只接受两个参数（测试里的 lambda 就是），带 message 的新回调走三参；
    异常一律吞掉——进度展示不该影响评测结果。
    """
    if progress is None:
        return
    try:
        progress(phase, payload, message)
    except TypeError:
        try:
            progress(phase, payload)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def _frac_text(num: str, den: str) -> str:
    """Render a fraction, adding parens only when needed to preserve structure.

    简单量（纯数字/字母/√）不加括号 → `\frac{1}{2}` 归一到 `1/2` 与手写等价；
    复合表达式加括号 → `\frac{x+1}{2}` 归一到 `(x+1)/2`，避免歧义。
    """
    if _FRAC_SIMPLE_RE.match(num) and _FRAC_SIMPLE_RE.match(den):
        return f"{num}/{den}"
    return f"({num})/({den})"


def _latex_to_text(s: str) -> str:
    """Convert LaTeX fraction/sqrt/boxed/text into a comparable text form.

    递归处理嵌套结构（如 \\frac{\\frac{1}{2}}{3}），使
    `1/2` 与 `\\frac{1}{2}`、`√2` 与 `\\sqrt{2}` 在归一化后可比。
    注意：这是"字符串等价"而非语义等价，超出（如 0.5 vs 1/2）留给 verifier。
    """
    s = _LATEX_NOARG.sub("", s)

    def read_group(text: str, start: int) -> tuple[str, int]:
        """从 start（'{' 处）读取配对 '{...}'，返回 (内容, '}' 之后下标)。

        调用方传入 '{' 所在下标，这里内部跳过它、depth 从 1 起，
        因此返回的内容不含首尾花括号。
        """
        depth = 1
        i = start + 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1
            i += 1
        return text[start + 1:], len(text)

    out = []
    i = 0
    while i < len(s):
        m = _LATEX_GROUP.match(s, i)
        if m:
            cmd = m.group(1)
            # _LATEX_GROUP 已消费到 '\cmd{'，m.end() 指向第一个参数的 '{' 之后。
            # read_group 期望从 '{' 开始读取 → 用 brace = m.end()-1（'{' 位置）。
            brace = i + m.end() - 1
            if brace < len(s) and s[brace] == "{":
                inner, nxt = read_group(s, brace)
                inner_t = _latex_to_text(inner)
                if cmd in ("frac", "dfrac", "tfrac"):
                    # \frac{a}{b} -> a/b（分子分母为简单量时不加括号，保证与 "1/2" 等价）
                    rest = s[nxt:]
                    if rest.startswith("{"):
                        denom, nxt2 = read_group(rest, 0)
                        denom_t = _latex_to_text(denom)
                        out.append(_frac_text(inner_t, denom_t))
                        i = nxt + nxt2
                    else:
                        out.append(inner_t)
                        i = nxt
                elif cmd == "sqrt":
                    # \sqrt[n]{x} 或 \sqrt{x}；简单量不加括号（√2 而非 √(2)）
                    rest = s[nxt:]
                    if rest.startswith("["):
                        end = rest.find("]")
                        if end != -1:
                            idx_t = _latex_to_text(rest[1:end])
                            out.append(f"√[{idx_t}]({inner_t})")
                            i = nxt + end + 1
                            continue
                    out.append(f"√{inner_t}" if _FRAC_SIMPLE_RE.match(inner_t)
                               else f"√({inner_t})")
                    i = nxt
                else:  # boxed / text / cfrac -> 直接取内部
                    out.append(inner_t)
                    i = nxt
                continue
        # 符号映射
        replaced = False
        for sym, val in _LATEX_SYM.items():
            if s.startswith(sym, i):
                out.append(val)
                i += len(sym)
                replaced = True
                break
        if replaced:
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def normalize_answer_text(s: str) -> str:
    """Normalize a final-answer text for exact comparison (whitespace/case-insensitive).

    覆盖：去除所有空白、统一小写、全角括号转半角，并将常见 LaTeX 结构
    （\\frac→/、\\sqrt→√、\\boxed/\\text 去壳）转成可比的文本形式。
    不做语义等价（如 0.5 与 1/2），超出范围的比对留给 verifier 判定。
    （数学/MATH 场景已放弃后，本函数仅作算法题 standard_answer 文本比对兜底。）
    """
    if not s:
        return s
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")
    s = _latex_to_text(s)
    return _WS_NORM_RE.sub("", s).lower()


class Pipeline:
    def __init__(self, config: Config, client: Hy3Client | None = None) -> None:
        self.config = config
        self.client = client or Hy3Client(
            api_key=config.hy3_api_key,
            base_url=config.hy3_base_url,
            model=config.hy3_model,
            reasoning_effort=config.hy3_reasoning_effort,
            max_retries=config.max_retries,
            timeout=config.timeout,
        )
        self.solver = SolverAgent(self.client)
        self.verifier = VerifierAgent(self.client)
        self.refiner = Refiner(self.solver, self.verifier)

    # -- eval mode ----------------------------------------------------------
    def run_eval(
        self,
        questions: list[QuestionItem],
        out_path: str | Path,
        resume: bool = True,
    ) -> list[EvalRecord]:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        done: dict[str, EvalRecord] = {}
        if resume and out.exists():
            for line in out.open(encoding="utf-8"):
                if line.strip():
                    rec = EvalRecord.model_validate_json(line)
                    done[rec.question_id] = rec
            log.info("resume: %d already done in %s", len(done), out)

        with out.open("a", encoding="utf-8") as f:
            for q in questions:
                if q.id in done:
                    continue
                try:
                    rec = self._eval_one(q)
                except Exception as e:  # noqa: BLE001
                    log.warning("eval %s failed: %s", q.id, e)
                    rec = EvalRecord(
                        question_id=q.id, scene=q.scene, difficulty=q.difficulty,
                        answer=_placeholder_answer(q.scene),  # 占位：运行失败无过程
                        verification=VerificationResult(verdict=Verdict.FAILED,
                                                        findings=[], confidence=0.0,
                                                        arbiter="FAILED"),
                        error=str(e),
                    )
                f.write(rec.model_dump_json() + "\n")
                f.flush()
                done[q.id] = rec
        return list(done.values())

    def _eval_one(self, q: QuestionItem,
                  progress: Callable[[str, object | None], None] | None = None,
                  on_step=None, on_reasoning=None) -> EvalRecord:
        """Evaluate one question.

        ``progress(phase, payload)``：可选阶段回调。phase 取值：
        "solve"(开始求解) → "answer"(完成，payload=Answer 可先展示) →
        "execute"(沙盒执行) → "static"(静态校验) → "verify"(过程评估)。
        供交互式界面实时展示进度（api 层 job 轮询/SSE 复用）。

        ``on_step``：可选流式回调，求解时逐片回调部分 Answer（交互演示逐 Step 显示）；
        不传则走原来的整段调用，正式评测口径不变。
        """
        from rex.executor.static_check import check_static, static_evidence_block, static_result_to_dict

        t0 = time.time()
        if progress:
            progress("solve", None)
        answer = self.solver.solve(q, on_step=on_step, on_reasoning=on_reasoning)
        if progress:
            progress("answer", answer)
        if progress:
            progress("execute", None)
        answer_correct, pass_rate, exec_err = self._execute(q, answer)
        # 静态规则校验：作为独立验证维度喂给 verifier（补充诊断，不改主判定）
        if progress:
            progress("static", None)
        static = check_static(q, answer)
        evidence = static_evidence_block(static)
        # 客观执行反馈：沙盒/比对结果是事实性证据，喂给 verifier 防止"答案错却判 CORRECT"
        exec_fb = _execution_feedback(q, answer_correct, pass_rate, exec_err)
        if progress:
            progress("verify", None)
        verification = self.verifier.verify(
            q, answer, static_evidence=evidence, execution_feedback=exec_fb,
            on_phase=lambda m: _emit(progress, "verify", None, f"过程交叉审查 · {m}"))
        # 程序化一致性裁决（有沙盒客观信号，是最终兜底层）：
        #   - 答案对 + fatal → SILENT_FAILURE；答案对 + 无 fatal → CORRECT（剥离 minor）
        #   - 答案错 → 绝不可能是 CORRECT/SILENT_FAILURE
        _reconcile_verdict(verification, answer_correct)
        # 编译/运行级失败兜底：执行反馈含编译/语法错误但 verifier 未定位时，程序化补一条
        # s4 fatal finding（指向 implement 步骤），保证"编译失败"类错误一定有可定位诊断，
        # 不依赖 LLM 自觉（曾出现 A1098 编译失败却 findings 空的情况）。
        if exec_err and _is_exec_failure(exec_err) and not verification.findings:
            verification.findings.append(ErrorFinding(
                step_id=4,
                error_type=ErrorType.OTHER,
                severity=ErrorSeverity.FATAL,
                detail=f"代码存在编译/运行级错误：{exec_err[:200]}",
                evidence="沙盒执行返回编译/运行错误（客观事实），对应 implement 步骤代码不可执行。",
            ))
            log.info("eval %s: 编译/运行失败未定位，程序化补充 s4 finding", q.id)
        rec = EvalRecord(
            question_id=q.id,
            scene=q.scene,
            difficulty=q.difficulty,
            answer=answer,
            answer_correct=answer_correct,
            test_pass_rate=pass_rate,
            verification=verification,
            static_check=static_result_to_dict(static),
            cost_calls=self.client.call_count,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        log.info("eval %s: verdict=%s ans=%s pass=%s (%.1fs)",
                 q.id, verification.verdict.value, answer_correct, pass_rate,
                 time.time() - t0)
        return rec

    # -- re-verify mode -----------------------------------------------------
    def reverify_one(self, q: QuestionItem, answer: Answer) -> EvalRecord:
        """单条重判定：复用已有 answer（不重跑 solver），重新走执行/静态/验证。

        用途：verifier 判定口径升级（如 severity 重构）后，对既有 eval 记录
        只重判 verdict/findings——solver 产物不变、沙盒答案结果不变，但
        verification 由新口径 verifier 重新生成。

        - execute/static 客观部分仍重算（沙盒 answer_correct 不变，保证记录自洽；
          静态校验代码已更新 C++ 检测，重算以获得最新规则诊断）。
        - verify → reconcile 走完整程序化一致性裁决（severity 语义）。
        - 不修改 question 的已有判定来源；由调用方决定写盘位置。
        """
        from rex.executor.static_check import check_static, static_evidence_block, static_result_to_dict

        answer_correct, pass_rate, exec_err = self._execute(q, answer)
        static = check_static(q, answer)
        evidence = static_evidence_block(static)
        exec_fb = _execution_feedback(q, answer_correct, pass_rate, exec_err)
        verification = self.verifier.verify(q, answer, static_evidence=evidence,
                                            execution_feedback=exec_fb)
        _reconcile_verdict(verification, answer_correct)
        if exec_err and _is_exec_failure(exec_err) and not verification.findings:
            verification.findings.append(ErrorFinding(
                step_id=4,
                error_type=ErrorType.OTHER,
                severity=ErrorSeverity.FATAL,
                detail=f"代码存在编译/运行级错误：{exec_err[:200]}",
                evidence="沙盒执行返回编译/运行错误（客观事实），对应 implement 步骤代码不可执行。",
            ))
            log.info("reverify %s: 编译/运行失败未定位，程序化补充 s4 finding", q.id)
        return EvalRecord(
            question_id=q.id,
            scene=q.scene,
            difficulty=q.difficulty,
            answer=answer,
            answer_correct=answer_correct,
            test_pass_rate=pass_rate,
            verification=verification,
            static_check=static_result_to_dict(static),
            cost_calls=self.client.call_count,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    # -- refine mode --------------------------------------------------------
    def run_refine(
        self,
        questions: list[QuestionItem],
        out_path: str | Path,
        resume: bool = True,
    ) -> list[RefineRecord]:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        done: dict[str, RefineRecord] = {}
        if resume and out.exists():
            for line in out.open(encoding="utf-8"):
                if line.strip():
                    rec = RefineRecord.model_validate_json(line)
                    done[rec.question_id] = rec
            log.info("resume: %d already done in %s", len(done), out)

        with out.open("a", encoding="utf-8") as f:
            for q in questions:
                if q.id in done:
                    continue
                try:
                    rec = self.refiner.refine(q)
                except Exception as e:  # noqa: BLE001
                    log.warning("refine %s failed: %s", q.id, e)
                    rec = RefineRecord(
                        question_id=q.id, scene=q.scene, difficulty=q.difficulty,
                        initial=VerificationResult(verdict=Verdict.FAILED,
                                                   findings=[], confidence=0.0,
                                                   arbiter="FAILED"),
                        final=VerificationResult(verdict=Verdict.FAILED,
                                                 findings=[], confidence=0.0,
                                                 arbiter="FAILED"),
                        converged=False, error=str(e),
                    )
                f.write(rec.model_dump_json() + "\n")
                f.flush()
                done[q.id] = rec
        return list(done.values())

    # -- shared executor hook ----------------------------------------------
    def _execute(self, q: QuestionItem, answer: Answer) -> tuple[bool | None, float | None, str | None]:
        """沙盒执行 + 答案比对（算法竞赛场景）。

        Returns (answer_correct, test_pass_rate, exec_error).
        有代码+用例：跑测试用例；无用例时仅比对 standard_answer 文本。
        """
        if answer.code and q.test_cases:
            from rex.executor.sandbox import detect_language
            lang = detect_language(answer.code)
            res = run_test_cases(
                answer.code, q.test_cases,
                language=lang,
                judge=q.judge, checker_code=q.checker_code,
                checker_language=q.checker_language,
            )
            return (res.pass_rate >= 1.0), res.pass_rate, res.error
        if q.standard_answer and answer.final_answer:
            return normalize_answer_text(answer.final_answer) == normalize_answer_text(q.standard_answer), None, None
        return None, None, None


def _reconcile_verdict(verification: VerificationResult,
                       answer_correct: bool | None) -> None:
    """程序化一致性裁决：以沙盒客观信号 + findings severity 强制 verdict 语义一致。

    （severity 语义见 models.ErrorSeverity；此函数是最终兜底，LLM 的判定
    可能自相矛盾——这里把它纠正到任务书口径。）

    规则：
    1. 答案客观正确（answer_correct=True）：
       - 存在 fatal finding → verdict 不得是 CORRECT/ANSWER_INCORRECT，
         统一为 SILENT_FAILURE（答案对但过程有实质缺陷）。
       - 无 fatal finding（全 minor 或空）→ verdict 强制 CORRECT
         （剥离"minor 被 LLM 提升为过程错误"的误报）。
    2. 答案客观错误（answer_correct=False）：
       - verdict 不可能是 CORRECT/SILENT_FAILURE（沙盒已证伪答案）：
         存在 fatal → PROCESS_INCORRECT；无 fatal → ANSWER_INCORRECT。
    3. answer_correct is None（无沙盒信号）：不动 LLM 判定（无客观依据）。

    执行反馈未注入时（pass_rate 未知的文本比对场景），verdict 仍由
    LLM 判定保留，此函数仅在 answer_correct 客观已知时生效。
    """
    if answer_correct is None:
        return
    has_fatal = any(
        getattr(f, "severity", ErrorSeverity.FATAL) == ErrorSeverity.FATAL
        for f in verification.findings
    )
    v = verification.verdict
    if answer_correct is True:
        if has_fatal and v in (Verdict.CORRECT, Verdict.ANSWER_INCORRECT):
            verification.verdict = Verdict.SILENT_FAILURE
            log.info("reconcile: 答案正确且存在 fatal finding，%s → SILENT_FAILURE", v.value)
        elif not has_fatal and v in (Verdict.PROCESS_INCORRECT, Verdict.SILENT_FAILURE):
            verification.verdict = Verdict.CORRECT
            log.info("reconcile: 答案正确且无 fatal finding，%s → CORRECT（剥离 minor）", v.value)
    elif answer_correct is False:
        if v == Verdict.CORRECT:
            verification.verdict = Verdict.ANSWER_INCORRECT
            log.info("reconcile: 答案客观错误但 LLM 判 CORRECT，→ ANSWER_INCORRECT")
        elif v == Verdict.SILENT_FAILURE:
            # SILENT_FAILURE 语义要求答案正确，客观已证伪 → 按是否 fatal 归类
            verification.verdict = Verdict.PROCESS_INCORRECT if has_fatal else Verdict.ANSWER_INCORRECT
            log.info("reconcile: 答案客观错误但判 SILENT_FAILURE，→ %s",
                     verification.verdict.value)


def _execution_feedback(
    q: QuestionItem,
    answer_correct: bool | None,
    pass_rate: float | None,
    exec_err: str | None,
) -> str | None:
    """把客观执行结果格式化为 verifier 可读的反馈文本（供 prompt 引用）。

    算法场景：给出测试用例通过率/失败原因（无用例时给出文本比对结果）。
    返回 None 表示无客观结果（answer_correct 未知），不注入反馈。
    """
    if answer_correct is None:
        return None
    if pass_rate is None:
        return None
        return None
    if answer_correct:
        return f"沙盒执行：全部 {int(round(pass_rate * 100))}% 测试用例通过（公开+隐藏）。"
    why = f"（运行错误：{(exec_err or '')[:120]}）" if exec_err else ""
    return f"沙盒执行：测试用例通过率 {pass_rate:.0%}，最终答案未通过全部用例{why}。"


def _is_exec_failure(exec_err: str) -> bool:
    """判断执行错误是否为编译/运行级失败（非普通 WA）。

    用于程序化兜底：这类错误说明代码本身不可执行（语法/编译错误、崩溃、
    超时），应定位到 implement 步骤，而非静默判"答案错"无诊断。
    """
    low = (exec_err or "").lower()
    markers = ("compile", "syntax", "compile failed", "error:", "traceback",
               "timeout", "segmentation", "returncode")
    return any(m in low for m in markers)


def _placeholder_answer(scene: str = "algorithm") -> Answer:
    """合法占位 Answer：运行失败时无真实过程，但仍满足 steps 契约。"""
    return Answer(
        steps=[Step(id=0, kind="understand", content="运行失败，无有效过程",
                    conclusion="无", deps=[])],
        final_answer="",
    )


def load_jsonl(path: str | Path, model) -> list:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [model.model_validate_json(line) for line in f if line.strip()]


def dump_jsonl(items: list, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(it.model_dump_json() + "\n")
