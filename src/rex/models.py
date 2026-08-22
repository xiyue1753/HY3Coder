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
    # 算法: understand/approach/complexity/implement/selftest
    # 数学: derive/calc/check
    kind: Literal[
        "understand", "approach", "complexity", "implement", "selftest",
        "derive", "calc", "check",
    ]
    content: str       # 本步文本（推导/代码/说明）
    conclusion: str    # 本步结论（供自含性检查）
    deps: list[int] = Field(default_factory=list)  # 依赖的前置步骤 id（供全局回溯）


class Answer(BaseModel):
    steps: list[Step] = Field(min_length=1)  # 过程评估：空步骤视为非法答案
    final_answer: str
    code: str | None = None  # implement 步骤的完整代码（算法场景）


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


class ErrorFinding(BaseModel):
    step_id: int
    error_type: ErrorType
    detail: str        # 问题描述
    evidence: str      # 判定依据（可解释，供仲裁与人工复核）


class Verdict(str, Enum):
    CORRECT = "CORRECT"                     # 过程与答案均正确
    PROCESS_INCORRECT = "PROCESS_INCORRECT" # 过程有问题（答案可能对也可能错）
    ANSWER_INCORRECT = "ANSWER_INCORRECT"   # 最终答案错误
    SILENT_FAILURE = "SILENT_FAILURE"       # 答案正确但过程不成立


class VerificationResult(BaseModel):
    verdict: Verdict
    findings: list[ErrorFinding] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    arbiter: Literal["V1", "V2", "ARBITER", "HUMAN_REVIEW"] = "ARBITER"
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


class QuestionItem(BaseModel):
    """题集 JSONL 一条记录（data/questions/*.jsonl）。"""

    id: str                       # 题号，如 A001 / M042
    scene: Literal["algorithm", "math"]
    title: str
    prompt: str                   # 完整题目文本
    difficulty: Difficulty
    source: str                   # 来源：TACO/CodeContests/MATH/自编
    source_id: str | None = None  # 原数据集 id（可复现溯源）
    layer_basis: str = ""         # 分层依据说明（可复现分层规则表）
    standard_answer: str          # 标准答案（数学：精确值；算法：参考输出）
    reference_solution: str | None = None
    test_cases: list[TestCase] = Field(default_factory=list)  # 算法场景
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline run records (data/outputs/)
# ---------------------------------------------------------------------------
class EvalRecord(BaseModel):
    """单题评估运行完整记录（eval 模式）。"""

    question_id: str
    scene: Literal["algorithm", "math"]
    difficulty: Difficulty
    answer: Answer
    answer_correct: bool | None = None    # 沙盒/精确比对结果
    test_pass_rate: float | None = None   # 算法场景用例通过率
    verification: VerificationResult
    # 有效性验证字段
    process_ok: bool | None = None        # 人工抽检/判定后回填
    located_step: int | None = None       # 实际出错步骤（人工抽检回填）
    located_hit: bool | None = None       # 定位命中
    is_false_positive: bool | None = None  # 误报标记
    cost_calls: int = 0
    created_at: str | None = None         # ISO 时间戳（结果文件追加式，先建字段成本最低）
    error: str | None = None              # 运行失败原因


class RefineRecord(BaseModel):
    """单题 refine 模式运行记录（含修正轮次轨迹）。"""

    question_id: str
    scene: Literal["algorithm", "math"]
    difficulty: Difficulty
    initial: VerificationResult
    rounds: list[RefineRound] = Field(default_factory=list)
    final: VerificationResult
    converged: bool                       # 是否在限轮内达成 CORRECT
    cost_calls: int = 0
    created_at: str | None = None         # ISO 时间戳
    error: str | None = None


class AuditRecord(BaseModel):
    """人工抽检标注记录（data/outputs/audit_records.jsonl）。

    模板由 scripts/audit_sample.py 生成，标注字段人工回填。
    """

    question_id: str
    verdict_human: Verdict | None = None
    error_step_id: int | None = None       # 真实错误起始步骤
    error_type_human: ErrorType | None = None
    is_false_positive: bool | None = None  # 系统误报标记
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
