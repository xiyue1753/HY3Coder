"""Local question-set loading & normalization.

题集以 JSON 存放在 ``data/questions/``；本模块只负责本地题集的读取与写回。
题库构建（抓题面、取参考解、生成隐藏用例、入库）是独立的离线步骤，其脚本
不随公开仓库发布（见 .gitignore），因此评测主流程不依赖网络。
"""
from __future__ import annotations

import json
from pathlib import Path

from rex.models import QuestionItem


def load_local(path: str | Path) -> list[QuestionItem]:
    """Load question items from a local JSON file (a list of item dicts)."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    return [QuestionItem.model_validate(d) for d in data]


def save_local(items: list[QuestionItem], path: str | Path) -> None:
    """Write question items to a local JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump([it.model_dump(mode="json") for it in items], f, ensure_ascii=False, indent=1)
