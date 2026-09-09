"""Static rule checks (executor/static_check.py) — paired rule test suite.

定位说明（架构分层）：
  规则校验审的是 **solver 产出的代码实现**（implement 步骤的产物）——复杂度
  声明一致性、死循环/递归无终止、边界启发式。它属于"实现/结果层审核"
  （对代码这个 artifact 的规则审查），与 verifier 对**推理链文本**的过程评估
  是两个正交维度。

  因此 static_check **不单独阻断 verdict**：启发式规则有误报，且它不直接
  判断推理链成立性。它的输出作为 verifier 的**补充诊断证据**（static_evidence）
  喂给 LLM 审查，帮助定位"实现层缺陷"（复杂度不达标、死循环等）——对应
  任务书"规则校验 + 分步 LLM 审查"多手段组合。

  本文件即规则的黄金样例集：每条规则配 正例（应命中）+ 负例（不应误报），
  开源后可直接运行 `pytest tests/test_static_check.py` 验证规则行为。
"""
from __future__ import annotations

from rex.executor.static_check import check_static, static_evidence_block, static_result_to_dict
from rex.models import Answer, QuestionItem, Step

Q = QuestionItem(
    id="A100", scene="algorithm", title="t",
    prompt="给定整数 x，若满足 x^2=4 输出 2，否则输出 0。",
    difficulty="basic", source="self", standard_answer="2",
)

AQ = QuestionItem(
    id="A000", scene="algorithm", title="t",
    prompt="给定 n，输出 1..n 的和。", difficulty="basic",
    source="self", standard_answer="",
)


def _algo_answer(code: str) -> Answer:
    return Answer(
        steps=[
            Step(id=1, kind="implement", content=code, conclusion="实现", deps=[]),
        ],
        final_answer="",
        code=code,
    )


def _static_q(prompt: str) -> QuestionItem:
    return QuestionItem(id="X", scene="algorithm", title="t", prompt=prompt,
                        difficulty="medium", source="self", standard_answer="")


def _cpp_answer(code: str) -> Answer:
    return _algo_answer("#include <iostream>\nusing namespace std;\n" + code)


# ---------------------------------------------------------------------------
# Python：复杂度声明一致性
# ---------------------------------------------------------------------------

def test_static_complexity_mismatch() -> None:
    """声明 O(n) 实为 O(n²) → mismatch（规则正例）。"""
    code = (
        "n = int(input())\narr = list(map(int, input().split()))\n"
        "for i in range(n):\n    for j in range(n):\n        print(arr[i] + arr[j])\n"
    )
    ans = Answer(
        steps=[
            Step(id=1, kind="complexity", content="时间复杂度 O(n)", conclusion="O(n)", deps=[]),
        ],
        final_answer="",
        code=code,
    )
    res = check_static(Q, ans)
    assert res.mismatch is True
    assert any(d.category == "complexity" and d.severity == "warn" for d in res.diagnostics)


def test_static_complexity_declared_o1_mismatch() -> None:
    """声明 O(1)（normalize 后为 0，falsy）也须检出 mismatch——回归保护：
    早期 `if est and dec` 把 O(1) 声明跳过导致漏检。"""
    code = "n = int(input())\nfor i in range(n):\n    print(i)\n"
    ans = Answer(
        steps=[
            Step(id=1, kind="implement", content=code, conclusion="x", deps=[]),
            Step(id=2, kind="complexity", content="时间复杂度 O(1)", conclusion="O(1)", deps=[]),
        ],
        final_answer="",
        code=code,
    )
    res = check_static(Q, ans)
    assert res.declared == "O(1)"
    assert res.estimated == "O(n)"
    assert res.mismatch is True


# ---------------------------------------------------------------------------
# Python：死循环检测
# ---------------------------------------------------------------------------

def test_static_infinite_loop_while_true_no_break() -> None:
    """`while True:` 无 break → 死循环风险。"""
    res = check_static(AQ, _algo_answer("while True:\n    print(1)\n"))
    assert res.loop_risk is True
    assert any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_while_condition_var_not_updated() -> None:
    """`while i < 10:` 但 i 从未更新 → 死循环风险。"""
    res = check_static(AQ, _algo_answer("i = 0\nwhile i < 10:\n    print(i)\n"))
    assert res.loop_risk is True
    assert any(d.category == "loop" for d in res.diagnostics)


def test_static_loop_no_risk_normal_while() -> None:
    """条件变量在循环内更新 → 正常终止，不误报（规则负例）。"""
    res = check_static(AQ, _algo_answer("i = 0\nwhile i < 10:\n    i += 1\n    print(i)\n"))
    assert res.loop_risk is False
    assert not any(d.category == "loop" for d in res.diagnostics)


def test_static_loop_no_risk_container_method_mutation() -> None:
    """`while dq:` + 循环内 dq.popleft() 是常见 BFS 终止模式，不应误报死循环。"""
    res = check_static(AQ, _algo_answer(
        "from collections import deque\ndq = deque([1])\n"
        "while dq:\n    u = dq.popleft()\n    print(u)\n"
    ))
    assert res.loop_risk is False
    assert not any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


# ---------------------------------------------------------------------------
# Python：递归无终止检测
# ---------------------------------------------------------------------------

def test_static_recursion_no_base_case() -> None:
    """递归调用但无非递归 return（base case）→ 递归无终止风险。"""
    res = check_static(AQ, _algo_answer(
        "def fib(n):\n    return fib(n - 1) + fib(n - 2)\nprint(fib(5))\n"
    ))
    assert res.recursion_risk is True
    assert any(d.category == "recursion" and d.severity == "warn" for d in res.diagnostics)


def test_static_recursion_with_base_no_risk() -> None:
    """有 `if n <= 1: return n` base case → 不误报（规则负例）。"""
    res = check_static(AQ, _algo_answer(
        "def fib(n):\n    if n <= 1:\n        return n\n    return fib(n - 1) + fib(n - 2)\nprint(fib(5))\n"
    ))
    assert res.recursion_risk is False
    assert not any(d.category == "recursion" for d in res.diagnostics)


# ---------------------------------------------------------------------------
# 序列化 / 证据块
# ---------------------------------------------------------------------------

def test_static_evidence_block_only_warns() -> None:
    """仅 warn 诊断才生成证据块（info 与无诊断不打扰 verifier）。"""
    ok = check_static(AQ, _algo_answer("print(1)\n"))
    assert static_evidence_block(ok) is None
    bad = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    block = static_evidence_block(bad)
    assert block is not None
    assert "规则校验证据" in block


def test_static_result_to_dict_roundtrip() -> None:
    res = check_static(AQ, _algo_answer("while True:\n    pass\n"))
    d = static_result_to_dict(res)
    assert d["loop_risk"] is True
    assert d["declared"] is None
    assert any(x["category"] == "loop" for x in d["diagnostics"])


# ---------------------------------------------------------------------------
# C++ 静态检测（CF/ABC 主场景代码为 C++，token 级启发式）
# ---------------------------------------------------------------------------

def test_static_cpp_single_loop_est() -> None:
    code = ("int main() {\n    int n; cin >> n;\n"
            "    for (int i = 0; i < n; i++) cout << i;\n    return 0;\n}")
    q = _static_q("输出 0..n-1，n<=1e5")
    res = check_static(q, _cpp_answer(code))
    assert res.estimated == "O(n)"
    assert res.mismatch is False  # 声明 O(n) 与估计一致
    # 声明 O(1) → mismatch 检出（此前 C++ 路径 estimated=unknown(syntax) 无法检出）
    ans_decl = Answer(
        steps=[Step(id=1, kind="implement", content=code, conclusion="x", deps=[]),
               Step(id=2, kind="complexity", content="时间复杂度 O(1)", conclusion="O(1)", deps=[])],
        final_answer="", code=_cpp_answer(code).code,
    )
    r2 = check_static(q, ans_decl)
    assert r2.mismatch is True


def test_static_cpp_nested_loops() -> None:
    """块循环 + 无块循环嵌套 → O(n^2)（覆盖 C++ 循环深度启发式）。"""
    code = ("int main() {\n    int n; cin >> n;\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        for (int j = 0; j < n; j++) cout << i * j << ' ';\n"
            "    }\n    return 0;\n}")
    res = check_static(_static_q("n<=1000 矩阵输出"), _cpp_answer(code))
    assert res.estimated == "O(n^2)"


def test_static_cpp_infinite_loop() -> None:
    code = "int main() {\n    while (true) { cout << 1; }\n    return 0;\n}"
    res = check_static(_static_q("输出循环"), _cpp_answer(code))
    assert res.loop_risk is True
    assert any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_cpp_infinite_loop_with_break_no_warn() -> None:
    """while(true) 内有 break → 不误报（规则负例）。"""
    code = ("int main() {\n    int x;\n    while (true) { cin >> x; if (x == 0) break; }\n"
            "    return 0;\n}")
    res = check_static(_static_q("读到 0 停"), _cpp_answer(code))
    assert res.loop_risk is False
    assert not any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_cpp_for_semicolon_infinite_loop() -> None:
    """for(;;) 无 break → 死循环风险。"""
    code = ("int main() {\n    for (;;) { cout << 1; }\n    return 0;\n}")
    res = check_static(_static_q("输出循环"), _cpp_answer(code))
    assert res.loop_risk is True
    assert any(d.category == "loop" and d.severity == "warn" for d in res.diagnostics)


def test_static_cpp_recursion_no_base() -> None:
    code = ("int fib(int n) { return fib(n - 1) + fib(n - 2); }\n"
            "int main() { cout << fib(5); return 0; }")
    res = check_static(_static_q("fib"), _cpp_answer(code))
    assert res.recursion_risk is True
    assert any(d.category == "recursion" and d.severity == "warn" for d in res.diagnostics)


def test_static_cpp_recursion_with_base_no_risk() -> None:
    code = ("int fib(int n) { if (n <= 1) return n; return fib(n - 1) + fib(n - 2); }\n"
            "int main() { cout << fib(5); return 0; }")
    res = check_static(_static_q("fib"), _cpp_answer(code))
    assert res.recursion_risk is False
    assert not any(d.category == "recursion" and d.severity == "warn" for d in res.diagnostics)


# ---------------------------------------------------------------------------
# 边界启发式
# ---------------------------------------------------------------------------

def test_static_boundary_negative_missing_detected() -> None:
    """题目含负数但代码只用 max()（未真正处理负数）→ 应报 boundary warn。

    回归保护：旧规则把 max() 当负数处理信号导致漏检（return max(a) 不报错）。
    """
    q = _static_q("数组中可能含负数，求最大子数组和。")
    res = check_static(q, _algo_answer("def f(a):\n    return max(a)\n"))
    assert any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_static_boundary_negative_handled_no_warn() -> None:
    """Kadane（负无穷初始化 + 比较）视为已处理负数 → 不报 boundary warn。"""
    q = _static_q("数组中可能含负数，求最大子数组和。")
    code = ("def f(a):\n    cur = 0\n    best = -10**9\n"
            "    for x in a:\n        cur = max(x, cur + x)\n"
            "        best = max(best, cur)\n    return best\n")
    res = check_static(q, _algo_answer(code))
    assert not any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_static_boundary_empty_missing_detected() -> None:
    q = _static_q("若输入为空，返回空数组。")
    res = check_static(q, _algo_answer("def f(n):\n    return sum(n)\n"))
    assert any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)


def test_static_boundary_negative_on_cpp() -> None:
    """C++ 场景边界规则也生效（题目含负数、代码未处理 → warn）。"""
    q = _static_q("数组元素可为负数，求最大子段和。")
    code = ("int main() {\n    int n; cin >> n;\n    int s = 0, ans = 0;\n"
            "    for (int i = 0; i < n; i++) { int x; cin >> x; s += x; ans = max(ans, s); }\n"
            "    cout << ans;\n    return 0;\n}")
    res = check_static(q, _cpp_answer(code))
    assert any(d.category == "boundary" and d.severity == "warn" for d in res.diagnostics)
