"""Question-set file format (data/questions/*.jsonl) helpers.

每条记录即 ``QuestionItem``（见 models.py），JSONL 一行一条。
本模块提供读写与校验辅助，保证题集文件可复现、可校验。
"""
from __future__ import annotations

import json
from pathlib import Path

from rex.models import QuestionItem


def load_questions(path: str | Path) -> list[QuestionItem]:
    """Read a JSONL question set, validating each line as QuestionItem."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"question set not found: {p}")
    items: list[QuestionItem] = []
    with p.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(QuestionItem.model_validate_json(line))
            except Exception as e:  # noqa: BLE001 - surface line for fixing
                raise ValueError(f"{p}:{line_no} invalid QuestionItem: {e}") from e
    return items


def dump_questions(items: list[QuestionItem], path: str | Path) -> None:
    """Write question items to a JSONL file (atomic-ish: write then move)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(it.model_dump_json(exclude_none=False) + "\n")
    tmp.replace(p)


def index_by_id(items: list[QuestionItem]) -> dict[str, QuestionItem]:
    return {it.id: it for it in items}
