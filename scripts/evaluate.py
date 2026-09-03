"""过程评估脚本（等价于 `python -m src.cli run-eval/run-refine`）。

用法:
    python scripts/evaluate.py --mode eval --scene algorithm --sample 5
    python scripts/evaluate.py --mode refine --scene algorithm --sample 10
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import typer

app = typer.Typer()


@app.command()
def run(
    mode: str = typer.Option("eval", help="eval | refine"),
    scene: str = typer.Option("algorithm", help="algorithm（数学/MATH 已放弃）"),
    sample: str = typer.Option("5", help="5/10/50/100/full"),
    difficulty: str = typer.Option(None),
    max_rounds: int = typer.Option(3),
    seed: int = typer.Option(42),
    resume: bool = typer.Option(True),
) -> None:
    from cli import run_eval, run_refine

    if mode == "refine":
        run_refine(scene=scene, sample=sample, max_rounds=max_rounds,
                   difficulty=difficulty, seed=seed, resume=resume, verbose=False)
    else:
        run_eval(scene=scene, sample=sample, difficulty=difficulty,
                 seed=seed, resume=resume, verbose=False)


if __name__ == "__main__":
    app()
