"""FastAPI backend for the HY3Coder dashboard.

Endpoints (all data under Hy3_APP2/data/):
  GET  /api/summary        — 评估总览指标（含 refine 前后对比）
  GET  /api/questions      — 题目列表（scene/verdict 过滤）
  GET  /api/questions/{qid}— 单题详情（步骤 + findings + refine 轮次）
  GET  /api/golden         — 沉默失败 golden 样本库
  GET  /api/audit          — 人工抽检记录
  POST /api/interact       — 交互式解题（同步，保留兼容）
  POST /api/interact/job   — 交互式解题（异步 job：后台线程 + 阶段进度）
  GET  /api/interact/job/{job_id}      — 查询 job 状态/中间结果
  GET  /api/interact/job/{job_id}/events — SSE 阶段事件流（可选）
  GET  /                   — 静态 SPA
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rex.config import Config
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.models import EvalRecord, GoldenSample, QuestionItem, RefineRecord
from rex.pipeline import load_jsonl

ROOT = Path(__file__).resolve().parents[2]
CFG = Config.from_env(ROOT)
STATIC = ROOT / "src" / "web" / "static"

# 共享的 RecordStore 实例（带缓存）：所有请求复用，避免每次全量读文件
from rex.store import RecordStore
STORE = RecordStore(CFG.outputs_dir)

app = FastAPI(title="HY3Coder 评估仪表盘", version="2.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _load_questions() -> list[QuestionItem]:
    qs: list[QuestionItem] = []
    for f in ("algorithm.jsonl", "abc_selfbuilt.jsonl", "cf_selfbuilt.jsonl"):
        p = CFG.data_dir / "questions" / f
        if p.exists():
            qs += load_jsonl(p, QuestionItem)
    return qs


def _load_evals() -> list[EvalRecord]:
    return STORE.load_evals()


def _load_refines() -> list[RefineRecord]:
    out = []
    for f in ("refine_algorithm.jsonl",):
        p = CFG.outputs_dir / f
        if p.exists():
            out += load_jsonl(p, RefineRecord)
    return out


def _dump(o):
    """dataclass / pydantic 通用序列化。"""
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if hasattr(o, "__dict__"):
        return {k: _dump(v) for k, v in vars(o).items()}
    return o


def _load_golden() -> list[GoldenSample]:
    out = []
    for name in ("golden_algorithm.jsonl",):
        p = CFG.data_dir / "golden" / name
        if p.exists():
            out += load_jsonl(p, GoldenSample)
    return out


@app.get("/api/summary")
def summary() -> dict:
    evals = _load_evals()
    refines = _load_refines()
    base = compute_metrics(evals) if evals else None
    golden = _load_golden()
    return {
        "n": base.n if base else 0,
        "answer_accuracy": base.answer_accuracy if base else None,
        "process_correctness": base.process_correctness if base else None,
        "verdict_dist": base.verdict_dist if base else {},
        "error_type_dist": base.error_type_dist if base else {},
        "per_tier": {k: _dump(v) for k, v in (base.per_tier.items() if base else {})},
        "refine": _dump(refine_comparison(refines)) if refines else None,
        "golden_n": len(golden),
        "last_run": evals[-1].created_at if evals else None,
    }


@app.get("/api/questions")
def questions(scene: str | None = None, verdict: str | None = None,
              tier: str | None = None, source: str | None = None,
              qid: str | None = None, keyword: str | None = None,
              since: str | None = None, until: str | None = None,
              sort: str = "created_at", order: str = "desc",
              limit: int = 100, offset: int = 0) -> dict:
    """评估记录列表：支持筛选（场景/难度/判定/来源/题号/关键词/时间）+ 分页 + 排序。"""
    store = STORE
    records, total = store.query_evals(
        scene=scene, difficulty=tier, verdict=verdict, source=source,
        qid=qid, keyword=keyword, since=since, until=until,
        sort=sort, order=order, limit=limit, offset=offset,
    )
    qmap = {q.id: q for q in _load_questions()}
    items = []
    for r in records:
        items.append({
            "question_id": r.question_id,
            "scene": r.scene,
            "difficulty": r.difficulty.value,
            "verdict": r.verification.verdict.value,
            "answer_correct": r.answer_correct,
            "test_pass_rate": r.test_pass_rate,
            "confidence": r.verification.confidence,
            "error_types": [f.error_type.value for f in r.verification.findings],
            "prompt": (qmap.get(r.question_id).prompt if r.question_id in qmap else "")[:80],
            "source": r.source,
            "created_at": r.created_at,
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/browse")
def browse(scene: str | None = None, limit: int = 100, offset: int = 0,
           source: str | None = None) -> dict:
    """临时题集浏览器：返回题集完整原始记录（含所有字段），供可视化浏览。

    仅用于人工检视题集结构/内容，不属于正式评估 API。
    """
    qs = _load_questions()
    if scene:
        qs = [q for q in qs if q.scene == scene]
    if source:
        qs = [q for q in qs if source in q.source]
    total = len(qs)
    page = qs[offset:offset + limit]
    items = [q.model_dump() for q in page]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/questions/{qid}")
def question_detail(qid: str) -> dict:
    evals = _load_evals()
    rec = next((r for r in evals if r.question_id == qid), None)
    if rec is None:
        raise HTTPException(404, f"question {qid} not evaluated")
    qmap = {q.id: q for q in _load_questions()}
    q = qmap.get(qid)
    refines = _load_refines()
    refine_rec = next((r for r in refines if r.question_id == qid), None)
    return {
        "question": q.model_dump() if q else None,
        "eval": rec.model_dump(),
        "refine": refine_rec.model_dump() if refine_rec else None,
    }


@app.get("/api/golden")
def golden() -> list[dict]:
    return [g.model_dump() for g in _load_golden()]


@app.get("/api/audit")
def audit() -> list[dict]:
    path = CFG.outputs_dir / "audit_records.jsonl"
    if not path.exists():
        return []
    from rex.models import AuditRecord
    return [a.model_dump() for a in load_jsonl(path, AuditRecord)]


class InteractSample(BaseModel):
    """算法题输入输出样例（作为沙盒测试用例 + 拼入题目描述）。"""
    input: str
    output: str


class InteractRequest(BaseModel):
    scene: str = "algorithm"
    prompt: str
    answer: str = ""                     # standard_answer 文本比对（无测试用例时兜底）
    samples: list[InteractSample] = []   # 算法场景输入输出样例（可选）
    refine: bool = False                 # 是否演示修正闭环
    max_rounds: int = 2


@app.post("/api/interact")
def interact(req: InteractRequest) -> dict:
    """交互式解题（同步版，保留兼容）：阻塞到全部完成才返回。"""
    job = _start_interact_job(req)
    job["event"].wait()   # 同步等待完成（线程安全）
    return _job_payload(job)


# ===========================================================================
# 异步交互 job：后台线程分阶段执行，前端轮询 / SSE 实时展示进度
# ===========================================================================
def _build_question(req: InteractRequest):
    """把请求体构造成 QuestionItem（算法场景样例拼入 prompt + 作为沙盒用例）。"""
    from rex.models import Difficulty, QuestionItem, TestCase

    prompt = req.prompt
    test_cases: list[TestCase] = []
    if req.scene == "algorithm" and req.samples:
        test_cases = [TestCase(input=s.input, output=s.output) for s in req.samples]
        sample_block = "\n".join(
            f"样例{i}：\n输入：\n{s.input}\n输出：\n{s.output}" for i, s in enumerate(req.samples, 1)
        )
        prompt = f"{req.prompt}\n\n【输入输出样例】\n{sample_block}"
    qid = "I" + time.strftime("%Y%m%d_%H%M%S")
    return QuestionItem(
        id=qid, scene=req.scene, title=req.prompt[:50], prompt=prompt,
        difficulty=Difficulty.BASIC, source="interactive",
        standard_answer=req.answer, test_cases=test_cases,
    )


# job 存储：{job_id: dict(phase, mode, answer, payload, event, queue, ...)}
JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _start_interact_job(req: InteractRequest) -> dict:
    """启动后台交互 job，返回 job 状态字典。"""
    job_id = "IJ" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    job = {
        "id": job_id,
        "mode": "refine" if req.refine else "eval",
        "phase": "queued",          # queued/solve/answer/execute/static/verify/revise-N/verify-N/done/failed
        "message": "排队中…",
        "answer": None,             # solve 完成后的中间答案（供先展示过程）
        "payload": None,            # 完成后的最终返回体（与同步版一致）
        "error": None,
        "elapsed": 0.0,
        "cost_calls": 0,
        "event": threading.Event(),  # 完成信号（同步版 wait 用）
        "queue": [],                # SSE 阶段事件缓冲（list + 游标）
        "req": req,
        "t0": time.time(),
    }
    with _JOBS_LOCK:
        JOBS[job_id] = job
        # 简单上限：只保留最近 50 个 job，避免无限增长
        if len(JOBS) > 50:
            for old_id in sorted(JOBS, key=lambda k: JOBS[k]["t0"])[: len(JOBS) - 50]:
                JOBS.pop(old_id, None)

    def _run() -> None:
        from rex.pipeline import Pipeline

        pipe = Pipeline(CFG)
        job["phase"] = "solve"
        job["message"] = "正在生成分步解答…"
        t0 = job["t0"]

        def _report(phase: str, payload=None, message: str | None = None) -> None:
            job["phase"] = phase
            if message:
                job["message"] = message
            if payload is not None and getattr(payload, "model_dump", None):
                job["answer"] = payload.model_dump()
            elif isinstance(payload, dict):
                job["answer"] = payload
            # SSE 事件缓冲（无订阅者也缓存，便于轮询端点直接读最终态）
            job["queue"].append({
                "phase": phase,
                "message": job["message"],
                "elapsed": round(time.time() - job["t0"], 1),
                "answer": job["answer"],
            })

        try:
            q = _build_question(job["req"])
            store = STORE
            if job["mode"] == "eval":
                rec = pipe._eval_one(q, progress=lambda p, payload=None: (
                    _report(p, payload, _PHASE_MSG.get(p) or _phase_default_msg(p))))
                rec.source = "interactive"
                store.append_eval(rec)
                # 单独重跑一次沙盒执行，拿到 exec 细节（错误信息）供前端展示
                _, pass_rate, exec_error = pipe._execute(q, rec.answer)
                job["payload"] = {
                    "mode": "eval", "eval": rec.model_dump(),
                    "elapsed": round(time.time() - t0, 2),
                    "cost_calls": pipe.client.call_count,
                    "exec": {"test_pass_rate": pass_rate, "error": exec_error},
                }
            else:
                rrec = pipe.refiner.refine(q, progress=lambda p, payload=None: (
                    _report(p, payload, _PHASE_MSG.get(p) or _phase_default_msg(p))))
                rrec.source = "interactive"
                store.append_refine(rrec)
                job["payload"] = {
                    "mode": "refine", "refine": rrec.model_dump(),
                    "elapsed": round(time.time() - t0, 2),
                    "cost_calls": pipe.client.call_count,
                }
            job["phase"] = "done"
            job["message"] = "评估完成"
            job["elapsed"] = round(time.time() - t0, 2)
            job["queue"].append({"phase": "done", "message": "评估完成",
                                 "elapsed": job["elapsed"], "answer": None})
        except Exception as e:  # noqa: BLE001
            job["phase"] = "failed"
            job["error"] = str(e)
            job["message"] = f"运行失败：{e}"
            job["queue"].append({"phase": "failed", "message": job["message"],
                                 "elapsed": round(time.time() - job["t0"], 1)})
        finally:
            pipe.client.close()
            job["event"].set()

    threading.Thread(target=_run, daemon=True).start()
    return job


_PHASE_MSG = {
    "solve": "正在生成分步解答…",
    "answer": "解答完成，执行测试中…",
    "execute": "沙盒执行测试用例…",
    "static": "静态规则校验…",
    "verify": "过程交叉审查（V1/V2）…",
    "revise-1": "第 1 轮修正…", "answer-1": "第 1 轮修订完成…", "verify-1": "第 1 轮复核…",
    "revise-2": "第 2 轮修正…", "answer-2": "第 2 轮修订完成…", "verify-2": "第 2 轮复核…",
    "revise-3": "第 3 轮修正…", "answer-3": "第 3 轮修订完成…", "verify-3": "第 3 轮复核…",
}


def _phase_default_msg(phase: str) -> str:
    """未注册阶段的兜底中文提示。"""
    if phase.startswith("answer-"):
        n = phase.split("-")[-1]
        return f"第 {n} 轮修订完成…"
    return "处理中…"


def _job_payload(job: dict) -> dict:
    """把 job 状态转成前端可读快照。"""
    return {
        "job_id": job["id"],
        "mode": job["mode"],
        "phase": job["phase"],
        "message": job["message"],
        "answer": job["answer"],
        "result": job["payload"],
        "error": job["error"],
        "elapsed": job["elapsed"],
        "cost_calls": job["cost_calls"],
        "status": "done" if job["phase"] == "done" else
                  ("failed" if job["phase"] == "failed" else "running"),
    }


def _get_job_or_404(job_id: str) -> dict:
    with _JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return job


@app.post("/api/interact/job")
def interact_job(req: InteractRequest) -> dict:
    """异步交互：立即返回 job_id，前端轮询 /events 展示实时进度。"""
    job = _start_interact_job(req)
    return {"job_id": job["id"], "mode": job["mode"]}


@app.get("/api/interact/job/{job_id}")
def interact_job_status(job_id: str) -> dict:
    """查询交互 job 的当前阶段与中间结果（轮询端点）。"""
    return _job_payload(_get_job_or_404(job_id))


@app.get("/api/interact/job/{job_id}/events")
def interact_job_events(job_id: str):
    """SSE 阶段事件流：实时推送 phase/answer，客户端可用 EventSource 订阅。"""
    job = _get_job_or_404(job_id)

    def gen():
        sent = 0
        while True:
            q = job["queue"]
            while sent < len(q):
                ev = q[sent]
                sent += 1
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if job["phase"] in ("done", "failed"):
                break
            time.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/browse")
def browse_page() -> FileResponse:
    """临时题集浏览器页面（独立于主仪表盘）。"""
    return FileResponse(STATIC / "browse.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
