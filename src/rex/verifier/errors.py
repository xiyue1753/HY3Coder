"""Error taxonomy: 6 baseline types (任务书) + scene extensions.

The taxonomy drives three things:
  1. verifier prompts (which error classes the judge must look for)
  2. refine feedback mapping (error_type -> actionable revision instruction)
  3. reporting (error-type distribution, capability profile weak spots)
"""
from __future__ import annotations

from rex.models import ErrorType

# name -> (判定说明, 典型示例)
_ERROR_CATALOG: dict[ErrorType, tuple[str, str]] = {
    ErrorType.MISREAD: (
        "题意误读：理解错误地解读了输入格式、输出要求或问题目标",
        "把整数坐标当成浮点数；把求最大值当成求和",
    ),
    ErrorType.CONCEPT: (
        "概念理解错误：使用了错误的公式/定理/数据结构或对概念理解偏差",
        "误用费马小定理；混淆时间复杂度的均摊与最坏情况",
    ),
    ErrorType.CALCULATION: (
        "计算错误：代数、算术、代入或代码中的数值计算错误",
        "2*2=9；数组下标越界却继续计算；分数化简错误",
    ),
    ErrorType.MISSING_CONDITION: (
        "条件遗漏：忽略了题目中的边界条件、特殊情形或附加约束",
        "未处理 n=0；未考虑负数输入；遗漏模数取余要求",
    ),
    ErrorType.JUMP: (
        "跳步推导：推理链存在缺口，某步结论无法由前置步骤推出",
        "直接给出结果未说明中间推导；断言等价于未证明的事实",
    ),
    ErrorType.FORMAT: (
        "格式不符：最终答案或输出格式不符合题目要求",
        "输出带多余空格/换行；答案未化简；保留位数错误",
    ),
    ErrorType.LOGIC: (
        "逻辑缺陷（扩展）：算法或证明的思路存在根本性错误，即便结果碰巧正确",
        "贪心策略不成立；归纳假设错误；代码逻辑分支缺失",
    ),
    ErrorType.BOUNDARY: (
        "边界条件（扩展）：未覆盖输入边界的处理，导致极端输入下错误",
        "单元素数组；极大数值溢出；空输入",
    ),
    ErrorType.COMPLEXITY: (
        "复杂度不达标（扩展）：算法复杂度超出题目数据范围允许的上限",
        "n≤1e5 却用 O(n²)；未利用题目暗示的优化空间",
    ),
    ErrorType.OTHER: ("其他无法归入以上类别的错误", ""),
}

# 判定优先级（报告/仲裁用）：数字越小越优先作为"根本错误"
_ORDER = {et: i for i, et in enumerate(ErrorType)}


def describe(error_type: ErrorType) -> str:
    desc, example = _ERROR_CATALOG[error_type]
    return f"{desc}（示例：{example}）" if example else desc


def catalog() -> dict[str, str]:
    return {et.value: describe(et) for et in ErrorType}


def root_cause(findings: list) -> ErrorType | None:
    """Pick the most fundamental error among findings (lowest order number)."""
    if not findings:
        return None
    return min((f.error_type for f in findings), key=lambda et: _ORDER.get(et, 99))
