"""人工验证 Cloudflare 并导出完整 cookie（含 cf_clearance）。

背景：Codeforces 的 Cloudflare 安全验证（challenge）在 headless 下无法自动
通过；一旦触发，后续请求全部被拦截。通过真实 Edge 窗口**人工过验证一次**
后，浏览器会获得 ``cf_clearance`` cookie（绑定 IP+UA），本脚本将其与登录态
(JSESSIONID) 一并导出到 ``data/cases/cf_cookies.json``，供
``batch_ingest_cf.py`` 复用 —— 有效期内批量抓取不再被 challenge 拦截。

用法：
    python scripts/cf_cookie_session.py
    # 可选：--wait 180（等待秒数，默认 180）；--url 指定起始页
流程：
    1. 弹出真实 Edge 窗口并打开 codeforces.com
    2. 若出现 Cloudflare 验证页/登录页，请在窗口内手动完成（脚本自动等待）
    3. 检测到已通过验证（出现 #header 且无 challenge）后自动导出 cookie 并退出
安全：cookie 文件仅保存在项目 data/cases/（已被 .gitignore 忽略），不入 git。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cases" / "cf_cookies.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _is_challenge(page) -> bool:
    try:
        t = page.title() or ""
        body = ""
        try:
            body = page.eval_on_selector("body", "e => e.innerText")[:600]
        except Exception:  # noqa: BLE001
            pass
        if "Just a moment" in t or "Attention" in t or "安全检查" in t:
            return True
        if "Ray ID" in body and ("security check" in body.lower() or "安全检查" in body):
            return True
        if "cf-chl" in (page.content() or ""):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _has_header(page) -> bool:
    try:
        return page.query_selector("#header") is not None
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=180,
                    help="最长等待人工验证的秒数（默认 180）")
    ap.add_argument("--url", default="https://codeforces.com/", help="起始页")
    args = ap.parse_args()

    print("[*] 启动真实 Edge 窗口，请在窗口内手动完成 Cloudflare 验证/登录…")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=False,
                              args=["--disable-blink-features=AutomationControlled",
                                    "--start-maximized"])
        ctx = b.new_context(user_agent=UA, viewport={"width": 1400, "height": 900})
        pg = ctx.new_page()
        pg.goto(args.url, timeout=45000, wait_until="domcontentloaded")

        deadline = time.time() + args.wait
        done = False
        while time.time() < deadline:
            pg.wait_for_timeout(2000)
            if _is_challenge(pg):
                print("[.] 检测到 Cloudflare 验证，请在窗口中手动完成…")
                continue
            if _has_header(pg):
                try:
                    nav = pg.eval_on_selector("#header", "e => e.innerText")[:80]
                except Exception:  # noqa: BLE001
                    nav = ""
                print(f"[+] 验证通过：#header 已出现 ({nav.replace(chr(10), ' | ')})")
                done = True
                break
            # 页面已加载但 header 还没渲染，继续等
            print("[.] 页面加载中…")

        if not done:
            print("[!] 等待超时：未检测到验证通过。请重试并在窗口内完成验证。")
            b.close()
            sys.exit(1)

        cookies = ctx.cookies("https://codeforces.com")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(cookies, indent=1), encoding="utf-8")
        names = sorted(c["name"] for c in cookies)
        has_clearance = any(c["name"] == "cf_clearance" for c in cookies)
        has_session = any(c["name"] == "JSESSIONID" for c in cookies)
        print(f"[+] cookies saved: {OUT} ({len(cookies)} 个)")
        print(f"    cf_clearance={has_clearance} JSESSIONID={has_session}")
        if not has_clearance:
            print("[!] 提示：未获取到 cf_clearance（可能未触发过验证，会话较脆弱，触发后需重跑本脚本）")
        b.close()


if __name__ == "__main__":
    main()
