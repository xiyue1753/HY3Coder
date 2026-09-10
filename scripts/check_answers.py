"""答案校验脚本（算法沙盒测试用例 + 标准答案文本比对兜底）。

用法:
    python scripts/check_answers.py data/outputs/eval_abc_selfbuilt_t0.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cli import check_answers  # noqa: E402

#: 默认校验对象：ABC 自建集 temperature=0 正式评测记录
DEFAULT_RESULTS = "data/outputs/eval_abc_selfbuilt_t0.jsonl"


def main() -> None:
    results = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RESULTS
    check_answers(results=Path(results), verbose=False)


if __name__ == "__main__":
    main()
