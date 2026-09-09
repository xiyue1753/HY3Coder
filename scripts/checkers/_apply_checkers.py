# -*- coding: utf-8 -*-
"""将 scripts/checkers/{sid}_checker.py 内嵌到题集记录的 checker_code，
并把 judge 置为 special（仅处理已有 checker 文件且当前为 exact 的题）。

用法：python scripts/checkers/_apply_checkers.py <file> <sid1> <sid2> ...
      <file>: abc_selfbuilt.jsonl 或 cf_selfbuilt.jsonl
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
CK_DIR = Path(__file__).resolve().parent


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    qfile = sys.argv[1]
    sids = sys.argv[2:]
    path = ROOT / "data" / "questions" / qfile
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    updated = 0
    for r in rows:
        if r["source_id"] not in sids:
            continue
        ck_path = CK_DIR / f"{r['source_id']}_checker.py"
        if not ck_path.exists():
            print(f"[skip] {r['source_id']}: 缺 {ck_path.name}")
            continue
        code = ck_path.read_text(encoding="utf-8")
        r["judge"] = "special"
        r["checker_code"] = code
        r["checker_language"] = "python"
        # 清理 needs_checker 标记（已用 checker 判定）
        r.get("metadata", {}).pop("needs_checker", None)
        updated += 1
        print(f"[ok] {r['source_id']} ({r['id']}) -> judge=special, checker={len(code)}B")
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"updated {updated} 题 in {qfile}")


if __name__ == "__main__":
    main()
