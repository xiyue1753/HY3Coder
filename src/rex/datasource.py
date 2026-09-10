"""数据源注册中心：全项目唯一权威的数据文件声明。

设计目标：**数据源与调用解耦**——题集/评测/refine/golden/audit 等一切
数据文件的物理位置只在本模块声明一次，其余代码（store / api / cli /
make_report / 前端提示）一律通过本模块的访问器取路径，
不再手写文件名。以后"删/加/改数据源"只改这里，调用方零改动。

组织方式：
    - 以**数据集 dataset** 为主维度：每个数据集是一道题池（题集文件 +
      评测输出文件 + refine 输出文件）。当前活跃数据集：abc_selfbuilt
      （AtCoder ABC 自建 175 题）、cf_selfbuilt（Codeforces 自建 184 题）。
    - 非数据集类 artifact 单独注册：golden（真实）、audit、交互演示输出。对应文件：
      eval_interactive.jsonl   = 交互演示记录（source=interactive）
      interactive.jsonl        = 交互题池（交互式解题现场输入的题，按题号可回放）
      interact_sessions.jsonl  = 交互解题完整会话快照（题面/用例/参考解/模型/试运行）
      refine_interactive.jsonl = 交互演示的 refine 记录（与正式 refine 严格分离）
      golden_real_algorithm.jsonl = 真实评测检出的 golden 样本
      audit_records.jsonl      = 人工抽检标注
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from rex.models import (
    AuditRecord,
    EvalRecord,
    GoldenSample,
    InteractSession,
    QuestionItem,
    RefineRecord,
)

# ---------------------------------------------------------------------------
# 数据集声明
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dataset:
    """一个数据集（题池）：题集文件 + 评测/refine 输出文件。

    ``enabled`` = False 表示暂停接入（新数据源接入前置 False，验证后置 True；
    废弃数据集从 ``DATASETS`` 移除即可）。
    """

    key: str                       # 逻辑名（注册表主键）
    label: str                     # 展示名
    enabled: bool
    questions: str                 # data/questions 下的题集文件
    evals: str | None              # data/outputs 下的正式评测输出（可为空，如 CF 尚未评测）
    refine: str | None             # data/outputs 下的正式 refine 输出（可为空）
    note: str = ""


# 正式基线 = temperature=0（temperature=0.9 时代的旧主文件 eval_*_all.jsonl
# 已归档至 data/outputs/_archived/，不再注册；REX_EVAL_SUFFIX 仅作读取侧兼容）。
DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="abc_selfbuilt",
        label="ABC 自建（175 题）",
        enabled=True,
        questions="abc_selfbuilt.jsonl",
        evals="eval_abc_selfbuilt_t0.jsonl",   # 正式评测主数据源（temperature=0 全量重跑）
        refine="refine_selfbuilt_all.jsonl",
        note="AtCoder ABC 公开竞赛题自建转化，含题面/参考解/测试用例/分层依据。",
    ),
    Dataset(
        key="cf_selfbuilt",
        label="Codeforces 自建（184 题）",
        enabled=True,
        questions="cf_selfbuilt.jsonl",
        evals="eval_cf_selfbuilt_t0.jsonl",    # 正式评测输出（temperature=0 全量重跑）
        refine=None,
        note="Codeforces 公开题自建转化，含题面/参考解/测试用例/分层依据与 SPJ checker。",
    ),
)

# 数据集 key 只保留当前活跃的两套自建集（见上）；历史 key 不再登记。


# ---------------------------------------------------------------------------
# 非数据集 artifact
# ---------------------------------------------------------------------------
#: 交互评测记录（source="interactive"），独立于正式评测，供单题回放检索。
INTERACTIVE_EVAL = "eval_interactive.jsonl"
#: 交互题池（data/questions）：交互式解题现场输入的题，每次求解分配一个新题号写入，
#: 单题回放按题号检索题面与用例；不参与正式统计。
INTERACTIVE_QUESTIONS = "interactive.jsonl"
#: 交互解题完整会话快照（data/outputs）：题面/用例/参考解/命中模型/试运行/判定摘要。
INTERACTIVE_SESSIONS = "interact_sessions.jsonl"
#: 交互演示的 refine 记录（data/outputs）：与正式 refine 严格分离，不进修正对比统计。
INTERACTIVE_REFINE = "refine_interactive.jsonl"
#: 人工抽检标注记录。
AUDIT_FILE = "audit_records.jsonl"
#: golden 文件名；文件不存在时读取为空。
GOLDEN_SYNTHETIC_FILE = "golden_algorithm.jsonl"
GOLDEN_REAL_FILE = "golden_real_algorithm.jsonl"
GOLDEN_FILES = (GOLDEN_REAL_FILE, GOLDEN_SYNTHETIC_FILE)

# ---------------------------------------------------------------------------
# 访问器
# ---------------------------------------------------------------------------


def active_datasets() -> tuple[Dataset, ...]:
    return tuple(d for d in DATASETS if d.enabled)


def dataset(key: str) -> Dataset:
    for d in DATASETS:
        if d.key == key:
            return d
    raise KeyError(f"unknown dataset: {key} (registered: {[d.key for d in DATASETS]})")


def dataset_by_questions(filename: str) -> Dataset | None:
    """由题集文件名反查数据集（供 CLI --questions 映射输出文件）。"""
    for d in DATASETS:
        if d.questions == filename:
            return d
    return None


# -- 目录定位 ----------------------------------------------------------------
def questions_dir(root: str | Path) -> Path:
    return Path(root) / "data" / "questions"


def outputs_dir(root: str | Path) -> Path:
    return Path(root) / "data" / "outputs"


def golden_dir(root: str | Path) -> Path:
    return Path(root) / "data" / "golden"


# -- 文件定位 ----------------------------------------------------------------
def questions_path(root: str | Path, ds: Dataset) -> Path:
    return questions_dir(root) / ds.questions


def evals_path(root: str | Path, ds: Dataset) -> Path | None:
    """评测输出文件路径。注册文件即正式基线（temperature=0 的 eval_*_t0.jsonl）；
    环境变量 REX_EVAL_SUFFIX 可追加额外后缀（旧版本兼容，正常流程不设置）。"""
    if not ds.evals:
        return None
    name = ds.evals
    suffix = os.getenv("REX_EVAL_SUFFIX", "").strip()
    if suffix:
        stem, _, ext = name.rpartition(".")
        name = f"{stem}{suffix}.{ext}" if ext else f"{name}{suffix}"
    return outputs_dir(root) / name


def refine_path(root: str | Path, ds: Dataset) -> Path | None:
    return outputs_dir(root) / ds.refine if ds.refine else None


def interactive_evals_path(root: str | Path) -> Path:
    return outputs_dir(root) / INTERACTIVE_EVAL


def interactive_questions_path(root: str | Path) -> Path:
    return questions_dir(root) / INTERACTIVE_QUESTIONS


def interact_sessions_path(root: str | Path) -> Path:
    return outputs_dir(root) / INTERACTIVE_SESSIONS


def interactive_refines_path(root: str | Path) -> Path:
    return outputs_dir(root) / INTERACTIVE_REFINE


def golden_real_path(root: str | Path) -> Path:
    return golden_dir(root) / GOLDEN_REAL_FILE


def golden_synthetic_path(root: str | Path) -> Path:
    return golden_dir(root) / GOLDEN_SYNTHETIC_FILE


def golden_paths(root: str | Path) -> list[Path]:
    return [golden_real_path(root), golden_synthetic_path(root)]


def audit_path(root: str | Path) -> Path:
    return outputs_dir(root) / AUDIT_FILE


# -- 读取集合（供展示/报告统一消费） -----------------------------------------
def load_active_questions(root: str | Path) -> list[QuestionItem]:
    """合并所有启用数据集的题集 + 交互题池（保持注册顺序，交互题排在最后）。

    交互题池只用于单题回放展示（按题号取题面/用例），不参与抽样与指标统计。
    """
    qs: list[QuestionItem] = []
    for ds in active_datasets():
        p = questions_path(root, ds)
        if p.exists():
            qs += _read_jsonl(p, QuestionItem)
    ip = interactive_questions_path(root)
    if ip.exists():
        qs += _read_jsonl(ip, QuestionItem)
    return qs


def load_active_evals(root: str | Path) -> list[EvalRecord]:
    """合并所有启用数据集的正式评测 + 交互评测记录（store 数据源）。"""
    recs: list[EvalRecord] = []
    for ds in active_datasets():
        p = evals_path(root, ds)
        if p is not None and p.exists():
            recs += _read_jsonl(p, EvalRecord)
    ip = interactive_evals_path(root)
    if ip.exists():
        recs += _read_jsonl(ip, EvalRecord)
    return recs


def active_eval_filenames() -> tuple[str, ...]:
    """启用数据集评测输出文件名 + 交互记录文件名（RecordStore 白名单）。"""
    names = [ds.evals for ds in active_datasets() if ds.evals]
    names.append(INTERACTIVE_EVAL)
    return tuple(names)


def load_active_refines(root: str | Path) -> list[RefineRecord]:
    """正式 refine 记录（只含启用数据集，交互演示的 refine 不进这里）。

    注意：报告 §5 修正闭环用的 ``refine_wrong_t0.jsonl`` 是脚本
    （``scripts/run_refine_wrong_t0.py``）产出的另一种 schema（带 eval_verdict /
    initial_public_pass / final.full_pass_rate 等），不是 ``RefineRecord``，
    因此不在这里读取；仪表盘的修正对比目前没有数据源。
    """
    refs: list[RefineRecord] = []
    for ds in active_datasets():
        p = refine_path(root, ds)
        if p is not None and p.exists():
            refs += _read_jsonl(p, RefineRecord)
    return refs


def load_interactive_refines(root: str | Path) -> list[RefineRecord]:
    """交互演示的 refine 记录（单独文件，只供单题回放检索）。"""
    p = interactive_refines_path(root)
    return _read_jsonl(p, RefineRecord) if p.exists() else []


def load_interact_sessions(root: str | Path) -> list[InteractSession]:
    """交互解题会话快照（追加式，最新在后）。"""
    p = interact_sessions_path(root)
    return _read_jsonl(p, InteractSession) if p.exists() else []


def load_golden(root: str | Path) -> list[GoldenSample]:
    """合成 + 真实 golden 都纳入展示（读序：真实优先，见 GOLDEN_FILES）。"""
    out: list[GoldenSample] = []
    for p in golden_paths(root):
        if p.exists():
            out += _read_jsonl(p, GoldenSample)
    return out


def load_audits(root: str | Path) -> list[AuditRecord]:
    p = audit_path(root)
    if not p.exists():
        return []
    return _read_jsonl(p, AuditRecord)


def _read_jsonl(path: Path, model) -> list:
    from rex.pipeline import load_jsonl
    return load_jsonl(path, model)


# ---------------------------------------------------------------------------
# 导出常用容器（兼容 `from rex.datasource import ...`）
# ---------------------------------------------------------------------------
__all__ = [
    "Dataset", "DATASETS",
    "INTERACTIVE_EVAL", "INTERACTIVE_QUESTIONS", "INTERACTIVE_SESSIONS",
    "INTERACTIVE_REFINE", "GOLDEN_FILES", "AUDIT_FILE",
    "active_datasets", "dataset", "dataset_by_questions",
    "questions_dir", "outputs_dir", "golden_dir",
    "questions_path", "evals_path", "refine_path",
    "interactive_evals_path", "interactive_questions_path",
    "interact_sessions_path", "interactive_refines_path",
    "golden_paths", "audit_path",
    "active_eval_filenames",
    "load_active_questions", "load_active_evals", "load_active_refines",
    "load_interactive_refines", "load_interact_sessions",
    "load_golden", "load_audits",
]
