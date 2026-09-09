# -*- coding: utf-8 -*-
"""跨平台统一难度打分：3 专家盲打（0-100 连续分）+ LLM 仲裁官。

背景（难度标签统一方案 B）：CF rating 与 ABC 官方分值不是同一把尺，无法直接
合并三档。本脚本用**平台无关的第三方判断**统一难度——3 个不同视角的 LLM 专家
只看题面 + 参考解（不给平台/官方难度），各自输出 0-100 连续分与理由；仲裁官
综合 3 份独立判断给出终分。终分落库 metadata.diff_score，报告层再按分位切档。

设计要点：
- 专家视角正交（选手实战 / 算法理论 / 反例与陷阱），避免单一偏见
- 盲打：prompt 不含平台、不含官方 rating/分值，保证跨平台可比
- 0-100 连续分：保留粒度，报告按需切档（不一定 basic/medium/hard）
- 仲裁：给出终分 + 区间 + 简要依据；分歧>25 分时要求仲裁官明确说明取舍
- 可断点续跑 / 成本记录 / 结果落 data/outputs/diff_scores.jsonl

用法：
  python scripts/score_difficulty.py --quiz abc_selfbuilt.jsonl --sample 2   # 小样试跑
  python scripts/score_difficulty.py --quiz cf_selfbuilt.jsonl --resume       # 全量
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rex._json import extract_json_object  # noqa: E402
from rex.config import Config  # noqa: E402
from rex.hy3_client import Hy3Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outputs" / "diff_scores.jsonl"

# ---------------- 专家系统 prompt ----------------
_BLIND_RULE = (
    "重要：题目文本中可能残留平台信息（如 'Score : 400 points'、时限/内存、场次号），"
    "请一律忽略，不要用它推断难度，只依据题目本身的算法内容与参考解判断难度。"
)

EXPERT_SYSTEMS = {
    "competitor": (
        "你是一位经验丰富的算法竞赛选手（Codeforces / AtCoder / ICPC 均打过），"
        "对题目难度有实战直觉。请判断一道算法题的难度，给出 0-100 的连续分。\n"
        + _BLIND_RULE
    ),
    "theorist": (
        "你是一位算法理论专家，熟悉复杂度理论、数据结构和各类算法范式。"
        "请从'所需算法知识与思维深度'角度判断一道算法题的难度，给出 0-100 的连续分。\n"
        + _BLIND_RULE
    ),
    "adversary": (
        "你是一位出题人与反例猎手，最擅长找出题目中隐藏的边界条件、陷阱、"
        "特殊数据（溢出/空/极值/多种合法输出）。请从'实现易错度与隐蔽性'角度"
        "判断一道算法题的难度，给出 0-100 的连续分。\n"
        + _BLIND_RULE
    ),
}

ARBITER_SYSTEM = (
    "你是难度仲裁官。三位独立专家（实战选手 / 理论专家 / 反例猎手）已分别对同一道"
    "算法题打分（0-100）。请综合三份独立判断给出最终难度分：\n"
    "1) 若三份接近（极差 ≤ 25）→ 取中位数附近的加权值；\n"
    "2) 若分歧大 → 判断哪位专家对这道题更有发言权，说明取舍理由；\n"
    "3) 只输出 JSON：{\"final_score\": 数字, \"range\": \"[lo,hi]\", "
    "\"rationale\": \"一句话理由\"}。\n"
    + _BLIND_RULE
)

_SCORE_RE = re.compile(r'final_score["\s:=]+(\d+(?:\.\d+)?)', re.IGNORECASE)


def _score_prompt(quiz: dict, ref: str) -> str:
    title = quiz.get("title", "")
    prompt = quiz.get("prompt", "")
    return (
        f"题目：{title}\n\n---- 题面 ----\n{prompt}\n\n"
        f"---- 参考解（仅辅助你理解预期解法，勿据此反推平台难度）----\n{ref}\n\n"
        "请输出 JSON：{\"score\": 0-100 的难度分, \"difficulty_hint\": "
        "\"一句话：核心算法/思维点\", \"level\": \"你用自己直觉给的三档标签 "
        "(easy/medium/hard)\"}。不要输出其它文字。"
    )


def _parse_json(raw: str) -> dict:
    """从模型输出提取 JSON 对象并解析为 dict（extract_json_object 返回字符串）。"""
    try:
        s = extract_json_object(raw)
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _ask(client: Hy3Client, system: str, user: str, retries: int = 2) -> str:
    for i in range(retries + 1):
        try:
            return client.chat(user, system=system)
        except Exception as e:  # noqa: BLE001
            if i == retries:
                raise
            time.sleep(2 + i * 2)
    raise RuntimeError("unreachable")


def _parse_score(obj: dict) -> int | None:
    s = obj.get("score")
    if isinstance(s, (int, float)):
        return int(s)
    if isinstance(s, str):
        m = re.search(r"\d+", s)
        return int(m.group()) if m else None
    return None


def score_one(client: Hy3Client, quiz: dict) -> dict:
    ref = (quiz.get("reference_solution") or "").strip()
    user = _score_prompt(quiz, ref[:4000])
    expert_scores = {}
    for name, system in EXPERT_SYSTEMS.items():
        raw = _ask(client, system, user)
        obj = _parse_json(raw)
        expert_scores[name] = {
            "score": _parse_score(obj),
            "hint": obj.get("difficulty_hint", "")[:200],
            "level": obj.get("level", ""),
        }
    # 仲裁
    arb_input = "\n".join(
        f"- {name}专家: {json.dumps(es, ensure_ascii=False)}"
        for name, es in expert_scores.items()
    )
    arb_raw = _ask(client, ARBITER_SYSTEM,
                   f"三位专家打分如下：\n{arb_input}\n\n请给出最终仲裁（只输出 JSON）。")
    arb_obj = _parse_json(arb_raw)
    final_score = arb_obj.get("final_score")
    if isinstance(final_score, str):
        m = re.search(r"\d+", final_score)
        final_score = int(m.group()) if m else None
    return {
        "question_id": quiz["id"],
        "source_id": quiz.get("source_id"),
        "platform": "abc" if quiz.get("source_id", "").startswith("abc") else "cf",
        "expert_scores": expert_scores,
        "final_score": int(final_score) if final_score is not None else None,
        "arbiter": arb_obj,
    }


def load_quiz(path: Path) -> list[dict]:
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiz", required=True, help="题集文件名（data/questions/ 下）")
    ap.add_argument("--sample", type=int, default=0, help=">0 时只跑前 N 题试跑")
    ap.add_argument("--resume", action="store_true", help="跳过已打分的 question_id")
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    if not cfg.has_credentials:
        print("未配置 HY3_API_KEY / HY3_BASE_URL（.env）")
        sys.exit(1)
    quiz_path = ROOT / "data" / "questions" / args.quiz
    quiz_rows = load_quiz(quiz_path)
    if args.sample:
        quiz_rows = quiz_rows[: args.sample]

    done_ids = set()
    if args.resume and OUT.exists():
        for l in OUT.open(encoding="utf-8"):
            if l.strip():
                done_ids.add(json.loads(l)["question_id"])

    with Hy3Client(api_key=cfg.hy3_api_key, base_url=cfg.hy3_base_url,
                   model=cfg.hy3_model) as client:
        for i, q in enumerate(quiz_rows):
            if q["id"] in done_ids:
                print(f"[{i+1}/{len(quiz_rows)}] 跳过 {q['source_id']}（已打分）")
                continue
            try:
                rec = score_one(client, q)
            except Exception as e:  # noqa: BLE001
                print(f"[{i+1}/{len(quiz_rows)}] {q['source_id']} 失败: {e}")
                continue
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{i+1}/{len(quiz_rows)}] {q['source_id']} → "
                  f"final={rec['final_score']} | 专家: "
                  f"{[es.get('score') for es in rec['expert_scores'].values()]}")

    print(f"\n完成。结果在 {OUT}")


if __name__ == "__main__":
    main()
