"""Build the golden silent-failure sample library under data/golden/.

Silent failure = 最终答案正确但解题过程存在根本缺陷（评估器的核心挑战）。
每个样本构造「陷阱过程」：答案对、过程错，且明确标注缺陷类型与构造思路，
用于验证评估器能否检出 SILENT_FAILURE 而非被正确答案误导。

产出:
    data/golden/golden_algorithm.jsonl  (15 条)
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

    # 3. 条件遗漏：n=0 边界未处理；用例恰好 n≥1
    q = algo_question(
        "GA003", "输入整数 n(0≤n≤10^9)，输出 1+2+...+n。", "15",
        [("5", "15"), ("100", "5050")],
    )
    S.append(gs(q, ErrorType.MISSING_CONDITION,
        "陷阱 n*(n+1)//2 未处理 n=0（公式对 n=0 也应得 0，实现却写成 range 循环从 1 开始求和，n=0 时返回空），用例恰好 n≥1",
        [
            Step(id=1, kind="understand", content="等差求和", conclusion="n(n+1)/2", deps=[]),
            Step(id=2, kind="approach", content="循环累加", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="s=0; for i in range(1,n+1): s+=i", conclusion="s=1+..+n", deps=[2]),
            Step(id=4, kind="selftest", content="n=5 → 15", conclusion="通过", deps=[3]),
        ], "15"))

    # 4. 概念错误：快排不稳定却宣称稳定；输入恰好无相等元素
    q = algo_question(
        "GA004", "按数值对数组稳定排序并输出（相等元素保持原相对顺序）。", "1 2 2",
        [("2 1 2", "1 2 2")],
    )
    S.append(gs(q, ErrorType.CONCEPT,
        "陷阱用快速排序并宣称稳定；Python 快排分区对相等元素会交换，但输入恰好无相等元素，输出碰巧正确",
        [
            Step(id=1, kind="understand", content="稳定排序", conclusion="需保持相对顺序", deps=[]),
            Step(id=2, kind="approach", content="快速排序，partition 保证稳定", conclusion="O(nlogn)", deps=[1]),
            Step(id=3, kind="implement", content="常规 quicksort", conclusion="排序完成", deps=[2]),
            Step(id=4, kind="selftest", content="2 1 2 → 1 2 2", conclusion="通过", deps=[3]),
        ], "1 2 2"))

    # 5. 复杂度不达标：递归斐波那契声明 O(n) 实际 O(2^n)；用例 n 小
    q = algo_question(
        "GA005", "求第 n(0≤n≤30) 个斐波那契数（F0=0,F1=1）。", "55",
        [("10", "55"), ("7", "13")],
    )
    S.append(gs(q, ErrorType.COMPLEXITY,
        "陷阱递归实现 fib(n)=fib(n-1)+fib(n-2) 声明时间复杂度 O(n)，实际 O(2^n)；用例 n≤30 恰好能跑完",
        [
            Step(id=1, kind="understand", content="F0=0,F1=1", conclusion="递推", deps=[]),
            Step(id=2, kind="approach", content="递归 fib(n)=fib(n-1)+fib(n-2)", conclusion="时间 O(n)", deps=[1]),
            Step(id=3, kind="implement", content="def fib(n): return n if n<2 else fib(n-1)+fib(n-2)", conclusion="递归完成", deps=[2]),
            Step(id=4, kind="selftest", content="fib(10)=55", conclusion="通过", deps=[3]),
        ], "55"))

    # 6. 逻辑缺陷：暴力三重循环声明 O(n)；用例 n 小
    q = algo_question(
        "GA006", "求数组的最大子数组和（n≤10^4）。", "6",
        [("-2 1 -3 4 -1 2 1 -5 4", "6")],
    )
    S.append(gs(q, ErrorType.LOGIC,
        "陷阱用 O(n^3) 枚举全部子数组并声明时间复杂度 O(n)；用例 n 小恰好通过，但数据范围 10^4 下必然超时",
        [
            Step(id=1, kind="understand", content="最大子数组和", conclusion="经典问题", deps=[]),
            Step(id=2, kind="approach", content="枚举全部子数组求最大和", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="三重循环枚举 (i,j,k) 求区间和", conclusion="max 更新", deps=[2]),
            Step(id=4, kind="selftest", content="样例得 6", conclusion="通过", deps=[3]),
        ], "6"))

    # 7. 概念错误：切片反转宣称原地反转
    q = algo_question(
        "GA007", "原地反转字符串并输出（不使用额外 O(n) 空间）。", "cba",
        [("abc", "cba")],
    )
    S.append(gs(q, ErrorType.CONCEPT,
        "陷阱用 s[::-1] 完成反转却宣称『原地反转，O(1) 空间』；切片实际创建新字符串，答案正确但空间声明错误",
        [
            Step(id=1, kind="understand", content="原地反转", conclusion="O(1) 额外空间", deps=[]),
            Step(id=2, kind="approach", content="前后指针交换", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="return s[::-1]", conclusion="反转完成", deps=[2]),
            Step(id=4, kind="selftest", content="abc → cba", conclusion="通过", deps=[3]),
        ], "cba"))

    # 8. 条件遗漏：假设输入已排序；恰好用例有序
    q = algo_question(
        "GA008", "求数组的中位数（未保证输入有序）。", "3",
        [("3 1 2", "2"), ("5 1 3 2 4", "3")],
    )
    S.append(gs(q, ErrorType.MISSING_CONDITION,
        "陷阱直接取排序中间下标 arr[n//2] 而不排序，宣称『输入已排序』；恰好用例是有序输入",
        [
            Step(id=1, kind="understand", content="中位数", conclusion="中间元素", deps=[]),
            Step(id=2, kind="approach", content="直接取 arr[n//2]", conclusion="O(1)", deps=[1]),
            Step(id=3, kind="implement", content="print(a[len(a)//2])", conclusion="输出中间元素", deps=[2]),
            Step(id=4, kind="selftest", content="[3,1,2] 中位 2", conclusion="通过", deps=[3]),
        ], "2"))

    # 9. 边界条件：十进制 0 转二进制返回空串；用例恰好无 0
    q = algo_question(
        "GA009", "将非负整数 n 转为二进制字符串输出。", "1010",
        [("10", "1010"), ("7", "111")],
    )
    S.append(gs(q, ErrorType.BOUNDARY,
        "陷阱 while n>0 收集余数，n=0 时返回空字符串；用例恰好不含 0",
        [
            Step(id=1, kind="understand", content="十进制转二进制", conclusion="短除法", deps=[]),
            Step(id=2, kind="approach", content="while n>0 收集余数", conclusion="O(logn)", deps=[1]),
            Step(id=3, kind="implement", content="bits=[]; while n>0: bits.append(n%2); n//=2", conclusion="逆序输出", deps=[2]),
            Step(id=4, kind="selftest", content="10 → 1010", conclusion="通过", deps=[3]),
        ], "1010"))

    # 10. 条件遗漏：split 不处理标点；样例恰好无标点
    q = algo_question(
        "GA010", "统计句子中的单词数（单词间以空格分隔，可含标点）。", "3",
        [("hello world code", "3")],
    )
    S.append(gs(q, ErrorType.MISSING_CONDITION,
        "陷阱用 len(s.split()) 统计，未处理标点粘连（如 hello, 会算成两个词）；样例恰好无标点",
        [
            Step(id=1, kind="understand", content="单词数", conclusion="空格分词", deps=[]),
            Step(id=2, kind="approach", content="split 后计数", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="print(len(s.split()))", conclusion="计数完成", deps=[2]),
            Step(id=4, kind="selftest", content="hello world code → 3", conclusion="通过", deps=[3]),
        ], "3"))

    # 11. 逻辑缺陷：gcd 未处理 b=0；恰好用例 b>0
    q = algo_question(
        "GA011", "求两个正整数 a,b 的最大公约数。", "4",
        [("12 8", "4"), ("17 5", "1")],
    )
    S.append(gs(q, ErrorType.LOGIC,
        "陷阱辗转相除递归无终止条件 b=0，宣称『欧几里得算法正确』；用例恰好 b>0 不触发死循环",
        [
            Step(id=1, kind="understand", content="最大公约数", conclusion="欧几里得", deps=[]),
            Step(id=2, kind="approach", content="gcd(a,b)=gcd(b,a%b)", conclusion="O(logn)", deps=[1]),
            Step(id=3, kind="implement", content="def gcd(a,b): return gcd(b, a%b)", conclusion="递归", deps=[2]),
            Step(id=4, kind="selftest", content="gcd(12,8)=4", conclusion="通过", deps=[3]),
        ], "4"))

    # 12. 逻辑缺陷：转置实现成翻转；恰好方阵对称样例
    q = algo_question(
        "GA012", "输出矩阵的转置（m 行 n 列）。", "1 4\n2 5\n3 6",
        [("1 2 3\n4 5 6", "1 4\n2 5\n3 6")],
    )
    S.append(gs(q, ErrorType.LOGIC,
        "陷阱用 list(zip(*m)) 反向？实现将行翻转而非转置；恰好测试用 2x2 对称矩阵，翻转与转置输出相同",
        [
            Step(id=1, kind="understand", content="矩阵转置", conclusion="行列互换", deps=[]),
            Step(id=2, kind="approach", content="把矩阵左右翻转", conclusion="O(mn)", deps=[1]),
            Step(id=3, kind="implement", content="for r in m: print(reversed(r))", conclusion="输出", deps=[2]),
            Step(id=4, kind="selftest", content="1 2/2 1 → 1 2/2 1 翻转", conclusion="通过", deps=[3]),
        ], "1 4\n2 5\n3 6"))

    # 13. 复杂度不达标：幂运算 O(n) 声明 O(log n)；n 小
    q = algo_question(
        "GA013", "计算 a^n (0≤n≤10^9)，输出结果。", "1024",
        [("2 10", "1024"), ("3 4", "81")],
    )
    S.append(gs(q, ErrorType.COMPLEXITY,
        "陷阱用 for 循环累乘 n 次并声明复杂度 O(log n)（快速幂未实现）；用例 n 恰好小",
        [
            Step(id=1, kind="understand", content="快速幂", conclusion="O(logn)", deps=[]),
            Step(id=2, kind="approach", content="循环累乘", conclusion="O(logn)", deps=[1]),
            Step(id=3, kind="implement", content="res=1; for _ in range(n): res*=a", conclusion="计算完成", deps=[2]),
            Step(id=4, kind="selftest", content="2^10=1024", conclusion="通过", deps=[3]),
        ], "1024"))

    # 14. 复杂度不达标：前缀和查询 O(n²)；查询少
    q = algo_question(
        "GA014", "n 个元素数组，q 次查询区间和（n,q≤10^5）。", "5",
        [("1 2 3 4\n2\n0 2\n1 3", "5\n8")],
    )
    S.append(gs(q, ErrorType.COMPLEXITY,
        "陷阱每次查询内层循环累加（O(nq)）却声明 O(n+q)；用例 q 恰好小",
        [
            Step(id=1, kind="understand", content="区间和查询", conclusion="前缀和", deps=[]),
            Step(id=2, kind="approach", content="每次查询循环累加区间", conclusion="O(n+q)", deps=[1]),
            Step(id=3, kind="implement", content="for l,r: print(sum(a[l:r+1]))", conclusion="输出", deps=[2]),
            Step(id=4, kind="selftest", content="[0,2]=5", conclusion="通过", deps=[3]),
        ], "5\n8"))

    # 15. 格式不符：多行输出写一行；恰好单元素用例
    q = algo_question(
        "GA015", "输入 n 个整数，每行输出一个数的平方。", "4\n9",
        [("2\n2 3", "4\n9")],
    )
    S.append(gs(q, ErrorType.FORMAT,
        "陷阱把全部结果 print(' '.join(...)) 输出在一行，宣称符合要求；恰好用例 n=1 时单行与多行相同",
        [
            Step(id=1, kind="understand", content="每行一个", conclusion="换行分隔", deps=[]),
            Step(id=2, kind="approach", content="平方后输出", conclusion="O(n)", deps=[1]),
            Step(id=3, kind="implement", content="print(' '.join(str(x*x) for x in a))", conclusion="输出", deps=[2]),
            Step(id=4, kind="selftest", content="2 → 4", conclusion="通过", deps=[3]),
        ], "4"))

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
