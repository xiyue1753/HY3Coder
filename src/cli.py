"""ReAgents v2 CLI entry (typer).

用法示例:
    # 评估模式（数据纯净，一次性）
    python -m src.cli run-eval --scene math --sample 5
    python -m src.cli run-eval --scene algorithm --sample 10 --resume

    # 修正模式（ReAct 闭环，限 3 轮）
    python -m src.cli run-refine --scene math --sample 5

    # 答案校验 / 人工抽检模板 / 仪表盘
    python -m src.cli check-answers --results data/outputs/eval_results.jsonl
    python -m src.cli audit --results data/outputs/eval_results.jsonl
    python -m src.cli serve
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(help="ReAgents v2 — 过程评估与自我修正评测系统")

ROOT = Path(__file__).resolve().parents[1]


def _config() -> object:
    sys.path.insert(0, str(ROOT / "src"))
    from rex.config import Config
    return Config.from_env(ROOT)


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_questions(scene: str, sample: str, difficulty: str | None, seed: int):
    sys.path.insert(0, str(ROOT / "src"))
    from rex.datasets.sampling import stratified_sample
    from rex.datasets.schema import load_questions

    pool = load_questions(ROOT / "data" / "questions" / f"{scene}.jsonl")
    if difficulty:
        pool = [q for q in pool if q.difficulty.value == difficulty]
    picked = stratified_sample(pool, scene, sample, seed=seed)
    return picked, pool


@app.command()
def run_eval(
    scene: str = typer.Option("math", help="algorithm | math"),
    sample: str = typer.Option("5", help="5/10/50/100/full"),
    difficulty: str = typer.Option(None, help="basic|medium|hard 过滤"),
    seed: int = typer.Option(42),
    resume: bool = typer.Option(True),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """一次性评测（评估模式）：solve → execute → verify，反馈不回流。"""
    _logging(verbose)
    cfg = _config()
    picked, pool = _load_questions(scene, sample, difficulty, seed)
    typer.echo(f"题库 {len(pool)} 题，本次评估 {len(picked)} 题（sample={sample}）")
    if not picked:
        typer.secho("抽样结果为空：题库不足或难度过滤过严", fg=typer.colors.RED)
        raise typer.Exit(2)

    from rex.pipeline import Pipeline
    pipe = Pipeline(cfg)
    out = cfg.outputs_dir / f"eval_{scene}.jsonl"
    records = pipe.run_eval(picked, out, resume=resume)
    typer.echo(f"评估完成 {len(records)} 题 → {out}")
    pipe.client.close()


@app.command()
def run_refine(
    scene: str = typer.Option("math", help="algorithm | math"),
    sample: str = typer.Option("5", help="5/10/50/100/full"),
    max_rounds: int = typer.Option(3, help="ReAct 修正限轮数"),
    difficulty: str = typer.Option(None, help="basic|medium|hard 过滤"),
    seed: int = typer.Option(42),
    resume: bool = typer.Option(True),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """修正模式（ReAct 闭环）：verify → feedback → revise → re-verify，限 N 轮。"""
    _logging(verbose)
    cfg = _config()
    picked, pool = _load_questions(scene, sample, difficulty, seed)
    typer.echo(f"题库 {len(pool)} 题，本次修正运行 {len(picked)} 题（sample={sample}，限 {max_rounds} 轮）")
    if not picked:
        typer.secho("抽样结果为空", fg=typer.colors.RED)
        raise typer.Exit(2)

    from rex.pipeline import Pipeline
    pipe = Pipeline(cfg)
    pipe.refiner._max_rounds = max_rounds
    out = cfg.outputs_dir / f"refine_{scene}.jsonl"
    records = pipe.run_refine(picked, out, resume=resume)
    typer.echo(f"修正运行完成 {len(records)} 题 → {out}")
    pipe.client.close()


@app.command()
def check_answers(
    results: Path = typer.Option(..., help="eval 结果 jsonl"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """答案校验：对已有结果重新做数学比对/沙盒执行，并输出统计。"""
    _logging(verbose)
    sys.path.insert(0, str(ROOT / "src"))
    from rex.metrics.compute import compute_metrics
    from rex.models import EvalRecord
    from rex.pipeline import load_jsonl

    records = load_jsonl(results, EvalRecord)
    m = compute_metrics(records)
    typer.echo(f"records={m.n} answer_acc={m.answer_accuracy:.3f} "
               f"process_corr={m.process_correctness:.3f}")
    typer.echo(f"verdict: {m.verdict_dist}")


@app.command()
def audit(
    results: Path = typer.Option(..., help="eval 结果 jsonl"),
    sample: int = typer.Option(30),
    seed: int = typer.Option(42),
) -> None:
    """生成人工抽检标注模板（分层抽样 30-40 题）。"""
    sys.path.insert(0, str(ROOT / "src"))
    from rex.config import Config
    from rex.models import AuditRecord, EvalRecord
    from rex.pipeline import load_jsonl
    from rex.datasets.sampling import stratified_sample

    cfg = Config.from_env(ROOT)
    records = load_jsonl(results, EvalRecord)
    if not records:
        typer.secho("结果文件为空", fg=typer.colors.RED)
        raise typer.Exit(2)
    scene = records[0].scene
    picked = stratified_sample(records, scene, str(sample), seed=seed)
    out = cfg.outputs_dir / "audit_records.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(AuditRecord(question_id=r.question_id).model_dump_json() + "\n")
    typer.echo(f"生成标注模板 {len(picked)} 条 → {out}（人工回填后校验）")


@app.command()
def report(out: Path = typer.Option(ROOT / "reports" / "REPORT.md")) -> None:
    """生成分析报告（分层退化/错误分布/case 归因/修正对比/golden 检出）。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    from make_report import build
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    typer.echo(f"report written -> {out}")


@app.command()
def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    """启动评估仪表盘（FastAPI + 静态 SPA）。"""
    import uvicorn
    uvicorn.run("web.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
