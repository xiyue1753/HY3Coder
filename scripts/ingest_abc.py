"""AtCoder ABC 题通用入库脚本（自建算法评测集）。

自动抓取：题目页（英文题面 lang-en） + AC 解（submission 源码），并解析题面样例。
额外测试用例由调用方传入（人工设计，非代码生成）。

用法（示例）：
    python scripts/ingest_abc.py --contest abc328 --problem b --submission 47452966 \
        --title "11/11" --source_id abc328_b --difficulty medium \
        --extra '["N=1,D=1|1", "N=100 all 100|36"]'
    # --extra 格式：JSON 数组，每项 "输入(用|换行)|期望输出"

不写 C 盘，抓取用 python requests（浏览器 headers），题面/AC解来自公开页面。
"""
from __future__ import annotations

import argparse
import html as h
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rex.models import QuestionItem, TestCase, Difficulty  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
           "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}


def fetch_problem(contest: str, problem: str) -> str:
    """抓题目页，提取英文题面（lang-en），转成 markdown 文本。"""
    url = f"https://atcoder.jp/contests/{contest}/tasks/{contest}_{problem}"
    r = requests.get(url, timeout=15, headers=HEADERS)
    m = re.search(r'<span class="lang-en">(.*?)</span>', r.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"problem page {url}: lang-en not found (status {r.status_code})")
    return _html_to_text(m.group(1))


def _html_to_text(html_block: str) -> str:
    """把题面 HTML 转为 markdown 文本（保留标题/代码块/换行）。"""
    s = re.sub(r'<h3[^>]*>', '\n### ', html_block)
    s = re.sub(r'<pre[^>]*>', '\n```\n', s)
    s = re.sub(r'</pre>', '\n```\n', s)
    s = re.sub(r'<[^>]+>', '', s)          # 去掉其余标签
    s = h.unescape(s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def fetch_ac_code(contest: str, submission_id: int) -> str:
    url = f"https://atcoder.jp/contests/{contest}/submissions/{submission_id}"
    r = requests.get(url, timeout=15, headers=HEADERS)
    m = re.search(r'<pre id="submission-code"[^>]*>(.*?)</pre>', r.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"submission {submission_id}: code not found (status {r.status_code})")
    return h.unescape(m.group(1))


def load_cases(path: str) -> list[TestCase]:
    """从 JSON 文件读测试用例（人工设计，含题面样例与自建边界）。

    JSON 格式：[{"input": "...", "output": "...", "hidden": false}, ...]
    """
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TestCase.model_validate(c) for c in cases]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contest", required=True)
    ap.add_argument("--problem", required=True)
    ap.add_argument("--submission", type=int, required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--source_id", required=True)
    ap.add_argument("--difficulty", choices=["basic", "medium", "hard"], required=True)
    ap.add_argument("--layer_basis", default="")
    ap.add_argument("--cases-file", required=True,
                    help="测试用例 JSON 文件（人工设计，含题面样例与自建边界）")
    args = ap.parse_args()

    prompt = fetch_problem(args.contest, args.problem)
    code = fetch_ac_code(args.contest, args.submission)
    all_tc = load_cases(args.cases_file)

    # 复用 A 编号（检查已有最大号）
    existing = []
    if OUT.exists():
        existing = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    next_id = max((int(q["id"][1:]) for q in existing if q["id"].startswith("A")), default=1000) + 1

    q = QuestionItem(
        id=f"A{next_id}", scene="algorithm", title=args.title, prompt=prompt,
        difficulty=Difficulty(args.difficulty), source="AtCoder-自建",
        source_id=args.source_id, layer_basis=args.layer_basis,
        standard_answer="", reference_solution=code, test_cases=all_tc,
        metadata={"contest": args.contest, "problem": args.source_id,
                  "ac_submission_id": args.submission},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({args.source_id}): {len(code)} chars code, "
          f"{len(all_tc)} test cases")


if __name__ == "__main__":
    main()
