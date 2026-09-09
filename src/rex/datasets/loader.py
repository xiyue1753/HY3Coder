"""Dataset loading & normalization.

Sources & licenses (HuggingFace):
  - agentica-org/DeepCoder-Preview-Dataset/taco      — TACO 数据镜像 (Apache-2.0), 7436 题, 含参考解+测试用例
  - agentica-org/DeepCoder-Preview-Dataset/codeforces — Codeforces 精选 (MIT), 408 题, 含测试用例

注：原 hkust-nlp/taco 与 deepmind/code_contests 因新版 datasets 不再支持
loading script / 磁盘占用过大而不可用，故采用上述镜像与替代源。

数学/MATH 评测场景已放弃（2026-09-03），不再加载该数据集。

Loader normalizes every raw row into QuestionItem. Building the local question
set is a separate step (scripts/build_questions.py) so the pipeline itself
never depends on network access.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from rex.models import Difficulty, QuestionItem, TestCase

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HF helpers
# ---------------------------------------------------------------------------
def _ensure_hf_cache_in_project() -> Path:
    """Force HF downloads/cache into the project tree (data/cache/hf).

    规则：所有中间数据（含 HF 数据集缓存）必须落在本项目目录内，
    绝不写入系统盘默认位置（%USERPROFILE%/.cache/huggingface）。
    在 import datasets 之前调用（datasets.config 在 import 时读环境变量）。
    """
    pkg_root = Path(__file__).resolve().parents[3]  # Hy3_APP2/
    cache = pkg_root / "data" / "cache" / "hf"
    # 强制覆盖外部 HF_HOME，保证中间数据不出项目目录
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_DATASETS_CACHE"] = str(cache / "datasets")
    os.environ["HF_HUB_CACHE"] = str(cache / "hub")
    os.environ["HF_ASSETS_CACHE"] = str(cache / "assets")
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _try_load_hf(
    name: str,
    config: str | None = None,
    split: str | None = None,
) -> list[dict] | None:
    """Best-effort HuggingFace load; returns raw rows or None if unavailable.

    Tries every common split name in order (train → test → all) when the
    caller does not pin one, since datasets differ in their split naming.
    """
    _ensure_hf_cache_in_project()  # 必须先于 import datasets 设置缓存路径
    try:
        from datasets import load_dataset  # heavy import — only when needed
    except Exception as e:  # noqa: BLE001
        log.warning("datasets lib unavailable, skip %s: %s", name, e)
        return None
    splits = [split] if split else ["train", "test", "all"]
    for sp in splits:
        try:
            ds = load_dataset(name, config, split=sp)
            return list(ds)
        except Exception as e:  # noqa: BLE001
            log.warning("load %s (%s/%s) failed: %s", name, config, sp, e)
    return None


def _deepcoder_tests(raw) -> list[TestCase]:
    """Normalize the two test formats found in DeepCoder datasets.

    - codeforces: [{"input": ..., "output": ...}, ...]
    - taco:       {"inputs": [...], "outputs": [...]}
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        inputs = raw.get("inputs") or []
        outputs = raw.get("outputs") or []
        return [
            TestCase(input=str(i), output=str(o), hidden=False)
            for i, o in zip(inputs, outputs)
        ]
    if isinstance(raw, list):
        return [
            TestCase(input=str(t.get("input", "")), output=str(t.get("output", "")), hidden=False)
            for t in raw
            if isinstance(t, dict)
        ]
    # some rows store tests as a JSON string
    if isinstance(raw, str):
        try:
            return _deepcoder_tests(json.loads(raw))
        except (ValueError, TypeError):
            return []
    return []


def _heuristic_difficulty(prob_len: int, ref_len: int) -> Difficulty:
    """Deterministic difficulty tiering (reproducible stratification rule).

    规则表（写入 layer_basis 便于复现）:
      hard   : 参考解长度 > 800 或 题目长度 > 2500
      medium : 参考解长度 350~800 或 题目长度 1200~2500
      basic  : 其余
    说明：数据源无官方难度时，以参考解与题目篇幅作为复杂度代理指标；
    有官方 level 的源（TACO 原始数据）优先使用官方值。
    """
    if ref_len > 800 or prob_len > 2500:
        return Difficulty.HARD
    if ref_len > 350 or prob_len > 1200:
        return Difficulty.MEDIUM
    return Difficulty.BASIC


# ---------------------------------------------------------------------------
# algorithm scene
# ---------------------------------------------------------------------------
def load_taco(limit: int | None = None) -> list[QuestionItem]:
    """TACO (via DeepCoder mirror): problem + tests{inputs,outputs} + solutions."""
    rows = _try_load_hf("agentica-org/DeepCoder-Preview-Dataset", config="taco", split="train")
    if rows is None:
        return []
    items: list[QuestionItem] = []
    for i, r in enumerate(rows):
        if limit is not None and len(items) >= limit:
            break
        prob = str(r.get("problem", "")).strip()
        if not prob:
            continue
        sols = r.get("solutions") or []
        ref_len = sum(len(s) for s in sols) / max(len(sols), 1)
        ref = sols[0] if sols else None
        diff = _heuristic_difficulty(len(prob), int(ref_len))
        items.append(QuestionItem(
            id=f"T{i:04d}",
            scene="algorithm",
            title=prob[:60],
            prompt=prob,
            difficulty=diff,
            source="TACO",
            source_id=f"deepcoder-taco-{i}",
            layer_basis=(f"TACO(DeepCoder镜像) 无官方level，启发式分层: "
                         f"prob_len={len(prob)} ref_len={int(ref_len)} → {diff.value}"),
            standard_answer="",
            reference_solution=ref,
            test_cases=_deepcoder_tests(r.get("tests")),
            metadata={"solutions_count": len(sols)},
        ))
    log.info("TACO loaded %d items", len(items))
    return items


def load_code_contests(limit: int | None = None) -> list[QuestionItem]:
    """CodeContests 替代源 (DeepCoder codeforces): problem + tests[]."""
    rows = _try_load_hf("agentica-org/DeepCoder-Preview-Dataset", config="codeforces", split="test")
    if rows is None:
        return []
    items: list[QuestionItem] = []
    for i, r in enumerate(rows):
        if limit is not None and len(items) >= limit:
            break
        prob = str(r.get("problem", "")).strip()
        if not prob:
            continue
        tests = _deepcoder_tests(r.get("tests"))
        diff = _heuristic_difficulty(len(prob), 0)
        items.append(QuestionItem(
            id=f"C{i:04d}",
            scene="algorithm",
            title=prob[:60],
            prompt=prob,
            difficulty=diff,
            source="CodeForces(DeepCoder镜像)",
            source_id=f"deepcoder-cf-{i}",
            layer_basis=(f"CodeForces(DeepCoder镜像) 无官方level，启发式分层: "
                         f"prob_len={len(prob)} → {diff.value}"),
            standard_answer="",
            reference_solution=None,
            test_cases=tests,
            metadata={},
        ))
    log.info("CodeContests(CF镜像) loaded %d items", len(items))
    return items


# ---------------------------------------------------------------------------
# local cache helpers
# ---------------------------------------------------------------------------
def load_local(path: str | Path) -> list[QuestionItem]:
    """Load from a local cache file (json) previously built by build script."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    return [QuestionItem.model_validate(d) for d in data]


def save_local(items: list[QuestionItem], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump([it.model_dump(mode="json") for it in items], f, ensure_ascii=False, indent=1)
