"""Build the layered question sets under data/questions/.

用法:
    python scripts/build_questions.py            # 全量构建（需网络拉取 HF）
    python scripts/build_questions.py --tiny      # 仅小样本（离线演示用，不依赖网络）

产出:
    data/questions/algorithm.jsonl   (TACO镜像 + CodeForces镜像 + 自编, 目标 500+)
    data/questions/math.jsonl        (MATH + 自编, 目标 300+)

分层：MATH 用官方 level(1-5)；算法题源无官方难度，用可复现启发式规则
（prob_len / ref_len 阈值），规则与依据写入每条 layer_basis 字段。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.datasets.loader import load_code_contests, load_math, load_taco  # noqa: E402
from rex.datasets.schema import dump_questions, load_questions  # noqa: E402
from rex.models import QuestionItem  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEMO_ALGO = ROOT / "data" / "questions" / "demo_algorithm.jsonl"
DEMO_MATH = ROOT / "data" / "questions" / "demo_math.jsonl"


def _load_demo(path: Path) -> list[QuestionItem]:
    if path.exists():
        return load_questions(path)
    return []


def _renumber(items: list[QuestionItem], prefix: str) -> None:
    """Rebuild stable ids: {prefix}{index:04d} in stable order."""
    for i, it in enumerate(items):
        it.id = f"{prefix}{i:04d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiny", action="store_true", help="build a tiny offline demo set")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "questions"
    out_dir.mkdir(parents=True, exist_ok=True)

    demo_algo = _load_demo(DEMO_ALGO)
    demo_math = _load_demo(DEMO_MATH)

    if args.tiny:
        algo = list(demo_algo)
        math = list(demo_math)
    else:
        # loader 自身按设计优雅降级（HF 不可用时返回 []），这里不再吞异常：
        # 若真因 bug 抛错，构建应显式失败，而不是静默生成不完整题库。
        algo: list[QuestionItem] = []
        for load in (load_taco, load_code_contests):
            algo += load(limit=350)
        algo += demo_algo
        math = load_math(limit=320) + demo_math
        if not algo:
            print("[fatal] 算法题库为空：HF 数据源不可用或解析失败", file=sys.stderr)
            sys.exit(2)

    # 算法题重新编号（A 前缀统一），数学题（M 前缀统一）——避免 id 冲突
    _renumber(algo, "A")
    _renumber(math, "M")

    dump_questions(algo, out_dir / "algorithm.jsonl")
    dump_questions(math, out_dir / "math.jsonl")
    print(f"algorithm: {len(algo)}  math: {len(math)}")
    print(f"written to {out_dir}")


if __name__ == "__main__":
    main()
