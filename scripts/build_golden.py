"""Build the golden silent-failure sample library under data/golden/.

Silent failure = 最终答案正确但解题过程存在根本缺陷（评估器的核心挑战）。
合成样本构造「陷阱过程」：答案对、过程错，且明确标注缺陷类型与构造思路，
用于验证评估器能否检出 SILENT_FAILURE 而非被正确答案误导。

样本策略（用户决策 2026-09-04）:
    合成陷阱库只保留 2 条展示样例（GA001 边界、GA002 set 无序），
    主要靠真实评测检出库 golden_real_algorithm.jsonl（真实模型的
    SILENT_FAILURE 样本，见 scripts/build_golden_real.py）。
    原 15 条全量合成构造已从本脚本移除（历史见 git）。

产出:
    data/golden/golden_algorithm.jsonl  (2 条展示样例)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.models import (  # noqa: E402
    Answer,
    Difficulty,
    ErrorType,
    GoldenSample,
    QuestionItem,
    Step,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "data" / "golden"


def algo_question(qid: str, prompt: str, answer: str, cases: list[tuple[str, str]] | None = None) -> QuestionItem:
    from rex.models import TestCase
    return QuestionItem(
        id=qid, scene="algorithm", title=prompt[:50], prompt=prompt,
        difficulty=Difficulty.BASIC, source="自编", standard_answer=answer,
        test_cases=[TestCase(input=i, output=o) for i, o in (cases or [])],
        metadata={"golden": True},
    )


def gs(question: QuestionItem, flaw_type: ErrorType, note: str,
       steps: list[Step], final_answer: str) -> GoldenSample:
    return GoldenSample(
        question=question,
        flaw_answer=Answer(steps=steps, final_answer=final_answer),
        flaw_type=flaw_type,
        construction_note=note,
    )


def build_algorithm() -> list[GoldenSample]:
    S: list[GoldenSample] = []

    # 1. 概念错误：1 被误判为质数；约束 1≤n 使 n=1 成为合法输入，
    #    但公开用例恰好只覆盖 n≥2（2/17/21），缺陷在用例上不暴露 → 静默失败有效
    q = algo_question(
        "GA001", "判断整数 n(1≤n≤10^4) 是否为质数，是输出 yes，否则 no。", "yes",
        [("2", "yes"), ("17", "yes"), ("21", "no")],
    )
    S.append(gs(q, ErrorType.CONCEPT,
        "陷阱把 1 当质数（is_prime 缺 n<2 分支）。题目合法输入含 n=1，但公开/隐藏用例"
        "恰好只覆盖 n≥2，故缺陷不触发、答案全部正确——过程却对合法输入 1 会答错",
        [
            Step(id=1, kind="understand", content="n∈[1,10^4]，质数需大于 1", conclusion="n≥1 为合法输入", deps=[]),
            Step(id=2, kind="approach", content="从 2 到 √n 试除即可判定质数", conclusion="试除法", deps=[1]),
            Step(id=3, kind="implement", content="for i in range(2,int(n**0.5)+1): if n%i==0: return no", conclusion="无因子则 yes", deps=[2]),
            Step(id=4, kind="selftest", content="n=2 无因子", conclusion="2 是质数", deps=[3]),
        ], "yes"))

    # 2. 概念错误：set 无序却宣称保持顺序；输入恰好有序
    q = algo_question(
        "GA002", "给定有序整数数组，输出去重后的数组（保持原顺序）。", "1 2 3",
        [("1 1 2 2 3", "1 2 3")],
    )
    S.append(gs(q, ErrorType.CONCEPT,
        "陷阱用 list(set(a)) 去重并宣称保持原顺序，Python set 无序；恰好输入升序，set 迭代序碰巧与升序一致",
        [
            Step(id=1, kind="understand", content="保持原顺序", conclusion="需稳定去重", deps=[]),
            Step(id=2, kind="approach", content="用 set 去重，set 保留插入顺序", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="print(' '.join(set(a)))", conclusion="去重完成", deps=[2]),
            Step(id=4, kind="selftest", content="1 1 2 2 3 → 1 2 3", conclusion="通过", deps=[3]),
        ], "1 2 3"))

    return S


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    algo = build_algorithm()
    out = GOLDEN_DIR / "golden_algorithm.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for s in algo:
            f.write(s.model_dump_json() + "\n")
    print(f"golden_algorithm.jsonl: {len(algo)} samples")
    print("written to", GOLDEN_DIR)


if __name__ == "__main__":
    main()
