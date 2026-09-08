"""数据源注册中心：全项目唯一权威的数据文件声明。

设计目标：**数据源与调用解耦**——题集/评测/refine/golden/audit/cases 等一切
数据文件的物理位置只在本模块声明一次，其余代码（store / api / cli /
make_report / 前端提示 / ingest 脚本）一律通过本模块的访问器取路径，
不再手写文件名。以后"删/加/改数据源"只改这里，调用方零改动。

组织方式：
    - 以**数据集 dataset** 为主维度：每个数据集是一道题池（题集文件 +
      评测输出文件 + refine 输出文件）。当前活跃数据集：abc_selfbuilt
      （AtCoder ABC 自建 175 题）、cf_selfbuilt（Codeforces 自建，抓取中）。
    - 非数据集类 artifact 单独注册：golden（合成 + 真实）、audit、
      demo 题集、cases 用例目录、交互评测输出。

历史命名（无需再理解）：
    - eval_selfbuilt_all.jsonl  = abc_selfbuilt 数据集的正式评测输出
    - refine_selfbuilt_all.jsonl = abc_selfbuilt 数据集的正式 refine 输出
    - eval_interactive.jsonl   = 交互演示记录（source=interactive）
    - golden_algorithm.jsonl   = 合成 golden（已删除，2026-09-08；常量注册保留兼容）
    - golden_real_algorithm.jsonl = 真实评测检出 golden
    - audit_records.jsonl      = 人工抽检标注

废弃（不再注册，若残留文件属历史存档）：
    - eval_algorithm.jsonl（旧 TACO 评测，含交互混入，2026-09 废弃）
    - refine_algorithm.jsonl（TACO 时代 refine）
    - algorithm.jsonl / taco*.jsonl（TACO 镜像题集，若未来引入按独立数据集注册）
    - eval_selfbuilt_{bm,hard,smoke,fixverify}.jsonl（ABC 评测的历史分片，
      内容已被 eval_selfbuilt_all.jsonl 全量覆盖）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rex.models import (
    AuditRecord,
    EvalRecord,
    GoldenSample,
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


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="abc_selfbuilt",
        label="ABC 自建（公开集 175 题）",
        enabled=True,
        questions="abc_selfbuilt.jsonl",
        evals="eval_selfbuilt_all.jsonl",      # 正式评测主数据源（run-eval）
        refine="refine_selfbuilt_all.jsonl",
        note="AtCoder ABC 公开竞赛题自建转化，含题面/参考解/测试用例/分层依据。",
    ),
    Dataset(
        key="cf_selfbuilt",
        label="Codeforces 自建（175 题）",
        enabled=True,
        questions="cf_selfbuilt.jsonl",
        evals="eval_cf_all.jsonl",             # 正式评测输出（run-eval --questions cf_selfbuilt）
        refine=None,
        note="Codeforces 公开题自建转化，含题面/参考解/测试用例/分层依据与 SPJ checker。",
    ),
    # demo：非正式数据集，仅供交互演示/示例，不进指标统计
    Dataset(
        key="demo",
        label="Demo 演示题",
        enabled=False,
        questions="demo_algorithm.jsonl",
        evals=None,
        refine=None,
        note="演示样例，不参与正式评测指标。",
    ),
)

# 废弃/历史数据集的 key（文档用途，便于检索）
DEPRECATED_KEYS = ("algorithm", "taco", "math")


# ---------------------------------------------------------------------------
# 非数据集 artifact
# ---------------------------------------------------------------------------
#: 交互评测记录（source="interactive"），独立于正式评测，供单题回放检索。
INTERACTIVE_EVAL = "eval_interactive.jsonl"
#: 人工抽检标注记录。
AUDIT_FILE = "audit_records.jsonl"
#: 测试用例源目录（data/cases，ingest 脚本生成）。
CASES_DIRNAME = "cases"
#: 真实评测检出 golden 文件名（合成 golden_algorithm.jsonl 已删除，常量保留兼容读取，文件不存在时自然为空）。
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


def cases_dir(root: str | Path) -> Path:
    return Path(root) / "data" / CASES_DIRNAME


# -- 文件定位 ----------------------------------------------------------------
def questions_path(root: str | Path, ds: Dataset) -> Path:
    return questions_dir(root) / ds.questions


def evals_path(root: str | Path, ds: Dataset) -> Path | None:
    return outputs_dir(root) / ds.evals if ds.evals else None


def refine_path(root: str | Path, ds: Dataset) -> Path | None:
    return outputs_dir(root) / ds.refine if ds.refine else None


def interactive_evals_path(root: str | Path) -> Path:
    return outputs_dir(root) / INTERACTIVE_EVAL


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
    """合并所有启用数据集的题集（保持注册顺序）。"""
    qs: list[QuestionItem] = []
    for ds in active_datasets():
        p = questions_path(root, ds)
        if p.exists():
            qs += _read_jsonl(p, QuestionItem)
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
    refs: list[RefineRecord] = []
    for ds in active_datasets():
        p = refine_path(root, ds)
        if p is not None and p.exists():
            refs += _read_jsonl(p, RefineRecord)
    return refs


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
    "Dataset", "DATASETS", "DEPRECATED_KEYS",
    "INTERACTIVE_EVAL", "GOLDEN_FILES", "AUDIT_FILE", "CASES_DIRNAME",
    "active_datasets", "dataset", "dataset_by_questions",
    "questions_dir", "outputs_dir", "golden_dir", "cases_dir",
    "questions_path", "evals_path", "refine_path",
    "interactive_evals_path", "golden_paths", "audit_path",
    "active_eval_filenames",
    "load_active_questions", "load_active_evals", "load_active_refines",
    "load_golden", "load_audits",
]
