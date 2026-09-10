"""交付副本一致性：根目录 REPORT.md 由 reports/REPORT.md 同步而来，两者必须匹配。

根目录放一份是为了仓库首页/评审一眼能看到正文（reports/REPORT.md 仍是权威版本，
由 ``scripts/make_report.py`` 生成，再由 ``scripts/sync_root_report.py`` 复制到根目录
并把配图等相对引用改写成相对仓库根的路径）。这里把它锁住，避免只改一份导致漂移，
也避免出现根目录解析不到的相对链接。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sync_root_report import render_delivery  # noqa: E402


def test_root_report_copy_matches_canonical() -> None:
    canonical = (ROOT / "reports" / "REPORT.md").read_text(encoding="utf-8")
    delivery = (ROOT / "REPORT.md").read_text(encoding="utf-8")
    assert delivery == render_delivery(canonical), (
        "根目录 REPORT.md 与 reports/REPORT.md 不一致；"
        "改完权威版本后重新同步：python scripts/sync_root_report.py"
    )


def test_delivery_report_relative_links_resolve_from_root() -> None:
    """根目录副本里的相对链接/配图要能在仓库根下解析到（GitHub 按文件位置解析）。"""
    delivery = (ROOT / "REPORT.md").read_text(encoding="utf-8")
    links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", delivery)
    relative = [l for l in links if not l.startswith(("http://", "https://", "#", "mailto:"))]
    assert relative, "交付副本里应当带有配图与相对链接"
    missing = [l for l in relative if not (ROOT / l).exists()]
    assert not missing, f"根目录副本的相对路径在仓库根下解析不到：{missing}"
