# Codeforces Cookie 获取与使用指南（路径 B：手动导出）

> 用途：让 `scripts/batch_ingest_cf.py` 能绕过 Cloudflare 安全验证（challenge）
> 进行低速小批量抓取。
>
> **核心原理**：`cf_clearance` cookie 绑定 **IP + 浏览器 UA**。手动导出时
> 必须同时带上你的浏览器 UA，脚本用该 UA 建会话，否则 clearance 无效仍会被拦截。

## 为什么需要 cf_clearance

Cloudflare 对 headless/高频访问会发 challenge 页。真实浏览器里人工过验证一次后
浏览器会获得 `cf_clearance`（有效期约 30 分钟 ~ 数小时），后续请求带上它即可放行。

## 手动导出步骤（约 1 分钟）

1. **用 Chrome/Edge 打开 codeforces.com**，正常浏览到任一题目页（如
   `https://codeforces.com/problemset/problem/1/A`）。
   - 若出现 Cloudflare 验证框，先手动完成（点 "I'm not a robot" 或等自动通过）。
   - 如需抓登录可见的提交源码页，请保持已登录状态（有 JSESSIONID）。
2. **打开开发者工具**（F12）→ **Application/应用** 标签 → 左侧 **Cookies** →
   点 `https://codeforces.com`。
3. 点页面底部的 `cf_clearance` 这一行，复制其 **Name** 和 **Value**。
   同样复制 `JSESSIONID`（如已登录）。
4. 把以下 JSON 保存为 `data/cases/cf_cookies.json`：

```json
{
  "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  "cookies": [
    {"name": "cf_clearance", "value": "粘贴这里", "domain": ".codeforces.com", "path": "/"},
    {"name": "JSESSIONID", "value": "粘贴这里（已登录才有）", "domain": ".codeforces.com", "path": "/"}
  ]
}
```

- `ua` 取开发者工具 Console 里 `navigator.userAgent` 的输出（**必须用你实际浏览器的**）。
- 也可以直接复制 cookies 面板里任意行（Chrome 右键 → Copy → Copy as...），但
  上面的最小格式（name/value/domain/path）已足够。

## 验证 cookie 是否有效（单页探测，不抓题）

```bash
& D:\.conda\envs\tensor_env\python.exe scripts/batch_ingest_cf.py --probe
```

- 输出 `首页放行 ✓` → cookie 有效，可以开始抓取。
- 输出 `仍被 Cloudflare 拦截` → UA 不匹配或 clearance 过期，重新导出一次。

## 开始小批量抓取（低速，符合正常人浏览节奏）

```bash
# 从离线题单自动选题，一轮 12 题，页间 2.5 秒，headless
& D:\.conda\envs\tensor_env\python.exe scripts/batch_ingest_cf.py --auto --round-size 12 --seed 1
# 更慢更稳：CF_DELAY=3（每页间隔 3 秒）
$env:CF_DELAY="3"; & D:\.conda\envs\tensor_env\python.exe scripts/batch_ingest_cf.py --auto --round-size 12 --seed 1
```

脚本特性：
- 每题先去重（已入库自动跳过），可反复续跑
- 页间延迟默认 1.5s（`CF_DELAY` 可调大），不会高频冲击
- 遇 Cloudflare 拦截**整批止损**，不空转重试；提示后换 cookie 或等 IP 冷却
- `--limit N` 只处理前 N 题（先小批试跑建议加 `--limit 3`）

## 安全

- cookie 文件在 `data/cases/cf_cookies.json`，已被 `.gitignore` 排除，**不入 git**。
- 不要在任何聊天/文档里粘贴完整 cookie value。
