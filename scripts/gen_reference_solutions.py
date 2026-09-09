"""Generate + verify reference solutions for CodeForces questions lacking them.

算法题"标准答案 = 可执行代码 + 测试用例"。CodeForces 镜像数据源无 solutions 字段，
故用 Hy3 为每题生成 Python 代码解，并用沙盒跑 test_cases 验证。通过率 100% 的
代码写入 reference_solution。

用法:
    python scripts/gen_reference_solutions.py            # 全量 350（需 Hy3 key）
    python scripts/gen_reference_solutions.py --limit 10 # 小批次验证

产出:
    data/questions/cf_reference_solutions.jsonl   (题目 source_id -> 验证通过的参考解)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rex.config import Config  # noqa: E402
from rex.datasets.loader import _deepcoder_tests, _try_load_hf  # noqa: E402
from rex.executor.tests import run_test_cases  # noqa: E402
from rex.models import QuestionItem  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

_SYSTEM = (
    "你是顶级算法工程师。根据给定的算法题目，只输出一个完整可独立运行的 Python 3 程序"
    "（含输入读取 input() 与输出打印 print()）。只输出代码本身，不要任何解释、"
    "不要 markdown 代码块围栏。"
)


def _gen_code(cfg: Config, prompt: str, attempts: int = 3) -> str:
    """生成代码，带重试（Hy3 偶发返回空/无效）。"""
    from rex.hy3_client import Hy3Client
    for _ in range(attempts):
        client = Hy3Client(
            api_key=cfg.hy3_api_key, base_url=cfg.hy3_base_url, model=cfg.hy3_model,
            reasoning_effort=cfg.hy3_reasoning_effort, max_retries=2, timeout=120.0,
        )
        try:
            raw = client.chat(prompt, system=_SYSTEM)
        finally:
            client.close()
        # 去掉可能的 ```python ... ``` 围栏
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw
            raw = raw.split("```", 1)[0].strip()
        # 有效代码判定：含可执行内容（def/input/print/等）
        if raw and any(kw in raw for kw in ("input(", "print(", "def ", "import ", "while", "for ")):
            return raw
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="处理题数上限（小批次验证）")
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    if not cfg.has_credentials:
        print("[fatal] 缺少 Hy3 凭据（.env 中 HY3_API_KEY/BASE_URL）", file=sys.stderr)
        sys.exit(2)

    rows = _try_load_hf("agentica-org/DeepCoder-Preview-Dataset", config="codeforces", split="test")
    if not rows:
        print("[fatal] CodeForces 数据源不可用", file=sys.stderr)
        sys.exit(2)

    results = []
    passed = failed = 0
    for i, r in enumerate(rows):
        if args.limit is not None and i >= args.limit:
            break
        prob = str(r.get("problem", "")).strip()
        tests = _deepcoder_tests(r.get("tests"))
        if not prob or not tests:
            continue
        source_id = f"deepcoder-cf-{i}"
        code = _gen_code(cfg, prob)
        res = run_test_cases(code, tests)
        if res.error or res.pass_rate < 1.0:
            failed += 1
            print(f"[{i}] {source_id}: FAIL (pass={res.pass_rate:.0%}, err={str(res.error)[:60]})")
            continue
        passed += 1
        results.append({"source_id": source_id, "reference_solution": code})
        print(f"[{i}] {source_id}: PASS")

    out = ROOT / "data" / "questions" / "cf_reference_solutions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"\n通过 {passed} / 失败 {failed} → 写入 {out} ({len(results)} 条参考解)")


if __name__ == "__main__":
    main()
