"""批量入库 Codeforces 自建题（第一轮，对齐 ABC 产线规则）。

复用 ABC 产线积累的 SOP：
1. 抓题面（playwright + Edge + cookie 绕 Cloudflare）
2. 从题面 DOM 提取官方样例（input/output 对，无需解析 Copy 文本）
3. 从提交列表（BY_CONSUMED_TIME_ASC）找 C++ AC 提交，用官方样例沙盒验证
4. 官方样例入库为公开用例（hidden=false）；边界隐藏用例后续由
   gen_cf_hidden_cases 用参考解跑出（不手写期望）

安全隔离：cookie 默认从 data/cases/cf_cookies.json 读取（由
scripts/cf_cookie_session.py 人工验证一次生成，含 cf_clearance，可不被
Cloudflare 拦截）；未生成时回退环境变量 CF_JSESSIONID。cookie 不入 git。

用法：
    python scripts/cf_cookie_session.py      # 先人工验证一次（生成 cf_cookies.json）
    python scripts/batch_ingest_cf.py
    # --only 只处理指定 source_id；--retry 每题失败重试；CF_DELAY 控制页间延迟
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK：强制 UTF-8 输出，避免 ✓/… 等字符 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playwright.sync_api import sync_playwright  # noqa: E402

from rex.models import Difficulty, QuestionItem, TestCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"
COOKIE_FILE = ROOT / "data" / "cases" / "cf_cookies.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
REQUEST_DELAY = float(os.environ.get("CF_DELAY", "1.5"))  # CF 页间间隔（秒），CF_DELAY 可调低频率防风控


def _load_cookies() -> tuple[list[dict], str]:
    """读取 cookie + 绑定的 UA。

    返回 (cookies, ua)。cf_clearance 绑定 IP+UA，因此必须用导出 cookie 时
    浏览器的 UA。支持两种 cookie 文件格式：
      - 推荐（路径 B 手动导出）：{"ua": "<浏览器UA>", "cookies": [...]}
      - 兼容：纯数组（则 UA 用 UA 常量，可能因 UA 不匹配而失效）
    未找到 cookie 文件时回退环境变量 CF_JSESSIONID（仅登录态，弱于 cf_clearance）。
    """
    if COOKIE_FILE.exists():
        try:
            data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "cookies" in data:
                ua = str(data.get("ua") or UA).strip()
                return list(data["cookies"]), ua
            if isinstance(data, list) and data:
                return data, UA
        except Exception as e:  # noqa: BLE001
            print(f"[warn] cf_cookies.json 解析失败: {e}，回退环境变量")
    env = os.environ.get("CF_JSESSIONID", "").strip()
    if env:
        return [{"name": "JSESSIONID", "value": env,
                 "domain": "codeforces.com", "path": "/",
                 "httpOnly": True, "secure": True}], UA
    return [], UA


def _is_challenge(page) -> bool:
    """判断当前页是否为 Cloudflare 安全验证/拦截页。"""
    try:
        t = page.title() or ""
        body = ""
        try:
            body = page.eval_on_selector("body", "e => e.innerText")[:600]
        except Exception:  # noqa: BLE001
            pass
        if "Just a moment" in t or "Attention" in t or "安全检查" in t:
            return True
        if "Ray ID" in body and ("security check" in body.lower() or "安全检查" in body):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _wait(pg, cond_fn, tries: int = 20, delay: float = 2.0) -> bool:
    for _ in range(tries):
        pg.wait_for_timeout(delay * 1000)
        if cond_fn():
            return True
    return False


class CFBatch:
    """CF 会话封装。

    两种模式：
    - headless=True：cookie 文件优先（含 cf_clearance）；遇 challenge 即止损。
    - headless=False（--headed 交互模式）：弹出真实 Edge，遇 Cloudflare 验证框时
      打印提示并等待用户在窗口内手动点击/完成验证，通过后**同一会话**继续抓取
      （cf_clearance 绑定会话指纹，同会话最可靠，无需导出/再导入）。
    """

    def __init__(self, cookies: list[dict], ua: str | None = None,
                 headless: bool = True, human_wait: int = 240) -> None:
        self.cookies = cookies
        self.headless = headless
        self.human_wait = human_wait
        self.p = sync_playwright().start()
        self.b = self.p.chromium.launch(
            channel="msedge", headless=headless,
            args=["--disable-blink-features=AutomationControlled"])
        self.ctx = self.b.new_context(user_agent=ua or UA,
                                      viewport={"width": 1400, "height": 900})
        if cookies:
            self.ctx.add_cookies(cookies)
        self.pg = self.ctx.new_page()
        # 关键：先访问首页完成会话初始化（含 CF 会话 cookie/防爬放行），
        # 否则直接访问提交源码页可能拿不到登录态。
        self._goto_ready("https://codeforces.com/")

    def close(self) -> None:
        self.b.close()
        self.p.stop()

    # -- 页面导航：统一等待 + challenge 处理 ----------------------------
    def _goto_ready(self, url: str, tries: int = 15, delay: float = 2.0) -> None:
        """goto 并等待 Cloudflare challenge 消失。

        处理顺序：
        1) 先按给定等待次数等 challenge 自动放行（CF 的 JS challenge 常自动过）；
        2) 仍被拦截 → 截图存档 + headless 下自动延长等待并重载几次（尝试拿新
           clearance）；仍失败抛 CFChallengeError；
        3) headless=False（交互）→ 打印提示并等待用户手动完成验证框。
        """
        self.pg.goto(url, timeout=30000, wait_until="domcontentloaded")
        if self._wait_challenge_clear(tries, delay):
            return
        self._snapshot_challenge(url)
        if self.headless:
            # 自动再等一轮（CF JS challenge 可能几秒后自行放行），并重载一次
            if self._wait_challenge_clear(20, 3.0):
                print("[+] challenge 自动放行（等待后通过）")
                return
            try:
                self.pg.reload(timeout=30000, wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001
                pass
            if self._wait_challenge_clear(15, 2.0):
                print("[+] challenge 自动放行（reload 后通过）")
                return
            raise CFChallengeError(
                "Cloudflare 安全验证拦截：已截图存档（data/cases/cf_challenge_*.png）。"
                "请运行 scripts/cf_cookie_session.py 重新人工验证生成新 cookie，"
                "或用 --headed 交互模式手动点击验证框。")
        self._resolve_challenge_human(url)

    def _snapshot_challenge(self, url: str) -> None:
        """把 challenge 页截图存档（便于确认验证类型/是否需人工点击）。"""
        try:
            d = Path(__file__).resolve().parents[1] / "data" / "cases"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"cf_challenge_{time.strftime('%Y%m%d_%H%M%S')}.png"
            self.pg.screenshot(path=str(p), full_page=False)
            print(f"[challenge] 验证页已截图存档: {p.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[challenge] 截图失败: {e}")

    def _wait_challenge_clear(self, tries: int, delay: float) -> bool:
        for _ in range(tries):
            self.pg.wait_for_timeout(delay * 1000)
            if not _is_challenge(self.pg):
                return True
        return not _is_challenge(self.pg)

    def _resolve_challenge_human(self, url: str) -> None:
        """交互模式：等待用户在真实 Edge 窗口内手动完成 Cloudflare 验证。"""
        print("\n[!] 检测到 Cloudflare 验证。请在弹出的 Edge 窗口内完成以下操作：")
        print("    1) 若出现验证框（I'm not a robot），点击它；通常等几秒后自动通过")
        print("    2) 若显示 'Verify you are human' 等按钮，点击后等待页面加载完成")
        print(f"    最长等待 {self.human_wait} 秒。通过后脚本会自动继续，无需其它操作。\n")
        waited = 0
        while waited < self.human_wait:
            self.pg.wait_for_timeout(2000)
            waited += 2
            if not _is_challenge(self.pg):
                print("[+] 验证已通过，继续抓取…")
                return
        raise CFChallengeError(
            f"人工验证等待超时（{self.human_wait}s）。可能当前 IP 仍被 CF 临时屏蔽，"
            "请更换网络出口或等待 IP 冷却后重试。")

    # -- 题面 + 样例 ---------------------------------------------------
    def fetch_statement_and_samples(self, contest: str, index: str) -> tuple[str, list[tuple[str, str]]]:
        url = f"https://codeforces.com/problemset/problem/{contest}/{index}"
        self._goto_ready(url)
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
        self._goto_ready(url, tries=25)
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
        url = "https://codeforces.com" + href
        last_err = "source not found"
        for attempt in range(3):
            self._goto_ready(url, tries=20)
            # 轮询等源码块出现（页面 JS 加载 + 登录态恢复可能较慢）
            found = _wait(self.pg, lambda: self.pg.query_selector("#program-source-text") is not None,
                          tries=12, delay=1.5)
            time.sleep(REQUEST_DELAY)
            if found:
                code = self.pg.eval_on_selector("#program-source-text", "e => e.innerText")
                if code.strip():
                    for ch in ("\xa0", "\u3000", "\u2009", "\u200b"):
                        code = code.replace(ch, " ")
                    return code
            last_err = f"{href}: source not loaded (attempt {attempt + 1}/3)"
        raise RuntimeError(last_err)

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
    """按行 + 空白 token 级容差比较输出。

    支持每行多个空格分隔数值（如坐标 `0.000 1.000 2.000`）——整行解析为
    单个 float 会失败。逐 token 比较：两侧 token 数一致、逐 token 字符串相等
    或浮点容差内相等。
    """
    got_lines = [ln.strip() for ln in got.replace("\r\n", "\n").split("\n")]
    exp_lines = [ln.strip() for ln in expected.replace("\r\n", "\n").split("\n")]
    if len(got_lines) != len(exp_lines):
        return False
    for g, e in zip(got_lines, exp_lines):
        gt = g.split()
        et = e.split()
        if gt == et:
            continue
        if len(gt) != len(et):
            return False
        for a, b in zip(gt, et):
            if a == b:
                continue
            try:
                fa, fb = float(a), float(b)
            except ValueError:
                return False
            if abs(fa - fb) <= float_tol * max(1.0, abs(fb), abs(fa)):
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


def looks_multi_solution(statement: str) -> bool:
    """检测多解构造题提示（CF 用 checker 判题，样例只是合法解之一）。

    命中后不能用样例文本比对验证 AC 解，自动收录阶段跳过（需 SPJ checker）。

    排除误判：数值/几何题（输出浮点坐标、半径等）同样带 CF 标准宽容声明
    "if there are several solutions, you are allowed to print any of them"，
    但那是浮点精度允许多个等价解，不是构造多解。此类题含 real numbers /
    coordinates / absolute error 等强信号时**不**判多解（仍可用样例文本比对，
    因为输出的是数值，AC 解会打印同值坐标）。
    """
    import re

    if not statement:
        return False
    s = statement.lower()
    # 数值输出题（浮点坐标/实数/容差声明）→ several solutions 指精度等价解，非多解
    numeric_ok = (
        r"print\s+three\s+space[-\s]separated\s+real\s+numbers"
        r"|real\s+numbers"
        r"|space[-\s]separated\s+real"
        r"|absolute\s+(or\s+relative\s+)?error"
        r"|within\s+[0-9.e-]+\s+(absolute|relative)"
    )
    if re.search(numeric_ok, s):
        return False
    patterns = [
        r"(print|output|return|submit)\s+any\b",
        r"any\s+valid",
        r"any\s+(of|one|answer|solution|way|sequence|permutation|order)\b",
        r"(not\s+unique|multiple\s+(valid\s+)?(answers|solutions))",
        r"if there are (several|multiple)",
        r"(several|multiple)\s+(possible|valid)\s+",
    ]
    return any(re.search(p, s) for p in patterns)


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
# 长程轮次：PLAN 为固定精选题（第一轮）；--auto 从 CF problemset 缓存自动选题。
# (contest, index, title, type, difficulty)
TAG_TYPE = {
    "implementation": "模拟", "greedy": "贪心", "math": "数学", "dp": "DP",
    "graphs": "图", "data structures": "数据结构", "strings": "字符串",
    "binary search": "二分", "sortings": "排序", "number theory": "数论",
    "dfs and similar": "DFS", "brute force": "暴力", "combinatorics": "组合",
    "constructive algorithms": "构造", "two pointers": "双指针", "bitmasks": "位运算",
    "trees": "树", "shortest paths": "最短路", "divide and conquer": "分治",
    "geometry": "几何", "games": "博弈", "probabilities": "概率",
}
BAD_TAGS = {"interactive", "*special", "fft", "chinese remainder theorem"}
# 每档 hard 上限：>2400 的题样例少且 AC 解模板化严重，沙盒验证不稳定，不自动收录
HARD_RATING_MAX = 2400


def type_of(tags: list[str]) -> str:
    for t in tags:
        if t in TAG_TYPE:
            return TAG_TYPE[t]
    return "综合"


def _load_cache() -> list[dict]:
    cache = ROOT / "data" / "cache" / "cf_problemset.json"
    if not cache.exists():
        print("[fatal] 缺少 data/cache/cf_problemset.json")
        sys.exit(2)
    return json.loads(cache.read_text(encoding="utf-8"))


def plan_from_ids(ids: list[str]) -> list[tuple[str, str, str, str, str]]:
    """根据 source_id 列表（cf{contest}{index}）从缓存构造 PLAN。"""
    probs = _load_cache()
    by_sid: dict[str, dict] = {}
    for p in probs:
        c = p.get("contestId")
        i = p.get("index")
        if c is None or i is None:
            continue
        by_sid[f"cf{c}{i.lower()}"] = p
    out = []
    for sid in ids:
        p = by_sid.get(sid)
        if not p:
            print(f"[skip] {sid}: 缓存中无此题")
            continue
        r = int(p["rating"])
        d = "basic" if r <= 1100 else ("medium" if r <= 1700 else "hard")
        out.append((str(p["contestId"]), p["index"], p.get("name", ""),
                    type_of(p.get("tags", [])), d))
    return out


def auto_plan(round_size: int = 17, seed: int = 1) -> list[tuple[str, str, str, str, str]]:
    """从 data/cache/cf_problemset.json 选下一轮题（未收录、按分层缺口+类型均匀）。"""
    import random

    cache = ROOT / "data" / "cache" / "cf_problemset.json"
    if not cache.exists():
        print("[fatal] 缺少 data/cache/cf_problemset.json（先跑 API 拉题单）")
        sys.exit(2)
    probs = json.loads(cache.read_text(encoding="utf-8"))
    existing = existing_source_ids()

    def sid(c: str, i: str) -> str:
        return f"cf{c}{i.lower()}"

    # 当前分层缺口（目标对齐 ABC：basic33/medium82/hard60）
    counts = {"basic": 0, "medium": 0, "hard": 0}
    for l in OUT.open(encoding="utf-8"):
        if l.strip():
            counts[json.loads(l)["difficulty"]] += 1
    target = {"basic": 33, "medium": 82, "hard": 60}
    need = {k: max(0, target[k] - counts[k]) for k in target}
    tiers: dict[str, list[dict]] = {"basic": [], "medium": [], "hard": []}
    for p in probs:
        if p.get("type") != "PROGRAMMING" or "rating" not in p:
            continue
        if sid(str(p.get("contestId")), p.get("index")) in existing:
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
    rnd = random.Random(seed)
    plan: list[tuple[str, str, str, str, str]] = []
    # 类型去重池（打散后按类型尽量不重复）
    for tier in ("basic", "medium", "hard"):
        alloc = round(round_size * need[tier] / max(1, sum(need.values())))
        rnd.shuffle(tiers[tier])
        used_types: set[str] = set()
        picked = []
        for p in tiers[tier]:
            t = type_of(p.get("tags", []))
            if len(picked) >= alloc:
                break
            if t in used_types and len(picked) < alloc:
                continue  # 仍有档位空缺时允许重复类型
            used_types.add(t)
            picked.append(p)
        for p in picked:
            plan.append((str(p["contestId"]), p["index"], p.get("name", ""),
                         type_of(p.get("tags", [])),
                         "basic" if int(p["rating"]) <= 1100
                         else ("medium" if int(p["rating"]) <= 1700 else "hard")))
    # 补齐到 round_size（优先未用档）
    pool = [p for p in tiers["basic"] + tiers["medium"] + tiers["hard"]]
    rnd.shuffle(pool)
    have = {sid(c, i) for c, i, *_ in plan}
    for p in pool:
        if len(plan) >= round_size:
            break
        if sid(str(p["contestId"]), p["index"]) in have:
            continue
        r = int(p["rating"])
        d = "basic" if r <= 1100 else ("medium" if r <= 1700 else "hard")
        plan.append((str(p["contestId"]), p["index"], p.get("name", ""),
                     type_of(p.get("tags", [])), d))
    plan.sort(key=lambda x: x[4])
    print(f"[auto] 下一轮 {len(plan)} 题："
          + ", ".join(f"{sid(c, i)}({d})" for c, i, _, _, d in plan))
    return plan


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
    if looks_multi_solution(statement):
        print(f"[skip] {task}: 多解构造题（需 SPJ checker，自动收录跳过）")
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


class CFChallengeError(RuntimeError):
    """Cloudflare 安全验证拦截（需人工过验证一次后重跑）。"""


# ---------------------------------------------------------------------------
# SPJ（多解/构造题）入库支持
# ---------------------------------------------------------------------------
def _load_special_checker(task: str) -> tuple[str | None, str]:
    """加载 data/scripts/checkers/{task}_checker.py 作为 checker 源码。

    Returns (checker_code, language)；无对应 checker 文件返回 (None, "python")。
    """
    p = Path(__file__).resolve().parent / "checkers" / f"{task}_checker.py"
    if not p.exists():
        return None, "python"
    return p.read_text(encoding="utf-8"), "python"


def ingest_special_one(batch: CFBatch, contest: str, index: str, title: str,
                       typ: str, diff: str) -> str | None:
    """SPJ 题入库：用 checker 验证参考解（而非样例文本比对）。

    - 题面样例的期望输出只是"其中一个合法解"，不能作唯一比对。
    - 流程：抓题面 → 找 C++ AC 提交 → 跑该代码 → 用 checker 判定输出是否
      满足题目谓词 → 取该合法输出作为测试用例期望（exact 回放时也通过）。
    - 入库：judge=special + checker_code，test_cases.output = checker 验证过
      的参考解输出。
    """
    from rex.executor.judge import run_checker

    task = _task(contest, index)
    if task in existing_source_ids():
        print(f"[skip] {task}: 已入库")
        return None
    checker_code, ck_lang = _load_special_checker(task)
    if not checker_code:
        print(f"[skip] {task}: 缺 checker（scripts/checkers/{task}_checker.py）")
        return None
    statement, samples = batch.fetch_statement_and_samples(contest, index)
    if not samples:
        print(f"[skip] {task}: 题面未提取到样例")
        return None
    print(f"[special-ac] {task}: {len(samples)} 组样例，找 C++ AC 并用 checker 验证…")
    href, code, valid_out = _find_special_ac(batch, contest, index, samples,
                                             checker_code, ck_lang)
    # 测试用例：题面样例输入 + 该参考解 checker 验证过的合法输出
    tcs = []
    for i, (inp, _exp) in enumerate(samples):
        out_for = valid_out if len(samples) == 1 else None
        # 多样例 SPJ 极少见；单样例时用参考解输出，多样例时仍存官方样例输出
        tcs.append(TestCase(input=inp, output=out_for if out_for is not None else _exp,
                            hidden=False))
    q = QuestionItem(
        id=next_id(), scene="algorithm", title=title, prompt=statement,
        difficulty=Difficulty(diff), source="Codeforces-自建",
        source_id=task,
        layer_basis=f"官方 rating 题，{typ} → {diff}（rating 分层；SPJ 构造题）",
        standard_answer="", reference_solution=code, test_cases=tcs,
        judge="special", checker_code=checker_code, checker_language=ck_lang,
        metadata={"contest": contest, "problem": task, "type": typ,
                  "submission_href": href, "round": "cf-round1", "special": True},
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    print(f"written {q.id} ({task}) [special/{diff}] code={len(code)} chars, "
          f"{len(tcs)} 样例用例 (checker 验证过)")
    return q.id


def _find_special_ac(batch: CFBatch, contest: str, index: str,
                     samples: list[tuple[str, str]], checker_code: str,
                     ck_lang: str, max_try: int = 6):
    """按时间正序试 C++ AC，用 checker 判定输出满足题目谓词。

    Returns (href, code, validated_output)。validated_output 是被 checker
    接受的那次运行的 stdout（作为该测试用例的合法期望，仅单样例时使用）。
    """
    from rex.executor.judge import run_checker
    from rex.executor.sandbox import run_code

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
        # 用第一条样例输入跑参考解，再让 checker 判定输出合法
        inp = samples[0][0]
        res = run_code(code, stdin=inp, timeout=20, language="cpp")
        if res.error or res.timed_out:
            print(f"  [skip] {href}: 运行失败 {(res.error or 'timeout')[:80]}")
            continue
        ok, msg = run_checker(checker_code, ck_lang, inp, res.stdout)
        if ok:
            print(f"  [ac] {href}: checker 验证通过")
            return href, code, res.stdout.strip()
        print(f"  [skip] {href}: checker 拒绝 {msg[:100]}")
    raise RuntimeError(f"{contest}{index}: 前 {max_try} 条 C++ AC 未通过 checker")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--retry", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 题（调试用）")
    ap.add_argument("--auto", action="store_true",
                    help="从 CF problemset 缓存自动选题（未收录、按分层缺口+类型均匀）")
    ap.add_argument("--round-size", type=int, default=17)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--headed", action="store_true",
                    help="交互模式：真实 Edge 窗口，遇 Cloudflare 验证框时人工点击后同会话继续")
    ap.add_argument("--human-wait", type=int, default=240,
                    help="交互模式下等待人工验证的最长秒数（默认 240）")
    ap.add_argument("--probe", action="store_true",
                    help="单次探测：打开 codeforces.com 1 页验证 cookie 放行后即退出（不抓题）")
    ap.add_argument("--special", action="store_true",
                    help="SPJ 入库模式：配合 --only <source_id>，用 scripts/checkers/"
                         "{task}_checker.py 验证参考解（用于多解/构造题）")
    ap.add_argument("--ua", default=None, help="覆盖 cookie 绑定的 UA（cf_clearance 绑定 UA）")
    args = ap.parse_args()
    cookies, cookie_ua = _load_cookies()
    ua = args.ua or cookie_ua
    if not cookies and not args.headed:
        print("[fatal] 未找到可用的 CF cookie：请把浏览器导出的 cookie 放入 "
              "data/cases/cf_cookies.json（格式见 README/脚本注释），或运行 "
              "scripts/cf_cookie_session.py 人工验证一次，或设置 CF_JSESSIONID")
        sys.exit(2)
    batch = CFBatch(cookies, ua=ua, headless=not args.headed,
                    human_wait=args.human_wait)
    if args.probe:
        try:
            print(f"[probe] UA={ua[:70]}…")
            print(f"[probe] cookie {len(cookies)} 个："
                  + ", ".join(sorted(c["name"] for c in cookies)))
            batch._goto_ready("https://codeforces.com/")
            title = batch.pg.title()
            print(f"[probe] 首页放行 ✓ title={title}")
            print("cookie 有效，可开始抓取。")
        except CFChallengeError as e:
            print(f"[probe] 仍被 Cloudflare 拦截: {e}")
            sys.exit(3)
        finally:
            batch.close()
        return
    if args.only:
        plan = plan_from_ids(args.only)
    elif args.auto:
        plan = auto_plan(args.round_size, args.seed)
    else:
        plan = PLAN
    plan = plan[:args.limit] if args.limit else plan
    only = set(args.only) if args.only else None
    done = 0
    failed: list[str] = []
    blocked = False
    try:
        for contest, index, title, typ, diff in plan:
            task = _task(contest, index)
            if only and task not in only:
                continue
            # SPJ 模式：多解/构造题走 checker 验证入库
            if args.special:
                try:
                    if ingest_special_one(batch, contest, index, title, typ, diff):
                        done += 1
                    ok = True
                except CFChallengeError as e:
                    print(f"[blocked] {task}: {e}")
                    blocked = True
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[error] {task}: {e}")
                    ok = False
                if not ok:
                    failed.append(task)
                continue
            ok = False
            for attempt in range(args.retry + 1):
                try:
                    if ingest_one(batch, contest, index, title, typ, diff):
                        done += 1
                    ok = True
                    break
                except CFChallengeError as e:
                    # 会话被 Cloudflare 拦截：重试无意义，整批止损
                    print(f"[blocked] {task}: {e}")
                    blocked = True
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[error] {task} (attempt {attempt + 1}/{args.retry + 1}): {e}")
                    if attempt < args.retry:
                        time.sleep(8)
            if blocked:
                break
            if not ok:
                failed.append(task)
    finally:
        batch.close()
    print(f"\n完成 {done}/{len(plan)} 题 → {OUT}")
    if failed:
        print(f"失败 {len(failed)} 题：{failed}")
    if blocked:
        print("[提示] 遭遇 Cloudflare 拦截。可选：")
        print("  - 运行 scripts/cf_cookie_session.py 人工验证一次（生成含 cf_clearance 的 cookie）")
        print("  - 或用 --headed 交互模式：同一 Edge 会话人工过验证后直接继续抓取")
        print("  - 若 IP 已被 CF 临时屏蔽，请更换网络出口或等待冷却后重试")


if __name__ == "__main__":
    main()
