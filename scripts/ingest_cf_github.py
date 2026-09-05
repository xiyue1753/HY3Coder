"""无 cookie 补 Codeforces 自建题（题目页 playwright + GitHub 本地 AC 解索引）。

背景：CF 对 submission 源码路由限流（第 13 轮起全挂），但题目路由（题面+
结构化样例）在有效 clearance 下仍可用。参考解改为从本地 GitHub 题解仓库
索引拉取（waqar-107/Codeforces + kantuni/Codeforces，已下载解压到
data/cache/cf_gh/），用官方样例沙盒验证后作参考解，完全绕开 submission 页。

入库 schema 与 batch_ingest_cf.ingest_one 完全一致：
- test_cases.output 取参考解实际输出（期望输出自洽化，多解题自动标记）
- source_id = cf{contest}{index.lower()}，id 延续 C 前缀自增

用法：
    python scripts/ingest_cf_github.py --dry-plan      # 只看本轮选题+GitHub覆盖
    python scripts/ingest_cf_github.py --limit 25 --seed 3
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from rex.models import Difficulty, QuestionItem, TestCase  # noqa: E402

from batch_ingest_cf import (  # noqa: E402
    BAD_TAGS,
    CFBatch,
    HARD_RATING_MAX,
    OUT,
    _load_cookies,
    _outputs_match,
    _task,
    _verify_with_samples,
    existing_source_ids,
    looks_multi_solution,
    next_id,
    record_pending,
    type_of,
)

GH_ROOT = ROOT / "data" / "cache" / "cf_gh"
CACHE_PROBS = ROOT / "data" / "cache" / "cf_problemset.json"

TARGET = {"basic": 33, "medium": 82, "hard": 60}


# ---------------------------------------------------------------------------
# GitHub 本地 AC 索引
# ---------------------------------------------------------------------------
def _build_gh_index() -> dict[str, list[Path]]:
    """扫描 data/cache/cf_gh/{waqar,kantuni} 建 sid -> [代码文件] 索引。

    - waqar:  {root}/Codeforces-master/A-set/{contest}{Index}.{Name}.cpp
    - kantuni: {root}/Codeforces-master/{contest}{Index}/{slug}.cpp
    """
    index: dict[str, list[Path]] = {}

    waqar = GH_ROOT / "waqar"
    pat = re.compile(r"^(\d+)([A-Z]\d*)\.")
    if waqar.exists():
        for dirpath, _dirs, files in os.walk(waqar):
            for f in files:
                if not f.endswith((".cpp", ".py", ".java", ".cc")):
                    continue
                m = pat.match(f)
                if m:
                    sid = f"cf{m.group(1)}{m.group(2).lower()}"
                    index.setdefault(sid, []).append(Path(dirpath) / f)

    kantuni = GH_ROOT / "kantuni"
    pat2 = re.compile(r"^(\d+)([A-Z]\d*)$")
    if kantuni.exists():
        for d in os.listdir(kantuni):
            m = pat2.match(d)
            if not m:
                continue
            dp = kantuni / d
            if not dp.is_dir():
                continue
            for f in os.listdir(dp):
                if f.endswith((".cpp", ".py", ".java", ".cc")):
                    sid = f"cf{m.group(1)}{m.group(2).lower()}"
                    index.setdefault(sid, []).append(dp / f)
    return index


# ---------------------------------------------------------------------------
# 选题（缺口分层 + 仅保留 GitHub 有解）
# ---------------------------------------------------------------------------
def _to_item(p: dict) -> dict:
    r = int(p["rating"])
    return {
        "contest": str(p["contestId"]), "index": p["index"],
        "name": p.get("name", ""),
        "typ": type_of(p.get("tags", [])),
        "diff": "basic" if r <= 1100 else ("medium" if r <= 1700 else "hard"),
    }


def auto_plan_github(gh_index: dict[str, list[Path]], seed: int) -> list[dict]:
    """返回按缺口分层优先排序的候选池（仅 GitHub 索引有解、未收录）。

    - 池内顺序：缺口目标层（basic/medium/hard 按需求比例交错取）在前，
      其余同层打散在后作为回填池。
    - 调用方循环消费池，直到成功目标数或池耗尽（单题 GitHub 解可能
      全验证失败 → 自动换池内下一题）。
    """
    probs = json.loads(CACHE_PROBS.read_text(encoding="utf-8"))
    existing = existing_source_ids()
    rnd = random.Random(seed)

    counts = {"basic": 0, "medium": 0, "hard": 0}
    for line in OUT.open(encoding="utf-8"):
        if line.strip():
            counts[json.loads(line)["difficulty"]] += 1
    need = {k: max(0, TARGET[k] - counts[k]) for k in TARGET}

    def sid(c, i):
        return f"cf{c}{i.lower()}"

    # 分层候选池（仅 GitHub 有解）
    tiers: dict[str, list[dict]] = {"basic": [], "medium": [], "hard": []}
    for p in probs:
        if p.get("type") != "PROGRAMMING" or "rating" not in p:
            continue
        s = sid(str(p.get("contestId")), p.get("index"))
        if s in existing or s not in gh_index:
            continue
        if any(t in BAD_TAGS for t in p.get("tags", [])):
            continue
        r = int(p["rating"])
        if r <= 1100:
            tiers["basic"].append(p)
        elif 1200 <= r <= 1700:
            tiers["medium"].append(p)
        elif 1800 <= r <= HARD_RATING_MAX:
            tiers["hard"].append(p)

    # 每层独立打散 + 类型去重为有序列表
    ordered_tiers: dict[str, list[dict]] = {}
    for tier in ("basic", "medium", "hard"):
        rnd.shuffle(tiers[tier])
        used_types: set[str] = set()
        arr: list[dict] = []
        for p in tiers[tier]:
            t = type_of(p.get("tags", []))
            if t in used_types and len(used_types) < len(tiers[tier]):
                continue
            used_types.add(t)
            arr.append(p)
            # 该类型后续不再连续取；类型用尽后允许重复
            # （去重后若全部类型已用一轮则放开）
            if len(used_types) >= 12:
                used_types.clear()
        ordered_tiers[tier] = arr

    # 主序列：按缺口比例逐层循环取（basic/medium/hard 均衡铺开）
    need_now = {k: max(0, need[k]) for k in need}
    main_seq: list[dict] = []
    while any(need_now.values()):
        progressed = False
        for tier in ("basic", "medium", "hard"):
            if need_now[tier] <= 0:
                continue
            if ordered_tiers[tier]:
                main_seq.append(_to_item(ordered_tiers[tier].pop(0)))
                need_now[tier] -= 1
                progressed = True
        if not progressed:
            break
    # 回填池：所有层余量（主序列未用到的）顺序打散放尾部
    rest: list[dict] = []
    for tier in ("basic", "medium", "hard"):
        rest.extend(_to_item(p) for p in ordered_tiers[tier])
    rnd.shuffle(rest)
    # 去重（保证不重复）
    seen: set[str] = set()
    out: list[dict] = []
    for it in main_seq + rest:
        s = sid(it["contest"], it["index"])
        if s in seen:
            continue
        seen.add(s)
        out.append(it)
    return out


# ---------------------------------------------------------------------------
# GitHub 候选验证 + 入库
# ---------------------------------------------------------------------------
def _prefer_lang(files: list[Path]) -> list[Path]:
    """候选排序：C++ 优先（参考解统一 C++ 与现有集一致），再 python/java。"""
    def rank(p: Path) -> int:
        return 0 if p.suffix in (".cpp", ".cc") else (1 if p.suffix == ".py" else 2)
    return sorted(files, key=rank)


def ingest_from_github(batch: CFBatch, item: dict,
                       gh_index: dict[str, list[Path]],
                       max_try: int = 5) -> str | None:
    contest, index = item["contest"], item["index"]
    task = _task(contest, index)
    if task in existing_source_ids():
        print(f"[skip] {task}: 已入库")
        return None
    candidates = _prefer_lang(gh_index.get(task, []))
    if not candidates:
        print(f"[skip] {task}: GitHub 索引无解（不应发生，plan 已过滤）")
        return None

    statement, samples = batch.fetch_statement_and_samples(contest, index)
    if not samples:
        print(f"[skip] {task}: 题面未提取到样例")
        return None
    print(f"[github-ac] {task}: {len(samples)} 组样例, {len(candidates)} 个本地候选…")

    # 逐个候选沙盒验证（沿用 _verify_with_samples 语义）
    code = None
    src = None
    for cand in candidates[:max_try]:
        c = cand.read_text(encoding="utf-8", errors="replace")
        if len(c) > 30_000 or "#include" not in c:
            continue
        ok, err = _verify_with_samples(c, samples)
        if ok:
            code, src = c, cand
            break
        print(f"  [skip] {Path(cand).name}: {err[:90]}")
    if code is None:
        print(f"[error] {task}: 前 {max_try} 个 GitHub 候选均未通过样例")
        return None

    # 期望输出自洽化（同 batch_ingest_cf.ingest_one）
    from rex.executor.sandbox import run_code
    tcs: list[TestCase] = []
    mismatch = False
    for i, (inp, exp) in enumerate(samples):
        res = run_code(code, stdin=inp, timeout=20, language="cpp")
        out_actual = (res.stdout or "").strip() if not res.error else ""
        if not out_actual:
            tcs.append(TestCase(input=inp, output=exp, hidden=False))
            continue
        if not _outputs_match(out_actual, exp):
            mismatch = True
        tcs.append(TestCase(input=inp, output=out_actual, hidden=False))
    needs_checker = mismatch

    meta = {"contest": contest, "problem": task, "type": item["typ"],
            "ref_source": f"github:{src}", "round": "cf-github1"}
    if needs_checker:
        meta["needs_checker"] = True
        record_pending(task, item["name"], item["typ"], item["diff"])
    q = QuestionItem(
        id=next_id(), scene="algorithm", title=item["name"], prompt=statement,
        difficulty=Difficulty(item["diff"]), source="Codeforces-自建",
        source_id=task,
        layer_basis=f"官方 rating 题，{item['typ']} → {item['diff']}（rating 分层；"
                    f"参考解源自 GitHub 公开题解）",
        standard_answer="", reference_solution=code, test_cases=tcs,
        metadata=meta,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({task}) [{item['typ']}/{item['diff']}] "
          f"code={len(code)} chars, {len(tcs)} 样例用例"
          + (f" | 源自 {src.name}" if src else "")
          + (" | needs_checker(多解)" if needs_checker else ""))
    return q.id


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="GitHub 源补 CF 自建题")
    ap.add_argument("--limit", type=int, default=25,
                    help="本轮目标成功题数（失败自动换候选回填）")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dry-plan", action="store_true", help="只打印候选池，不抓取")
    ap.add_argument("--delay", type=float,
                    default=float(os.environ.get("CF_DELAY", "2.0")))
    args = ap.parse_args()

    os.environ.setdefault("CF_DELAY", str(args.delay))
    gh_index = _build_gh_index()
    print(f"[idx] GitHub 索引 {len(gh_index)} 题")

    pool = auto_plan_github(gh_index, args.seed)
    if not pool:
        print("[plan] 无可用候选（缺口已满或 GitHub 覆盖不足）")
        return
    counts: dict[str, int] = {}
    for x in pool:
        counts[x["diff"]] = counts.get(x["diff"], 0) + 1
    print(f"[pool] {len(pool)} 候选：{counts}")
    if args.dry_plan:
        for x in pool[: args.limit]:
            print(f"  {_task(x['contest'], x['index'])}({x['diff']}) {x['name']}")
        return

    cookies, ua = _load_cookies()
    batch = CFBatch(cookies, ua=ua, headless=True, human_wait=30)
    ok = fail = exhausted = 0
    try:
        for item in pool:
            if ok >= args.limit:
                break
            r = ingest_from_github(batch, item, gh_index)
            if r:
                ok += 1
            else:
                fail += 1
        if ok < args.limit:
            exhausted = args.limit - ok
    finally:
        batch.close()
    print(f"\n完成 {ok}/{args.limit} 题；失败 {fail} 题；"
          f"未达标缺口 {exhausted}（候选池耗尽）")


if __name__ == "__main__":
    main()
