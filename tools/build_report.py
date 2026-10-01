#!/usr/bin/env python3
"""Build report.html from LIBRA.md (Bootstrap 5.3 + Mermaid via CDN)."""
import html
import re
import sys
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "LIBRA.md"
OUT = ROOT / "report.html"

text = SRC.read_text()

# Drop the title block and contents list; the template provides its own.
start = re.search(r"(?m)^## ", text).start()
body_md = text[start:]

# Pull mermaid blocks out so markdown does not touch them.
mermaid_blocks = []


FLOW_KEYWORDS = {"flowchart", "graph", "LR", "RL", "TB", "BT", "TD", "subgraph", "end", "direction"}


def namespace_flowchart(src, prefix):
    """Prefix node/subgraph ids so diagrams on one page cannot collide.

    Labels ([...], |...|, "...") are left alone so displayed text is unchanged.
    """
    src = re.sub(r"(?m)^(\s*subgraph )(\w+)\s*$", r"\1\2[\2]", src)
    tokens = re.split(r'(\(\([^)]*\)\)|\[[^\]]*\]|\|[^|]*\||"[^"]*")', src)
    for i in range(0, len(tokens), 2):  # even indices are non-label text
        tokens[i] = re.sub(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            lambda m: m.group(0) if m.group(0) in FLOW_KEYWORDS else prefix + m.group(0),
            tokens[i],
        )
    return "".join(tokens)



def layers_html(src):
    """Render a flowchart that is just a stack of subgraphs as Bootstrap layer rows."""
    layers = []
    for m in re.finditer(r"subgraph\s+\w+\[(.*?)\]\s*\n(.*?)\n\s*end", src, re.S):
        nodes = re.findall(r"^\s*\w+\[(.*?)\]\s*$", m.group(2), re.M)
        layers.append((m.group(1), nodes))
    rows = []
    for n, (title, nodes) in enumerate(layers):
        chips = "".join(f'<span class="node-chip">{html.escape(x)}</span>' for x in nodes)
        rows.append(f'<div class="layer"><div class="layer-title">{html.escape(title)}</div>'
                    f'<div class="layer-nodes">{chips}</div></div>')
        if n < len(layers) - 1:
            rows.append('<div class="layer-arrow" aria-hidden="true">&#9660;</div>')
    return ('<div class="layer-stack">' + "".join(rows) +
            '<div class="text-body-secondary small text-center mt-2">Each layer calls the layer(s) below it.</div></div>')

def stash_mermaid(m):
    src = m.group(1)
    if src.count("subgraph ") >= 5:
        mermaid_blocks.append(("layers", layers_html(src)))
        return f"\n\nMERMAIDPLACEHOLDER{len(mermaid_blocks) - 1}\n\n"
    if src.lstrip().startswith("flowchart"):
        src = namespace_flowchart(src, f"d{len(mermaid_blocks)}_")
    mermaid_blocks.append(src)
    return f"\n\nMERMAIDPLACEHOLDER{len(mermaid_blocks) - 1}\n\n"


body_md = re.sub(r"```mermaid\n(.*?)```", stash_mermaid, body_md, flags=re.S)


def fix_list_spacing(md_text):
    """Python-Markdown needs a blank line before a list; GitHub does not."""
    chunks = re.split(r"(```.*?```)", md_text, flags=re.S)
    for i, chunk in enumerate(chunks):
        if chunk.startswith("```"):
            continue
        chunks[i] = re.sub(
            r"(?m)^([^\s\-*|>#\d][^\n]*)\n((?:- |\* |\d+\. |\|))", r"\1\n\n\2", chunk
        )
    return "".join(chunks)


body_md = fix_list_spacing(body_md)

# Split into sections on level-2 headings.
parts = re.split(r"(?m)^## ", body_md)
sections = []
for p in parts:
    if not p.strip():
        continue
    title, _, rest = p.partition("\n")
    rest = rest.strip()
    rest = re.sub(r"(?m)^---\s*$", "", rest).strip()
    sections.append((title.strip(), rest))


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "attr_list"])


def render(md_text):
    md.reset()
    h = md.convert(md_text)
    # Bootstrap tables
    h = h.replace("<table>", '<div class="table-responsive"><table class="table table-sm table-striped table-hover align-middle">')
    h = h.replace("</table>", "</table></div>")
    # sub-headings
    h = re.sub(r"<h3( id=\"[^\"]*\")?>", r'<h3\1 class="h5 mt-4 mb-2 text-primary-emphasis">', h)
    h = re.sub(r"<h4( id=\"[^\"]*\")?>", r'<h4\1 class="h6 mt-3 mb-2">', h)
    # code blocks
    h = h.replace("<pre><code>", '<pre class="diagram"><code>')
    # (verify) badges
    h = h.replace("<em>(verify)</em>", '<span class="badge text-bg-warning verify">verify</span>')
    h = re.sub(
        r"<em>\(verify[^<]*\)</em>",
        '<span class="badge text-bg-warning verify">verify</span>',
        h,
    )
    # mermaid
    def put_mermaid(m):
        idx = int(m.group(1))
        if isinstance(mermaid_blocks[idx], tuple):
            return mermaid_blocks[idx][1]
        return (
            '<figure class="figure w-100 diagram-fig">'
            f'<pre class="mermaid">{html.escape(mermaid_blocks[idx])}</pre>'
            "</figure>"
        )

    h = re.sub(r"<p>MERMAIDPLACEHOLDER(\d+)</p>", put_mermaid, h)

    def put_wiring(m):
        name = m.group(1)
        return f'<figure class="wiring">{wiring.DIAGRAMS[name]()}</figure>'

    h = re.sub(r"<!--\s*wiring:(\w+)\s*-->", put_wiring, h)
    return h


nav_items = []
section_html = []
for i, (title, rest) in enumerate(sections):
    # Headings are "Title {#anchor}": the anchor is the stable id; sections are numbered by position.
    mo = re.match(r"(.*?)\s*\{#([\w-]+)\}\s*$", title)
    name, sid = (mo.group(1), mo.group(2)) if mo else (title, slug(title))
    num = str(i + 1)
    nav_items.append(
        f'<a class="nav-link" href="#{sid}"><span class="num">{num}</span>{html.escape(name)}</a>'
    )
    section_html.append(
        f'<section id="{sid}" class="report-section">\n'
        f'<div class="section-head"><span class="section-num">{num}</span>'
        f"<h2>{html.escape(name)}</h2></div>\n"
        f"{render(rest)}\n</section>"
    )

TEMPLATE = Path(__file__).with_name("report_template.html").read_text()
out = (
    TEMPLATE.replace("{{NAV}}", "\n".join(nav_items))
    .replace("{{SECTIONS}}", "\n".join(section_html))
    .replace("{{WIRING_CSS}}", wiring.CSS)
)
OUT.write_text(out)
print(f"wrote {OUT} ({len(out)//1024} KB, {len(sections)} sections, {len(mermaid_blocks)} diagrams)")
sys.exit(0)
