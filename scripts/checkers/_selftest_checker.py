# -*- coding: utf-8 -*-
"""checker 自测：对单题 checker，验证
1) 参考解输出（题集 test_cases 中 output 字段）→ checker 应 AC；
2) 若干显式非法输出 → checker 应 WA（非 AC）。

用法：
    python scripts/checkers/_selftest_checker.py <source_id> [--only-ac|--only-wa]
    python scripts/checkers/_selftest_checker.py abc392_e
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rex.executor.judge import run_checker  # noqa: E402

# 显式非法输出（按题目不同自行补充）。key: source_id
ILLEGAL_OUTPUTS: dict[str, list[str]] = {
    # 每个元素为一个非法输出文本（或 None 表示跳过显式 WA 校验）
}


def find_record(source_id: str):
    for name in ("abc_selfbuilt.jsonl", "cf_selfbuilt.jsonl"):
        p = ROOT / "data" / "questions" / name
        if not p.exists():
            continue
        for line in p.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r["source_id"] == source_id:
                    return r
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    sid = sys.argv[1]
    rec = find_record(sid)
    if rec is None:
        print(f"[fail] 题集未找到 {sid}")
        return
    checker_code = rec.get("checker_code")
    if not checker_code:
        print(f"[skip] {sid} 尚未写 checker_code（题集字段）")
        return
    ck_lang = rec.get("checker_language", "python")

    print(f"=== {sid} checker 自测（{rec.get('title')}）===")
    ok_all = True
    # 1) 参考解输出（每个 test_case 的 output）应 AC
    for i, tc in enumerate(rec.get("test_cases", [])):
        exp_out = tc.get("output") or ""
        if not exp_out.strip():
            continue  # 空期望（参考解输出为空的行）跳过
        ok, msg = run_checker(checker_code, ck_lang, tc["input"], exp_out)
        status = "AC " if ok else "WA!"
        if not ok:
            ok_all = False
        print(f"  [ref {i}] {status} {msg[:100]}")
    # 2) 显式非法输出应 WA
    for j, bad in ILLEGAL_OUTPUTS.get(sid, []):
        # 取一个合法输入作为样例
        sample_in = rec["test_cases"][0]["input"]
        ok, msg = run_checker(checker_code, ck_lang, sample_in, bad)
        status = "拒(AC?! bad)" if ok else "正确拒 WA"
        if ok:
            ok_all = False
        print(f"  [illegal {j}] {status} {msg[:100]}")
    print("=== 结果:", "ALL PASS" if ok_all else "有 FAIL")


if __name__ == "__main__":
    main()
