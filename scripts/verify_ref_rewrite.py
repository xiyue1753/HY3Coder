"""核对脚本：改前（原 AC 解）与改后（清晰版）参考解对全部输入样例输出一致。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rex.executor.sandbox import run_code  # noqa: E402

QFILE = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"
BAK = Path(__file__).resolve().parents[1] / "data" / "cases" / "ref_originals.json"


def main() -> None:
    recs = [json.loads(l) for l in QFILE.open(encoding="utf-8") if l.strip()]
    bak = json.loads(BAK.read_text(encoding="utf-8"))
    all_ok = True
    for q in recs:
        qid = q["id"]
        old_code = bak[qid]["ref"]
        new_code = q["reference_solution"]
        cases = q["test_cases"]
        print(f"=== {qid} ({q['source_id']}) {len(cases)} cases ===")
        for i, tc in enumerate(cases):
            old = run_code(old_code, stdin=tc["input"], timeout=20, language="cpp")
            new = run_code(new_code, stdin=tc["input"], timeout=20, language="cpp")
            o, n = old.stdout.strip(), new.stdout.strip()
            exp = tc["output"].strip()
            old_ok = (o == exp)
            new_ok = (n == exp)
            same = (o == n)
            if not (old_ok and new_ok and same):
                all_ok = False
            print(f"  case{i} old={o!r}({'OK' if old_ok else 'X'}) "
                  f"new={n!r}({'OK' if new_ok else 'X'}) same={same} exp={exp!r}")
    print("\nALL CONSISTENT" if all_ok else "\nSOME MISMATCH")


if __name__ == "__main__":
    main()
