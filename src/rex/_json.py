"""Shared JSON extraction helpers for model outputs (solver & verifier)."""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?", re.MULTILINE)


def extract_json_object(text: str) -> str:
    """Pull the first balanced JSON object out of a model response.

    Handles markdown code fences and surrounding prose (some models prefix the
    JSON with a short sentence). The scanner tracks nesting depth while
    respecting string literals, so braces inside strings do not break it.

    Edge case: prose *before* the JSON may itself contain a lone ``{``
    (e.g. "答案含 { 细节如下: {...json...}"). We then scan forward: try each
    candidate ``{`` as a JSON start and keep the first that balances.
    """
    t = _FENCE_RE.sub("", text.strip())
    if t.endswith("```"):
        t = t[: t.rfind("```")].rstrip()
    start = 0
    while True:
        s = t.find("{", start)
        if s == -1:
            raise ValueError("no balanced JSON object found in model output")
        try:
            return _balanced_object(t, s)
        except ValueError:
            start = s + 1  # 该候选不闭合，尝试下一个 `{`


def _balanced_object(t: str, start: int) -> str:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return t[start : i + 1]
    raise ValueError("unbalanced JSON in model output")
