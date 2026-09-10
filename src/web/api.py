"""FastAPI backend for the HY3Coder dashboard.

Endpoints (all data under Hy3_APP2/data/):
  GET  /api/summary        — 评估总览指标（含 refine 前后对比）
  GET  /api/questions      — 题目列表（scene/verdict 过滤）
  GET  /api/questions/{qid}— 单题详情（步骤 + findings + refine 轮次）
  GET  /api/golden         — 沉默失败 golden 样本库
  GET  /api/audit          — 人工抽检记录
  GET  /api/meta           — 数据源元信息（路径/命令）
  GET  /api/config/model   — 当前模型调用配置（Key 只回显掩码）
  POST /api/config/model   — 保存模型配置（写内存 + 本地 .env）
  POST /api/config/model/test — 模型连通性测试
  GET  /api/lab/questions  — 选题列表（交互式解题工作台）
  GET  /api/lab/questions/{qid} — 选题详情（题面/公开样例/自带参考解）
  POST /api/lab/run        — 试运行：沙盒跑代码，逐用例回显
  POST /api/interact       — 交互式解题（同步，保留兼容）
  POST /api/interact/job   — 交互式解题（异步 job：后台线程 + 阶段进度）
  GET  /api/interact/job/{job_id}      — 查询 job 状态/中间结果
  GET  /api/interact/job/{job_id}/events — SSE 阶段事件流（可选）
  GET  /                   — 静态 SPA
"""
from __future__ import annotations

import json
import logging
import re
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
from rex.executor.sandbox import detect_language
from rex.hy3_client import Hy3Client
from rex.metrics.compute import audit_metrics, compute_metrics, refine_comparison
from rex.models import (
    EvalRecord,
    GoldenSample,
    InteractResult,
    InteractSession,
    InteractTrial,
    InteractTrialCase,
    QuestionItem,
    RefineRecord,
)
from rex.pipeline import load_jsonl

ROOT = Path(__file__).resolve().parents[2]
CFG = Config.from_env(ROOT)
STATIC = ROOT / "src" / "web" / "static"
log = logging.getLogger(__name__)

#: 交互题的 source 前缀（题池里靠它把演示题与正式题集区分开）
INTERACTIVE_SOURCE = "交互解题 · "

# 共享的 RecordStore 实例（带缓存）：所有请求复用，避免每次全量读文件
from rex.store import RecordStore
STORE = RecordStore(CFG.outputs_dir, root=ROOT)

app = FastAPI(title="HY3Coder 评估仪表盘", version="2.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _load_questions() -> list[QuestionItem]:
    """合并所有启用数据集的题集（路径由数据源注册中心统一声明）。"""
    from rex.datasource import load_active_questions
    return load_active_questions(ROOT)


def _load_evals() -> list[EvalRecord]:
    return STORE.load_evals()


def _load_refines() -> list[RefineRecord]:
    """启用数据集的正式 refine 记录（无则返回空，展示『暂无 refine』）。"""
    from rex.datasource import load_active_refines
    return load_active_refines(ROOT)


def _load_interactive_refines() -> list[RefineRecord]:
    """交互演示的 refine 记录（独立文件，只供单题回放，不进正式统计）。"""
    from rex.datasource import load_interactive_refines
    return load_interactive_refines(ROOT)


def _load_interact_sessions() -> list[InteractSession]:
    """交互解题会话快照（题面/用例/参考解/模型/试运行）。"""
    from rex.datasource import load_interact_sessions
    return load_interact_sessions(ROOT)


def _dump(o):
    """dataclass / pydantic 通用序列化。"""
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if hasattr(o, "__dict__"):
        return {k: _dump(v) for k, v in vars(o).items()}
    return o


def _load_golden() -> list[GoldenSample]:
    """真实评测检出的 SILENT_FAILURE 留档，路径由注册中心统一声明。"""
    from rex.datasource import load_golden
    return load_golden(ROOT)


@app.get("/api/summary")
def summary(ds: str | None = None, minor: int | None = None) -> dict:
    """``minor=1`` 可临时切到副口径（minor 计入过程错），否则用 config 开关。"""
    evals = _load_evals()
    refines = _load_refines()
    # 数据集过滤（按题号前缀 A*/C*），便于分别看 ABC / Codeforces 总览
    prefix = {"abc_selfbuilt": "A", "cf_selfbuilt": "C"}.get(ds or "")
    if prefix:
        evals = [r for r in evals if r.question_id.startswith(prefix)]
        refines = [r for r in refines if r.question_id.startswith(prefix)]
    # formal_only：总览指标只统计正式 run-eval（交互演示不入统计口径）
    formal = [r for r in evals if r.source == "run-eval"]
    minor_as_error = (minor == 1) if minor is not None else CFG.minor_as_error
    base = compute_metrics(evals, formal_only=True, minor_as_error=minor_as_error) if evals else None
    base_main = compute_metrics(evals, formal_only=True) if evals else None  # 主口径参考
    golden = _load_golden()
    # 多维画像（join 题集元数据：alg_classes / scale_tier）
    from rex.metrics.compute import compute_facets
    qmap = {q.id: q.model_dump() for q in _load_questions()}
    if prefix:
        qmap = {k: v for k, v in qmap.items() if k.startswith(prefix)}
    facets = compute_facets(evals, qmap)
    return {
        "n": base.n if base else 0,
        "answer_accuracy": base.answer_accuracy if base else None,
        "process_correctness": base.process_correctness if base else None,
        "minor_as_error": minor_as_error,   # 当前口径：True=副口径(minor计入)
        "process_correctness_main": base_main.process_correctness if base_main else None,
        "verdict_dist": base.verdict_dist if base else {},
        "error_type_dist": base.error_type_dist if base else {},
        "per_tier": {k: _dump(v) for k, v in (base.per_tier.items() if base else {})},
        "per_type": facets["per_type"],
        "per_scale": facets["per_scale"],
        "per_tier_scale": facets["per_tier_scale"],
        "refine": _dump(refine_comparison(refines)) if refines else None,
        "golden_n": len(golden),
        "last_run": formal[-1].created_at if formal else None,
    }


@app.get("/api/meta")
def meta() -> dict:
    """数据源元信息：前端提示命令不再写死文件路径。"""
    from rex import datasource
    rel = lambda p: str(p.relative_to(ROOT)).replace("\\", "/")
    dss = [
        {"key": d.key, "label": d.label, "enabled": d.enabled,
         "questions": rel(datasource.questions_path(ROOT, d)),
         "evals": rel(datasource.evals_path(ROOT, d)) if d.evals else None,
         "refine": rel(datasource.refine_path(ROOT, d)) if d.refine else None}
        for d in datasource.DATASETS
    ]
    return {
        "datasets": dss,
        "audit_file": rel(datasource.audit_path(ROOT)),
        "golden_files": [rel(p) for p in datasource.golden_paths(ROOT)],
        "interactive_eval": rel(datasource.interactive_evals_path(ROOT)),
        "interactive_sessions": rel(datasource.interact_sessions_path(ROOT)),
        "interactive_questions": rel(datasource.interactive_questions_path(ROOT)),
        "audit_command": "python -m src.cli audit --results "
                         + rel(datasource.evals_path(ROOT, next(d for d in datasource.active_datasets() if d.evals))),
    }


# ===========================================================================
# 模型调用配置：读写 + 连通性测试
# 演示/复现都要求「看得出这次调用的是哪个模型」，故把运行期配置显式暴露出来。
# Key 只落本地 .env（已 gitignore），接口只回显掩码，留空即保持原值。
# ===========================================================================
PROVIDERS: dict[str, dict] = {
    "hy3": {"label": "Hy3（默认 · 腾讯 TokenHub）",
            "base_url": "https://tokenhub.tencentmaas.com/v1", "model": "hy3"},
    "openai": {"label": "OpenAI 兼容",
               "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"label": "DeepSeek",
                 "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "vllm": {"label": "本地 vLLM / Ollama",
             "base_url": "http://127.0.0.1:8000/v1", "model": "local"},
    "custom": {"label": "自定义", "base_url": "", "model": ""},
}

_ENV_KEYS = {
    "base_url": "HY3_BASE_URL", "model": "HY3_MODEL",
    "reasoning": "HY3_REASONING_EFFORT", "api_key": "HY3_API_KEY",
}


def _guess_provider(base_url: str, model: str) -> str:
    """按 Base URL / 模型名回推提供方，供前端下拉框定位。"""
    u = (base_url or "").lower()
    if "tokenhub" in u or "hy3" in (model or "").lower():
        return "hy3"
    if "openai" in u:
        return "openai"
    if "deepseek" in u:
        return "deepseek"
    if "localhost" in u or "127.0.0.1" in u:
        return "vllm"
    return "custom"


def _mask_key(key: str) -> str:
    """只回显尾部 4 位——页面不回传完整 Key。"""
    k = (key or "").strip()
    return ("*" * max(0, len(k) - 4) + k[-4:]) if k else ""


def _write_env(updates: dict[str, str]) -> None:
    """就地更新项目根 .env 的 HY3_* 键，保留注释与其它变量（如 AtCoder cookie）。"""
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").split("\n") if path.exists() else []
    seen: set[str] = set()
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z_0-9]+)\s*=", ln)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)} = {updates[m.group(1)]}"
            seen.add(m.group(1))
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k} = {v}")
    # 显式 newline="\n"（不依赖平台默认的换行转换）；项目环境是 Python 3.9，
    # Path.write_text(newline=...) 要到 3.10 才有，故走 open()。
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


class ModelConfigIn(BaseModel):
    """模型接入配置；字段为 None 表示不改动该项。"""
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    reasoning: str | None = None
    temperature: float | None = None
    timeout: float | None = None
    api_key: str | None = None      # None / 空串 = 保留已存 Key


def _cfg_payload() -> dict:
    return {
        "providers": {k: v["label"] for k, v in PROVIDERS.items()},
        "presets": PROVIDERS,
        "provider": _guess_provider(CFG.hy3_base_url, CFG.hy3_model),
        "base_url": CFG.hy3_base_url,
        "model": CFG.hy3_model,
        "reasoning": CFG.hy3_reasoning_effort,
        "temperature": CFG.temperature,
        "timeout": CFG.timeout,
        "api_key_masked": _mask_key(CFG.hy3_api_key),
        "api_key_set": bool(CFG.hy3_api_key),
        "has_credentials": CFG.has_credentials,
        "env_file": ".env",
    }


@app.get("/api/config/model")
def get_model_config() -> dict:
    """当前生效的模型调用配置（Key 只给掩码）。"""
    return _cfg_payload()


@app.post("/api/config/model")
def set_model_config(req: ModelConfigIn) -> dict:
    """保存模型配置：更新内存 CFG（后续 job 立即生效）并落本地 .env。"""
    if req.base_url is not None:
        CFG.hy3_base_url = req.base_url.strip()
    if req.model is not None:
        CFG.hy3_model = req.model.strip()
    if req.reasoning is not None:
        CFG.hy3_reasoning_effort = req.reasoning.strip()
    if req.temperature is not None:
        CFG.temperature = float(req.temperature)
    if req.timeout is not None:
        CFG.timeout = float(req.timeout)
    if req.api_key:                     # 留空 = 不动已存 Key
        CFG.hy3_api_key = req.api_key.strip()
    updates = {
        _ENV_KEYS["base_url"]: CFG.hy3_base_url,
        _ENV_KEYS["model"]: CFG.hy3_model,
        _ENV_KEYS["reasoning"]: CFG.hy3_reasoning_effort,
    }
    if req.api_key:
        updates[_ENV_KEYS["api_key"]] = CFG.hy3_api_key
    _write_env(updates)
    return _cfg_payload()


@app.post("/api/config/model/test")
def test_model_config(req: ModelConfigIn) -> dict:
    """连通性测试：用表单里的值（未填的用当前配置）发一条最小请求。"""
    key = (req.api_key or CFG.hy3_api_key or "").strip()
    base = (req.base_url or CFG.hy3_base_url or "").strip()
    model = (req.model or CFG.hy3_model or "").strip()
    if not key:
        return {"ok": False, "model": model, "base_url": base, "error": "未填 API Key"}
    client = Hy3Client(
        api_key=key, base_url=base, model=model,
        reasoning_effort=(req.reasoning or CFG.hy3_reasoning_effort),
        timeout=min(60.0, req.timeout or CFG.timeout), max_retries=0,
    )
    t0 = time.time()
    try:
        reply = client.chat("ping", system="你是连通性探针，回复 pong 即可。")
        return {"ok": True, "model": model, "base_url": base,
                "elapsed": round(time.time() - t0, 2), "reply": (reply or "")[:80]}
    except Exception as e:  # noqa: BLE001 — 连通性探测要把失败原因原样回给页面
        return {"ok": False, "model": model, "base_url": base,
                "elapsed": round(time.time() - t0, 2), "error": str(e)[:300]}
    finally:
        client.close()


@app.get("/api/questions")
def questions(scene: str | None = None, verdict: str | None = None,
              tier: str | None = None, source: str | None = None,
              ds: str | None = None,
              qid: str | None = None, keyword: str | None = None,
              since: str | None = None, until: str | None = None,
              sort: str = "created_at", order: str = "desc",
              limit: int = 100, offset: int = 0) -> dict:
    """评估记录列表：支持筛选（场景/难度/判定/来源/数据集/题号/关键词/时间）+ 分页 + 排序。

    ``ds`` 按题号前缀区分数据集：abc_selfbuilt(A*) / cf_selfbuilt(C*)。
    """
    store = STORE
    prefix = {"abc_selfbuilt": "A", "cf_selfbuilt": "C"}.get(ds or "")
    # 数据集过滤需在分页前生效：带 ds 时先查全量再本地过滤+分页
    eff_limit = limit if not prefix else 10_000
    eff_offset = offset if not prefix else 0
    records, total = store.query_evals(
        scene=scene, difficulty=tier, verdict=verdict, source=source,
        qid=qid, keyword=keyword, since=since, until=until,
        sort=sort, order=order, limit=eff_limit, offset=eff_offset,
    )
    if prefix:
        records = [r for r in records if r.question_id.startswith(prefix)]
        total = len(records)
        records = records[offset:offset + limit]
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
    # 交互演示的 refine 单独存放（不混进正式 refine 文件），回放时两处都查
    refines = _load_refines() + _load_interactive_refines()
    refine_rec = next((r for r in refines if r.question_id == qid), None)
    sessions = _load_interact_sessions()
    session = next((s for s in sessions if s.question_id == qid), None)
    return {
        "question": q.model_dump() if q else None,
        "eval": rec.model_dump(),
        "refine": refine_rec.model_dump() if refine_rec else None,
        # 交互解题会话快照（题面来源/命中模型/参考解试运行），正式评测题为 None
        "session": session.model_dump() if session else None,
    }


@app.get("/api/golden")
def golden() -> list[dict]:
    return [g.model_dump() for g in _load_golden()]


@app.get("/api/audit")
def audit() -> list[dict]:
    from rex.datasource import load_audits
    return [a.model_dump() for a in load_audits(ROOT)]


# ===========================================================================
# 交互式解题工作台：题集选题（只暴露公开用例）+ 参考解试运行
# ===========================================================================
class LabSample(BaseModel):
    """算法题输入输出样例（试运行用例）。"""
    input: str
    output: str


class LabRunIn(BaseModel):
    code: str
    language: str = "auto"           # auto / python / cpp
    question_id: str | None = None   # 给定时用该题公开用例 + 该题判题模式
    samples: list[LabSample] = []    # 未给题集时用手填样例
    timeout: float = 10.0


def _question_map() -> dict[str, QuestionItem]:
    return {q.id: q for q in _load_questions()}


@app.get("/api/lab/questions")
def lab_questions(keyword: str | None = None, ds: str | None = None,
                  limit: int = 30, offset: int = 0) -> dict:
    """选题列表：题面预览 + 公开用例数（隐藏用例只给数量，不外发内容）。

    只列正式题集：交互题池里的题（演示现场输入、每次求解新增一条）不在这里出现，
    否则演示几次后选题列表会被 IX00xx 淹掉；交互题仍可在「单题回放」按题号查看。
    """
    qs = [q for q in _load_questions() if not q.source.startswith(INTERACTIVE_SOURCE)]
    prefix = {"abc_selfbuilt": "A", "cf_selfbuilt": "C"}.get(ds or "")
    if prefix:
        qs = [q for q in qs if q.id.startswith(prefix)]
    if keyword:
        kw = keyword.lower()
        qs = [q for q in qs
              if kw in q.id.lower() or kw in q.title.lower() or kw in q.prompt.lower()]
    total = len(qs)
    return {
        "items": [{
            "id": q.id, "title": q.title, "difficulty": q.difficulty.value,
            "source": q.source, "source_id": q.source_id,
            "n_public": sum(1 for t in q.test_cases if not t.hidden),
            "n_hidden": sum(1 for t in q.test_cases if t.hidden),
            "preview": re.sub(r"\s+", " ", q.prompt)[:120],
        } for q in qs[offset:offset + limit]],
        "total": total, "limit": limit, "offset": offset,
    }


@app.get("/api/lab/questions/{qid}")
def lab_question(qid: str) -> dict:
    """选题详情：题面 + 公开样例 + 标准答案 + 题集自带参考解。"""
    q = _question_map().get(qid)
    if q is None:
        raise HTTPException(404, f"question {qid} not found")
    public = [t for t in q.test_cases if not t.hidden]
    ref = q.reference_solution or ""
    return {
        "id": q.id, "title": q.title, "prompt": q.prompt,
        "difficulty": q.difficulty.value, "source": q.source, "source_id": q.source_id,
        "standard_answer": q.standard_answer,
        "samples": [{"input": t.input, "output": t.output} for t in public],
        "n_public": len(public), "n_hidden": len(q.test_cases) - len(public),
        "reference_solution": ref,
        "reference_language": detect_language(ref) if ref else None,
        "judge": q.judge.value, "checker_language": q.checker_language,
    }


@app.post("/api/lab/run")
def lab_run(req: LabRunIn) -> dict:
    """试运行：在沙盒里跑给定代码，逐用例回显输入/期望/实际输出与耗时。

    指定 ``question_id`` 时用该题公开用例并沿用其判题模式（special 走 checker）；
    否则用手填样例，走 EXACT 文本比对（与正式评测同一套判定函数）。
    """
    from rex.executor.tests import run_cases_detailed
    from rex.models import Judge, TestCase

    if not (req.code or "").strip():
        return {"language": None, "total": 0, "passed": 0, "pass_rate": None,
                "elapsed": 0.0, "cases": [], "error": "没有可运行的代码"}
    lang = req.language if req.language in ("python", "cpp") else detect_language(req.code)
    judge, checker, checker_lang, qid = Judge.EXACT, None, "python", None
    if req.question_id:
        q = _question_map().get(req.question_id)
        if q is None:
            raise HTTPException(404, f"question {req.question_id} not found")
        qid, judge, checker, checker_lang = q.id, q.judge, q.checker_code, q.checker_language
        samples = [LabSample(input=t.input, output=t.output)
                   for t in q.test_cases if not t.hidden]
    else:
        samples = req.samples
    if not samples:
        return {"language": lang, "question_id": qid, "total": 0, "passed": 0,
                "pass_rate": None, "elapsed": 0.0, "cases": [],
                "error": "没有可运行的用例：请选择题目或填写输入输出样例"}
    if Judge(judge) == Judge.SPECIAL and not checker:
        return {"language": lang, "question_id": qid, "total": 0, "passed": 0,
                "pass_rate": None, "elapsed": 0.0, "cases": [],
                "error": "该题为 SPJ 判题，但题集未提供 checker 代码，无法试运行"}
    t0 = time.time()
    runs = run_cases_detailed(
        req.code, [TestCase(input=s.input, output=s.output) for s in samples],
        timeout=req.timeout, language=lang, judge=judge,
        checker_code=checker, checker_language=checker_lang,
    )
    passed = sum(1 for r in runs if r.passed)
    return {
        "language": lang, "question_id": qid, "judge": Judge(judge).value,
        "total": len(runs), "passed": passed, "pass_rate": passed / len(runs),
        "elapsed": round(time.time() - t0, 2),
        "cases": [{"index": r.index, "input": r.input, "expected": r.expected,
                   "got": r.got, "passed": r.passed, "duration": round(r.duration, 3),
                   "error": r.error} for r in runs],
    }


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
    # 从题集载入时一并带上：留档要记清"这题是从哪来的、参考解长什么样"
    origin_question_id: str | None = None   # 题集原题号（如 A1001）
    origin_title: str | None = None
    source_id: str | None = None            # 平台侧题号（如 abc161_d）
    reference_solution: str | None = None
    reference_language: str | None = None


@app.post("/api/interact")
def interact(req: InteractRequest) -> dict:
    """交互式解题（同步版，保留兼容）：阻塞到全部完成才返回。"""
    job = _start_interact_job(req)
    job["event"].wait()   # 同步等待完成（线程安全）
    return _job_payload(job)


# ===========================================================================
# 异步交互 job：后台线程分阶段执行，前端轮询 / SSE 实时展示进度
# ===========================================================================
def _next_interactive_qid(root: Path = ROOT) -> str:
    """给交互题分配题号：IX0001、IX0002 …（顺序号，单题回放里可读）。"""
    from rex.datasource import interactive_questions_path
    p = interactive_questions_path(root)
    used: set[str] = set()
    if p.exists():
        for line in p.open(encoding="utf-8"):
            if not line.strip():
                continue
            try:
                used.add(str(json.loads(line).get("id", "")))
            except ValueError:
                continue
    n = 1
    while f"IX{n:04d}" in used:
        n += 1
    return f"IX{n:04d}"


def _build_question(req: InteractRequest, root: Path = ROOT):
    """把请求体构造成 QuestionItem（样例拼入 prompt + 作为沙盒用例）。

    交互题分配一个**新题号**（IX0001…），不用会话 id 当主键：题号会连同题目一起
    写进交互题池，单题回放按题号就能取到题面与用例。
    """
    from rex.models import Difficulty, QuestionItem, TestCase

    prompt = req.prompt
    test_cases: list[TestCase] = []
    if req.scene == "algorithm" and req.samples:
        test_cases = [TestCase(input=s.input, output=s.output) for s in req.samples]
        sample_block = "\n".join(
            f"样例{i}：\n输入：\n{s.input}\n输出：\n{s.output}" for i, s in enumerate(req.samples, 1)
        )
        prompt = f"{req.prompt}\n\n【输入输出样例】\n{sample_block}"
    origin = req.origin_question_id
    if origin and req.origin_title:
        title = f"{origin} · {req.origin_title}"
    else:
        title = req.origin_title or origin or req.prompt[:50]
    return QuestionItem(
        id=_next_interactive_qid(root), scene=req.scene, title=title.strip(), prompt=prompt,
        difficulty=Difficulty.BASIC,
        source=f"{INTERACTIVE_SOURCE}{origin}" if origin else f"{INTERACTIVE_SOURCE}手动输入",
        source_id=req.source_id,
        standard_answer=req.answer, test_cases=test_cases,
        reference_solution=req.reference_solution,
    )


def _trial_reference(q) -> InteractTrial:
    """在沙盒里跑一遍题集自带参考解，逐用例留档（会话证据，不依赖前端上传）。

    没有参考解或没有公开用例时返回 ``ran=False``，表示本次没有可留档的试运行。
    """
    from rex.executor.tests import run_cases_detailed

    code = (q.reference_solution or "").strip()
    cases = [c for c in q.test_cases if not c.hidden]
    if not code or not cases:
        return InteractTrial(ran=False)
    t0 = time.time()
    runs = run_cases_detailed(
        q.reference_solution, cases,
        language=detect_language(q.reference_solution),   # 参考解可能是 C++（默认是 python）
        judge=q.judge.value,
        checker_code=q.checker_code, checker_language=q.checker_language, timeout=20,
    )
    trial_cases = [
        InteractTrialCase(
            index=r.index, passed=r.passed, input=r.input, expected=r.expected,
            got=r.got, duration=round(r.duration, 3), error=r.error,
        )
        for r in runs if not r.hidden
    ]
    return InteractTrial(
        ran=True, language=detect_language(q.reference_solution or ""),
        judge=q.judge.value, total=len(trial_cases),
        passed=sum(1 for c in trial_cases if c.passed),
        elapsed=round(time.time() - t0, 2), cases=trial_cases,
    )


def _session_snapshot(session_id: str, req: InteractRequest, q: QuestionItem,
                      trial: InteractTrial, result: InteractResult,
                      cost_calls: int, elapsed: float,
                      error: str | None = None) -> InteractSession:
    """组装会话快照：题目来源与内容 + 本次命中的模型 + 试运行证据 + 判定摘要。

    题目内容以**用户输入的原题面**为准（模型看到的题面含样例块，在交互题池里），
    这样快照里存的是"当时问的是什么"，而不是拼接后的中间产物。
    """
    cases = list(q.test_cases)
    return InteractSession(
        session_id=session_id,
        question_id=q.id,
        origin="dataset" if req.origin_question_id else "manual",
        origin_question_id=req.origin_question_id,
        origin_title=req.origin_title,
        scene=q.scene,
        title=q.title,
        prompt=req.prompt,
        difficulty=q.difficulty.value,
        source_id=q.source_id,
        standard_answer=req.answer,
        reference_solution=q.reference_solution,
        reference_language=req.reference_language or (detect_language(q.reference_solution) if q.reference_solution else None),
        judge=q.judge.value,
        n_public_cases=sum(1 for c in cases if not c.hidden),
        n_hidden_cases=sum(1 for c in cases if c.hidden),
        model=CFG.hy3_model,
        base_url=CFG.hy3_base_url,
        reasoning=CFG.hy3_reasoning_effort,
        temperature=CFG.temperature,
        trial=trial,
        result=result,
        cost_calls=cost_calls,
        elapsed=round(elapsed, 2),
        error=error,
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

        req = job["req"]

        def _fail(msg: str) -> None:
            job["phase"] = "failed"
            job["error"] = msg
            job["message"] = msg
            job["queue"].append({"phase": "failed", "message": msg,
                                 "elapsed": round(time.time() - job["t0"], 1)})
            job["event"].set()

        # 未配置模型就不要进入求解：直接给出可操作的提示（前端在入口处也做了门禁）
        if not CFG.has_credentials:
            _fail("未配置模型：请在「模型配置」里填入 API Key 与 Base URL")
            return
        pipe = Pipeline(CFG)
        t0 = job["t0"]
        trial = InteractTrial(ran=False)
        q = None
        result = InteractResult(mode=job["mode"])

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
            # 1) 建题并落交互题池：题目是现场输入的，先落池，单题回放才取得到题面与用例
            q = _build_question(req)
            job["question_id"] = q.id
            try:
                STORE.append_interactive_question(q)
            except OSError as e:  # 落池失败不影响本次求解，但要在日志里看得见
                log.warning("交互题落池失败 %s: %s", q.id, e)

            # 2) 参考解试运行：沙盒真跑一遍留档（服务端自己跑，不依赖前端上传的结果）
            job["phase"] = "trial"
            job["message"] = "先在沙盒里跑一遍参考解（留档证据）…"
            if (q.reference_solution or "").strip():
                trial = _trial_reference(q)
                job["trial"] = trial.model_dump()
                job["message"] = (
                    f"参考解试运行 {trial.passed}/{trial.total} 通过，开始求解…"
                    if trial.ran else "正在生成分步解答…"
                )

            # 3) 求解 + 判定
            job["phase"] = "solve"
            job["message"] = "正在生成分步解答…"

            def _on_step(partial: dict) -> None:
                """流式回调：把正在生成的过程推给前端（逐 Step 出现）。

                轮询端点读的是 ``job["answer"]`` 最新快照，所以这里每次都更新；
                队列（SSE 用）只在**步骤数变化**时入队，避免几百个 token 事件堆积。
                """
                job["answer"] = partial
                job["message"] = "正在逐 Step 生成解答过程…"
                n = len(partial.get("steps") or [])
                if n != job.get("_steps_seen"):
                    job["_steps_seen"] = n
                    job["queue"].append({
                        "phase": job["phase"], "message": job["message"],
                        "elapsed": round(time.time() - job["t0"], 1), "answer": partial,
                    })

            def _on_reasoning(n_reason: int) -> None:
                """Hy3 的思考阶段不产出正文，这里给界面一个"模型在动"的信号。"""
                job["message"] = f"模型推理中…（已思考 {n_reason} 字）"

            store = STORE
            if job["mode"] == "eval":
                rec = pipe._eval_one(q, progress=lambda p, payload=None: (
                    _report(p, payload, _PHASE_MSG.get(p) or _phase_default_msg(p))),
                    on_step=_on_step, on_reasoning=_on_reasoning)
                rec.source = "interactive"
                store.append_eval(rec)
                # 单独重跑一次沙盒执行，拿到 exec 细节（错误信息）供前端展示
                _, pass_rate, exec_error = pipe._execute(q, rec.answer)
                result = InteractResult(
                    mode="eval", verdict=rec.verification.verdict.value,
                    answer_correct=rec.answer_correct, test_pass_rate=rec.test_pass_rate,
                    confidence=rec.verification.confidence,
                    findings=len(rec.verification.findings),
                )
                job["payload"] = {
                    "mode": "eval", "eval": rec.model_dump(),
                    "elapsed": round(time.time() - t0, 2),
                    "cost_calls": pipe.client.call_count,
                    "exec": {"test_pass_rate": pass_rate, "error": exec_error},
                }
            else:
                rrec = pipe.refiner.refine(q, progress=lambda p, payload=None: (
                    _report(p, payload, _PHASE_MSG.get(p) or _phase_default_msg(p))),
                    on_step=_on_step, on_reasoning=_on_reasoning)
                rrec.source = "interactive"
                store.append_refine(rrec)
                result = InteractResult(
                    mode="refine", verdict=rrec.final.verdict.value,
                    confidence=rrec.final.confidence,
                    findings=len(rrec.final.findings),
                    converged=rrec.converged, rounds=len(rrec.rounds),
                )
                # 回放列表是按 eval 记录组织的，而 refine 模式只产 refine 记录：
                # 这里补一条"终局判定"记录（答案=最终修订答案，判定=终局判定），
                # 回放页的会话块会标明本次是修正闭环演示，不会与一次性求解混淆。
                if rrec.rounds:
                    store.append_eval(EvalRecord(
                        question_id=q.id, scene=q.scene, difficulty=q.difficulty,
                        answer=rrec.rounds[-1].revised_answer, verification=rrec.final,
                        cost_calls=rrec.cost_calls, source="interactive",
                    ))
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
            job["cost_calls"] = pipe.client.call_count
            # 4) 会话快照：成功与失败都留档（含模型、试运行、判定摘要）
            if q is not None:
                try:
                    session = _session_snapshot(
                        job["id"], req, q, trial, result,
                        cost_calls=pipe.client.call_count,
                        elapsed=time.time() - t0, error=job.get("error"),
                    )
                    STORE.append_interact_session(session)
                    job["session_id"] = session.session_id
                    if isinstance(job.get("payload"), dict):
                        job["payload"]["session"] = session.model_dump()
                except OSError as e:
                    log.warning("交互会话快照写入失败 %s: %s", q.id, e)
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
        # 运行中实时走表（长思考阶段界面不至于看起来卡住）
        "elapsed": job["elapsed"] or round(time.time() - job["t0"], 1),
        "cost_calls": job["cost_calls"],
        # 交互题号与会话号：求解完即可在「单题回放」里按题号查这次演示
        "question_id": job.get("question_id"),
        "session_id": job.get("session_id"),
        "trial": job.get("trial"),
        # 本次调用实际使用的模型（演示/复现都要看得出调用的是哪个模型）
        "model": {
            "name": CFG.hy3_model,
            "base_url": CFG.hy3_base_url,
            "provider": _guess_provider(CFG.hy3_base_url, CFG.hy3_model),
        },
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
