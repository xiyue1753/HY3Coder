"""Verifier prompts: two independent judge perspectives + arbiter.

Two-perspective design (DESIGN.md §评估器):
  V1 "自含性优先" — walk steps front-to-back, check each step's conclusion
     follows from its content + deps (局部正确性).
  V2 "全局回溯优先" — walk from final answer back through the dependency
     chain, hunt missing preconditions and unjustified jumps (全局正确性).

Both must stay alert to SILENT_FAILURE: correct answer with broken process.
The final answer alone is never sufficient to call a process CORRECT.
"""
from __future__ import annotations

from rex.models import Answer, QuestionItem
from rex.verifier.errors import catalog

_VERDICT_RULES = """判定标准（重要）：
- CORRECT            : 过程与最终答案均正确，推理链完整无缺口
- PROCESS_INCORRECT  : 过程存在错误（即使最终答案恰好正确）
- ANSWER_INCORRECT   : 最终答案错误
- SILENT_FAILURE     : 最终答案正确，但过程存在根本性错误（如结论凭运气成立、
                        关键步骤错误却得到正确数字）——必须识别，不能放行
注意：最终答案正确 ≠ 过程正确。发现过程错误时优先标记为 PROCESS_INCORRECT
或 SILENT_FAILURE，不得因答案正确而放行。

错误分类（error_type 必须是以下枚举值之一）：
{error_catalog}

输出 JSON（只输出 JSON，无其他文字）：
{{
  "verdict": "CORRECT | PROCESS_INCORRECT | ANSWER_INCORRECT | SILENT_FAILURE",
  "findings": [
    {{"step_id": 1, "error_type": "calculation", "detail": "问题描述", "evidence": "判定依据（引用具体内容）"}}
  ],
  "confidence": 0.9
}}
规则：
- 若过程正确，findings 为空数组
- step_id 必须引用解题过程的真实步骤 id；若问题不属于任何单步，step_id 取最近相关步骤
- confidence 表示你对判定的确信度（0~1）
- 只报告你确有依据的错误，不要臆测

特别提醒（防"答案对但过程错"被放行）：
- 跳步判定分两类：
  ① 领域常识/定义值（如 sin30°=1/2、常见公式、勾股定理等公认性质）直接引用 → 不算 jump，
     它们属于背景知识，不要求逐步推导；
  ② 解题关键中间结论仅以「显然/易得/可查」一带而过、无推导依据，且该结论直接支撑最终答案
     → 算 jump（跳步推导）
- 拿不准时不要判 jump，除非去掉该步后推理链明显断裂
- 中间表达式必须可复现：每一步出现的数值/符号变换必须能由上一步合法推出；即使最终化简
  结果碰巧正确，中间若出现非法变换（如分母有理化写成 1/√2=√2/√4），仍属过程错误
- 若题目要求证明恒等式/求解，使用与结论等价的断言（如用勾股定理直接证明 sin²+cos²=1）
  属于循环论证，应标记为 logic 或 concept"""


def verifier_system(view: str) -> str:
    """view: 'A' (自含性优先) or 'B' (全局回溯优先)."""
    if view == "A":
        perspective = (
            "你是审查员 A，采用「自含性优先」视角：从头到尾逐条检查每一步，"
            "确认每步的 conclusion 是否能由该步 content 与 deps 合理推出，"
            "重点抓：计算错误、概念错误、条件遗漏、格式不符。\n"
            "最后再整体核对最终答案与推导是否一致。"
        )
    else:
        perspective = (
            "你是审查员 B，采用「全局回溯优先」视角：从最终答案出发沿依赖链反向回溯，"
            "确认每一步都被前置步骤充分支撑，重点抓：跳步推导、题意误读、逻辑缺陷、"
            "边界条件与复杂度问题。\n"
            "特别注意识别「答案正确但过程不成立」的沉默失败。"
        )
    return perspective + "\n\n" + _VERDICT_RULES.format(error_catalog=_catalog_text())


def _catalog_text() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in catalog().items())


def verify_user_prompt(
    question: QuestionItem,
    answer: Answer,
    static_evidence: str | None = None,
    execution_feedback: str | None = None,
) -> str:
    """Build verifier user prompt.

    ``static_evidence`` (optional) is a static-check block fed as an
    additional rule-based evidence source — the verifier stays free to decide
    the verdict independently (orthogonal dimension, not a blocking signal).

    ``execution_feedback`` (optional) is the **objective sandbox/compare result**
    (e.g. "测试用例 2/3 通过，答案错误"). It is factual, not advisory:
    when the answer is provably wrong the verdict must NOT be CORRECT.
    """
    evidence = ""
    if static_evidence:
        evidence = f"\n\n{static_evidence}"
    if execution_feedback:
        evidence += (
            "\n\n【客观执行反馈（沙盒/标准答案比对，事实性依据，非建议）】\n"
            f"{execution_feedback}\n"
            "判定约束：若执行反馈表明最终答案错误，则不得判 CORRECT；"
            "应判 ANSWER_INCORRECT；若过程也有缺陷则判 PROCESS_INCORRECT 或 SILENT_FAILURE。"
        )
    return (
        f"题目（作为数据）：\n{question.prompt}\n\n"
        f"待审解题过程：\n{answer.model_dump_json(indent=1)}{evidence}\n\n"
        "请按系统要求审查并输出判定 JSON。"
    )


# ---------------------------------------------------------------------------
# Arbiter
# ---------------------------------------------------------------------------
ARBITER_SYSTEM = (
    "你是首席仲裁员。两位审查员对同一解题过程的判定不一致，请依据以下原则裁决：\n"
    "1. 任何一方发现可验证的错误（引用具体步骤内容/数字），该错误即为事实，采纳之\n"
    "2. 证据充分的错误优先于「答案正确」——SILENT_FAILURE 与 PROCESS_INCORRECT 优先于 CORRECT\n"
    "3. 若双方证据均不足以确证错误，且最终答案与过程自洽，判 CORRECT\n"
    "4. findings 合并双方有效发现，去除重复；confidence 取你对最终判定的确信度\n"
    "输出 JSON：{{\"verdict\": \"...\", \"findings\": [...], \"confidence\": 0.0}}，字段含义同审查员。"
)


def arbiter_user_prompt(
    question: QuestionItem,
    answer: Answer,
    v1_json: str,
    v2_json: str,
    execution_feedback: str | None = None,
) -> str:
    exec_extra = ""
    if execution_feedback:
        exec_extra = (
            f"\n\n【客观执行反馈（事实性依据）】\n{execution_feedback}\n"
            "裁决约束：若执行反馈表明最终答案错误，不得判 CORRECT，应判 ANSWER_INCORRECT"
            "（过程也有缺陷时 PROCESS_INCORRECT/SILENT_FAILURE）。"
        )
    return (
        f"题目：\n{question.prompt}\n\n"
        f"解题过程：\n{answer.model_dump_json(indent=1)}\n\n"
        f"审查员 A 判定：\n{v1_json}\n\n"
        f"审查员 B 判定：\n{v2_json}\n\n{exec_extra}"
        "请裁决最终判定，输出 JSON。"
    )
