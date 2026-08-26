"""FastAPI backend for the ReAgents v2 dashboard.

Endpoints (all data under Hy3_APP2/data/):
  GET  /api/summary        — 评估总览指标（含 refine 前后对比）
  GET  /api/questions      — 题目列表（scene/verdict 过滤）
  GET  /api/questions/{qid}— 单题详情（步骤 + findings + refine 轮次）
  GET  /api/golden         — 沉默失败 golden 样本库
  GET  /api/audit          — 人工抽检记录
  POST /api/interact       — 交互式解题（eval/refine 实时演示，需 Hy3 key）
  GET  /                   — 静态 SPA
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rex.config import Config
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.models import EvalRecord, GoldenSample, QuestionItem, RefineRecord
from rex.pipeline import load_jsonl

ROOT = Path(__file__).resolve().parents[2]
CFG = Config.from_env(ROOT)
STATIC = ROOT / "src" / "web" / "static"

app = FastAPI(title="ReAgents v2 评估仪表盘", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _load_questions() -> list[QuestionItem]:
    qs: list[QuestionItem] = []
    for scene in ("math", "algorithm"):
        qs += load_jsonl(CFG.data_dir / "questions" / f"{scene}.jsonl", QuestionItem)
    return qs


def _load_evals() -> list[EvalRecord]:
    out = []
    for scene in ("math", "algorithm"):
        out += load_jsonl(CFG.outputs_dir / f"eval_{scene}.jsonl", EvalRecord)
    return out


def _load_refines() -> list[RefineRecord]:
    out = []
    for scene in ("math", "algorithm"):
        out += load_jsonl(CFG.outputs_dir / f"refine_{scene}.jsonl", RefineRecord)
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
    for name in ("golden_math.jsonl", "golden_algorithm.jsonl"):
        out += load_jsonl(CFG.data_dir / "golden" / name, GoldenSample)
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
              tier: str | None = None) -> list[dict]:
    evals = _load_evals()
    qmap = {q.id: q for q in _load_questions()}
    items = []
    for r in evals:
        if scene and r.scene != scene:
            continue
        if verdict and r.verification.verdict.value != verdict:
            continue
        if tier and r.difficulty.value != tier:
            continue
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
            "created_at": r.created_at,
        })
    items.sort(key=lambda x: x["created_at"] or "")
    return items


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
    scene: str = "math"
    prompt: str
    answer: str = ""                     # 数学场景标准答案（可选）
    samples: list[InteractSample] = []   # 算法场景输入输出样例（可选）
    refine: bool = False                 # 是否演示修正闭环
    max_rounds: int = 2


@app.post("/api/interact")
def interact(req: InteractRequest) -> dict:
    """交互式解题：自定义题目 → 求解 → 执行/比对 → 验证 →（可选）修正。

    返回含：elapsed（总耗时秒）、cost_calls（模型调用次数）、以及 eval/refine 记录。
    前端据此展示沙盒执行结果、错误定位 findings、耗时与调用成本。
    """
    from rex.models import Difficulty, QuestionItem, TestCase
    from rex.pipeline import Pipeline

    # 构造题目：算法场景把输入输出样例既拼入 prompt，又作为沙盒测试用例
    prompt = req.prompt
    test_cases: list[TestCase] = []
    if req.scene == "algorithm" and req.samples:
        test_cases = [TestCase(input=s.input, output=s.output) for s in req.samples]
        sample_block = "\n".join(
            f"样例{i}：\n输入：\n{s.input}\n输出：\n{s.output}" for i, s in enumerate(req.samples, 1)
        )
        prompt = f"{req.prompt}\n\n【输入输出样例】\n{sample_block}"

    q = QuestionItem(
        id="interact", scene=req.scene, title=req.prompt[:50], prompt=prompt,
        difficulty=Difficulty.BASIC, source="interactive",
        standard_answer=req.answer, test_cases=test_cases,
    )
    pipe = Pipeline(CFG)
    t0 = time.time()
    try:
        if not req.refine:
            rec = pipe._eval_one(q)
            # 单独重跑一次沙盒执行，拿到 exec 细节（错误信息）供前端展示
            _, pass_rate, exec_error = pipe._execute(q, rec.answer)
            payload = {
                "mode": "eval", "eval": rec.model_dump(),
                "elapsed": round(time.time() - t0, 2),
                "cost_calls": pipe.client.call_count,
                "exec": {"test_pass_rate": pass_rate, "error": exec_error},
            }
            return payload
        rrec = pipe.refiner.refine(q)
        payload = {
            "mode": "refine", "refine": rrec.model_dump(),
            "elapsed": round(time.time() - t0, 2),
            "cost_calls": pipe.client.call_count,
        }
        return payload
    finally:
        pipe.client.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
