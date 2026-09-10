"""把 reports/REPORT.md 渲染成单文件 HTML（reports/REPORT.html）。

内容以 REPORT.md 为唯一来源，本脚本只负责呈现：
- 表格、代码块、配图与目录排版；
- 题面（````prompt 围栏）沿用应用侧的 marked + KaTeX 渲染，容器收成滑动窗口；
- 典型案例的三段（题目 / HY3 求解过程 / 过程评估判定）折成 <details>，
  步��做成编号卡片、结论与证据各自成套色小框、严重度做成标签。
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
  --fatal:#b42318; --fatal-bg:#fdeceb; --minor:#b25e09; --minor-bg:#fff6e5;
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
h3.case-title{
  font-size:1.22em; margin:2.2em 0 .4em; display:flex; align-items:baseline; gap:10px;
  padding-bottom:.35em; border-bottom:1px dashed var(--line);
}
h3.case-title .qid{
  font-family:"JetBrains Mono",Consolas,Menlo,monospace; color:var(--accent);
  background:var(--accent-soft); padding:1px 9px; border-radius:6px; font-size:.92em;
}
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
  border-radius:0 0 6px 6px; padding:14px 16px; overflow-x:auto; margin:0;
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

/* 案例头：难度 / 过程评估 / 答案正确 三枚信息条 */
ul.meta{list-style:none; display:flex; flex-wrap:wrap; gap:8px; padding:0; margin:.2em 0 .8em}
ul.meta li{
  margin:0; padding:3px 12px; font-size:.88em; color:#334155; background:#f6f9fc;
  border:1px solid var(--line-soft); border-radius:999px;
}

/* 折叠段：题目 / HY3 求解过程 / 过程评估判定 */
details.case-sec{margin:.7em 0; border:1px solid var(--line-soft); border-radius:8px; background:#fff}
details.case-sec>summary{
  cursor:pointer; padding:9px 14px; font-weight:600; color:#111827; list-style:none;
  background:#f6f9fc; border-radius:7px; display:flex; align-items:center; gap:8px;
  transition:background .15s;
}
details.case-sec>summary:hover{background:#eef4fa}
details.case-sec>summary::-webkit-details-marker{display:none}
details.case-sec>summary::before{content:"\\25B8"; color:var(--accent); font-size:.85em}
details.case-sec[open]>summary::before{content:"\\25BE"}
details.case-sec[open]>summary{border-bottom:1px solid var(--line-soft); border-radius:7px 7px 0 0}
details.case-sec>.sec-body{padding:12px 16px 16px}
details.case-sec>.sec-body>*:first-child{margin-top:.3em}
details.case-sec>.sec-body>*:last-child{margin-bottom:.3em}
@keyframes secIn{from{opacity:0; transform:translateY(-2px)}to{opacity:1; transform:none}}
details.case-sec[open]>.sec-body{animation:secIn .16s ease}

/* 题面：滑动窗口（与应用侧 md-bound 一致） */
.prompt{
  margin:.2em 0; padding:14px 20px 18px; background:#fbfcfe;
  border:1px solid var(--line-soft); border-left:3px solid var(--accent); border-radius:6px;
  font-size:.95em; line-height:1.72;
  max-height:340px; overflow:auto; overscroll-behavior:contain;
}
.prompt::-webkit-scrollbar{width:10px; height:10px}
.prompt::-webkit-scrollbar-thumb{background:#cdd6e0; border-radius:6px;
  border:2px solid transparent; background-clip:content-box}
.prompt::-webkit-scrollbar-thumb:hover{background:#aebbc9; background-clip:content-box}
.md-bound{word-break:break-word}
.md-bound p{margin:.55em 0}
.md-bound h1,.md-bound h2,.md-bound h3,.md-bound h4{
  font-size:1em; margin:1em 0 .3em; padding:0; border:none; color:#1f2937;
}
.md-bound pre{background:#f2f5f8; border:1px solid var(--line-soft); border-left:none;
  border-radius:6px; margin:.7em 0; padding:10px 12px}
.md-bound pre,.md-bound code{font-size:.88em; white-space:pre-wrap; word-break:break-word}
.md-bound .katex-display{margin:.5em 0; overflow-x:auto; overflow-y:hidden}
.md-bound ul,.md-bound ol{margin:.5em 0 .7em}

/* 求解过程：结论框、编号步骤卡片 */
.answer{
  display:flex; gap:10px; align-items:baseline; margin:.5em 0 .9em; padding:10px 14px;
  background:var(--accent-soft); border:1px solid #d6e6f6; border-left:3px solid var(--accent);
  border-radius:6px; font-size:.96em; color:#14395c;
}
.lbl{
  flex:none; font-size:.82em; font-weight:600; letter-spacing:.04em; color:var(--accent);
  background:#fff; border:1px solid #d6e6f6; border-radius:999px; padding:1px 9px;
}
ol.cards{list-style:none; counter-reset:card; padding-left:0; margin:.4em 0 .8em}
ol.cards>li{
  counter-increment:card; position:relative; margin:.55em 0; padding:11px 14px 11px 46px;
  background:#fbfcfd; border:1px solid var(--line-soft); border-left:3px solid #c7d3e0;
  border-radius:7px; font-size:.96em;
}
ol.cards>li::before{
  content:counter(card); position:absolute; left:13px; top:11px; width:22px; height:22px;
  border-radius:50%; background:var(--accent); color:#fff; font-size:.76em; font-weight:600;
  display:flex; align-items:center; justify-content:center;
}
ol.cards>li>strong{color:#0b3d63}
ol.cards>li>ul{list-style:none; padding-left:0; margin:.35em 0 0}
li.note,li.ev{
  margin-top:.45em; padding:.4em .7em; border-radius:5px; font-size:.92em;
  list-style:none; color:#475569; background:#f4f7fa; border-left:2px solid #cbd5e1;
}
li.note>.lbl,li.ev>.lbl{background:#fff; border-color:var(--line); color:var(--muted)}
li.ev{background:#f8fafc}

/* 判定：findings 卡片与严重度标签 */
ol.cards.findings>li{border-left-color:#e4a2a2; background:#fffdfd}
.badge{
  display:inline-block; padding:0 8px; border-radius:999px; font-size:.78em; font-weight:600;
  vertical-align:.1em; margin:0 2px;
}
.badge.fatal{background:var(--fatal-bg); color:var(--fatal)}
.badge.minor{background:var(--minor-bg); color:var(--minor)}

/* 代码块：带语言条与复制按钮 */
.code{margin:.9em 0; border:1px solid var(--line-soft); border-radius:7px; overflow:hidden}
.code-bar{
  display:flex; align-items:center; justify-content:space-between; padding:6px 12px;
  background:#eef2f6; border-bottom:1px solid var(--line-soft); font-size:.8em; color:var(--muted);
}
.code-bar .lang{
  font-family:"JetBrains Mono",Consolas,Menlo,monospace; letter-spacing:.06em; text-transform:lowercase;
}
.code-bar .copy{
  font:inherit; cursor:pointer; color:var(--accent); background:#fff; padding:2px 12px;
  border:1px solid var(--line); border-radius:999px;
}
.code-bar .copy:hover{background:var(--accent-soft)}
.code pre{border:none; border-radius:0}

@media print{
  body{background:#fff}
  .page{box-shadow:none; max-width:none; padding:0 8mm}
  nav.toc{break-inside:avoid}
  h1.appendix{break-before:page}
  h2,h3,h4{break-after:avoid}
  table,img,pre,.code{break-inside:avoid}
  a{color:inherit; text-decoration:none}
  .prompt{max-height:none; overflow:visible}
  details.case-sec>summary{background:#fff}
  .code-bar .copy{display:none}
}
"""

# 题面渲染 + 代码复制：渲染顺序与应用侧 src/web/static/main.js 的 renderMath 一致
PAGE_JS = r"""
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
  document.querySelectorAll('.code-bar .copy').forEach(function(btn){
    btn.addEventListener('click', function(){
      var code = btn.closest('.code').querySelector('code');
      var text = code ? code.textContent : '';
      var done = function(){ btn.textContent = '已复制'; setTimeout(function(){ btn.textContent = '复制'; }, 1200); };
      if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done, done); }
      else { done(); }
    });
  });
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
<script>{page_js}</script>
</body>
</html>
"""

CASE_SECS = ("题目", "HY3 求解过程", "过程评估判定")
CODE_RE = re.compile(r'<pre><code( class="language-(\w+)")?>(.*?)</code></pre>', re.S)


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


def _wrap_code(body: str) -> str:
    """代码块加语言条与复制按钮。"""
    def repl(m: re.Match) -> str:
        lang = m.group(2) or "text"
        return ('<div class="code"><div class="code-bar"><span class="lang">' + lang
                + '</span><button class="copy" type="button">复制</button></div>'
                + '<pre><code' + (m.group(1) or "") + '>' + m.group(3) + "</code></pre></div>")

    return CODE_RE.sub(repl, body)


def _process_solve(inner: str) -> str:
    """求解过程：结论独立成框，编号步骤做成卡片，小结作为卡片内注释。"""
    inner = re.sub(r'<p>最终答案：(.+?)</p>',
                   r'<div class="answer"><span class="lbl">最终答案：</span><span>\1</span></div>',
                   inner, flags=re.S)
    inner = inner.replace("<ol>", '<ol class="cards">', 1)
    inner = re.sub(r'<li>小结：', '<li class="note"><span class="lbl">小结：</span>', inner)
    return inner


def _process_verdict(inner: str) -> str:
    """判定：findings 做成卡片，严重度做成标签，证据单独成框。"""
    inner = inner.replace("<ol>", '<ol class="cards findings">', 1)
    inner = re.sub(r'<li>证据：', '<li class="ev"><span class="lbl">证据：</span>', inner)
    inner = re.sub(r'<strong>(fatal|minor)</strong>', r'<span class="badge \1">\1</span>', inner)
    return inner


def _collapsible(body: str) -> str:
    """把典型案例里的三段折成 <details>，并按段做组件化排版。"""
    pat = re.compile(r"<h4[^>]*>(" + "|".join(CASE_SECS) + r")</h4>")
    out: list[str] = []
    pos = 0
    for m in pat.finditer(body):
        out.append(body[pos:m.start()])
        rest = body[m.end():]
        nxt = re.search(r"<h[1-4][ >]", rest)
        end = m.end() + (nxt.start() if nxt else len(rest))
        label, inner = m.group(1), body[m.end():end].strip()
        if label == "HY3 求解过程":
            inner = _process_solve(inner)
        elif label == "过程评估判定":
            inner = _process_verdict(inner)
        opened = " open" if label == "过程评估判定" else ""
        out.append(
            f'<details class="case-sec"{opened}><summary>{label}</summary>'
            f'<div class="sec-body">{inner}</div></details>\n'
        )
        pos = end
    out.append(body[pos:])
    return "".join(out)


def _case_headers(body: str) -> str:
    """案例标题拆成「题号 + 名称」，紧跟的信息条收成三枚 chip。"""
    body = re.sub(r'<h3 id="[^"]*">([AC]\d{4})( · [^<]+)?</h3>',
                  lambda m: '<h3 class="case-title"><span class="qid">' + m.group(1) + "</span>"
                            + (m.group(2) or "").lstrip(" ·") + "</h3>", body)
    return body.replace("<ul>\n<li>难度：", '<ul class="meta">\n<li>难度：')


def render(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8")
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
        extension_configs={"toc": {"toc_depth": "1-4"}},
    )
    body = md.convert(text)
    body = re.sub(r'<pre><code class="language-prompt">(.*?)</code></pre>',
                  lambda m: '<div class="prompt md-bound" data-prompt="1">'
                            + html.escape(html.unescape(m.group(1))) + "</div>",
                  body, flags=re.S)
    body = _collapsible(body)
    body = _wrap_code(body)
    body = _case_headers(body)
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
                        toc=_build_toc(md.toc_tokens), body=body.strip(), page_js=PAGE_JS),
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
