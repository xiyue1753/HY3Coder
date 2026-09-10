"""阶段回调兼容层 `_emit`：既支持老的二参回调，也支持带 message 的新回调（离线）。"""
from __future__ import annotations

from rex.pipeline import _emit


def test_emit_supports_three_arg_callback() -> None:
    seen: list[tuple] = []
    _emit(lambda p, payload=None, message=None: seen.append((p, payload, message)),
          "verify", None, "过程交叉审查 · V2 全局回溯…")
    assert seen == [("verify", None, "过程交叉审查 · V2 全局回溯…")]


def test_emit_falls_back_to_two_arg_callback() -> None:
    seen: list[tuple] = []
    _emit(lambda p, payload=None: seen.append((p, payload)), "solve", None, "带文案")
    assert seen == [("solve", None)]           # 老回调收到两参，不炸


def test_emit_swallows_callback_errors() -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("界面炸了")

    _emit(boom, "verify")                      # 不该抛出去
    _emit(None, "verify")                      # None 直接返回


def test_emit_defaults_message_to_none() -> None:
    seen: list[tuple] = []
    _emit(lambda p, payload=None, message=None: seen.append((p, message)), "execute")
    assert seen == [("execute", None)]
