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

from rex.config import Config
from rex.executor.tests import run_test_cases
from rex.hy3_client import Hy3Client
from rex.models import (
    Answer,
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

_MATH_NORM_RE = re.compile(r"\s+")
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


def normalize_math_answer(s: str) -> str:
    """Normalize a math answer for exact comparison (whitespace/case-insensitive).

    覆盖：去除所有空白、统一小写、全角括号转半角，并将常见 LaTeX 结构
    （\\frac→/、\\sqrt→√、\\boxed/\\text 去壳）转成可比的文本形式。
    不做语义等价（如 1/2 与 0.5），超出范围的比对留给 verifier 判定。
    """
    if not s:
        return s
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")
    s = _latex_to_text(s)
    return _MATH_NORM_RE.sub("", s).lower()


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

    def _eval_one(self, q: QuestionItem) -> EvalRecord:
        t0 = time.time()
        answer = self.solver.solve(q)
        answer_correct, pass_rate, _ = self._execute(q, answer)
        verification = self.verifier.verify(q, answer)
        rec = EvalRecord(
            question_id=q.id,
            scene=q.scene,
            difficulty=q.difficulty,
            answer=answer,
            answer_correct=answer_correct,
            test_pass_rate=pass_rate,
            verification=verification,
            cost_calls=self.client.call_count,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        log.info("eval %s: verdict=%s ans=%s pass=%s (%.1fs)",
                 q.id, verification.verdict.value, answer_correct, pass_rate,
                 time.time() - t0)
        return rec

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
        """沙盒执行 + 答案比对。

        Returns (answer_correct, test_pass_rate, exec_error).
        - 数学场景：比对 standard_answer（无法比对时 answer_correct=None）
        - 算法场景：运行测试用例（无用例时仅比对 standard_answer 文本）
        """
        if q.scene == "math":
            if q.standard_answer and answer.final_answer:
                ok = normalize_math_answer(answer.final_answer) == normalize_math_answer(q.standard_answer)
                return ok, None, None
            return None, None, None
        # algorithm
        if answer.code and q.test_cases:
            res = run_test_cases(answer.code, q.test_cases)
            return (res.pass_rate >= 1.0), res.pass_rate, res.error
        if q.standard_answer and answer.final_answer:
            return normalize_math_answer(answer.final_answer) == normalize_math_answer(q.standard_answer), None, None
        return None, None, None


def _placeholder_answer(scene: str) -> Answer:
    """合法占位 Answer：运行失败时无真实过程，但仍满足 steps 契约。"""
    kind = "derive" if scene == "math" else "understand"
    return Answer(
        steps=[Step(id=0, kind=kind, content="运行失败，无有效过程",
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
