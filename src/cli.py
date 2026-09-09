"""HY3Coder CLI entry (typer).

用法示例:
    # 评估模式（数据纯净，一次性）
    python -m src.cli run-eval --scene algorithm --sample 10 --resume

    # 修正模式（ReAct 闭环，限 3 轮）
    python -m src.cli run-refine --scene algorithm --sample 5

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

app = typer.Typer(help="HY3Coder — 可验证算法场景的过程评估与自我修正评测系统")

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


def _load_questions(scene: str, sample: str, difficulty: str | None, seed: int,
                    questions: str | None = None):
    sys.path.insert(0, str(ROOT / "src"))
    from rex.datasets.sampling import stratified_sample
    from rex.datasets.schema import load_questions

    if questions:
        # 直接指定题集文件（如自建 abc_selfbuilt.jsonl），便于独立评估。
        # scene 保留仅兼容签名（algorithm 档）；难度分层字段来自题目本身。
        pool = load_questions(ROOT / "data" / "questions" / questions)
    else:
        pool = load_questions(ROOT / "data" / "questions" / f"{scene}.jsonl")
    if difficulty:
        pool = [q for q in pool if q.difficulty.value == difficulty]
    picked = stratified_sample(pool, scene, sample, seed=seed)
    return picked, pool


def _default_eval_out(questions: str | None) -> str:
    """按题集反查数据集注册中心，返回默认评测输出文件名。

    - 指定 --questions：优先用该题集所属数据集的评测文件
    - 未指定：用第一个「启用且带评测输出」的数据集（当前 = abc_selfbuilt）
    """
    from rex import datasource as ds
    if questions:
        d = ds.dataset_by_questions(questions)
        if d and d.evals:
            return d.evals
        typer.secho(f"题集 {questions} 未注册到数据集（或无评测输出），"
                    f"请用 --out 指定输出文件", fg=typer.colors.YELLOW)
    for d in ds.active_datasets():
        if d.evals:
            return d.evals
    typer.secho("无启用数据集带评测输出，请用 --out 指定", fg=typer.colors.YELLOW)
    return "eval_selfbuilt_all.jsonl"


def _default_refine_out(questions: str | None) -> str:
    from rex import datasource as ds
    if questions:
        d = ds.dataset_by_questions(questions)
        if d and d.refine:
            return d.refine
    for d in ds.active_datasets():
        if d.refine:
            return d.refine
    return "refine_selfbuilt_all.jsonl"


@app.command()
def run_eval(
    scene: str = typer.Option("algorithm", help="algorithm（数学/MATH 已放弃）"),
    sample: str = typer.Option("5", help="5/10/50/100/full"),
    difficulty: str = typer.Option(None, help="basic|medium|hard 过滤"),
    seed: int = typer.Option(42),
    resume: bool = typer.Option(True),
    retries: int = typer.Option(2, help="单题失败重试次数（0 禁用）"),
    concurrency: int = typer.Option(4, help="并发 worker 数（1=串行，2-4 建议）"),
    questions: str = typer.Option(None, help="直接指定题集文件（如 abc_selfbuilt.jsonl）"),
    out: str = typer.Option(None, help="评测输出文件（默认正式主源 eval_selfbuilt_all.jsonl）"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """一次性评测（评估模式）：solve → execute → verify，反馈不回流。"""
    _logging(verbose)
    cfg = _config()
    picked, pool = _load_questions(scene, sample, difficulty, seed, questions)
    src = questions or f"{scene}.jsonl"
    typer.echo(f"题库 {len(pool)} 题（{src}），本次评估 {len(picked)} 题"
               f"（sample={sample}，单题重试 {retries}，并发 {concurrency}）")
    if not picked:
        typer.secho("抽样结果为空：题库不足或难度过滤过严", fg=typer.colors.RED)
        raise typer.Exit(2)

    from rex.runner import EvalRunner
    runner = EvalRunner(cfg, retries=retries, concurrency=concurrency)
    # 输出文件默认取「数据集注册中心」映射：题集 → 该数据集评测文件
    # （未指定 --questions 时用第一个启用且带评测输出的数据集）。
    from rex import datasource as ds
    out_path = cfg.outputs_dir / (out or _default_eval_out(questions))
    records, costs = runner.run_eval(picked, out_path, resume=resume)
    typer.echo(f"评估完成 {len(records)} 题 → {out_path}（模型调用 {costs['calls']} 次）")


@app.command()
def run_refine(
    scene: str = typer.Option("algorithm", help="algorithm（数学/MATH 已放弃）"),
    sample: str = typer.Option("5", help="5/10/50/100/full"),
    max_rounds: int = typer.Option(3, help="ReAct 修正限轮数"),
    difficulty: str = typer.Option(None, help="basic|medium|hard 过滤"),
    seed: int = typer.Option(42),
    resume: bool = typer.Option(True),
    questions: str = typer.Option(None, help="直接指定题集文件（如 abc_selfbuilt.jsonl）"),
    out: str = typer.Option(None, help="修正输出文件（默认正式 refine 主源 refine_selfbuilt_all.jsonl）"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """修正模式（ReAct 闭环）：verify → feedback → revise → re-verify，限 N 轮。"""
    _logging(verbose)
    cfg = _config()
    picked, pool = _load_questions(scene, sample, difficulty, seed, questions)
    src = questions or f"{scene}.jsonl"
    typer.echo(f"题库 {len(pool)} 题（{src}），本次修正运行 {len(picked)} 题（sample={sample}，限 {max_rounds} 轮）")
    if not picked:
        typer.secho("抽样结果为空", fg=typer.colors.RED)
        raise typer.Exit(2)

    from rex.pipeline import Pipeline
    pipe = Pipeline(cfg)
    pipe.refiner._max_rounds = max_rounds
    # 输出文件默认取数据集注册中心映射（同 run_eval 规则，refine 用对应文件）
    from rex import datasource as ds
    out_path = cfg.outputs_dir / (out or _default_refine_out(questions))
    records = pipe.run_refine(picked, out_path, resume=resume)
    typer.echo(f"修正运行完成 {len(records)} 题 → {out_path}")
    pipe.client.close()


@app.command()
def check_answers(
    results: Path = typer.Option(..., help="eval 结果 jsonl"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """答案校验：对已有结果重新做沙盒执行/文本比对，并输出统计。"""
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
def re_verify(
    results: Path = typer.Option(..., help="旧 eval 结果 jsonl（读取 answer）"),
    questions: Path = typer.Option(None, help="题集 jsonl（附题面/用例；默认按前缀自动找）"),
    qids: str = typer.Option(None, help="逗号分隔的题号白名单（小样本验证用）"),
    difficulty: str = typer.Option(None, help="basic|medium|hard 过滤"),
    diff_min: float = typer.Option(None, help="只重判 metadata.diff_score >= 阈值 的样本"),
    out: Path = typer.Option(None, help="输出文件（默认 <results>.reverified.jsonl）"),
    resume: bool = typer.Option(True),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """重判定既有 eval 记录：不重跑 solver，用新 verifier(severity) 重判 verification。

    用途：verifier 口径升级后（如 P1 severity 重构 / P4 C++ 静态补盲），对历史
    eval 数据重判 verdict/findings。answer（solver 产物）与沙盒答案结果复用/重算，
    仅 verification 由新口径重新生成。
    """
    _logging(verbose)
    cfg = _config()
    sys.path.insert(0, str(ROOT / "src"))
    import json as _json

    from rex import datasource as ds
    from rex.models import EvalRecord, QuestionItem
    from rex.pipeline import Pipeline, load_jsonl

    records = load_jsonl(results, EvalRecord)
    if not records:
        typer.secho(f"结果文件为空：{results}", fg=typer.colors.RED)
        raise typer.Exit(2)

    # 题目池：显式 --questions 或按数据集注册中心自动加载全部启用题集
    qmap: dict[str, QuestionItem] = {}
    if questions is not None and questions.exists():
        for line in questions.open(encoding="utf-8"):
            if line.strip():
                q = QuestionItem.model_validate_json(line)
                qmap[q.id] = q
    else:
        for q in ds.load_active_questions(ROOT):
            qmap[q.id] = q
    if not qmap:
        typer.secho("题目池为空：需 --questions 或存在启用数据集", fg=typer.colors.RED)
        raise typer.Exit(2)

    # 过滤
    sel = list(records)
    if qids:
        whitelist = set(x.strip() for x in qids.split(",") if x.strip())
        sel = [r for r in sel if r.question_id in whitelist]
    if difficulty:
        sel = [r for r in sel if r.difficulty.value == difficulty]
    if diff_min is not None:
        def _diff(r) -> float | None:
            q = qmap.get(r.question_id)
            return (q.metadata or {}).get("diff_score") if q else None
        sel = [r for r in sel if (_diff(r) is not None and _diff(r) >= diff_min)]
    missing_q = [r.question_id for r in sel if r.question_id not in qmap]
    if missing_q:
        typer.secho(f"以下题在题集中缺失（无法重判）：{','.join(missing_q)}",
                    fg=typer.colors.YELLOW)
        sel = [r for r in sel if r.question_id in qmap]
    if not sel:
        typer.secho("过滤后无样本", fg=typer.colors.RED)
        raise typer.Exit(2)

    out_path = out or Path(str(results) + ".reverified.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if resume and out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            if line.strip():
                done_ids.add(EvalRecord.model_validate_json(line).question_id)
        typer.echo(f"resume: {len(done_ids)} 已完成")

    pipe = Pipeline(cfg)
    todo = [r for r in sel if r.question_id not in done_ids]
    typer.echo(f"重判定 {len(todo)}/{len(sel)} 题 → {out_path}（新 verifier severity 口径）")
    with out_path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            q = qmap[r.question_id]
            try:
                rec = pipe.reverify_one(q, r.answer)
            except Exception as e:  # noqa: BLE001
                typer.secho(f"[{i}/{len(todo)}] {r.question_id} 失败: {e}",
                            fg=typer.colors.RED)
                continue
            f.write(rec.model_dump_json() + "\n")
            f.flush()
            n_fatal = sum(1 for x in rec.verification.findings
                          if getattr(x, "severity", None) == "fatal")
            n_minor = len(rec.verification.findings) - n_fatal
            typer.echo(f"[{i}/{len(todo)}] {r.question_id} "
                       f"旧={r.verification.verdict.value} → 新={rec.verification.verdict.value} "
                       f"ans={rec.answer_correct} findings={len(rec.verification.findings)}"
                       f"(fatal{n_fatal}/minor{n_minor})")
    pipe.client.close()
    typer.echo(f"完成 → {out_path}（模型调用 {pipe.client.call_count} 次）")


@app.command()
def audit(
    results: Path = typer.Option(..., help="eval 结果 jsonl"),
    questions: Path = typer.Option(None, help="题目池 jsonl（附题面上下文，可选）"),
    sample: int = typer.Option(35, help="抽样数量（30-40）"),
    seed: int = typer.Option(42),
    out: Path = typer.Option(None, help="模板输出路径（默认 outputs/audit_records.jsonl）"),
) -> None:
    """生成人工抽检标注模板（按答案正确性×判定分层抽样）。"""
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from rex.config import Config
    from rex.models import EvalRecord
    from rex.pipeline import load_jsonl
    from audit_sample import build_template

    cfg = Config.from_env(ROOT)
    records = load_jsonl(results, EvalRecord)
    if not records:
        typer.secho("结果文件为空", fg=typer.colors.RED)
        raise typer.Exit(2)
    qmap = {}
    if questions is not None:
        import json as _json
        if questions.exists():
            qmap = {q["id"]: q for q in
                    (_json.loads(l) for l in questions.open(encoding="utf-8") if l.strip())}
        else:
            typer.secho(f"题目池不存在：{questions}", fg=typer.colors.YELLOW)
    template = build_template(records, qmap, sample, seed=seed)
    # 抽检记录默认文件由注册中心声明（audit_records.jsonl）
    from rex import datasource as ds
    out_path = out or ds.audit_path(ROOT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json2
    with out_path.open("w", encoding="utf-8") as f:
        for t in template:
            f.write(_json2.dumps(t, ensure_ascii=False) + "\n")
    typer.echo(f"生成标注模板 {len(template)} 条 → {out_path}（人工回填后校验）")


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
    sys.path.insert(0, str(ROOT / "src"))
    uvicorn.run("web.api:app", host=host, port=port, reload=False)


@app.command()
def cleanup(days: int = 30, dry_run: bool = True) -> None:
    """手动清理超期评估记录（默认 30 天，默认只预览不删除）。

    记录默认不自动删除；此命令用于查看/清理超过保留期的记录。
    清理规则：删除超过保留期的所有记录（手动操作，不自动执行）。
    - --dry-run False 才会真正删除。
    """
    cfg = _config()
    sys.path.insert(0, str(ROOT / "src"))
    from rex.store import RecordStore
    store = RecordStore(cfg.outputs_dir)
    would, removed = store.cleanup(days=days, dry_run=dry_run)
    expired = store.expired(days=days)
    if dry_run:
        typer.echo(f"[预览] 超期({days}天)记录 {len(expired)} 条，"
                   f"其中将移除 {would} 条（仅保留每题最新）。未实际删除。")
        for r in expired[:20]:
            typer.echo(f"  - {r.question_id} ({r.scene}/{r.source}) "
                       f"created_at={r.created_at}")
        if len(expired) > 20:
            typer.echo(f"  … 其余 {len(expired)-20} 条省略")
    else:
        typer.echo(f"[清理] 已移除 {removed} 条超期记录。")


if __name__ == "__main__":
    app()
