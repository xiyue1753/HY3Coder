"""流式 JSON 增量提取：逐 Step 显示依赖它，必须在任意切分点都不炸（离线，不调模型）。"""
from __future__ import annotations

import json

from rex.stream_json import iter_elements, partial_answer, read_json_string

SAMPLE = {
    "steps": [
        {"id": 1, "kind": "understand",
         "content": "题意：输入数组\n第二行含\"引号\"、反斜杠\\ 与中文：接雨水",
         "conclusion": "理解正确", "deps": []},
        {"id": 2, "kind": "approach",
         "content": "双指针，注意边界 if x] == 3 { } 这种情况", "conclusion": "思路可行", "deps": [1]},
    ],
    "final_answer": "6",
    "code": "print(6)",
}
TEXT = json.dumps(SAMPLE, ensure_ascii=False)


def test_complete_text_parses_like_full_json() -> None:
    out = partial_answer(TEXT)
    assert out["steps"] == SAMPLE["steps"]
    assert out["final_answer"] == "6" and out["code"] == "print(6)"


def test_every_prefix_is_safe_and_consistent() -> None:
    """在任意字符处截断：不抛异常，且已出现的内容必须是最终结果的前缀。"""
    full = SAMPLE["steps"]
    for i in range(len(TEXT) + 1):
        out = partial_answer(TEXT[:i])           # 不得抛异常
        steps = out["steps"]
        assert len(steps) <= len(full)
        for got, want in zip(steps, full):
            assert got.get("id") == want["id"]
            if got == want:
                continue                      # 已闭合的步骤必须与最终结果完全一致
            # 只有最后一步允许不完整，且其内容必须是最终值的前缀（不丢字、不串行）
            assert got is steps[-1], f"第 {got.get('id')} 步不完整但后面还有步骤"
            assert want["content"].startswith(got.get("content", ""))
            assert want["conclusion"].startswith(got.get("conclusion", ""))
            assert want["kind"].startswith(got.get("kind", ""))


def test_partial_step_keeps_prefix_content() -> None:
    """切在第 2 步正文中间：第 2 步应给出已生成的部分正文（不丢字、不串行）。"""
    marker = "双指针，注意边界"
    cut = TEXT.index(marker) + len(marker)
    out = partial_answer(TEXT[:cut])
    assert len(out["steps"]) == 2
    assert out["steps"][0] == SAMPLE["steps"][0]
    assert out["steps"][1]["content"].startswith(marker)
    assert SAMPLE["steps"][1]["content"].startswith(out["steps"][1]["content"])


def test_tail_keys_only_after_array_closes() -> None:
    """steps 数组没闭合前不吐 final_answer/code（避免把正文里的字样当顶层字段）。"""
    before = TEXT[:TEXT.index('"final_answer"')]
    assert "final_answer" not in partial_answer(before)
    assert "code" not in partial_answer(before)
    assert partial_answer(TEXT)["code"] == "print(6)"


def test_iter_elements_reports_closed_flag() -> None:
    complete, pending, closed = iter_elements(TEXT)
    assert len(complete) == 2 and pending == "" and closed is True
    cut = TEXT.index("思路可行")
    complete, pending, closed = iter_elements(TEXT[:cut])
    assert len(complete) == 1 and pending and closed is False


def test_read_json_string_handles_partial_escapes() -> None:
    assert read_json_string(r'"a\nb"', 1) == ("a\nb", True)
    assert read_json_string(r'"中\u4e2d"', 1) == ("中中", True)
    assert read_json_string(r'"未闭合', 1) == ("未闭合", False)
    # 尾部半个转义：丢弃该片段而不是抛异常
    assert read_json_string('"尾巴\\', 1) == ("尾巴", False)
    assert read_json_string('"半个\\u12', 1) == ("半个", False)


def test_degenerate_inputs() -> None:
    for text in ("", "not json at all", '{"steps":[', '{"other": 1}', '{"steps": []}'):
        out = partial_answer(text)
        assert out["steps"] == []
