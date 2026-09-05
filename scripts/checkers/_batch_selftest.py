# -*- coding: utf-8 -*-
"""批量自测 checkers：用题集记录的 test_cases.output（参考解自洽化输出）
跑对应 checker，应全部 AC。

用法：python scripts/checkers/_batch_selftest.py <file> <sid1> <sid2> ...
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from rex.executor.judge import run_checker  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    qfile = sys.argv[1]
    sids = set(sys.argv[2:])
    path = ROOT / "data" / "questions" / qfile
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    all_ok = True
    for r in rows:
        if r["source_id"] not in sids:
            continue
        ck = r.get("checker_code") or ""
        if not ck:
            print(f"[skip] {r['source_id']} 缺 checker_code")
            continue
        ck_lang = r.get("checker_language", "python")
        n_ok = 0
        total = 0
        for i, tc in enumerate(r.get("test_cases", [])):
            exp = tc.get("output") or ""
            if not exp.strip():
                continue  # 空期望跳过（参考解输出为空）
            total += 1
            ok, msg = run_checker(ck, ck_lang, tc["input"], exp)
            if ok:
                n_ok += 1
            else:
                print(f"  [FAIL] {r['source_id']} case{i}: {msg[:120]}")
                all_ok = False
        status = "PASS" if n_ok == total and total > 0 else "FAIL"
        if status == "PASS":
            print(f"  {status} {r['source_id']} ({r['id']}) {n_ok}/{total}")
        else:
            all_ok = False
            print(f"  {status} {r['source_id']} ({r['id']}) {n_ok}/{total}")
    print("=== 结果:", "ALL PASS" if all_ok else "有 FAIL")


if __name__ == "__main__":
    main()
