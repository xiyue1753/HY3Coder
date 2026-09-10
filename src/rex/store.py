"""RecordStore: centralized persistence + retrieval for evaluation records.

Data purity: metrics must only come from run-eval records; interactive records
are tagged ``source="interactive"`` and can be filtered out of metric runs.

Storage layout — 文件位置由数据源注册中心 :mod:`rex.datasource` 声明
(RecordStore 只接收 eval 文件白名单，不绑定文件名)：
    启用数据集的正式评测文件（如 abc → eval_selfbuilt_all.jsonl）
    eval_interactive.jsonl                     -- 交互演示的判定记录
    refine_interactive.jsonl                   -- 交互演示的 refine 记录
    data/questions/interactive.jsonl           -- 交互题池（回放用）
    interact_sessions.jsonl                    -- 交互解题完整会话快照

Retention: records keep their ``created_at``; a manual ``cleanup(days)`` is
provided (never auto-deletes). ``expired(days)`` lists stale records so the
caller (CLI/button) can decide.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence, TypeVar

from rex.models import EvalRecord, InteractSession, QuestionItem, RefineRecord

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

    ``eval_files``: 评测记录文件白名单。**默认从数据源注册中心派生**
    （见 :mod:`rex.datasource`：当前 = abc_selfbuilt 正式评测文件 + 交互文件），
    以后加/删数据集只改注册中心，此处自动跟随。
    """

    def __init__(self, outputs_dir: str | Path,
                 eval_files: tuple[str, ...] | None = None,
                 root: str | Path | None = None) -> None:
        # 默认文件白名单从数据源注册中心派生：启用数据集的正式评测 + 交互文件
        from rex.datasource import active_eval_filenames
        self.outputs_dir = Path(outputs_dir)
        # 项目根：交互题池在 <root>/data/questions，需要它来定位。
        # 默认按约定 "outputs_dir = <root>/data/outputs" 反推。
        self.root = Path(root) if root is not None else self.outputs_dir.parent.parent
        self._eval_files = tuple(eval_files) if eval_files else active_eval_filenames()
        self._eval_cache: list[EvalRecord] | None = None
        #: 缓存指纹：[(路径, 是否存在, mtime), ...]，含存在性以支持"文件被删除"失效
        self._eval_fingerprint: tuple | None = None

    # -- file paths ---------------------------------------------------------
    def eval_path(self, scene: str) -> Path:
        return self.outputs_dir / f"eval_{scene}.jsonl"

    def refine_path(self, scene: str) -> Path:
        return self.outputs_dir / f"refine_{scene}.jsonl"

    # -- read ---------------------------------------------------------------
    def _formal_eval_paths(self) -> list[Path]:
        return [self.outputs_dir / f for f in self._eval_files]

    def load_evals(self, scene: str | None = None) -> list[EvalRecord]:
        # 缓存（带指纹失效）：避免重复请求时全量重读文件，显著提速。
        # 指纹含"文件是否存在 + mtime"——只比 mtime 的话，文件被删除（例如清空
        # 交互演示记录）不会让缓存失效，界面会一直显示已经不存在的记录。
        paths = self._formal_eval_paths()
        fingerprint = tuple(
            (str(p), p.exists(), p.stat().st_mtime if p.exists() else 0.0) for p in paths
        )
        if self._eval_cache is not None and fingerprint == self._eval_fingerprint:
            if scene is None:
                return self._eval_cache
            return [r for r in self._eval_cache if r.scene == scene]

        out: list[EvalRecord] = []
        for p in paths:
            if p.exists():
                for line in p.open(encoding="utf-8"):
                    if line.strip():
                        out.append(EvalRecord.model_validate_json(line))
        if scene is None:
            self._eval_cache = out
            self._eval_fingerprint = fingerprint
        return out

    #: refine 记录场景（数学/MATH 已放弃，仅算法）
    REFINE_SCENES = ("algorithm",)

    def load_refines(self, scene: str | None = None) -> list[RefineRecord]:
        scenes = [scene] if scene else self.REFINE_SCENES
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
        """落盘一条评估记录。

        正式评测（source="run-eval"）追加到主评测文件（与 ``load_evals`` 同一文件，
        保证 append→load 闭环一致）；交互演示（source="interactive"）独立写入
        `eval_interactive.jsonl`，避免混入正式统计口径。
        """
        if rec.created_at is None:
            rec.created_at = _now_iso()
        if rec.source == "interactive":
            from rex.datasource import INTERACTIVE_EVAL
            p = self.outputs_dir / INTERACTIVE_EVAL
        else:
            p = self._formal_eval_paths()[0]
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(rec.model_dump_json() + "\n")
        self._eval_cache = None  # 失效缓存

    def append_refine(self, rec: RefineRecord) -> None:
        """落盘一条 refine 记录。

        正式 refine（source="run-eval"）写数据集注册的 refine 文件；交互演示
        （source="interactive"）写独立的 ``refine_interactive.jsonl``——正式文件是
        报告修正闭环章节的数据源，必须保持纯净，不能被演示记录混入。
        """
        if rec.created_at is None:
            rec.created_at = _now_iso()
        if rec.source == "interactive":
            from rex.datasource import interactive_refines_path
            p = interactive_refines_path(self.root)
        else:
            p = self.refine_path(rec.scene)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(rec.model_dump_json() + "\n")

    # -- 交互式解题工作台：题池 + 会话快照 -----------------------------------
    def append_interactive_question(self, q: QuestionItem) -> None:
        """把交互题写入交互题池（data/questions/interactive.jsonl）。

        交互题是现场输入的，不落池的话单题回放取不到题面与用例。
        """
        from rex.datasource import interactive_questions_path
        p = interactive_questions_path(self.root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(q.model_dump_json() + "\n")

    def append_interact_session(self, session: InteractSession) -> None:
        """把交互解题会话快照追加到 ``interact_sessions.jsonl``（完整留档）。"""
        from rex.datasource import interact_sessions_path
        if session.created_at is None:
            session.created_at = _now_iso()
        p = interact_sessions_path(self.root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(session.model_dump_json() + "\n")

    def load_interact_sessions(self) -> list[InteractSession]:
        from rex.datasource import load_interact_sessions
        return load_interact_sessions(self.root)

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
        for p in self._formal_eval_paths():
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
