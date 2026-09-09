"""Unified contracts (pydantic) across solver -> verifier -> refine -> executor.

These models are the single source of truth for every JSON blob exchanged
between pipeline stages (DESIGN.md §3 contract-first). Keep them minimal and
stable — changing them ripples through the whole pipeline.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Solver output (also refined rounds)
# ---------------------------------------------------------------------------
class Step(BaseModel):
    id: int
    # 算法竞赛步骤类型（数学/MATH 场景已放弃，2026-09-03）
    kind: Literal[
        "understand", "approach", "complexity", "implement", "selftest",
    ]
    content: str       # 本步文本（推导/代码/说明）
    conclusion: str    # 本步结论（供自含性检查）
    deps: list[int] = Field(default_factory=list)  # 依赖的前置步骤 id（供全局回溯）


class Answer(BaseModel):
    steps: list[Step] = Field(min_length=1)  # 过程评估：空步骤视为非法答案
    final_answer: str
    code: str | None = None  # implement 步骤的完整代码


# ---------------------------------------------------------------------------
# Verifier output
# ---------------------------------------------------------------------------
class ErrorType(str, Enum):
    """6 类基线（任务书要求）+ 场景扩展。"""

    MISREAD = "misread"                    # 题意误读
    CONCEPT = "concept"                    # 概念理解错误
    CALCULATION = "calculation"            # 计算错误
    MISSING_CONDITION = "missing_condition"  # 条件遗漏
    JUMP = "jump"                          # 跳步推导
    FORMAT = "format"                      # 格式不符
    LOGIC = "logic"                        # 逻辑缺陷（扩展）
    BOUNDARY = "boundary"                  # 边界条件（扩展）
    COMPLEXITY = "complexity"              # 复杂度不达标（扩展）
    OTHER = "other"                        # 其他


class ErrorSeverity(str, Enum):
    """缺陷严重度（过程评估判定的核心分层）：

    - FATAL: 破坏推理链成立性/算法正确性的实质缺陷——只有 FATAL 才驱动
      PROCESS_INCORRECT / SILENT_FAILURE / ANSWER_INCORRECT 判定。
    - MINOR: 不影响推理链成立性的轻微瑕疵（表述笔误、自测文字错误、
      可重建的常规论证省略、复杂度叙述不精确但结论仍成立等）——仅记录，
      不驱动非 CORRECT 判定。
    """
    FATAL = "fatal"
    MINOR = "minor"


class ErrorFinding(BaseModel):
    step_id: int
    error_type: ErrorType
    detail: str        # 问题描述
    evidence: str      # 判定依据（可解释，供仲裁与人工复核）
    severity: ErrorSeverity = ErrorSeverity.FATAL  # 默认 fatal：无标注时按实质缺陷处理


class Verdict(str, Enum):
    CORRECT = "CORRECT"                     # 过程与答案均正确
    PROCESS_INCORRECT = "PROCESS_INCORRECT" # 过程有问题（答案可能对也可能错）
    ANSWER_INCORRECT = "ANSWER_INCORRECT"   # 最终答案错误
    SILENT_FAILURE = "SILENT_FAILURE"       # 答案正确但过程不成立
    FAILED = "FAILED"                       # 运行失败（网络/超时等，无有效判定）


class VerificationResult(BaseModel):
    verdict: Verdict
    findings: list[ErrorFinding] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    arbiter: Literal["V1", "V2", "ARBITER", "HUMAN_REVIEW", "FAILED"] = "ARBITER"
    timestamp: float | None = None  # epoch 秒，供耗时分析


# ---------------------------------------------------------------------------
# Refine (ReAct loop) contracts
# ---------------------------------------------------------------------------
class RefineFeedback(BaseModel):
    step_id: int | None
    error_type: ErrorType
    instruction: str   # 映射为可操作修订指令："第 N 步存在 X 问题，请……"
    evidence: str


class RefineRound(BaseModel):
    round_no: int
    revised_answer: Answer
    feedbacks: list[RefineFeedback]
    verification: VerificationResult
    cost_calls: int = 0  # 本轮模型调用数（逐轮预算核算）


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
class Difficulty(str, Enum):
    BASIC = "basic"
    MEDIUM = "medium"
    HARD = "hard"


class TestCase(BaseModel):
    __test__ = False  # pytest 收集约定：避免与测试类名混淆
    input: str
    output: str
    hidden: bool = False  # hidden 用例不随仓库公开（评测时注入）


class Judge(str, Enum):
    """算法题判题模式。

    - EXACT: 输出唯一，比对期望文本（含浮点容差，见 executor/tests.py）
    - SPECIAL: 多解/构造题，跑 checker 判定输出是否满足题目谓词（SPJ）
    """

    EXACT = "exact"
    SPECIAL = "special"


class QuestionItem(BaseModel):
    """题集 JSONL 一条记录（data/questions/*.jsonl）。"""

    id: str                       # 题号，如 A001
    scene: Literal["algorithm"]
    title: str
    prompt: str                   # 完整题目文本
    difficulty: Difficulty
    source: str                   # 来源：TACO/CodeForces(镜像)/AtCoder-自编/自编
    source_id: str | None = None  # 原数据集 id（可复现溯源）
    layer_basis: str = ""         # 分层依据说明（可复现分层规则表）
    standard_answer: str          # 标准答案（算法：期望输出/参考文本）
    reference_solution: str | None = None
    test_cases: list[TestCase] = Field(default_factory=list)  # 算法场景
    metadata: dict = Field(default_factory=dict)
    # ---- 判题模式（多解构造题支持）----
    judge: Judge = Judge.EXACT          # 默认精确比对；special 时走 checker
    checker_code: str | None = None     # special 判定程序源码
    checker_language: Literal["python", "cpp"] = "python"


# ---------------------------------------------------------------------------
# Pipeline run records (data/outputs/)
# ---------------------------------------------------------------------------
class EvalRecord(BaseModel):
    """单题评估运行完整记录（eval 模式）。"""

    question_id: str
    scene: Literal["algorithm"] = "algorithm"
    difficulty: Difficulty
    answer: Answer
    answer_correct: bool | None = None    # 沙盒/精确比对结果
    test_pass_rate: float | None = None   # 算法场景用例通过率
    verification: VerificationResult
    static_check: dict | None = None      # 静态规则校验结果（static_check.py，作为补充诊断）
    # 有效性验证字段
    process_ok: bool | None = None        # 人工抽检/判定后回填
    located_step: int | None = None       # 实际出错步骤（人工抽检回填）
    located_hit: bool | None = None       # 定位命中
    is_false_positive: bool | None = None  # 误报标记
    cost_calls: int = 0
    created_at: str | None = None         # ISO 时间戳（结果文件追加式，先建字段成本最低）
    source: str = "run-eval"              # 记录来源：run-eval（批量）/ interactive（交互式解题）
    error: str | None = None              # 运行失败原因


class RefineRecord(BaseModel):
    """单题 refine 模式运行记录（含修正轮次轨迹）。"""

    question_id: str
    scene: Literal["algorithm"] = "algorithm"
    difficulty: Difficulty
    initial: VerificationResult
    rounds: list[RefineRound] = Field(default_factory=list)
    final: VerificationResult
    converged: bool                       # 是否在限轮内达成 CORRECT
    cost_calls: int = 0
    created_at: str | None = None         # ISO 时间戳
    source: str = "run-eval"              # 记录来源：run-eval（批量）/ interactive（交互式解题）
    error: str | None = None


class HumanSeverityMatch(str, Enum):
    """人工抽检对「系统 fatal/minor 分级」的三层复核结论。

    人工抽检的对象不是 AI 解题本身，而是**系统判定准不准**——即 verifier
    给出的 verdict 与每条 finding 的 severity(fatal/minor) 是否属实。三层结论：

    - MATCH（完全相符）  : 系统对 fatal/minor 的分级与实际一致——系统判
      PROCESS_INCORRECT/SILENT_FAILURE 确有 fatal（或判 CORRECT 确无 fatal）。
      系统审查正确 → 非误报、非漏检。
    - LEVEL_MISMATCH（层次不符）: 系统方向对但分级打反——确有缺陷但严重级错了
      （如系统把 minor 瑕疵判成 fatal，或把 fatal 判成 minor）。
      fatal→minor 属漏检侧（本应驱动非 CORRECT 却放行）；
      minor→fatal 属误报侧（主口径误报、副口径不计）。
    - FP（完全不符）    : 系统说有错实际过程正确（或说正确实际有致命缺陷），
      与真实完全相反 → 主/副口径均计误报。
    """

    MATCH = "match"
    LEVEL_MISMATCH = "level_mismatch"
    FP = "fp"


class AuditRecord(BaseModel):
    """人工抽检标注记录（data/outputs/audit_records.jsonl）。

    模板由 scripts/audit_sample.py 生成，标注字段人工回填。
    主判定字段为 human_severity_match（三层：match/level_mismatch/fp）；
    旧字段 is_false_positive / human_error_severity 仅用于兼容历史标注，
    新标注请直接填 human_severity_match。
    """

    question_id: str
    verdict_human: Verdict | None = None
    error_step_id: int | None = None       # 真实错误起始步骤
    error_type_human: ErrorType | None = None
    human_severity_match: HumanSeverityMatch | None = None  # 三层复核结论（主字段）
    is_false_positive: bool | None = None  # [兼容] 系统误报标记（旧字段，新标注不用）
    human_error_severity: Literal["none", "minor", "fatal"] | None = None
    # [兼容] 旧字段：none/minor/fatal，见 HumanSeverityMatch 说明；新标注用上面的三层
    note: str = ""
    audited_by: str = ""
    audited_at: str | None = None


class GoldenSample(BaseModel):
    """沉默失败 golden 样本：答案正确但过程存在根本缺陷（陷阱样本）。

    用于验证评估器能否检出 SILENT_FAILURE，而非让 solver 求解。
    """

    question: QuestionItem                # 题目（含标准答案/参考解）
    flaw_answer: Answer                   # 陷阱解题过程：答案正确但过程有缺陷
    flaw_type: ErrorType                  # 缺陷类型
    construction_note: str                # 构造说明：覆盖哪类沉默失败
    expected_verdict: Verdict = Verdict.SILENT_FAILURE
