"""EvalRunner: scheduling layer over the single-question pipeline.

Separation of concerns (DESIGN goal):
  - Pipeline._eval_one  = "how to evaluate ONE question"  (business, unchanged)
  - EvalRunner          = "how to SCHEDULE many questions" (concurrency / retry /
                           resume / persistence / cost aggregation)

Data-purity contract is preserved: the runner only decides *when* a question is
evaluated, never *how* it is judged. Metrics still come from eval records only.

Step 1 = serial runner with per-question retry + resume + cost aggregation.
Step 2 (later) = same interface, ProcessPoolExecutor underneath; each worker
builds its own Pipeline (independent Hy3Client) so concurrency is safe.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from rex.config import Config
from rex.models import EvalRecord, QuestionItem, VerificationResult, Verdict
from rex.pipeline import Pipeline, _placeholder_answer

log = logging.getLogger(__name__)

# A pipeline factory returns a per-question Pipeline (each with its own client).
# Injectable so tests can substitute a fake client without touching _eval_one.
PipelineFactory = Callable[[Config], Pipeline]


def _placeholder_eval_record(
    q: QuestionItem, error: Exception | None, config: Config | None = None
) -> EvalRecord:
    """Legal placeholder EvalRecord when a question fails after all retries.

    Uses Verdict.FAILED (not PROCESS_INCORRECT) so an infra failure is never
    counted as a process-error in the metrics. Mirrors Pipeline's semantics.
    """
    return EvalRecord(
        question_id=q.id,
        scene=q.scene,
        difficulty=q.difficulty,
        answer=_placeholder_answer(q.scene),
        verification=VerificationResult(
            verdict=Verdict.FAILED,
            findings=[],
            confidence=0.0,
            arbiter="FAILED",
        ),
        error=str(error) if error else "evaluation failed after retries",
    )


class EvalRunner:
    """Serial scheduler over a question pool, with retry / resume / cost tracking.

    - ``retries``: extra attempts per question beyond the first (0 = no retry).
      HTTP-level retries already live in Hy3Client; this is the QUESTION-level
      retry that recovers from one-off whole-question failures.
    - ``resume``: completed question_ids are skipped (loaded from the JSONL).
    - Cost aggregation: each question records its own cost; totals are summed
      here so callers never double-count solver+verifier.
    """

    def __init__(
        self,
        config: Config,
        retries: int = 2,
        backoff_base: float = 3.0,
        concurrency: int = 4,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        self.config = config
        self.retries = retries
        self.backoff_base = backoff_base
        self.concurrency = max(1, concurrency)
        # 默认工厂：每个题目新建一个独立 Pipeline（每 worker 独立 client）。
        # 测试可注入返回 Fake client 的工厂。
        self._pipeline_factory = pipeline_factory or Pipeline

    # -- main entry --------------------------------------------------------
    def run_eval(
        self,
        questions: list[QuestionItem],
        out_path: str | Path,
        resume: bool = True,
        concurrency: int | None = None,
    ) -> tuple[list[EvalRecord], dict[str, int]]:
        """Evaluate all questions; returns (records, cost_totals).

        ``records`` includes both newly-evaluated and resume-skipped questions
        (mirrors Pipeline.run_eval which returns the full ``done`` set), so
        callers can report the total completed count.

        ``cost_totals`` = {"calls": int, "total_cost": float} where calls is
        the aggregated model-call count across every question evaluated in THIS
        run (resume-skipped questions add 0).

        ``concurrency``: >1 evaluates questions in parallel (thread pool).
        Each worker thread gets its OWN Pipeline (independent Hy3Client), so
        there is no shared mutable client state. Resume bookkeeping and file
        appends happen only in this (main) thread, protected by a lock — safe
        under concurrency (plan X: main thread owns done_ids).
        """
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        concurrency = max(1, concurrency if concurrency is not None else self.concurrency)

        done: dict[str, EvalRecord] = {}
        if resume and out.exists():
            for line in out.open(encoding="utf-8"):
                if line.strip():
                    rec = EvalRecord.model_validate_json(line)
                    done[rec.question_id] = rec
            log.info("resume: %d already done in %s", len(done), out)

        pending = [q for q in questions if q.id not in done]
        total = len(pending)
        t_start = time.time()

        if total == 0 or concurrency == 1:
            total_calls = self._run_serial(pending, done, out)
        else:
            total_calls = self._run_parallel(pending, done, out, concurrency)

        return list(done.values()), {"calls": total_calls, "total_cost": 0.0}

    # -- serial path -------------------------------------------------------
    def _run_serial(
        self,
        pending: list[QuestionItem],
        done: dict[str, EvalRecord],
        out: Path,
    ) -> int:
        total = len(pending)
        total_calls = 0
        t_start = time.time()
        with out.open("a", encoding="utf-8") as f:
            for i, q in enumerate(pending, 1):
                rec, calls = self._eval_with_retry(q)
                f.write(rec.model_dump_json() + "\n")
                f.flush()
                done[q.id] = rec
                total_calls += calls
                self._log_progress(i, total, q, rec, calls, t_start)
        return total_calls

    # -- parallel path (thread pool; each worker owns its own Pipeline) -----
    def _run_parallel(
        self,
        pending: list[QuestionItem],
        done: dict[str, EvalRecord],
        out: Path,
        concurrency: int,
    ) -> int:
        total = len(pending)
        total_calls = 0
        t_start = time.time()
        completed = 0
        lock = threading.Lock()

        def _handle(q: QuestionItem, result) -> None:
            nonlocal total_calls, completed
            rec, calls = result
            with lock:                       # 串行化写盘 + done 更新（并发安全）
                with out.open("a", encoding="utf-8") as f:
                    f.write(rec.model_dump_json() + "\n")
                    f.flush()
                done[q.id] = rec
                total_calls += calls
                completed += 1
            self._log_progress(completed, total, q, rec, calls, t_start)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(self._eval_with_retry, q): q for q in pending}
            for fut in as_completed(futures):
                _handle(futures[fut], fut.result())
        return total_calls

    @staticmethod
    def _log_progress(i, total, q, rec, calls, t_start) -> None:
        elapsed = time.time() - t_start
        eta = elapsed / i * (total - i) if i else 0.0
        log.info(
            "[%d/%d] %s verdict=%s ans=%s calls=%d elapsed=%.0fs eta=%.0fs",
            i, total, q.id, rec.verification.verdict.value,
            rec.answer_correct, calls, elapsed, eta,
        )

    # -- single-question evaluation with retry -----------------------------
    def _eval_with_retry(self, q: QuestionItem) -> tuple[EvalRecord, int]:
        """Build a fresh Pipeline and evaluate one question, retrying failures.

        A fresh Pipeline per question is safe for Step 2 (each worker would own
        one anyway) and guarantees no shared mutable client state leaks across
        questions. Cost = that question's model-call count (solver+verifier+arb).
        """
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            pipe = self._pipeline_factory(self.config)
            try:
                t0 = time.time()
                rec = pipe._eval_one(q)          # noqa: SLF001 — reuse business logic
                calls = pipe.client.call_count
                rec.cost_calls = calls
                return rec, calls
            except Exception as e:  # noqa: BLE001 — retry whole-question failures
                pipe.client.close()
                last_err = e
                if attempt < self.retries:
                    delay = self.backoff_base * (2 ** attempt)  # 3s, 6s
                    log.warning(
                        "eval %s failed (attempt %d/%d): %s; retry in %.1fs",
                        q.id, attempt + 1, self.retries + 1, e, delay,
                    )
                    time.sleep(delay)
        log.warning("eval %s failed after %d attempts: %s",
                    q.id, self.retries + 1, last_err)
        calls = 0
        rec = _placeholder_eval_record(q, last_err)
        rec.cost_calls = calls
        return rec, calls
