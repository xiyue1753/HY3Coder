"""修复已确认的 3 题 5 个坏用例：补齐合法输入 + 参考解重算期望输出。

用法:
    python scripts/fix_bad_cases.py

修复表（A1035/A1057/A1059 的隐藏用例）：
  - A1035 c5: 声明 M=2 但只有 1 行冲突 → M=1（期望 0 语义不变）
  - A1035 c8: 同上 → M=1
  - A1057 c6: 缺 y/A 值（N=2,x=3 后应 y + 2 个 A）→ 补成合法输入
  - A1057 c7: 缺 A 值（N=3,x=5 后应 y + 3 个 A）→ 补成合法输入
  - A1059 c3: 首行多了 1 个数（应 N M）→ 拆行归位

每个坏用例修复后都用参考解重算期望输出，保证"期望=标准答案"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex.executor.sandbox import detect_language, run_code  # noqa: E402

QP = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"

# qid -> {用例序号(1-based) -> 修复后的合法 input}
FIXES = {
    "A1035": {5: "3 1 1\n1 2", 8: "3 2 1\n1 2"},   # M: 2->1（只有 1 行冲突）
    "A1057": {6: "2 3 1\n1 1", 7: "3 5 1\n1 1 1"},  # 补 y（x 需 >可达范围保证 No）
    "A1059": {3: "3 1\n1 1\n1 1"},                   # 首行 N M 归位
}

rows = [json.loads(l) for l in QP.open(encoding="utf-8") if l.strip()]
for r in rows:
    fixes = FIXES.get(r["id"])
    if not fixes:
        continue
    ref = r.get("reference_solution") or ""
    lang = detect_language(ref)
    for ci, new_inp in fixes.items():
        idx = ci - 1
        tcs = r["test_cases"]
        if idx >= len(tcs):
            print(f"{r['id']} c{ci} 越界")
            continue
        res = run_code(ref, stdin=new_inp, timeout=15, language=lang)
        new_out = res.stdout.rstrip()
        old = tcs[idx]
        print(f"{r['id']} c{ci}: in {old['input']!r} -> {new_inp!r}")
        print(f"     exp {old['output']!r} -> {new_out!r} (rc={res.returncode} err={(res.error or '')[:60]})")
        if res.error or res.timed_out:
            print("     !! 参考解修复后仍失败，跳过写回")
            continue
        old["input"] = new_inp
        old["output"] = new_out

with QP.open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("done ->", QP)
