"""Static checks on solver-produced code: complexity declaration vs code,
boundary-condition hints. Heuristic diagnostics — feed the verifier and the
report, never a blocking verdict on their own.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from rex.models import Answer, QuestionItem

_COMPLEXITY_RE = re.compile(r"O\s*\(\s*(1|log\s*n|n\s*log\s*n|n\s*\^?\s*\{?2\}?|n\^?2|n\s*3?)\s*\)", re.IGNORECASE)

# 声明复杂度档次: O(1)=0, O(log n)=1, O(n)=2, O(n log n)=3, O(n^2)=4, O(n^3)=5
_DECL_ORDER: dict[str, int] = {
    "1": 0, "logn": 1, "nlogn": 3, "n": 2, "n2": 4, "n3": 5,
}


@dataclass
class StaticDiagnostic:
    category: str                      # "complexity" | "boundary" | "loop" | "recursion"
    severity: str                      # "warn" | "info"
    detail: str
    code_ref: str = ""                 # 引用的代码片段/行


@dataclass
class StaticCheckResult:
    declared: str | None               # 声明复杂度原文
    estimated: str | None              # 启发式估计
    mismatch: bool
    diagnostics: list[StaticDiagnostic] = field(default_factory=list)
    loop_risk: bool = False            # 死循环风险（while 无条件/条件不更新/无 break）
    recursion_risk: bool = False       # 递归无终止风险（递归调用但缺少终止分支）


def _extract_declared(answer: Answer) -> str | None:
    for s in answer.steps:
        if s.kind == "complexity":
            m = _COMPLEXITY_RE.search(s.content)
            if m:
                return m.group(0)
    return None


def _estimate_complexity(code: str) -> str | None:
    """Heuristic: loop nesting depth + recursion + inner linear scans."""
    if not code:
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "unknown(syntax)"
    max_depth = 0
    recursion = False

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal max_depth, recursion
        if isinstance(node, (ast.For, ast.While)):
            depth += 1
            max_depth = max(max_depth, depth)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "input" and depth > 0:
                pass
        for child in ast.iter_child_nodes(node):
            walk(child, depth)

    walk(tree, 0)
    if max_depth >= 2:
        return f"O(n^{max_depth})"
    if max_depth == 1:
        return "O(n)"
    if recursion:
        return "O(recursive)"
    return "O(1)"


def _loop_and_recursion_diagnostics(code: str) -> tuple[list[StaticDiagnostic], bool, bool]:
    """Detect infinite-loop / non-terminating-recursion risks (heuristic).

    Loop checks:
      - `while True:` without a `break` anywhere inside → likely infinite.
      - `while <cond>:` where the loop body never mutates any variable that
        appears in the condition → likely no progress (heuristic).
    Recursion checks:
      - any recursive call (a function calling itself by name) without a base
        case (`if ...: return` before the recursion in the same body) → risk.
    Both are *hints* for the verifier, never blocking verdicts on their own.
    """
    diags: list[StaticDiagnostic] = []
    loop_risk = False
    recursion_risk = False
    if not code:
        return diags, loop_risk, recursion_risk
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return diags, loop_risk, recursion_risk

    for node in ast.walk(tree):
        # --- while loops ---
        if isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
                if not has_break:
                    loop_risk = True
                    diags.append(StaticDiagnostic(
                        "loop", "warn",
                        "检测到 `while True` 且循环体内无 break，存在死循环风险",
                        code_ref=_snippet(node),
                    ))
            else:
                # 条件中出现的变量名集合
                cond_vars = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                # 循环体内可能改变条件变量的途径：
                #   (a) 直接赋值 / 复合赋值（i = i+1, i += 1）
                #   (b) 条件变量作为容器/迭代对象被方法调用修改（dq.popleft()、lst.pop()、
                #       it=next(it) 之类）——`while dq:` 常见模式，若忽略会造成大量误报
                assigned = set()        # (a) 直接赋值
                mutated = set()         # (b) 方法/函数调用可能修改
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.For, ast.While)):
                        continue  # 嵌套循环内部赋值不影响本循环条件
                    for n in ast.walk(child):
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                            continue
                        if isinstance(n, ast.Assign):
                            for t in n.targets:
                                if isinstance(t, ast.Name):
                                    assigned.add(t.id)
                        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                            assigned.add(n.target.id)
                        elif isinstance(n, ast.Call):
                            f = n.func
                            # obj.method(...) → obj 可能被修改（dq.popleft / lst.pop / set.add）
                            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                                mutated.add(f.value.id)
                            # func 本身是条件变量且返回新值被用作迭代推进不在此列；
                            # 保守起见不把 Name 调用当修改。
                if cond_vars and not (cond_vars & assigned) and not (cond_vars & mutated):
                    loop_risk = True
                    diags.append(StaticDiagnostic(
                        "loop", "info",
                        "while 条件依赖的变量在循环体内未被赋值或通过方法调用更新，"
                        "可能无法终止（启发式）",
                        code_ref=_snippet(node),
                    ))

        # --- recursion: function calls itself, no non-recursive return path ---
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            has_non_recursive_return = False
            recursive_call = False
            for n in ast.walk(node):
                if isinstance(n, ast.Return):
                    # return 的值若是本函数递归调用，不算终止路径；否则视为 base case
                    is_recursive_return = False
                    val = n.value
                    if val is not None:
                        for call in ast.walk(val):
                            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                                    and call.func.id == name:
                                is_recursive_return = True
                                break
                    if not is_recursive_return:
                        has_non_recursive_return = True
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name:
                    recursive_call = True
            if recursive_call and not has_non_recursive_return:
                recursion_risk = True
                diags.append(StaticDiagnostic(
                    "recursion", "warn",
                    f"函数 `{name}` 存在递归调用，但所有 return 都是递归路径，"
                    "未发现非递归的终止（base case）分支，递归可能无终止条件",
                    code_ref=_snippet(node),
                ))

    return diags, loop_risk, recursion_risk


def _snippet(node: ast.AST, max_len: int = 120) -> str:
    """Best-effort source snippet for the AST node (via ast.unparse)."""
    try:
        s = ast.unparse(node).replace("\n", " ").strip()
    except Exception:  # noqa: BLE001 - unparse 偶发失败，降级为空串
        return ""
    return s[:max_len]


def _boundary_diagnostics(question: QuestionItem, answer: Answer) -> list[StaticDiagnostic]:
    """Heuristic boundary checks based on problem keywords."""
    code = answer.code or ""
    diags: list[StaticDiagnostic] = []
    prompt = question.prompt.lower()
    if not code:
        return diags

    def _has(patterns: list[str]) -> bool:
        return any(p in code.lower() for p in patterns)

    if "empty" in prompt or "空" in prompt or "非空" in prompt:
        if not _has(["if not ", "len(", "== 0", "if n == 0", "if not data", "if not s"]):
            diags.append(StaticDiagnostic(
                "boundary", "warn",
                "题目涉及空输入边界，代码中未发现显式空/长度为 0 的处理分支",
            ))
    if "negative" in prompt or "负数" in prompt:
        # 信号需指向"真正的负数处理"：abs()、与 0 的比较、负数字面量/负无穷。
        # 注意不能把 max()/min() 当作信号——`return max(a)` 并不处理负数，
        # 只是复用内建函数（旧规则因此漏检）。
        neg_patterns = re.compile(
            r"abs\s*\(|< 0|<= 0|>= 0|> 0|float\(['\"]-inf|-\d[\d_]*(\s*[eE][+-]?\d+)?|is_negative|negative\b",
            re.IGNORECASE,
        )
        if not neg_patterns.search(code):
            diags.append(StaticDiagnostic(
                "boundary", "warn",
                "题目涉及负数，代码中未发现显式负数处理（abs/与0比较/负字面量）",
            ))
    if any(k in prompt for k in ("long", "大数", "溢出", "int 范围", "10^9", "1e9")):
        if not _has(["int64", "long", "float(", "Decimal", "mod"]):
            diags.append(StaticDiagnostic(
                "boundary", "info",
                "题目可能涉及大数/溢出，代码未使用宽类型或取模（仅供参考）",
            ))
    if not diags:
        diags.append(StaticDiagnostic("boundary", "info", "未发现明显边界遗漏（启发式）"))
    return diags


def _is_cpp(code: str) -> bool:
    head = (code or "")[:4000]
    return "#include" in head or "using namespace" in head


def check_static(question: QuestionItem, answer: Answer) -> StaticCheckResult:
    """Run static checks; language-aware (Python via ast, C++ via token heuristics).

    C++ 路径（task 2 补盲）：CF/ABC 主场景代码是 C++，ast 无法解析 → 此前
    complexity/loop/recursion 检测全部失效（estimated=unknown(syntax)）。
    现按 detect_language 分发到 C++ token 级分析器。
    """
    declared = _extract_declared(answer)
    code = answer.code or ""
    diags: list[StaticDiagnostic] = []
    if _is_cpp(code):
        estimated = _cpp_complexity_estimate(code)
        loop_diags = _cpp_infinite_loop_diags(code)
        recursion_diags = _cpp_recursion_diags(code)
        diags.extend(loop_diags)
        diags.extend(recursion_diags)
        loop_risk = any(d.category == "loop" and d.severity == "warn" for d in loop_diags)
        recursion_risk = bool(recursion_diags)
    else:
        estimated = _estimate_complexity(code)
        loop_diags, loop_risk, recursion_risk = _loop_and_recursion_diagnostics(code)
        diags.extend(loop_diags)
    mismatch = False
    if declared and estimated:
        est = _normalize(estimated)
        dec = _normalize(declared)
        # 注意：dec=0 表示 O(1)（falsy），不能用 `est and dec` 判空，须用 is not None
        if est is not None and dec is not None and est > dec:
            mismatch = True
            diags.append(StaticDiagnostic(
                "complexity", "warn",
                f"声明复杂度 {declared} 但代码启发式估计 {estimated}，可能复杂度不达标",
            ))
    diags.extend(_boundary_diagnostics(question, answer))
    return StaticCheckResult(
        declared=declared, estimated=estimated, mismatch=mismatch,
        diagnostics=diags, loop_risk=loop_risk, recursion_risk=recursion_risk,
    )


def static_result_to_dict(result: StaticCheckResult) -> dict:
    """Serialize StaticCheckResult to a plain dict (for EvalRecord.metadata)."""
    return {
        "declared": result.declared,
        "estimated": result.estimated,
        "mismatch": result.mismatch,
        "loop_risk": result.loop_risk,
        "recursion_risk": result.recursion_risk,
        "diagnostics": [
            {"category": d.category, "severity": d.severity,
             "detail": d.detail, "code_ref": d.code_ref}
            for d in result.diagnostics
        ],
    }


def static_evidence_block(result: StaticCheckResult) -> str | None:
    """Render static-check findings as verifier evidence text (or None).

    只在有实质告警时返回非空，供 verifier 作为"规则校验证据"参考。
    """
    warns = [d for d in result.diagnostics if d.severity == "warn"]
    if not warns and not result.mismatch and not result.loop_risk and not result.recursion_risk:
        return None
    lines = ["【规则校验证据（静态检查，仅供参考，请独立判定）】"]
    for d in warns:
        lines.append(f"- {d.detail}")
    return "\n".join(lines)


def _normalize(expr: str) -> int | None:
    e = expr.strip().lower().replace(" ", "")
    e = e.replace("o(", "").replace(")", "")
    if e.startswith("n^"):
        e = "n" + e[2:]
    mapping = {
        "1": 0, "logn": 1, "log(n)": 1, "log2n": 1,
        "n": 2, "n": 2, "nlogn": 3, "nlog(n)": 3, "nlog2n": 3,
        "n2": 4, "n^2": 4, "n{2}": 4, "n3": 5, "n^3": 5,
    }
    return mapping.get(e)


# ---------------------------------------------------------------------------
# C++ 静态分析（轻量启发式，不追求完整 C++ 解析）
#
# Python 路径用 ast；C++ 没有内置 parser。这里用 token 级启发式：
#   1. 剔除注释/字符串字面量；
#   2. 配对 `{ }` / `( )`，识别 for/while 块及其嵌套深度 → 复杂度粗估；
#   3. 常量真 while / for(;;) 且块内无 break/return/goto → 死循环风险；
#   4. 递归函数无"非递归 return"的终止分支 → 递归无终止风险。
# 与 Python 版一致的定位：启发式诊断，仅供 verifier 参考，绝不阻断 verdict。
# ---------------------------------------------------------------------------

_CPP_KEYWORDS = {
    "for", "while", "do", "if", "else", "switch", "case", "default",
    "return", "break", "continue", "goto", "new", "delete", "using",
    "namespace", "typedef", "class", "struct", "union", "enum",
    "const", "static", "constexpr", "inline", "template", "typename",
    "int", "long", "short", "char", "bool", "float", "double", "void",
    "auto", "signed", "unsigned", "size_t", "true", "false", "nullptr",
    "main", "cin", "cout", "endl",
}

# 注释 / 字符串 / 字符字面量（替换为等长空白，保留位置信息）
_CPP_SKIP_RE = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
    re.DOTALL,
)
_CPP_IDENT_START = re.compile(r"[A-Za-z_]")
_CPP_IDENT = re.compile(r"[A-Za-z0-9_]")


def _cpp_tokens(code: str) -> list[tuple[str, int, int]]:
    """Tokenize C++ source (comments/strings removed): list of (value, start, end)."""
    if not code:
        return []
    cleaned = _CPP_SKIP_RE.sub(lambda m: " " * (m.end() - m.start()), code)
    toks: list[tuple[str, int, int]] = []
    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch.isspace():
            i += 1
            continue
        start = i
        if _CPP_IDENT_START.match(ch):
            i += 1
            while i < n and _CPP_IDENT.match(cleaned[i]):
                i += 1
            toks.append((cleaned[start:i], start, i))
            continue
        if ch.isdigit():
            i += 1
            while i < n and (cleaned[i].isalnum() or cleaned[i] in "xX.+-eE'"):
                i += 1
            toks.append((cleaned[start:i], start, i))
            continue
        toks.append((ch, start, i + 1))
        i += 1
    return toks


def _cpp_match_paren(tokens: list[tuple[str, int, int]]) -> dict[int, int]:
    """Map every '(' token index -> matching ')' token index."""
    stack: list[int] = []
    match: dict[int, int] = {}
    for idx, (val, _, _) in enumerate(tokens):
        if val == "(":
            stack.append(idx)
        elif val == ")":
            if stack:
                match[stack.pop()] = idx
    return match


def _cpp_block_children(tokens: list[tuple[str, int, int]]) -> tuple[dict[int, list[int]], list[int]]:
    """Build a block tree over '{...}' pairs."""
    stack: list[int] = []
    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for idx, (val, _, _) in enumerate(tokens):
        if val == "{":
            if stack:
                children.setdefault(stack[-1], []).append(idx)
            else:
                roots.append(idx)
            stack.append(idx)
        elif val == "}":
            if stack:
                stack.pop()
    return children, roots


def _cpp_is_loop_block(tokens, paren_close: dict[int, int], open_idx: int) -> bool:
    """A '{' opens a for/while body iff the token before it is ')' of a for/while head."""
    if open_idx <= 0 or tokens[open_idx][0] != "{":
        return False
    prev = tokens[open_idx - 1][0]
    if prev != ")":
        return False
    # find matching '('
    close_idx = open_idx - 1
    for op, cl in paren_close.items():
        if cl == close_idx:
            if op > 0 and tokens[op - 1][0] in ("for", "while"):
                return True
            return False
    return False


def _cpp_analyze_loops(code: str) -> tuple[int, bool]:
    """Return (max_loop_depth, headless_loop).

    - max_loop_depth: 最大循环嵌套深度（块循环 + 无块循环均计入）
    - headless_loop: 存在 for/while 头后不接 `{` 的循环
    """
    toks = _cpp_tokens(code)
    if not toks:
        return 0, False
    paren = _cpp_match_paren(toks)
    children, roots = _cpp_block_children(toks)
    values = [t[0] for t in toks]

    # 1) collect block-loops with their depth
    loop_blocks: list[tuple[int, int, int]] = []  # (open_idx, close_idx, depth)

    def _block_close(open_idx: int) -> int:
        bal = 1
        j = open_idx + 1
        while j < len(toks) and bal:
            if values[j] == "{":
                bal += 1
            elif values[j] == "}":
                bal -= 1
            j += 1
        return j - 1  # index of matching '}'

    def _walk(open_idx: int, depth: int) -> None:
        is_loop = _cpp_is_loop_block(toks, paren, open_idx)
        d = depth + 1 if is_loop else depth
        if is_loop:
            loop_blocks.append((open_idx, _block_close(open_idx), d))
        for child in children.get(open_idx, []):
            _walk(child, d)

    for r in roots:
        _walk(r, 0)

    max_depth = max((d for _, _, d in loop_blocks), default=0)

    # 2) headless loops (for/while body without '{'): find the block-loop that
    #    contains their head '(' and count as depth+1; otherwise depth >= 1.
    headless = False
    for op, cl in paren.items():
        if op <= 0 or values[op - 1] not in ("for", "while"):
            continue
        if cl + 1 < len(toks) and values[cl + 1] == "{":
            continue  # already a block-loop
        headless = True
        d = 1
        for (bo, bc, bd) in loop_blocks:
            if bo < op < bc:
                d = max(d, bd + 1)
        max_depth = max(max_depth, d)
    return max_depth, headless


def _cpp_infinite_loop_diags(code: str) -> list[StaticDiagnostic]:
    """Detect `while(true)` / `for(;;)` bodies lacking break/return/goto."""
    diags: list[StaticDiagnostic] = []
    toks = _cpp_tokens(code)
    if not toks:
        return diags
    values = [t[0] for t in toks]
    paren = _cpp_match_paren(toks)

    def _has_exit(start: int, end: int) -> bool:
        return any(values[j] in ("break", "return", "goto", "continue", "exit") for j in range(start, end))

    for op, cl in paren.items():
        if op <= 0:
            continue
        kw = values[op - 1]
        if kw not in ("for", "while"):
            continue
        # constant-true check
        inner = [values[j] for j in range(op + 1, cl)]
        const_true = False
        if kw == "while":
            body = [x for x in inner if x not in ("(", ")")]
            const_true = all(x in ("true", "1") for x in body) if body else False
        else:  # for(;;)
            no_semi = [x for x in inner if x != ";"]
            const_true = not no_semi
        if not const_true:
            continue
        snippet = code[toks[op][1]:min(len(code), toks[op][1] + 60)] if code else ""
        # body range: next '{' after cl -> matching close
        body_start = cl + 1
        if body_start >= len(toks) or values[body_start] != "{":
            # single-statement infinite loop: for(;;); or while(true) stmt;
            stmt_end = body_start
            while stmt_end < len(toks) and values[stmt_end] != ";":
                stmt_end += 1
            if not _has_exit(body_start, min(stmt_end + 1, len(toks))):
                diags.append(StaticDiagnostic(
                    "loop", "warn",
                    f"检测到 `{kw}(...)` 为恒真循环且循环体无 break/return/goto，存在死循环风险",
                    code_ref=snippet,
                ))
            continue
        bal = 1
        j = body_start + 1
        while j < len(toks) and bal:
            if values[j] == "{":
                bal += 1
            elif values[j] == "}":
                bal -= 1
            j += 1
        if not _has_exit(body_start, min(j, len(toks))):
            diags.append(StaticDiagnostic(
                "loop", "warn",
                f"检测到 `{kw}(...)` 为恒真循环且循环体内无 break/return/goto，存在死循环风险",
                code_ref=snippet,
            ))
    return diags


def _cpp_recursion_diags(code: str) -> list[StaticDiagnostic]:
    """Detect recursion without a non-recursive return (no base case)."""
    diags: list[StaticDiagnostic] = []
    toks = _cpp_tokens(code)
    if not toks:
        return diags
    values = [t[0] for t in toks]
    paren = _cpp_match_paren(toks)
    # find function definitions: name '(' ... ')' '{'
    func_bodies: dict[str, tuple[int, int]] = {}  # name -> (body_open, body_close)
    for idx in range(len(toks) - 1):
        val = values[idx]
        if not _CPP_IDENT_START.match(val or ""):
            continue
        if val in _CPP_KEYWORDS:
            continue
        if idx + 1 < len(toks) and values[idx + 1] != "(":
            continue
        if idx + 1 not in paren:
            continue
        cl = paren[idx + 1]
        if cl + 1 >= len(toks) or values[cl + 1] != "{":
            continue
        # distinguish call vs definition: a definition's '{' is the body.
        # we still need to ensure the identifier isn't a return type/name confusion;
        # acceptable heuristic for contest C++.
        body_start = cl + 1
        bal = 1
        j = body_start + 1
        while j < len(toks) and bal:
            if values[j] == "{":
                bal += 1
            elif values[j] == "}":
                bal -= 1
            j += 1
        func_bodies[val] = (body_start, min(j, len(toks)))

    for name, (bs, be) in func_bodies.items():
        # recursive call inside body: name '('
        recursive = False
        has_base_return = False
        for idx in range(bs + 1, be):
            if values[idx] == "return":
                # check the return value for a direct recursive call up to ';'
                k = idx + 1
                rec_ret = False
                while k < be and values[k] != ";":
                    if values[k] == name and k + 1 < be and values[k + 1] == "(":
                        rec_ret = True
                        break
                    k += 1
                if not rec_ret:
                    has_base_return = True
            elif values[idx] == name and idx + 1 < be and values[idx + 1] == "(":
                recursive = True
        if recursive and not has_base_return:
            diags.append(StaticDiagnostic(
                "recursion", "warn",
                f"函数 `{name}` 存在递归调用，但未发现非递归 return 的终止（base case）分支，"
                "递归可能无终止条件",
                code_ref=(code[toks[bs][1]:] or "")[:120],
            ))
    return diags


def _cpp_complexity_estimate(code: str) -> str | None:
    """Estimate C++ complexity from loop nesting depth (heuristic)."""
    max_depth, headless = _cpp_analyze_loops(code)
    if max_depth >= 3:
        return f"O(n^{max_depth})"
    if max_depth == 2:
        return "O(n^2)"
    if max_depth == 1 or headless:
        return "O(n)"
    return "O(1)"
