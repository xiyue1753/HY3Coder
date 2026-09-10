"""交付副本一致性：根目录 REPORT.md 是 reports/REPORT.md 的交付副本，两者必须同内容。

根目录放一份是为了仓库首页/评审一眼能看到正文（reports/REPORT.md 仍是权威版本，
由 ``scripts/make_report.py`` 生成）。这里把它锁住，避免只改一份导致两份漂移。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_report_copy_matches_canonical() -> None:
    canonical = (ROOT / "reports" / "REPORT.md").read_text(encoding="utf-8")
    delivery = (ROOT / "REPORT.md").read_text(encoding="utf-8")
    assert delivery == canonical, (
        "根目录 REPORT.md 与 reports/REPORT.md 不一致；"
        "改完权威版本后重新复制：copy reports/REPORT.md REPORT.md"
    )
