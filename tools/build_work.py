#!/usr/bin/env python3
"""Build the /work/ section of johnnyk1090.github.io from the public project repositories.

Every project gets a page with its README and every file in the repository, readable in place:
notebooks are rendered with their outputs, source and text files are shown with highlighting,
images are copied next to the page, and data or model files get a direct download link.
Nothing on these pages links to a repository page, so a visitor reads the code without ever
landing on GitHub's star and fork counters (GitHub has no setting that hides those).

Usage: build_work.py <site_dir>
  Reads the account from GITHUB_REPOSITORY_OWNER (default johnnyk1090) and, when set,
  authenticates API calls with GITHUB_TOKEN. Writes <site_dir>/work/ and <site_dir>/sitemap.xml.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import markdown
import nbformat
from nbconvert import HTMLExporter
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer_for_filename
from pygments.util import ClassNotFound

OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "johnnyk1090")
SITE = f"https://{OWNER.lower()}.github.io"
# The profile's own order comes first; any other public repository follows, newest push first.
FEATURED = [
    "AI-Powered-Analytics-App",
    "AB-Testing-and-KPIs-for-Appstore-Games",
    "Predictive-Retail-Analytics-EDA-to-Forecasting",
    "A-Tale-of-Two-Models-U2Net-vs.-CNN-for-Medical-Diagnosis",
    "ESG-Dashboard",
    "Quantifying-Bias-A-Website-Ratings-Study",
]
SKIP = {OWNER.lower(), f"{OWNER.lower()}.github.io"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
VIDEO_EXT = {".mp4", ".webm"}
COPY_LIMIT = 25 * 1024 * 1024      # media above this is linked for download instead of copied
INLINE_LIMIT = 256 * 1024          # text above this is shown as its first lines plus a download
PREVIEW_LINES = 60
TEXT_NAMES = {"dockerfile", "instructions", "read_me", "makefile", "license"}
CODE_STYLE = "github-dark"


def api(path: str):
    req = urllib.request.Request(f"https://api.github.com{path}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def project_repos() -> list[dict]:
    repos, page = [], 1
    while True:
        batch = api(f"/users/{OWNER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    repos = [r for r in repos if not r["private"] and not r["fork"] and not r["archived"]
             and r["name"].lower() not in SKIP]
    rank = {n: i for i, n in enumerate(FEATURED)}
    repos.sort(key=lambda r: (rank.get(r["name"], len(FEATURED)), -_ts(r["pushed_at"])))
    return repos


def _ts(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def anchor(path: str) -> str:
    return "f-" + re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:65536].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def lexer_for(path: str, text: str):
    name = Path(path).name.lower()
    if name == "dockerfile":
        return get_lexer_by_name("docker")
    if name.endswith(".csv"):
        return TextLexer()
    try:
        return guess_lexer_for_filename(path, text)
    except ClassNotFound:
        return TextLexer()


def code_html(path: str, text: str) -> str:
    fmt = HtmlFormatter(cssclass="hl", linenos="table", lineanchors=anchor(path), anchorlinenos=True)
    return highlight(text, lexer_for(path, text), fmt)


def title_of(readme: str, repo: str) -> str:
    m = re.search(r'<img[^>]*src="assets/banner\.svg"[^>]*alt="([^"]+)"', readme)
    if m:
        first = re.split(r"(?<=[^.])\.\s", m.group(1), maxsplit=1)[0].rstrip(".")
        if 3 <= len(first) <= 90:
            return first
    return repo.replace("-", " ")


# ── shared chrome ────────────────────────────────────────────────────────────────────────
CSS = """
:root{color-scheme:dark;--bg:#07070a;--panel:#0f0f14;--line:#24222b;--text:#ece6da;--mute:#a49d90;
--gold:#E9B872;--cream:#F6DCAE;--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 var(--sans)}
a{color:var(--cream);text-decoration-color:rgba(233,184,114,.45);text-underline-offset:3px}
a:hover{color:var(--gold)}a:focus-visible{outline:2px solid var(--gold);outline-offset:3px;border-radius:3px}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
header.top{position:sticky;top:0;z-index:5;background:rgba(7,7,10,.86);backdrop-filter:blur(8px);
-webkit-backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;gap:18px;align-items:center;height:52px;font:500 12px/1 var(--mono);
letter-spacing:.2em;text-transform:uppercase}
header.top a{text-decoration:none;color:var(--mute)}header.top a:hover,header.top a[aria-current]{color:var(--cream)}
header.top .sp{flex:1}
h1{font:600 clamp(28px,5vw,44px)/1.15 var(--sans);letter-spacing:-.01em;margin:44px 0 10px}
h2{font:600 22px/1.3 var(--sans);margin:40px 0 12px}h3{font:600 18px/1.35 var(--sans);margin:28px 0 10px}
.lede{color:var(--mute);font-size:18px;margin:0 0 18px;max-width:70ch}
.tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px;padding:0;list-style:none}
.tags li{font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--gold);
border:1px solid rgba(233,184,114,.35);border-radius:999px;padding:7px 11px}
.label{font:500 11px/1 var(--mono);letter-spacing:.22em;text-transform:uppercase;color:var(--gold);margin:56px 0 14px}
.readme{border-top:1px solid var(--line);padding-top:8px}
.readme img{max-width:100%;height:auto;border-radius:6px}
.readme table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}
.readme td,.readme th{border:1px solid var(--line);padding:8px}
.readme code,.file code{font-family:var(--mono);font-size:.9em}
.readme :not(pre)>code{background:#17161c;border:1px solid var(--line);border-radius:5px;padding:1px 6px}
.readme pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;overflow-x:auto}
.tree{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tree li{display:flex;gap:12px;align-items:baseline;padding:10px 14px;border-top:1px solid var(--line);min-width:0}
.tree li:first-child{border-top:0}
.tree a{font-family:var(--mono);font-size:14px;overflow-wrap:anywhere;flex:1;min-width:0}
.tree .k{font:500 10px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--mute);white-space:nowrap}
.file{margin:28px 0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--panel)}
.file>.fh{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);
font:13px/1.4 var(--mono)}
.file>.fh b{font-weight:600;color:var(--cream);overflow-wrap:anywhere;flex:1;min-width:0}
.file>.fh span{color:var(--mute)}
.file>.body{overflow-x:auto}
.file>.body img,.file>.body video{display:block;max-width:100%;height:auto;margin:0 auto;background:#fff1}
.file>.note{padding:12px 14px;color:var(--mute);font-size:14px;border-top:1px solid var(--line)}
.hl{margin:0}.hl pre{margin:0;padding:12px 14px;font:13px/1.55 var(--mono);background:transparent}
.hl table{border-collapse:collapse;width:100%}.hl td{padding:0;vertical-align:top}
.hl td.linenos{width:1%;user-select:none;border-right:1px solid var(--line)}
.hl td.linenos pre{color:#5f5a66;text-align:right}.hl td.linenos a{color:inherit;text-decoration:none}
.btn{display:inline-block;font:500 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
color:var(--cream);border:1px solid rgba(233,184,114,.55);border-radius:999px;padding:9px 13px;text-decoration:none}
.btn:hover{background:rgba(233,184,114,.14)}
.clone{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 8px}
.clone code{font:13px/1.5 var(--mono);background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:9px 12px;overflow-wrap:anywhere;flex:1;min-width:0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin:28px 0 64px}
.card{display:flex;flex-direction:column;gap:10px;padding:18px;border:1px solid var(--line);border-radius:12px;
background:var(--panel);text-decoration:none;color:var(--text);min-width:0}
.card:hover{border-color:rgba(233,184,114,.6)}
.card img{width:100%;height:auto;border-radius:8px;background:#000}
.card h3{margin:4px 0 0;color:var(--cream)}.card p{margin:0;color:var(--mute);font-size:15px}
.card .meta{margin-top:auto;font:500 11px/1.6 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--gold)}
footer{border-top:1px solid var(--line);margin-top:64px;padding:28px 0 48px;color:var(--mute);font-size:14px}
@media (max-width:640px){header.top .wrap{gap:12px;letter-spacing:.14em}.file>.fh{font-size:12px}}
"""


def page(title: str, body: str, desc: str, path: str, current: str = "work") -> str:
    canon = f"{SITE}{path}"
    nav = (f'<a href="/" {"aria-current=page" if current == "film" else ""}>Film</a>'
           f'<a href="/work/" {"aria-current=page" if current == "work" else ""}>Work</a>'
           f'<span class="sp"></span><a href="https://github.com/{OWNER}">Profile</a>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canon}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{SITE}/film-still.jpg">
<meta name="theme-color" content="#07070a">
<link rel="stylesheet" href="/work/work.css">
</head>
<body>
<header class="top"><div class="wrap">{nav}</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">John Konteas · selected work. Every file on these pages is the project's own source, rebuilt automatically from the repository.</div></footer>
</body>
</html>
"""


# ── notebooks ────────────────────────────────────────────────────────────────────────────
_EXPORTER = HTMLExporter(template_name="lab", theme="dark")
PLOTLY_MIME = "application/vnd.plotly.v1+json"
# The notebooks were written with plotly.py 5.x, whose charts target plotly.js 2.x (3.0 removed
# attributes they may carry), so they are drawn with the last 2.x release, pinned and hash-checked.
PLOTLY_JS = ('<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.3/plotly.min.js" '
             'integrity="sha384-MqL7Cy3itNqCI1Wlc926K0XhyRKJ/NMqTaytIIEB+QIdInOploxqRIHRKLlhPykM" '
             'crossorigin="anonymous"></script>')


def plotly_to_html(nb) -> bool:
    """Give every chart stored only as plotly JSON an HTML form that draws it; the exporter
    has no renderer for that type and would otherwise drop the chart from the page."""
    n = 0
    for cell in nb.cells:
        for o in cell.get("outputs", []):
            data = o.get("data", {})
            if PLOTLY_MIME in data and "text/html" not in data:
                fig = data[PLOTLY_MIME]
                cfg = {**fig.get("config", {}), "responsive": True}
                # the page sets the width: a width fixed for the notebook window would clip on a phone
                layout = {k: v for k, v in fig.get("layout", {}).items() if k != "width"} | {"autosize": True}
                dump = lambda v: json.dumps(v, separators=(",", ":")).replace("</", "<\\/")
                # on a narrow screen the legend goes under the plot so it does not squeeze it away
                data["text/html"] = (
                    f'<div id="plotly-{n}" style="width:100%;min-height:450px"></div><script>(function(){{'
                    f'var el=document.getElementById("plotly-{n}"),L={dump(layout)};'
                    'if(el.clientWidth<600){L.legend=Object.assign({},L.legend,{orientation:"h",x:0,y:-0.25,'
                    'xanchor:"left",yanchor:"top"});L.height=Math.max(L.height||450,640);'
                    'L.title=typeof L.title==="object"?Object.assign({},L.title,{font:Object.assign({},'
                    '(L.title||{}).font,{size:13})}):L.title;}'
                    f'Plotly.newPlot(el,{dump(fig.get("data", []))},L,{json.dumps(cfg)});}})();</script>')
                n += 1
    return n > 0


def render_notebook(src: Path, out: Path, back: str, back_label: str, title: str) -> None:
    nb = nbformat.read(src, as_version=4)
    has_plotly = plotly_to_html(nb)
    body, _ = _EXPORTER.from_notebook_node(nb, resources={"metadata": {"name": title}})
    if has_plotly:  # before the template's require.js, so the library defines its global
        body = re.sub(r"(<meta charset=[^>]*>)", lambda m: m.group(1) + PLOTLY_JS, body, count=1)
    bar = (f'<div style="position:sticky;top:0;z-index:50;display:flex;gap:16px;align-items:center;'
           f'padding:12px 16px;background:rgba(7,7,10,.92);border-bottom:1px solid #24222b;'
           f'font:500 12px/1.3 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.12em;text-transform:uppercase">'
           f'<a href="{esc(back)}" style="color:#F6DCAE;text-decoration:none">&larr; {esc(back_label)}</a>'
           f'<span style="color:#a49d90;overflow-wrap:anywhere">{esc(src.name)}</span></div>')
    body = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + bar, body, count=1)
    body = body.replace("<head>", '<head>\n<meta name="viewport" content="width=device-width, initial-scale=1">'
                        f'\n<link rel="canonical" href="{SITE}{back}notebooks/{urllib.parse.quote(out.name)}">', 1)
    body = re.sub(r"<title>.*?</title>", f"<title>{esc(src.name)} · {esc(title)}</title>", body, count=1, flags=re.S)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")


# ── one project ──────────────────────────────────────────────────────────────────────────
def build_project(repo: dict, work: Path, tmp: Path) -> dict:
    name, branch = repo["name"], repo["default_branch"]
    src = tmp / name
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", branch,
                    f"https://github.com/{OWNER}/{name}.git", str(src)], check=True)
    files = subprocess.run(["git", "-C", str(src), "ls-files", "-z"], check=True,
                           capture_output=True).stdout.decode().split("\0")
    files = sorted((f for f in files if f), key=lambda p: (p.count("/"), p.lower()))
    out = work / name
    out.mkdir(parents=True, exist_ok=True)
    raw = f"https://raw.githubusercontent.com/{OWNER}/{name}/{branch}/"
    base = f"/work/{name}/"

    readme_path = next((f for f in files if f.lower() == "readme.md"), None)
    readme_md = (src / readme_path).read_text(encoding="utf-8") if readme_path else ""
    title = title_of(readme_md, name)
    desc = repo.get("description") or title

    targets: dict[str, str] = {}   # repository path → where this site shows it
    blocks, tree = [], []
    for f in files:
        p = src / f
        if f == readme_path or f in (".gitattributes", ".gitignore"):
            continue
        size = p.stat().st_size
        ext = p.suffix.lower()
        a = anchor(f)
        dl = raw + urllib.parse.quote(f)
        head = f'<div class="fh"><b>{esc(f)}</b><span>{human_size(size)}</span><a class="btn" href="{dl}" download>Download</a></div>'
        if ext == ".ipynb":
            nb_out = out / "notebooks" / (Path(f).with_suffix(".html").name)
            render_notebook(p, nb_out, base, title, title)
            href = f"{base}notebooks/{urllib.parse.quote(nb_out.name)}"
            targets[f] = href
            tree.append((f, href, "notebook"))
            blocks.append(f'<section class="file" id="{a}">{head}<div class="note">Rendered with every output: '
                          f'<a href="{href}">read the notebook</a>.</div></section>')
            continue
        targets[f] = f"#{a}"
        if ext in IMAGE_EXT or ext in VIDEO_EXT:
            if size <= COPY_LIMIT:
                dst = out / "files" / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst)
                url = base + "files/" + urllib.parse.quote(f)
                targets[f + "#asset"] = url
                media = (f'<video src="{url}" controls preload="metadata" playsinline></video>' if ext in VIDEO_EXT
                         else f'<img src="{url}" alt="{esc(Path(f).stem.replace("_", " "))}" loading="lazy">')
                blocks.append(f'<section class="file" id="{a}">{head}<div class="body">{media}</div></section>')
            else:
                blocks.append(f'<section class="file" id="{a}">{head}<div class="note">Large media file; use Download.</div></section>')
            tree.append((f, f"#{a}", "video" if ext in VIDEO_EXT else "image"))
            continue
        data = p.read_bytes()
        if is_text(data):
            text = data.decode("utf-8", errors="replace")
            note = ""
            if size > INLINE_LIMIT or (ext in (".csv", ".tsv") and text.count("\n") > PREVIEW_LINES):
                text = "\n".join(text.splitlines()[:PREVIEW_LINES])
                note = f'<div class="note">First {PREVIEW_LINES} lines shown; the full file is in Download.</div>'
            blocks.append(f'<section class="file" id="{a}">{head}<div class="body">{code_html(f, text)}</div>{note}</section>')
            tree.append((f, f"#{a}", "data" if ext in (".csv", ".tsv") else "code" if ext in (".py", ".r", ".sql", ".js", ".ts", ".sh") or Path(f).name.lower() == "dockerfile" else "text"))
        else:
            blocks.append(f'<section class="file" id="{a}">{head}<div class="note">Binary file (data or a trained model); use Download.</div></section>')
            tree.append((f, f"#{a}", "binary"))

    readme_html = ""
    if readme_md:
        readme_html = markdown.markdown(readme_md, extensions=["fenced_code", "tables", "sane_lists", "codehilite"],
                                        extension_configs={"codehilite": {"css_class": "hl", "guess_lang": False}})

        def fix(m: re.Match) -> str:
            attr, url = m.group(1), html.unescape(m.group(2))
            if re.match(r"^(https?:|mailto:|#|/)", url):
                if url.rstrip("/") == f"https://github.com/{OWNER}":
                    return f'{attr}="/work/"'
                return m.group(0)
            path = urllib.parse.unquote(url.split("#")[0]).lstrip("./")
            if attr == "src":
                hit = targets.get(path + "#asset")
                return f'{attr}="{hit or raw + urllib.parse.quote(path)}"'
            hit = targets.get(path)
            return f'{attr}="{hit or raw + urllib.parse.quote(path)}"'

        readme_html = re.sub(r'\b(src|href)="([^"]*)"', fix, readme_html)
        readme_html = readme_html.replace("← back to the profile", "← all work")

    tree_html = "".join(f'<li><a href="{esc(h)}">{esc(f)}</a><span class="k">{k}</span></li>' for f, h, k in tree)
    topics = "".join(f"<li>{esc(t)}</li>" for t in repo.get("topics") or [])
    zip_url = f"https://codeload.github.com/{OWNER}/{name}/zip/refs/heads/{urllib.parse.quote(branch)}"
    body = f"""
<h1>{esc(title)}</h1>
<p class="lede">{esc(desc)}</p>
<ul class="tags">{topics}</ul>
<div class="clone"><code>git clone https://github.com/{OWNER}/{esc(name)}.git</code><a class="btn" href="{zip_url}">Download ZIP</a></div>
<div class="readme">{readme_html}</div>
<p class="label" id="code">The code · {len(tree)} file{'s' if len(tree) != 1 else ''}</p>
<ul class="tree">{tree_html}</ul>
{''.join(blocks)}
"""
    (out / "index.html").write_text(page(f"{title} · John Konteas", body, desc, base), encoding="utf-8")
    banner = "files/assets/banner.svg" if (out / "files/assets/banner.svg").exists() else None
    notebooks = [p for p in tree if p[2] == "notebook"]
    return {"name": name, "title": title, "desc": desc, "banner": banner, "files": len(tree),
            "notebooks": len(notebooks), "pages": [base] + [h for _, h, _ in notebooks]}


def build(site: Path) -> None:
    work = site / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "work.css").write_text(CSS + HtmlFormatter(style=CODE_STYLE).get_style_defs(".hl"), encoding="utf-8")
    built = []
    with tempfile.TemporaryDirectory() as t:
        for repo in project_repos():
            built.append(build_project(repo, work, Path(t)))
            print(f"built {repo['name']}: {built[-1]['files']} files, {built[-1]['notebooks']} notebooks", flush=True)
    cards = "".join(
        f'<a class="card" href="/work/{esc(b["name"])}/">'
        + (f'<img src="/work/{esc(b["name"])}/{b["banner"]}" alt="" width="1000" height="300"'
           f'{" loading=lazy" if i >= 6 else ""}>' if b["banner"] else "")
        + f'<h3>{esc(b["title"])}</h3><p>{esc(b["desc"])}</p>'
        f'<span class="meta">{b["files"]} files{" · " + str(b["notebooks"]) + " notebook" + ("s" if b["notebooks"] != 1 else "") if b["notebooks"] else ""} · <span style="white-space:nowrap">read the code</span></span></a>'
        for i, b in enumerate(built))
    body = (f'<h1>Selected work</h1><p class="lede">Every project with its full source, readable here: '
            f'notebooks with their outputs, scripts, data previews and figures.</p><div class="cards">{cards}</div>')
    (work / "index.html").write_text(page("Selected work · John Konteas", body,
                                          "Data science projects with their complete, readable source.", "/work/"),
                                     encoding="utf-8")
    urls = ["/", "/work/"] + [u for b in built for u in b["pages"]]
    (site / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{esc(SITE + u)}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    print(f"done: {len(built)} projects, {len(urls)} pages")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
