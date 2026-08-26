"""Codeforces 题入库脚本（自建算法评测集）。

用 playwright + 系统 Edge + JSESSIONID cookie 会话（绕开 Cloudflare Turnstile）：
1. 抓题面（.problem-statement innerText）
2. 从提交列表（order=BY_CONSUMED_TIME_ASC）找 C++ AC submission，抓源码
3. 测试用例从 cases JSON 读（人工设计，含题面样例与自建边界）

cookie 从环境变量 CF_JSESSIONID 传入（不落盘、不入 git）。
用法：
    $env:CF_JSESSIONID="xxx"
    python scripts/ingest_cf.py --contest 1 --index A --title "Theatre Square" \
        --source_id cf1a --difficulty basic --layer_basis "..." --cases-file data/cases/cf1a_cases.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rex.models import QuestionItem, TestCase, Difficulty  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "questions" / "cf_selfbuilt.jsonl"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def _wait_statement(pg) -> None:
    for _ in range(15):
        pg.wait_for_timeout(2000)
        if "Just a moment" not in pg.content():
            return


def fetch_statement(pg, contest: str, index: str) -> str:
    url = f"https://codeforces.com/problemset/problem/{contest}/{index}"
    pg.goto(url, timeout=30000, wait_until="domcontentloaded")
    _wait_statement(pg)
    st = pg.eval_on_selector(".problem-statement", "e => e.innerText")
    return st.strip()


def fetch_cpp_ac_code(pg, contest: str, index: str) -> str:
    """从提交列表找 C++ AC 提交，返回源码。"""
    url = f"https://codeforces.com/problemset/status/{contest}/problem/{index}?order=BY_CONSUMED_TIME_ASC"
    pg.goto(url, timeout=30000)
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(2500)
    rows = pg.eval_on_selector_all(
        '.status-frame-datatable tbody tr',
        'els => els.filter(e => e.querySelector("a[href*=submission]")).map(e => {'
        ' const tds=e.querySelectorAll("td");'
        ' return e.querySelector("a[href*=submission]").getAttribute("href")+"|"+(tds[4]?tds[4].innerText.trim():"")+"|"+(tds[5]?tds[5].innerText.trim():""); })',
    )
    cpp = [r for r in rows if "C++" in r and "Accepted" in r]
    if not cpp:
        raise RuntimeError(f"{contest}{index}: no C++ AC submission found")
    sub_link = cpp[0].split("|")[0]  # /problemset/submission/{c}/{sid}
    pg.goto("https://codeforces.com" + sub_link, timeout=30000)
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(3000)
    code = pg.eval_on_selector("#program-source-text", "e => e.innerText") \
        if pg.query_selector("#program-source-text") else ""
    if not code:
        raise RuntimeError(f"{sub_link}: source not found")
    return _clean_code(code)


def _clean_code(code: str) -> str:
    """清理 CF 源码里的非 ASCII 空白（\\xa0 不间断空格等），避免编译失败。"""
    for ch in ("\xa0", "\u3000", "\u2009", "\u200b"):
        code = code.replace(ch, " ")
    return code


def load_cases(path: str) -> list[TestCase]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TestCase.model_validate(c) for c in cases]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contest", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--source_id", required=True)
    ap.add_argument("--difficulty", choices=["basic", "medium", "hard"], required=True)
    ap.add_argument("--layer_basis", default="")
    ap.add_argument("--cases-file", required=True)
    args = ap.parse_args()

    jsession = os.environ.get("CF_JSESSIONID", "")
    if not jsession:
        print("[fatal] 请设置 CF_JSESSIONID 环境变量（安全隔离，不落盘）")
        sys.exit(2)

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA)
        ctx.add_cookies([{"name": "JSESSIONID", "value": jsession,
                          "domain": "codeforces.com", "path": "/", "httpOnly": True, "secure": True}])
        pg = ctx.new_page()
        try:
            statement = fetch_statement(pg, args.contest, args.index)
            code = fetch_cpp_ac_code(pg, args.contest, args.index)
        finally:
            b.close()

    all_tc = load_cases(args.cases_file)
    existing = []
    if OUT.exists():
        existing = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    next_id = max((int(q["id"][1:]) for q in existing if q["id"].startswith("C")), default=2000) + 1
    q = QuestionItem(
        id=f"C{next_id}", scene="algorithm", title=args.title, prompt=statement,
        difficulty=Difficulty(args.difficulty), source="Codeforces-自建",
        source_id=args.source_id, layer_basis=args.layer_basis,
        standard_answer="", reference_solution=code, test_cases=all_tc,
        metadata={"contest": args.contest, "problem": args.source_id},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({args.source_id}): {len(code)} chars code, {len(all_tc)} test cases")


if __name__ == "__main__":
    main()
