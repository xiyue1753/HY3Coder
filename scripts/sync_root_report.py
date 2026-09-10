"""把 reports/REPORT.md 同步成根目录的交付副本 REPORT.md。

根目录那份是给评审一眼看到的交付副本（README 指向它）；权威版本始终是
``reports/REPORT.md``。正文里的配图写的是相对 ``reports/`` 的路径
（``figures/*.png``），直接从根目录解析会断，所以复制时把这类相对引用改写成
相对仓库根的路径——正文文字一字不改。

用法：
    python scripts/sync_root_report.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "reports" / "REPORT.md"
DELIVERY = ROOT / "REPORT.md"

#: 相对 reports/ 的引用 → 相对仓库根（按需扩充）
REWRITES: tuple[tuple[str, str], ...] = (
    ("](figures/", "](reports/figures/"),
)


def render_delivery(text: str) -> str:
    """把权威版本正文改写成根目录副本形态（只动相对引用）。"""
    out = text
    for old, new in REWRITES:
        out = out.replace(old, new)
    return out


def main() -> None:
    text = CANONICAL.read_text(encoding="utf-8")
    delivery = render_delivery(text)
    # 按字节写：保持与权威版本一致的 LF（Path.write_text 的 newline 参数要 3.10+）
    DELIVERY.write_bytes(delivery.encode("utf-8"))
    print(f"已同步 {DELIVERY.name}（{len(delivery)} 字符，改写 {len(REWRITES)} 类相对引用）")


if __name__ == "__main__":
    main()
