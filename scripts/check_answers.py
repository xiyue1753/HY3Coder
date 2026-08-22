"""答案校验脚本（数学精确比对 + 算法沙盒测试用例）。

用法:
    python scripts/check_answers.py --results data/outputs/eval_math.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli import check_answers  # noqa: E402


def main() -> None:
    results = sys.argv[1] if len(sys.argv) > 1 else "data/outputs/eval_math.jsonl"
    check_answers(results=Path(results), verbose=False)


if __name__ == "__main__":
    main()
