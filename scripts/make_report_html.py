"""把 reports/REPORT.md 渲染成单文件 HTML（reports/REPORT.html）。

内容以 REPORT.md 为唯一来源，本脚本只负责呈现：表格、代码块、配图与目录排版。
题面（````prompt 围栏）沿用应用侧同一套渲染方式：marked 解析 Markdown + KaTeX 渲染
$…$ 与 $$…$$ 公式，先提公式再解析，避免公式里的 < > 被转义。CDN 不可达时退化为
原始题面文本，不影响阅读。
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]

CSS = """
:root{
  --ink:#1f2328; --muted:#5b6673; --line:#d9dee5; --line-soft:#eceff3;
  --accent:#0b5fa5; --accent-soft:#eef4fa; --code-bg:#f6f8fa; --zebra:#fbfcfd;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:#eef1f4; color:var(--ink);
  font:16px/1.8 "Microsoft YaHei","PingFang SC","Source Han Sans SC","Hiragino Sans GB",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.page{
  max-width:1010px; margin:0 auto; padding:56px 68px 88px; background:#fff;
  box-shadow:0 1px 4px rgba(15,23,42,.08);
}
h1,h2,h3,h4{line-height:1.35; font-weight:600; color:#111827}
h1{font-size:1.85em; margin:0 0 .5em; padding-bottom:.4em; border-bottom:1px solid var(--line)}
h1.appendix{margin-top:3.2em; padding-top:1.6em; border-top:3px solid var(--accent); border-bottom:none}
h2{font-size:1.42em; margin:2.4em 0 .7em; padding-left:.6em; border-left:5px solid var(--accent)}
h3{font-size:1.14em; margin:1.8em 0 .5em; color:#111827}
h4{font-size:1.02em; margin:1.4em 0 .4em; color:#374151}
p{margin:.75em 0}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
strong{font-weight:600}
hr{border:none; border-top:1px solid var(--line-soft); margin:2.2em 0}
blockquote{
  margin:1.1em 0; padding:.7em 1.1em; background:var(--accent-soft);
  border-left:4px solid var(--accent); color:#243b53; font-size:.95em;
}
blockquote p{margin:.2em 0}
ul,ol{margin:.6em 0 .9em; padding-left:1.6em}
li{margin:.28em 0}
li>ul,li>ol{margin:.2em 0}
code{
  font-family:"JetBrains Mono",Consolas,"Cascadia Mono",Menlo,monospace;
  font-size:.9em; background:#eff2f6; padding:.12em .38em; border-radius:4px;
  color:#0f172a; word-break:break-word;
}
pre{
  background:var(--code-bg); border:1px solid var(--line-soft); border-left:3px solid #b9c4d0;
  border-radius:6px; padding:14px 16px; overflow-x:auto; margin:1em 0;
}
pre code{background:none; padding:0; font-size:.86em; line-height:1.62; white-space:pre}
.tw{overflow-x:auto; margin:1.1em 0}
table{border-collapse:collapse; width:100%; font-size:.94em}
thead th{
  background:#f1f5f9; color:#111827; font-weight:600; text-align:left;
  padding:9px 12px; border-bottom:2px solid var(--line); white-space:nowrap;
}
tbody td{padding:8px 12px; border-bottom:1px solid var(--line-soft); vertical-align:top}
tbody tr:nth-child(even){background:var(--zebra)}
tbody tr:hover{background:var(--accent-soft)}
img{max-width:100%; height:auto; display:block; margin:1.2em auto;
  border:1px solid var(--line-soft); border-radius:4px}
nav.toc{
  margin:1.6em 0 2.4em; padding:18px 22px; background:#f8fafc;
  border:1px solid var(--line-soft); border-radius:8px; font-size:.94em;
}
nav.toc h2{margin:0 0 .6em; font-size:1em; border:none; padding:0; color:var(--muted);
  letter-spacing:.06em}
nav.toc ol{list-style:none; margin:0; padding:0; columns:2; column-gap:34px}
nav.toc ol li{margin:.18em 0; break-inside:avoid}
nav.toc .lvl3{padding-left:1.1em; color:var(--muted); font-size:.95em}
/* 题面：与应用侧同一套容器样式（md-bound），数学块横向可滚 */
.prompt{
  margin:1.1em 0; padding:14px 20px 18px; background:#fbfcfe;
  border:1px solid var(--line-soft); border-left:3px solid var(--accent); border-radius:6px;
  font-size:.95em; line-height:1.72;
}
.md-bound{word-break:break-word}
.md-bound p{margin:.55em 0}
.md-bound h1,.md-bound h2,.md-bound h3,.md-bound h4{
  font-size:1em; margin:1em 0 .3em; padding:0; border:none; color:#1f2937;
}
.md-bound pre{background:#f2f5f8; border:1px solid var(--line-soft); border-left:none;
  margin:.7em 0; padding:10px 12px}
.md-bound pre,.md-bound code{font-size:.88em; white-space:pre-wrap; word-break:break-word}
.md-bound .katex-display{margin:.5em 0; overflow-x:auto; overflow-y:hidden}
.md-bound ul,.md-bound ol{margin:.5em 0 .7em}
@media print{
  body{background:#fff}
  .page{box-shadow:none; max-width:none; padding:0 8mm}
  nav.toc{break-inside:avoid}
  h1.appendix{break-before:page}
  h2,h3{break-after:avoid}
  table,img,pre{break-inside:avoid}
  a{color:inherit; text-decoration:none}
}
"""

# 题面渲染脚本：与应用侧 src/web/static/main.js 的 renderMath 保持一致
PROMPT_JS = r"""
(function(){
  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function renderMath(text){
    if(!text) return '';
    var katexHtml = [], safe = text;
    if (window.katex) {
      safe = text.replace(/\$\$([\s\S]+?)\$\$/g, function(m, exp){
        try { katexHtml.push(katex.renderToString(exp, {displayMode:true, throwOnError:false})); }
        catch(e){ katexHtml.push(''); }
        return '\u0000K' + (katexHtml.length - 1) + '\u0000';
      }).replace(/\$([^$\n]+?)\$/g, function(m, exp){
        try { katexHtml.push(katex.renderToString(exp, {displayMode:false, throwOnError:false})); }
        catch(e){ katexHtml.push(''); }
        return '\u0000K' + (katexHtml.length - 1) + '\u0000';
      });
    }
    var out;
    try { out = (window.marked ? marked.parse(safe) : escapeHtml(safe).replace(/\n/g,'<br>')); }
    catch(e){ out = escapeHtml(safe).replace(/\n/g,'<br>'); }
    return out.replace(/\u0000K(\d+)\u0000/g, function(m, i){ return katexHtml[+i] || ''; });
  }
  var nodes = document.querySelectorAll('.prompt[data-prompt]');
  for (var i = 0; i < nodes.length; i++) {
    nodes[i].innerHTML = renderMath(nodes[i].textContent);
  }
})();
"""

HEAD_EXTRA = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@9.1.2/marked.min.js"></script>
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{head_extra}<style>{css}</style>
</head>
<body>
<div class="page">
{toc}
{body}
</div>
<script>{prompt_js}</script>
</body>
</html>
"""


def _build_toc(tokens: list[dict]) -> str:
    """目录：收 h1/h2，以及形如 1.1 / A.2 / 案例标题的 h3。"""
    rows: list[str] = []

    def walk(items: list[dict]) -> None:
        for it in items:
            lvl, name = it["level"], it["name"]
            keep = lvl <= 2 or (lvl == 3 and re.match(
                r"^(\d+\.\d+|[A-D]\.|[AC]\d{4} · )", name) is not None)
            if keep:
                cls = "" if lvl <= 2 else ' class="lvl3"'
                rows.append(f'<li{cls}><a href="#{it["id"]}">{html.escape(name)}</a></li>')
            if it.get("children"):
                walk(it["children"])

    walk(tokens)
    if not rows:
        return ""
    return ('<nav class="toc">\n<h2>目录</h2>\n<ol>\n' + "\n".join(rows) + "\n</ol>\n</nav>")


def _wrap_prompts(body: str) -> str:
    """````prompt 围栏交给前端渲染：原始题面留在容器里，JS 不可用时退化为文本。"""
    def repl(m: re.Match) -> str:
        raw = html.unescape(m.group(1))
        return ('<div class="prompt md-bound" data-prompt="1">'
                + html.escape(raw) + "</div>")

    return re.sub(r'<pre><code class="language-prompt">(.*?)</code></pre>', repl, body, flags=re.S)


def render(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8")
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list", "md_in_html"],
        extension_configs={"toc": {"toc_depth": "1-4"}},
    )
    body = md.convert(text)
    body = _wrap_prompts(body)
    # 表格套一层可横向滚动的容器，窄屏下不挤压
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    # 附录大标题单独一个类，打印时另起一页
    body = re.sub(r'<h1 id="([^"]+)">(附录)', r'<h1 class="appendix" id="\1">\2', body)

    title = "HY3Coder 分析报告"
    m = re.search(r"<h1[^>]*>([^<]+)</h1>", body)
    if m:
        title = m.group(1).strip()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        TEMPLATE.format(title=html.escape(title), head_extra=HEAD_EXTRA, css=CSS,
                        toc=_build_toc(md.toc_tokens), body=body.strip(),
                        prompt_js=PROMPT_JS),
        encoding="utf-8", newline="\n",
    )
    print(f"html written -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=ROOT / "reports" / "REPORT.md")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "REPORT.html")
    args = ap.parse_args()
    render(args.src, args.out)


if __name__ == "__main__":
    main()
