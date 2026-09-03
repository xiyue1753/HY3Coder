"""批量入库 Codeforces 自建题（第一轮，对齐 ABC 产线规则）。

复用 ABC 产线积累的 SOP：
1. 抓题面（playwright + Edge + cookie 绕 Cloudflare）
2. 从题面 DOM 提取官方样例（input/output 对，无需解析 Copy 文本）
3. 从提交列表（BY_CONSUMED_TIME_ASC）找 C++ AC 提交，用官方样例沙盒验证
4. 官方样例入库为公开用例（hidden=false）；边界隐藏用例后续由
   gen_cf_hidden_cases 用参考解跑出（不手写期望）

安全隔离：cookie 仅经环境变量 CF_JSESSIONID 传入，不写文件、不入 git。

用法：
    $env:CF_JSESSIONID="xxx"
    & D:\.conda\envs\tensor_env\python.exe scripts/batch_ingest_cf.py
    # --only 只处理指定 source_id；--retry 每题失败重试
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playwright.sync_api import sync_playwright  # noqa: E402

from rex.models import Difficulty, QuestionItem, TestCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
REQUEST_DELAY = 1.5  # CF 页间间隔（秒），避免风控


def _wait(pg, cond_fn, tries: int = 20, delay: float = 2.0) -> bool:
    for _ in range(tries):
        pg.wait_for_timeout(delay * 1000)
        if cond_fn():
            return True
    return False


class CFBatch:
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie
        self.p = sync_playwright().start()
        self.b = self.p.chromium.launch(channel="msedge", headless=True,
                                        args=["--disable-blink-features=AutomationControlled"])
        self.ctx = self.b.new_context(user_agent=UA)
        if cookie:
            self.ctx.add_cookies([{"name": "JSESSIONID", "value": cookie,
                                   "domain": "codeforces.com", "path": "/",
                                   "httpOnly": True, "secure": True}])
        self.pg = self.ctx.new_page()

    def close(self) -> None:
        self.b.close()
        self.p.stop()

    # -- 题面 + 样例 ---------------------------------------------------
    def fetch_statement_and_samples(self, contest: str, index: str) -> tuple[str, list[tuple[str, str]]]:
        url = f"https://codeforces.com/problemset/problem/{contest}/{index}"
        self.pg.goto(url, timeout=30000, wait_until="domcontentloaded")
        _wait(self.pg, lambda: "Just a moment" not in self.pg.content())
        time.sleep(REQUEST_DELAY)
        statement = self.pg.eval_on_selector(
            ".problem-statement", "e => e.innerText").strip()
        samples = self._extract_samples_dom()
        return statement, samples

    def _extract_samples_dom(self) -> list[tuple[str, str]]:
        """从 .sample-test 的 input/output pre 提取样例对（DOM，最可靠）。"""
        ins = self.pg.eval_on_selector_all(
            ".sample-test .input pre",
            "els => els.map(e => e.innerText)")
        outs = self.pg.eval_on_selector_all(
            ".sample-test .output pre",
            "els => els.map(e => e.innerText)")
        pairs: list[tuple[str, str]] = []
        for i, o in zip(ins, outs):
            inp = i.strip().replace("\r\n", "\n")
            exp = o.strip().replace("\r\n", "\n")
            if inp or exp:
                pairs.append((inp, exp))
        return pairs

    # -- C++ AC 参考解 -------------------------------------------------
    def fetch_cpp_ac_candidates(self, contest: str, index: str) -> list[tuple[str, str]]:
        """返回 [(submission_href, verdict_lang), ...]（时间正序，找 C++ AC）。"""
        url = (f"https://codeforces.com/problemset/status/{contest}/problem/{index}"
               f"?order=BY_CONSUMED_TIME_ASC")
        self.pg.goto(url, timeout=30000)
        self.pg.wait_for_load_state("networkidle")
        self.pg.wait_for_timeout(2500)
        time.sleep(REQUEST_DELAY)
        rows = self.pg.eval_on_selector_all(
            '.status-frame-datatable tbody tr',
            'els => els.filter(e => e.querySelector("a[href*=submission]")).map(e => {'
            ' const tds=e.querySelectorAll("td");'
            ' return e.querySelector("a[href*=submission]").getAttribute("href")+"|"'
            ' +(tds[4]?tds[4].innerText.trim():"")+"|"+(tds[5]?tds[5].innerText.trim():""); })',
        )
        return [r for r in rows if "C++" in r and "Accepted" in r]

    def fetch_source(self, href: str) -> str:
        self.pg.goto("https://codeforces.com" + href, timeout=30000)
        self.pg.wait_for_load_state("networkidle")
        self.pg.wait_for_timeout(3000)
        time.sleep(REQUEST_DELAY)
        code = (self.pg.eval_on_selector("#program-source-text", "e => e.innerText")
                if self.pg.query_selector("#program-source-text") else "")
        if not code:
            raise RuntimeError(f"{href}: source not found")
        for ch in ("\xa0", "\u3000", "\u2009", "\u200b"):
            code = code.replace(ch, " ")
        return code

    @staticmethod
    def _prescreen(code: str) -> str | None:
        if not code.strip():
            return "空代码"
        if len(code) > 15_000:
            return f"代码过长({len(code)})"
        if "#include" not in code:
            return "非 C++"
        if "#include <atcoder/" in code:
            return "依赖 atcoder 库"
        if "print(" in code and "def " in code:
            return "疑似 Python"
        return None


def _outputs_match(got: str, expected: str, float_tol: float = 1e-5) -> bool:
    got_lines = [ln.strip() for ln in got.replace("\r\n", "\n").split("\n")]
    exp_lines = [ln.strip() for ln in expected.replace("\r\n", "\n").split("\n")]
    if len(got_lines) != len(exp_lines):
        return False
    for g, e in zip(got_lines, exp_lines):
        if g == e:
            continue
        try:
            fg, fe = float(g), float(e)
        except ValueError:
            return False
        if abs(fg - fe) <= float_tol * max(1.0, abs(fe), abs(fg)):
            continue
        return False
    return True


def _verify_with_samples(code: str, samples: list[tuple[str, str]]) -> tuple[bool, str]:
    from rex.executor.sandbox import run_code

    for i, (inp, exp) in enumerate(samples):
        res = run_code(code, stdin=inp, timeout=20, language="cpp")
        if res.error or res.timed_out:
            return False, f"sample{i + 1} 运行失败: {(res.error or 'timeout')[:100]}"
        got = res.stdout.strip()
        if not _outputs_match(got, exp):
            return False, f"sample{i + 1} 输出不符: 期望={exp.strip()[:60]!r} 实际={got[:60]!r}"
    return True, ""


def _find_ac(batch: CFBatch, contest: str, index: str,
             samples: list[tuple[str, str]], max_try: int = 6) -> tuple[str, str]:
    """按时间正序试前 max_try 条 C++ AC，用样例验证；返回 (submission_href, code)。"""
    cands = batch.fetch_cpp_ac_candidates(contest, index)
    tried = 0
    for cand in cands:
        if tried >= max_try:
            break
        href = cand.split("|")[0]
        code = batch.fetch_source(href)
        msg = batch._prescreen(code)
        if msg:
            print(f"  [skip] {href}: {msg}")
            continue
        tried += 1
        ok, err = _verify_with_samples(code, samples)
        if ok:
            return href, code
        print(f"  [skip] {href}: {err[:120]}")
    raise RuntimeError(f"{contest}{index}: 前 {max_try} 条 C++ AC 未通过样例")


# ---------------------------------------------------------------- 题单
# 第一轮（对齐 ABC 首轮 ~17 题规模；rating 分层 basic<=1100/medium1200-1700/hard>=1800）
# (contest, index, title, type, difficulty)
PLAN: list[tuple[str, str, str, str, str]] = [
    # ---- basic (rating <=1100) ----
    ("486", "A", "Calculating Function", "模拟/数学", "basic"),
    ("910", "A", "The Way to Home", "贪心/DP", "basic"),
    ("1660", "A", "Vasya and Coins", "贪心/数学", "basic"),
    ("1795", "A", "Two Towers", "字符串/模拟", "basic"),
    ("757", "A", "Gotta Catch Em' All!", "模拟/计数", "basic"),
    ("1730", "A", "Planets", "哈希/计数", "basic"),
    ("110", "A", "Nearly Lucky Number", "模拟/计数", "basic"),
    ("96", "A", "Football", "字符串/模拟", "basic"),
    # ---- medium (rating 1200-1700) ----
    ("676", "C", "Vasya and String", "双指针", "medium"),
    ("144", "B", "Meeting", "模拟/几何", "medium"),
    ("343", "B", "Alternating Current", "栈/思维", "medium"),
    ("455", "A", "Boredom", "DP", "medium"),
    ("414", "B", "Mashmokh and ACM", "DP/计数", "medium"),
    ("429", "A", "Xor-tree", "DFS/贪心", "medium"),
    # ---- hard (rating >=1800) ----
    ("1060", "E", "Sergey and Subway", "DFS/图", "hard"),
    ("358", "D", "Dima and Hares", "DP/递推", "hard"),
    ("300", "C", "Beautiful Numbers", "组合/数学", "hard"),
]

# 预置 source_id（去重用）：task = f"cf{contest}{index.lower()}"
def _task(contest: str, index: str) -> str:
    return f"cf{contest}{index.lower()}"


def next_id() -> str:
    existing = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()] if OUT.exists() else []
    n = max((int(q["id"][1:]) for q in existing if q["id"].startswith("C")), default=2000) + 1
    return f"C{n}"


def existing_source_ids() -> set[str]:
    if not OUT.exists():
        return set()
    return {json.loads(l)["source_id"] for l in OUT.open(encoding="utf-8") if l.strip()}


def ingest_one(batch: CFBatch, contest: str, index: str, title: str,
               typ: str, diff: str) -> str | None:
    task = _task(contest, index)
    if task in existing_source_ids():
        print(f"[skip] {task}: 已入库")
        return None
    statement, samples = batch.fetch_statement_and_samples(contest, index)
    if not samples:
        print(f"[skip] {task}: 题面未提取到样例")
        return None
    print(f"[auto-ac] {task}: {len(samples)} 组样例，翻找 C++ AC…")
    href, code = _find_ac(batch, contest, index, samples)
    tcs = [TestCase(input=i, output=o, hidden=False) for i, o in samples]
    q = QuestionItem(
        id=next_id(), scene="algorithm", title=title, prompt=statement,
        difficulty=Difficulty(diff), source="Codeforces-自建",
        source_id=task,
        layer_basis=f"官方 rating 题，{typ} → {diff}（rating 分层）",
        standard_answer="", reference_solution=code, test_cases=tcs,
        metadata={"contest": contest, "problem": task, "type": typ,
                  "submission_href": href, "round": "cf-round1"},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({task}) [{typ}/{diff}] code={len(code)} chars, "
          f"{len(tcs)} 样例用例")
    return q.id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--retry", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 题（调试用）")
    args = ap.parse_args()
    cookie = os.environ.get("CF_JSESSIONID", "").strip()
    if not cookie:
        print("[fatal] 请设置 CF_JSESSIONID 环境变量（隔离使用，不落盘）")
        sys.exit(2)
    plan = PLAN[:args.limit] if args.limit else PLAN
    only = set(args.only) if args.only else None
    batch = CFBatch(cookie)
    done = 0
    failed: list[str] = []
    try:
        for contest, index, title, typ, diff in plan:
            task = _task(contest, index)
            if only and task not in only:
                continue
            ok = False
            for attempt in range(args.retry + 1):
                try:
                    if ingest_one(batch, contest, index, title, typ, diff):
                        done += 1
                    ok = True
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[error] {task} (attempt {attempt + 1}/{args.retry + 1}): {e}")
                    if attempt < args.retry:
                        time.sleep(8)
            if not ok:
                failed.append(task)
    finally:
        batch.close()
    print(f"\n完成 {done}/{len(plan)} 题 → {OUT}")
    if failed:
        print(f"失败 {len(failed)} 题：{failed}")


if __name__ == "__main__":
    main()
