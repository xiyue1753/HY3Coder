"""AtCoder ABC 题通用入库脚本（自建算法评测集）。

自动抓取：题目页（英文题面 lang-en） + AC 解（submission 源码），并解析题面样例。
额外测试用例由调用方传入（人工设计，非代码生成）。

用法（示例）：
    python scripts/ingest_abc.py --contest abc328 --problem b --submission 47452966 \
        --title "11/11" --source_id abc328_b --difficulty medium \
        --extra '["N=1,D=1|1", "N=100 all 100|36"]'
    # --extra 格式：JSON 数组，每项 "输入(用|换行)|期望输出"

可选自动找 AC 提交（需登录 cookie）：
    python scripts/ingest_abc.py --contest abc098 --problem c --auto-ac \
        --title "Attention" --source_id abc098_c --difficulty medium --extra '...'
    # 从提交列表页按 AC+C++ 筛选最新一条，自动填 submission id。

登录隔离：cookie 经环境变量 ATCODER_REVEL_SESSION 传入（放项目根 .env，
.gitignore 已排除 .env），不落盘、不入 git。请求间有固定间隔限速，避免封号。
"""
from __future__ import annotations

import argparse
import html as h
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Windows 控制台 GBK 打印编译错误等含非 ASCII 字符时可能崩溃 → 强制 UTF-8 + 替换
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # 非流式 stdout（如测试环境）跳过

# 加载项目根 .env（含 ATCODER_REVEL_SESSION cookie，gitignore 排除，不入 git）
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rex.models import QuestionItem, TestCase, Difficulty, Judge  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
           "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}
# 请求间隔（秒）：避免高频请求触发风控/封号
REQUEST_DELAY = 2.0


def _cookies() -> dict[str, str]:
    """从环境变量读 AtCoder 登录 cookie（REVEL_SESSION），未设置返回空 dict。"""
    session = os.environ.get("ATCODER_REVEL_SESSION", "").strip()
    return {"REVEL_SESSION": session} if session else {}


def _get(url: str, timeout: int = 15, **kw) -> requests.Response:
    """统一 GET：带 cookie（若设置）+ 固定间隔限速。"""
    time.sleep(REQUEST_DELAY)
    return requests.get(url, timeout=timeout, headers=HEADERS, cookies=_cookies(), **kw)


def fetch_problem(contest: str, problem: str) -> str:
    """抓题目页，提取英文题面（lang-en），转成 markdown 文本。"""
    url = f"https://atcoder.jp/contests/{contest}/tasks/{contest}_{problem}"
    r = _get(url)
    m = re.search(r'<span class="lang-en">(.*?)</span>', r.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"problem page {url}: lang-en not found (status {r.status_code})")
    return _html_to_text(m.group(1))


def _html_to_text(html_block: str) -> str:
    """把题面 HTML 转为 markdown 文本（保留标题/代码块/换行）。

    AtCoder 用 <var>...</var> 包裹数学公式（裸 LaTeX，无 $ 包裹）。
    这里先把 <var> 内容包上 $...$，使下游 KaTeX 能正确渲染内联公式；
    若不加 $，裸 LaTeX（如 \\leq、\\ldots）会原样显示成乱码。
    """
    # 1) var 数学标记 → $...$（在通用去标签前处理，避免内容被剥掉）
    s = re.sub(r'<var>(.*?)</var>', r'$\1$', html_block)
    # 2) 标题（h3 → ###）与代码块（pre → ```）
    s = re.sub(r'<h3[^>]*>', '\n### ', s)
    s = re.sub(r'<pre[^>]*>', '\n```\n', s)
    s = re.sub(r'</pre>', '\n```\n', s)
    # 3) 其余段落/块级标签补换行，避免"StatementYou"粘连
    s = re.sub(r'<(p|div|li|section|ul|ol)[^>]*>', '\n', s)
    s = re.sub(r'</(p|div|li|section|ul|ol)>', '\n', s)
    # 4) 去掉其余标签（var 已转换，这里只处理残余）
    s = re.sub(r'<[^>]+>', '', s)
    s = h.unescape(s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def iter_ac_submissions(contest: str, task: str, page: int = 1) -> list[int]:
    """从提交列表页 HTML 拿一页该题的 AC 提交 id（时间倒序）。

    注意：必须用提交列表页（服务端渲染，f.Task 筛选生效），
    不要用 status/json API（实测其 f.Task/page 参数均失效，返回固定 20 条）。
    每页 20 条；调用方仍用题面样例沙盒验证最终是否匹配。
    """
    url = (
        f"https://atcoder.jp/contests/{contest}/submissions"
        f"?f.Task={task}&f.Status=AC&f.User=&page={page}"
    )
    r = _get(url)
    if r.status_code != 200:
        raise RuntimeError(f"submissions page failed: status={r.status_code}")
    ids = re.findall(rf"/contests/{contest}/submissions/(\d+)", r.text)
    # 去重保序，取本页前 20 条
    seen: set[str] = set()
    out: list[int] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(int(x))
        if len(out) >= 20:
            break
    return out


def fetch_ac_code(contest: str, submission_id: int) -> str:
    url = f"https://atcoder.jp/contests/{contest}/submissions/{submission_id}"
    r = _get(url)
    m = re.search(r'<pre id="submission-code"[^>]*>(.*?)</pre>', r.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"submission {submission_id}: code not found (status {r.status_code})")
    return h.unescape(m.group(1))


_SAMPLE_BLOCK = re.compile(
    r"### Sample (Input|Output) (\d+)\s*\n```\s*\n(.*?)\n```", re.DOTALL
)


def extract_samples(prompt: str) -> list[tuple[str, str]]:
    """从题面 markdown 提取 (input, output) 样例对。

    依赖题面格式：`### Sample Input N` 与 `### Sample Output N` 成对出现。
    统一把 \r\n 归一到 \n（题面 HTML 可能残留 CRLF，会导致样例比对失败）。

    修复：空 output 块（如 abc389_c 的 Sample Output 2 为空）后若紧接解释文字，
    原正则的非贪婪 ``(.*?)`` 会一直吞到下一个 ``` 代码块（Sample Output 3），
    导致错位。这里改用**按编号配对**，每个块内容截断到下一个 `### Sample` 标题之前，
    杜绝跨块吞内容；空的 input/output 块直接丢弃（空样例无验证价值）。
    """
    # 先把内容按下一个 Sample 标题截断，防止 (.*?) 跨块吞掉解释文字
    parts = re.split(r"(?=### Sample )", prompt)
    by_no: dict[int, dict[str, str]] = {}
    for part in parts:
        m = re.match(r"### Sample (Input|Output) (\d+)\s*\n```\s*\n(.*?)\n```", part, re.DOTALL)
        if not m:
            continue
        kind, no, content = m.group(1), int(m.group(2)), m.group(3)
        by_no.setdefault(no, {})[kind] = content
    pairs: list[tuple[str, str]] = []
    for no in sorted(by_no):
        d = by_no[no]
        inp = d.get("Input", "").strip().replace("\r\n", "\n")
        out = d.get("Output", "").strip().replace("\r\n", "\n")
        if inp and out:
            pairs.append((inp, out))
    return pairs


def _outputs_match(got: str, expected: str, float_tol: float = 1e-5) -> bool:
    """比较两段输出是否一致。

    - 普通文本：逐行精确比较（去尾部空白）。
    - 浮点题：若某行两侧都能解析为浮点数，则按相对/绝对误差 <= float_tol 判定
      （AtCoder 对浮点输出通常接受绝对或相对误差 1e-5，不同 AC 提交打印精度不同）。
    """
    got_lines = [ln.strip() for ln in got.replace("\r\n", "\n").split("\n")]
    exp_lines = [ln.strip() for ln in expected.replace("\r\n", "\n").split("\n")]
    if len(got_lines) != len(exp_lines):
        return False
    for g, e in zip(got_lines, exp_lines):
        if g == e:
            continue
        # 尝试浮点容差比较
        try:
            fg, fe = float(g), float(e)
        except ValueError:
            return False
        if abs(fg - fe) <= float_tol * max(1.0, abs(fe), abs(fg)):
            continue
        return False
    return True


def verify_code_with_samples(
    code: str,
    samples: list[tuple[str, str]],
    checker_code: str | None = None,
    checker_language: str = "python",
) -> tuple[bool, str]:
    """用题面样例沙盒验证代码（C++）。全通过返回 (True, "")。

    checker_code 非空时按 SPJ 判定：不比对样例文本，而用 checker 验证
    代码输出是否满足题目谓词（多解构造题入库用，见 executor/judge.py）。
    """
    from rex.executor.sandbox import run_code

    if not samples:
        return False, "题面无样例，无法验证"
    for i, (inp, exp) in enumerate(samples):
        res = run_code(code, stdin=inp, timeout=20, language="cpp")
        if res.error or res.timed_out:
            return False, f"sample{i + 1} 运行失败: {res.error or 'timeout'}"
        got = res.stdout.strip()
        if checker_code:
            from rex.executor.judge import run_checker

            ok, msg = run_checker(checker_code, checker_language, inp, got)
            if not ok:
                return False, f"sample{i + 1} checker 拒绝: {msg}"
            continue
        if not _outputs_match(got, exp):
            return False, f"sample{i + 1} 输出不符: 期望={exp.strip()!r} 实际={got!r}"
    return True, ""


def find_ac_with_verification(
    contest: str,
    task: str,
    samples: list[tuple[str, str]],
    max_pages: int = 5,
    checker_code: str | None = None,
    checker_language: str = "python",
) -> tuple[int, str]:
    """翻页找一条通过题面样例的 AC 提交（代码+样例双重校验）。

    返回 (submission_id, verified_code)。每页 20 条，最多 max_pages 页。
    因 API 无法按题筛选，逐条抓取并用题面样例验证；通常 1~2 页内命中。
    checker_code 非空时按 SPJ 校验候选代码输出（多解构造题入库）。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    checked = 0
    for page in range(1, max_pages + 1):
        ids = iter_ac_submissions(contest, task, page)
        if not ids:
            break
        for sid in ids:
            code = fetch_ac_code(contest, sid)
            # 预筛：跳过显然不是"简洁 C++ 题解"的提交（Python/巨型模板/依赖 atcoder 库），
            # 避免为每条垃圾提交浪费一次编译（编译是大头耗时）。
            msg = _prescreen_cpp(code)
            if msg:
                print(f"  [skip] {task} submission {sid}: {msg}")
                continue
            ok, msg = verify_code_with_samples(code, samples, checker_code, checker_language)
            if ok:
                return sid, code
            print(f"  [skip] {task} submission {sid}: {msg}")
            checked += 1
    raise RuntimeError(
        f"{task}: {max_pages} 页内未找到通过样例的 AC 提交"
        "（题面样例可能无/API 受限，请人工提供 submission id）"
    )


def _prescreen_cpp(code: str) -> str | None:
    """快速预筛：返回 None 表示可能是简洁 C++ 题解，否则返回跳过原因。"""
    if not code.strip():
        return "空代码"
    # 长度：>15KB 基本是巨型模板，跳过（题解通常 <5KB）
    if len(code) > 15_000:
        return f"代码过长({len(code)} 字符，疑似模板)"
    # 必须含 C++ 头文件包含语句
    if "#include" not in code:
        return "非 C++（无 #include）"
    # 依赖 atcoder 库（本机无该库，编译必失败）→ 跳过省一次编译
    if "#include <atcoder/" in code:
        return "依赖 atcoder 库（本机无法编译）"
    # Python 特征（不可能出现在合法 C++ 中）
    if "print(" in code and "def " in code:
        return "疑似 Python 代码"
    return None
    raise RuntimeError(
        f"{task}: {max_pages} 页内未找到通过样例的 AC 提交"
        "（题面样例可能无/API 受限，请人工提供 submission id）"
    )


def load_cases(path: str) -> list[TestCase]:
    """从 JSON 文件读测试用例（人工设计，含题面样例与自建边界）。

    JSON 格式：[{"input": "...", "output": "...", "hidden": false}, ...]
    """
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TestCase.model_validate(c) for c in cases]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contest", required=True)
    ap.add_argument("--problem", required=True)
    ap.add_argument("--submission", type=int, default=None,
                    help="AC 提交 id（不传且带 --auto-ac 时自动找并样例验证）")
    ap.add_argument("--auto-ac", action="store_true",
                    help="自动找通过题面样例的 AC 提交（需 ATCODER_REVEL_SESSION）")
    ap.add_argument("--title", required=True)
    ap.add_argument("--source_id", required=True)
    ap.add_argument("--difficulty", choices=["basic", "medium", "hard"], required=True)
    ap.add_argument("--layer_basis", default="")
    ap.add_argument("--cases-file", required=True,
                    help="测试用例 JSON 文件（人工设计，含题面样例与自建边界）")
    ap.add_argument("--judge", choices=["exact", "special"], default="exact",
                    help="判题模式：exact=文本比对(默认)；special=多解构造题，跑 checker")
    ap.add_argument("--checker-file", default=None,
                    help="SPJ checker 源码文件路径（--judge special 必填）")
    ap.add_argument("--checker-language", choices=["python", "cpp"], default="python")
    args = ap.parse_args()

    if args.submission is None and not args.auto_ac:
        ap.error("必须提供 --submission 或 --auto-ac")

    special = args.judge == "special"
    checker_code = None
    if special:
        if not args.checker_file:
            ap.error("--judge special 需要 --checker-file")
        checker_code = Path(args.checker_file).read_text(encoding="utf-8")

    prompt = fetch_problem(args.contest, args.problem)
    task = f"{args.contest}_{args.problem}"
    if args.auto_ac:
        samples = extract_samples(prompt)
        if not samples:
            ap.error(f"{task}: 题面未提取到样例，无法自动验证，请改用 --submission")
        print(f"[auto-ac] {task}: 提取 {len(samples)} 组样例，翻页查找 AC 提交…")
        args.submission, code = find_ac_with_verification(
            args.contest, task, samples, checker_code=checker_code,
            checker_language=args.checker_language)
        mode = "checker(SPJ)" if special else "全部样例"
        print(f"[auto-ac] {task}: 采用 submission {args.submission}（通过{mode}）")
    else:
        code = fetch_ac_code(args.contest, args.submission)
    all_tc = load_cases(args.cases_file)

    # 复用 A 编号（检查已有最大号）
    existing = []
    if OUT.exists():
        existing = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    next_id = max((int(q["id"][1:]) for q in existing if q["id"].startswith("A")), default=1000) + 1

    q = QuestionItem(
        id=f"A{next_id}", scene="algorithm", title=args.title, prompt=prompt,
        difficulty=Difficulty(args.difficulty), source="AtCoder-自建",
        source_id=args.source_id, layer_basis=args.layer_basis,
        standard_answer="", reference_solution=code, test_cases=all_tc,
        metadata={"contest": args.contest, "problem": args.source_id,
                  "ac_submission_id": args.submission},
        judge=Judge.SPECIAL if special else Judge.EXACT,
        checker_code=checker_code,
        checker_language=args.checker_language,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(q.model_dump_json() + "\n")
    mode = "special/SPJ" if special else "exact"
    print(f"written {q.id} ({args.source_id}): {len(code)} chars code, "
          f"{len(all_tc)} test cases, judge={mode}")


if __name__ == "__main__":
    main()
