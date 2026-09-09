# -*- coding: utf-8 -*-
"""数据集记忆暴露（contamination）行为探测。

两个 probe（temperature=0，题目原文不含 source_id）：
  P1 出处召回：{verdict: seen/not_sure/not_seen, contest, problem_id, solution}
  P2 解法盲答：{solution, complexity}
自动判定先做「出处命中」（强证据），解法高吻合样本留人工复核（见
reports/CONTAMINATION_METHOD.md）。分层抽样 ABC/CF × basic/medium/hard。

用法：
    python scripts/run_contamination_probe.py --pilot          # 6 题 pilot（每层1）
    python scripts/run_contamination_probe.py                  # 全量 30 题
    python scripts/run_contamination_probe.py --ids A1002 C2009 --out x.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex._json import extract_json_object  # noqa: E402
from rex.config import Config  # noqa: E402

P1_SYSTEM = (
    "你是一名算法竞赛专家。下面给你一道题（可能来自公开题库）。请判断你是否曾经在训练语料或"
    "此前见过这道题。只输出一个 JSON 对象，字段含义："
    "verdict: 'seen' / 'not_sure' / 'not_seen'（你对该题是否见过的诚实判断）；"
    "contest: 你记得的竞赛名/轮次，不记得就空字符串；"
    "problem_id: 你记得的题号（如 ABC213 D、CF 486A、213D 之类），不记得就空字符串；"
    "solution: 该题标准解法的一句话（不超过 40 词），不记得就空字符串。"
    "注意：contest/problem_id/solution 不知道就留空字符串，绝对不要编造。"
)
P1_USER = "题目如下：\n{prompt}\n\n请只输出一个合法 JSON 对象。"

P2_SYSTEM = (
    "你是一名算法竞赛专家。给定一道算法题，请只描述它的主流标准解法与时间复杂度"
    "（1-3 句话），不要猜测出处，不要写代码。只输出一个 JSON 对象："
    "{solution: 解法描述, complexity: 时间复杂度}。"
)
P2_USER = "题目如下：\n{prompt}\n\n请只输出一个合法 JSON 对象。"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def judge_source_match(given_contest: str, given_pid: str, source_id: str) -> tuple[str, str]:
    """出处命中判定。返回 (level, note)：level in {'hit','partial','near','none'}。

    - hit：主题号精确命中且平台方向一致（Codeforces↔cf、AtCoder/ABC↔abc）
    - partial：主题号命中但平台不明/只有数字
    - near：给出的题号与真值邻近（记串一题，如 568A↔569C）——记忆痕迹，交人工
    - none：无出处线索
    """
    src = norm(source_id)          # e.g. abc213d / cf486a
    m = re.match(r"^(abc|cf)(\d+)([a-z])?$", src)
    prefix, num = (m.group(1), m.group(2)) if m else ("", "")
    g1, g2 = norm(given_contest), norm(given_pid)
    blob = g1 + g2
    if not blob:
        return "none", "模型未给出任何出处线索"
    plat_ok = ("codeforces" in blob or "cf" in blob) if prefix == "cf" \
        else ("atcoder" in blob or "abc" in blob)
    if num and num in g2:
        if plat_ok:
            return "hit", f"题号 {num} 命中且平台一致（模型：{given_contest} {given_pid}，真值 {source_id}）"
        return "partial", f"题号 {num} 命中但平台不明（模型：{given_contest} {given_pid}）"
    # 题号未命中：检查数字相近（±1 或同长度前缀）作为记忆痕迹
    for cand in re.findall(r"\d+", blob):
        if cand.isdigit() and num.isdigit() and abs(int(cand) - int(num)) <= 1:
            return "near", f"题号邻近（模型 {cand} vs 真值 {num}，模型：{given_contest} {given_pid}）"
    return "none", f"无匹配（模型：{given_contest} {given_pid}，真值 {source_id}）"


def ask(client, system: str, user: str) -> str:
    last: str | None = None
    for _ in range(2):
        msg = user if not last else f"{user}\n\n注意：上次输出非法：{last}\n请只输出合法 JSON。"
        raw = client.chat(msg, system=system, reasoning_effort="low")
        try:
            extract_json_object(raw)
            return raw
        except Exception as e:  # noqa: BLE001
            last = str(e)
    return raw


def run_one(client, q: dict) -> dict:
    prompt = q["prompt"]
    p1_raw = ask(client, P1_SYSTEM, P1_USER.format(prompt=prompt))
    p2_raw = ask(client, P2_SYSTEM, P2_USER.format(prompt=prompt))
    try:
        p1 = json.loads(extract_json_object(p1_raw))
    except Exception:  # noqa: BLE001
        p1 = {"verdict": "parse_fail"}
    try:
        p2 = json.loads(extract_json_object(p2_raw))
    except Exception:  # noqa: BLE001
        p2 = {}
    sid = q["source_id"] or ""
    level, note = judge_source_match(p1.get("contest", ""), p1.get("problem_id", ""), sid)
    return {
        "question_id": q["id"],
        "source_id": sid,
        "platform": "ABC" if (sid or "").startswith("abc") else "CF",
        "difficulty": q["difficulty"],
        "diff_score": (q.get("metadata") or {}).get("diff_score"),
        "p1_verdict": p1.get("verdict"),
        "p1": {"raw": p1_raw, "parsed": p1},
        "p2": {"raw": p2_raw, "parsed": p2},
        "match": {"level": level, "note": note},
    }


def sample_questions(per_cell: int, seed: int = 42, pilot: bool = False) -> list[dict]:
    qs: list[dict] = []
    for f in (ROOT / "data" / "questions" / "abc_selfbuilt.jsonl",
              ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"):
        for line in f.open(encoding="utf-8"):
            if line.strip():
                qs.append(json.loads(line))
    # 平台×难度档分组（CF 的难度字段用 difficulty）
    groups: dict[tuple[str, str], list[dict]] = {}
    for q in qs:
        sid = q.get("source_id") or ""
        plat = "ABC" if sid.startswith("abc") else "CF"
        groups.setdefault((plat, q.get("difficulty", "basic")), []).append(q)
    rng = random.Random(seed)
    picked: list[dict] = []
    for cell in sorted(groups):
        rng.shuffle(groups[cell])
        n = 1 if pilot else per_cell
        picked.extend(groups[cell][:n])
    # pilot：只取每平台每难度一个即可（即 n=1 已够），否则正常 per_cell
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="每层 1 题（共 6 题）")
    ap.add_argument("--per-cell", type=int, default=5, help="每平台×难度抽题数（默认 5 → 30）")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--out", default="contamination_probe.jsonl")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    cfg = Config.from_env(ROOT)
    from rex.hy3_client import Hy3Client
    client = Hy3Client(api_key=cfg.hy3_api_key, base_url=cfg.hy3_base_url,
                       model=cfg.hy3_model, reasoning_effort=cfg.hy3_reasoning_effort,
                       temperature=0.0, max_retries=cfg.max_retries, timeout=cfg.timeout)

    if args.ids:
        pool = []
        for f in (ROOT / "data" / "questions" / "abc_selfbuilt.jsonl",
                  ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"):
            for line in f.open(encoding="utf-8"):
                if line.strip():
                    q = json.loads(line)
                    if q["id"] in args.ids:
                        pool.append(q)
        picked = pool
    else:
        picked = sample_questions(args.per_cell, pilot=args.pilot)
    print(f"待探测 {len(picked)} 题" + ("（pilot，每层1题）" if args.pilot else ""), flush=True)

    out = ROOT / "data" / "outputs" / args.out
    done = set()
    if not args.no_resume and out.exists():
        for line in out.open(encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["question_id"])
    with out.open("a", encoding="utf-8") as f:
        for q in picked:
            if q["id"] in done:
                print("-", q["id"], "已存在，跳过", flush=True)
                continue
            try:
                rec = run_one(client, q)
            except Exception as e:  # noqa: BLE001
                print("-", q["id"], "FAILED:", str(e)[:160], flush=True)
                rec = {"question_id": q["id"], "source_id": q.get("source_id"),
                       "error": str(e)[:400]}
            rec["created_at"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            ml = rec.get("match", {}).get("level", "-")
            p1v = rec.get("p1_verdict")
            print(f"- {q['id']} P1_verdict={p1v} match={ml} "
                  f"({rec.get('match', {}).get('note', '')[:60]})", flush=True)
    print("写盘完成", out)


if __name__ == "__main__":
    main()
