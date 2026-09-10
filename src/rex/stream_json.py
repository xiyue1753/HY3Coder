"""流式 JSON 增量提取：模型一边吐，界面一边逐 Step 显示。

求解 prompt 约定输出 ``{"steps":[{...}], "final_answer":"...", "code":"..."}``。
整段收完再解析的话，交互演示只能憋到最后一次性出现；这里按大括号配对流式切出
**已闭合的 step 对象**立刻返回，并对"正在生成的那一步"做容错抽取（未闭合的字符串
截到最后一个完整转义），让步骤卡片边生成边出现。

设计约束：解析永远不抛异常——展示层容错，解析不出来的部分直接跳过，
最终判定仍以整段收完后的正规解析（``SolverAgent._parse_answer``）为准。
"""
from __future__ import annotations

import json
import re
from typing import Any

_TAIL_KEYS = ("final_answer", "code")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
            "/": "/", "\\": "\\", '"': '"'}


def _find_array_start(text: str) -> int:
    """定位 "steps" 之后的第一个 ``[``；找不到返回 -1。"""
    m = re.search(r'"steps"\s*:\s*\[', text)
    return m.end() if m else -1


def read_json_string(text: str, i: int) -> tuple[str, bool]:
    """从 ``text[i]`` 开始读一个（可能尚未闭合的）JSON 字符串内容。

    返回 ``(已解码文本, 是否已闭合)``。尾部若是半个转义序列（``\\`` 或 ``\\u12``）
    则丢弃该片段，保证不抛异常。
    """
    out: list[str] = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            return "".join(out), True
        if ch == "\\":
            if i + 1 >= n:
                break                                  # 半个转义，丢弃
            nxt = text[i + 1]
            if nxt == "u":
                hexs = text[i + 2:i + 6]
                if len(hexs) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hexs):
                    break                              # \u 还没收全
                out.append(chr(int(hexs, 16)))
                i += 6
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out), False


def iter_elements(text: str) -> tuple[list[str], str, bool]:
    """切分 steps 数组：``(已闭合元素原文, 最后一个未闭合元素原文, 数组是否已闭合)``。"""
    start = _find_array_start(text)
    if start < 0:
        return [], "", False
    depth = 0
    in_str = False
    esc = False
    elem_start = -1
    complete: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                elem_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and elem_start >= 0:
                complete.append(text[elem_start:i + 1])
                elem_start = -1
        elif ch == "]" and depth == 0:
            return complete, "", True
        i += 1
    return complete, (text[elem_start:] if elem_start >= 0 else ""), False


def _obj_from_text(raw: str) -> dict | None:
    """整段是合法 JSON 就正规解析；否则容错抽字段（用于未闭合的那一步）。"""
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = None
    if isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for key in ("kind", "content", "conclusion"):
        m = re.search(r'"%s"\s*:\s*"' % key, raw)
        if m:
            out[key] = read_json_string(raw, m.end())[0]
    m = re.search(r'"id"\s*:\s*(\d+)', raw)
    if m:
        out["id"] = int(m.group(1))
    m = re.search(r'"deps"\s*:\s*\[([0-9,\s]*)\]', raw)
    if m:
        out["deps"] = [int(x) for x in re.findall(r"\d+", m.group(1))]
    return out or None


def partial_answer(text: str) -> dict:
    """流式文本 → 前端可渲染的部分 Answer：``{"steps": [...], "final_answer"?, "code"?}``。

    ``steps`` = 已闭合的步骤 + 正在生成的那一步（字段可能不全，前端按缺省渲染）；
    尾部两个键只在 steps 数组闭合之后才取，避免把步骤正文里的字样误当成顶层字段。
    """
    complete, pending, closed = iter_elements(text)
    steps: list[dict] = []
    for raw in complete:
        obj = _obj_from_text(raw)
        if obj:
            steps.append(obj)
    if pending:
        obj = _obj_from_text(pending)
        if obj:
            steps.append(obj)
    out: dict[str, Any] = {"steps": steps}
    if closed:
        for key in _TAIL_KEYS:
            m = re.search(r'"%s"\s*:\s*"' % key, text)
            if m:
                out[key] = read_json_string(text, m.end())[0]
    return out
