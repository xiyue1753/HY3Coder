"""一次性入库脚本：把 ABC161 D（Lunlun 数）写入自建题集（第 1 题质量样板）。

流程：题面（人工整理） + AC 解（submission 11499133 抓取） + 测试用例（题面样例 + 人工设计）。
"""
import json
import re
import html as h
import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rex.models import QuestionItem, TestCase, Difficulty  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"

PROMPT = """AtCoder Beginner Contest 161 D - Lunlun Number（ルンルン数）

一个正整数 X 被称为「Lunlun 数」，当且仅当：在 X 的十进制表示（无前导零）中，任意相邻两个数字的差的绝对值不超过 1。
例如：1234、1、334 都是 Lunlun 数，而 31415、119、13579 都不是 Lunlun 数。

给定一个正整数 K，请找出第 K 小的 Lunlun 数。

【约束条件】
- 1 ≤ K ≤ 10^5
- 所有输入均为整数。

【输入格式】
输入以以下格式从标准输入给出：
K

【输出格式】
输出答案。

【样例输入 1】
15
【样例输出 1】
23
（说明：前 15 个 Lunlun 数为 1,2,3,4,5,6,7,8,9,10,11,12,21,22,23，答案是 23）

【样例输入 2】
1
【样例输出 2】
1

【样例输入 3】
13
【样例输出 3】
21

【样例输入 4】
100000
【样例输出 4】
3234566667
（注意：答案可能超出 32 位整数范围，需用 64 位整数）

【时间限制】2 秒 / 【内存限制】1024 MiB"""

# 人工设计的测试用例（输入为人工设计，期望输出由已验证的 AC 解跑出）
TEST_CASES = [
    TestCase(input="15", output="23", hidden=False),
    TestCase(input="1", output="1", hidden=False),
    TestCase(input="13", output="21", hidden=False),
    TestCase(input="100000", output="3234566667", hidden=False),
    TestCase(input="9", output="9", hidden=False),      # 个位数最后一个
    TestCase(input="10", output="10", hidden=False),    # 进入两位数
    TestCase(input="19", output="43", hidden=False),    # 进位跨越（11,12,21,22,23 之后跳）
    TestCase(input="100", output="878", hidden=False),  # 三位数
]


def fetch_ac_code(submission_id: int) -> str:
    H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
         "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}
    url = f"https://atcoder.jp/contests/abc161/submissions/{submission_id}"
    r = requests.get(url, timeout=15, headers=H)
    m = re.search(r'<pre id="submission-code"[^>]*>(.*?)</pre>', r.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"submission {submission_id}: code not found (status {r.status_code})")
    return h.unescape(m.group(1))


def main() -> None:
    ac_code = fetch_ac_code(11499133)
    q = QuestionItem(
        id="A1001",
        scene="algorithm",
        title="ABC161 D - Lunlun Number",
        prompt=PROMPT,
        difficulty=Difficulty.MEDIUM,  # 官方分值 400 → medium
        source="AtCoder-自建",
        source_id="abc161_d",
        layer_basis="官方分值 400（ABC 第 6 题难度）→ medium",
        standard_answer="",  # 算法题靠测试用例沙盒验证，无需字符串标准答案
        reference_solution=ac_code,
        test_cases=TEST_CASES,
        metadata={"contest": "abc161", "problem": "abc161_d", "score": 400,
                  "time_limit_ms": 2000, "memory_limit_mb": 1024,
                  "ac_submission_id": 11499133, "ac_user": "chocorusk", "language": "C++14"},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({len(ac_code)} chars code, {len(TEST_CASES)} test cases) -> {OUT}")


if __name__ == "__main__":
    main()
