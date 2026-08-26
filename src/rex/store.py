"""RecordStore: centralized persistence + retrieval for evaluation records.

Data purity: metrics must only come from run-eval records; interactive records
are tagged ``source="interactive"`` and can be filtered out of metric runs.

Storage layout (kept compatible with existing files):
    data/outputs/eval_{scene}.jsonl        -- EvalRecord (run-eval + interactive)
    data/outputs/refine_{scene}.jsonl      -- RefineRecord

Retention: records keep their ``created_at``; a manual ``cleanup(days)`` is
provided (never auto-deletes). ``expired(days)`` lists stale records so the
caller (CLI/button) can decide.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence, TypeVar

from rex.models import EvalRecord, RefineRecord

log = logging.getLogger(__name__)

T = TypeVar("T", EvalRecord, RefineRecord)

ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def _now_iso() -> str:
    return datetime.now().strftime(ISO_FMT)


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, ISO_FMT)
    except ValueError:
        return None


class RecordStore:
    """Central read/write/query/cleanup for evaluation records.

    All record I/O goes through here so that a single implementation provides
    consistent timestamps, source tagging, retrieval and retention.
    """

    def __init__(self, outputs_dir: str | Path) -> None:
        self.outputs_dir = Path(outputs_dir)

    # -- file paths ---------------------------------------------------------
    def eval_path(self, scene: str) -> Path:
        return self.outputs_dir / f"eval_{scene}.jsonl"

    def refine_path(self, scene: str) -> Path:
        return self.outputs_dir / f"refine_{scene}.jsonl"

    # -- read ---------------------------------------------------------------
    def load_evals(self, scene: str | None = None) -> list[EvalRecord]:
        scenes = [scene] if scene else ("math", "algorithm")
        out: list[EvalRecord] = []
        for s in scenes:
            p = self.eval_path(s)
            if p.exists():
                for line in p.open(encoding="utf-8"):
                    if line.strip():
                        out.append(EvalRecord.model_validate_json(line))
        return out

    def load_refines(self, scene: str | None = None) -> list[RefineRecord]:
        scenes = [scene] if scene else ("math", "algorithm")
        out: list[RefineRecord] = []
        for s in scenes:
            p = self.refine_path(s)
            if p.exists():
                for line in p.open(encoding="utf-8"):
                    if line.strip():
                        out.append(RefineRecord.model_validate_json(line))
        return out

    # -- append -------------------------------------------------------------
    def append_eval(self, rec: EvalRecord) -> None:
        if rec.created_at is None:
            rec.created_at = _now_iso()
        p = self.eval_path(rec.scene)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(rec.model_dump_json() + "\n")

    def append_refine(self, rec: RefineRecord) -> None:
        if rec.created_at is None:
            rec.created_at = _now_iso()
        p = self.refine_path(rec.scene)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(rec.model_dump_json() + "\n")

    # -- rich query ---------------------------------------------------------
    def query_evals(
        self,
        scene: str | None = None,
        difficulty: str | None = None,
        verdict: str | None = None,
        source: str | None = None,
        qid: str | None = None,
        keyword: str | None = None,
        since: str | None = None,   # ISO 起
        until: str | None = None,   # ISO 止
        sort: str = "created_at",   # created_at | question_id
        order: str = "desc",        # asc | desc
        limit: int | None = 100,
        offset: int = 0,
    ) -> tuple[list[EvalRecord], int]:
        """Query eval records with filters; returns (records, total_matching).

        Filters are ANDed. ``limit``/``offset`` implement pagination.
        """
        recs = self.load_evals(scene)

        def _match(r: EvalRecord) -> bool:
            if difficulty and r.difficulty.value != difficulty:
                return False
            if verdict and r.verification.verdict.value != verdict:
                return False
            if source and r.source != source:
                return False
            if qid and qid not in r.question_id:
                return False
            if keyword:
                hay = f"{r.question_id} {r.scene} {r.verification.verdict.value}"
                if keyword.lower() not in hay.lower():
                    return False
            if since:
                st = _parse_ts(since)
                ct = _parse_ts(r.created_at)
                if st and ct and ct < st:
                    return False
            if until:
                ut = _parse_ts(until)
                ct = _parse_ts(r.created_at)
                if ut and ct and ct > ut:
                    return False
            return True

        matched = [r for r in recs if _match(r)]

        if sort == "question_id":
            matched.sort(key=lambda r: r.question_id, reverse=(order == "desc"))
        else:  # created_at
            matched.sort(
                key=lambda r: _parse_ts(r.created_at) or datetime.min,
                reverse=(order == "desc"),
            )

        total = len(matched)
        page = matched[offset:offset + limit] if limit else matched[offset:]
        return page, total

    # -- retention ----------------------------------------------------------
    def expired(self, days: int = 30) -> list[EvalRecord]:
        """List records older than ``days`` (by created_at), for manual cleanup."""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            r for r in self.load_evals()
            if (ts := _parse_ts(r.created_at)) is not None and ts < cutoff
        ]

    def _record_key(self, r: EvalRecord) -> tuple[str, str, str]:
        """唯一标识一条记录：scene + question_id + created_at。"""
        return (r.scene, r.question_id, r.created_at or "")

    def cleanup(self, days: int = 30, dry_run: bool = True) -> tuple[int, int]:
        """Manually remove records older than ``days``.

        Returns (would_remove, removed). Never auto-invoked; caller decides.
        With ``dry_run=True`` only reports (no deletion).

        Semantics: every record older than the retention window is removed.
        This is an explicit manual action (records are never auto-deleted).
        """
        expired = self.expired(days)
        to_remove_keys = {self._record_key(r) for r in expired}
        if dry_run or not to_remove_keys:
            return len(to_remove_keys), 0

        removed = 0
        for scene in ("math", "algorithm"):
            p = self.eval_path(scene)
            if not p.exists():
                continue
            keep_lines = []
            with p.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = EvalRecord.model_validate_json(line)
                    if self._record_key(rec) in to_remove_keys:
                        removed += 1
                        continue
                    keep_lines.append(line)
            p.write_text("".join(keep_lines), encoding="utf-8")
        return len(to_remove_keys), removed
