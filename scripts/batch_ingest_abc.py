"""批量入库 AtCoder 自建题（第一轮 17 题）。

逐题调用 ingest_abc.main() 的等价逻辑：抓题面 → auto-ac 找 AC（样例验证）→ 入库。
每个题写入 metadata.type（算法类型），供 browse 页展示。

用法：
    python scripts/batch_ingest_abc.py [--only abc211_d abc292_d ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import ingest_abc  # noqa: E402
from rex.models import Difficulty, QuestionItem  # noqa: E402

# (contest, problem, title, type, difficulty)
PLAN: list[tuple[str, str, str, str, str]] = [
    # 第 7 轮（23：basic 8 + medium 7 + hard 8，场次 abc376-395 未收录，收尾至 175）
    # ---- basic ----
    ("abc376", "c", "Prepare Another Box", "贪心/排序", "basic"),
    ("abc378", "c", "Repeating", "哈希/映射", "basic"),
    ("abc380", "c", "Move Segment", "模拟/计数", "basic"),
    ("abc382", "c", "Kaiten Sushi", "排序/单调", "basic"),
    ("abc384", "c", "Perfect Standings", "位枚举", "basic"),
    ("abc388", "c", "Various Kagamimochi", "贪心/二分", "basic"),
    ("abc389", "c", "Snake Queue", "队列/前缀和", "basic"),
    ("abc392", "c", "Bib", "映射/模拟", "basic"),
    # ---- medium ----
    ("abc377", "d", "Many Segments 2", "贪心/区间", "medium"),
    ("abc379", "d", "Home Garden", "模拟/差分", "medium"),
    ("abc381", "d", "1122 Substring", "双指针/滑窗", "medium"),
    ("abc385", "d", "Santa Claus 2", "哈希/有序集", "medium"),
    ("abc386", "d", "Diagonal Separation", "排序/扫描", "medium"),
    ("abc393", "d", "Swap to Gather", "前缀和", "medium"),
    ("abc395", "d", "Pigeon Swap", "并查集/映射", "medium"),
    # ---- hard ----
    ("abc376", "d", "Cycle", "BFS/图", "hard"),
    ("abc378", "e", "Mod Sigma Problem", "数学/前缀", "hard"),
    ("abc383", "e", "Sum of Max Matching", "贪心/图", "hard"),
    ("abc384", "e", "Takahashi is Slime 2", "BFS/优先级", "hard"),
    ("abc386", "e", "Maximize XOR", "组合/枚举", "hard"),
    ("abc388", "e", "Simultaneous Kagamimochi", "二分", "hard"),
    ("abc389", "e", "Square Price", "二分/数学", "hard"),
    ("abc392", "e", "Cables and Servers", "并查集/图", "hard"),
]

OUT = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"


def next_id() -> str:
    existing = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()] if OUT.exists() else []
    n = max((int(q["id"][1:]) for q in existing if q["id"].startswith("A")), default=1000) + 1
    return f"A{n}"


def existing_source_ids() -> set[str]:
    if not OUT.exists():
        return set()
    return {json.loads(l)["source_id"] for l in OUT.open(encoding="utf-8") if l.strip()}


def ingest_one(contest: str, problem: str, title: str, typ: str, diff: str) -> str | None:
    task = f"{contest}_{problem}"
    if task in existing_source_ids():
        print(f"[skip] {task}: 已入库，跳过")
        return None
    cases_file = ROOT / "data" / "cases" / f"{task}_cases.json"
    if not cases_file.exists():
        print(f"[skip] {task}: cases file missing")
        return None
    prompt = ingest_abc.fetch_problem(contest, problem)
    samples = ingest_abc.extract_samples(prompt)
    if not samples:
        print(f"[skip] {task}: no samples extracted")
        return None
    print(f"[auto-ac] {task}: {len(samples)} samples, finding AC…")
    sid, code = ingest_abc.find_ac_with_verification(contest, task, samples)
    all_tc = ingest_abc.load_cases(str(cases_file))
    q = QuestionItem(
        id=next_id(), scene="algorithm", title=title, prompt=prompt,
        difficulty=Difficulty(diff), source="AtCoder-自建",
        source_id=task, layer_basis=f"官方分值题目，{typ} → {diff}",
        standard_answer="", reference_solution=code, test_cases=all_tc,
        metadata={"contest": contest, "problem": task, "type": typ, "ac_submission_id": sid},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({task}) [{typ}] code={len(code)} chars, {len(all_tc)} cases")
    return q.id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="只处理指定 source_id 列表")
    ap.add_argument("--max-pages", type=int, default=5,
                    help="翻页上限（老比赛 AC 提交多混入其他题，需更多页）")
    ap.add_argument("--retry", type=int, default=2, help="每题失败重试次数（500 偶发）")
    args = ap.parse_args()
    only = set(args.only) if args.only else None
    done = 0
    failed: list[str] = []
    for contest, problem, title, typ, diff in PLAN:
        task = f"{contest}_{problem}"
        if only and task not in only:
            continue
        ok = False
        for attempt in range(args.retry + 1):
            try:
                if ingest_one(contest, problem, title, typ, diff):
                    done += 1
                ok = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"[error] {task} (attempt {attempt + 1}/{args.retry + 1}): {e}")
                if attempt < args.retry:
                    time.sleep(8)
        if not ok:
            failed.append(task)
    print(f"\n完成 {done}/{len(PLAN)} 题")
    if failed:
        print(f"失败 {len(failed)} 题（需人工提供 submission id）：{failed}")


if __name__ == "__main__":
    main()
