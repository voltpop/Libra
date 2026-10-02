#!/usr/bin/env python3
"""Build software-map.html from tools/softmap_data.py.

The build fails if the data breaks the architecture rules, so the map cannot drift
from the rules written in LIBRA.md.
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import softmap_data as D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "software-map.html"
def esc(x):
    return html.escape(x).replace("`", "")

C = {c["id"]: c for c in D.COMPONENTS}
LAYER = {c["id"]: c["layer"] for c in D.COMPONENTS}


# ---------------------------------------------------------------- validation
def validate():
    errs, notes = [], []
    anchors = set(re.findall(r"\{#([\w-]+)\}", (ROOT / "LIBRA.md").read_text()))
    ids = list(C)
    if len(ids) != len(set(ids)):
        errs.append("duplicate component ids")

    fn_owner = {}
    for c in D.COMPONENTS:
        if c["anchor"] not in anchors:
            errs.append(f"{c['id']}: anchor #{c['anchor']} is not in LIBRA.md")
        for sig, _ in c["funcs"]:
            m = re.search(r"\b(lb_\w+)\s*\(", sig)
            if not m:
                errs.append(f"{c['id']}: cannot read function name in {sig!r}")
                continue
            name = m.group(1)
            if name in fn_owner:
                errs.append(f"function {name} defined in both {fn_owner[name]} and {c['id']}")
            fn_owner[name] = c["id"]
        for kind in ("uses", "notifies"):
            for t in c[kind]:
                if t not in C:
                    errs.append(f"{c['id']}: {kind} unknown component {t}")

    # layering: calls go to the same or a lower layer; callbacks go strictly upward
    for c in D.COMPONENTS:
        for t in c["uses"]:
            if t in C and LAYER[t] < LAYER[c["id"]]:
                errs.append(f"layering: {c['id']} calls up into {t}")
        for t in c["notifies"]:
            if t in C and LAYER[t] >= LAYER[c["id"]]:
                errs.append(f"layering: {c['id']} notifies {t}, which is not above it")

    # the call graph must be acyclic
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            errs.append("call cycle: " + " -> ".join(path + [n]))
            return
        if state.get(n) == 2:
            return
        state[n] = 1
        for t in C[n]["uses"]:
            if t in C:
                visit(t, path + [n])
        state[n] = 2

    for n in C:
        visit(n, [])

    # flows must follow declared relationships and name real functions
    for fl in D.FLOWS:
        for i, (a, b, fn, _) in enumerate(fl["steps"], 1):
            where = f"flow {fl['id']} step {i}"
            if a not in C or b not in C:
                errs.append(f"{where}: unknown component")
                continue
            if fn not in fn_owner:
                errs.append(f"{where}: unknown function {fn}")
            elif fn_owner[fn] != b:
                errs.append(f"{where}: {fn} belongs to {fn_owner[fn]}, not {b}")
            if a != b and b not in C[a]["uses"] and b not in C[a]["notifies"]:
                errs.append(f"{where}: {a} -> {b} is not a declared relationship")

    used_by = {n: set() for n in C}
    for c in D.COMPONENTS:
        for t in c["uses"] + c["notifies"]:
            if t in used_by:
                used_by[t].add(c["id"])
    for n, u in used_by.items():
        if not u:
            notes.append(f"{n}")
    return errs, notes, fn_owner


errs, NOTES, FN = validate()
if errs:
    print("software map validation FAILED:")
    for e in errs:
        print("  -", e)
    sys.exit(1)

# ---------------------------------------------------------------- layout
NW, NH, CGAP, LEFT, PITCH, TOP = 128, 40, 24, 200, 84, 24
ROWS = max(c["row"] for c in D.COMPONENTS) + 1


def node_box(c):
    x = LEFT + c["col"] * (NW + CGAP)
    w = c["span"] * NW + (c["span"] - 1) * CGAP
    y = TOP + c["row"] * PITCH
    return x, y, w, NH


NODES = {}
for c in D.COMPONENTS:
    x, y, w, h = node_box(c)
    NODES[c["id"]] = dict(x=x, y=y, w=w, h=h, row=c["row"], col=c["col"], span=c["span"])
EDGES = [dict(f=c["id"], t=t, k="call") for c in D.COMPONENTS for t in c["uses"]] + \
        [dict(f=c["id"], t=t, k="cb") for c in D.COMPONENTS for t in c["notifies"]]
SVG_W = LEFT + 6 * (NW + CGAP) - CGAP + 20
SVG_H = TOP + ROWS * PITCH


def map_svg():
    p = [f'<svg id="map" class="map-svg" viewBox="0 0 {SVG_W} {SVG_H}" role="img" '
         f'aria-label="Component dependency map" xmlns="http://www.w3.org/2000/svg">',
         '<defs>'
         '<marker id="m-out" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk-out"/></marker>'
         '<marker id="m-cb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk-cb"/></marker>'
         '<marker id="m-in" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk-in"/></marker>'
         '<marker id="m-incb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk-incb"/></marker>'
         '</defs>']
    # layer bands
    for li, name in enumerate(D.LAYERS):
        rows = [c["row"] for c in D.COMPONENTS if c["layer"] == li]
        y0 = TOP + min(rows) * PITCH - 10
        y1 = TOP + max(rows) * PITCH + NH + 10
        p.append(f'<rect class="band b{li % 2}" x="8" y="{y0}" width="{SVG_W - 16}" height="{y1 - y0}" rx="8"/>')
        p.append(f'<text class="bandlbl" x="20" y="{y0 + 22}">{esc(name)}</text>')
    p.append('<g id="edges"></g>')
    for c in D.COMPONENTS:
        n = NODES[c["id"]]
        cls = "node untrusted" if c["untrusted"] else "node"
        p.append(f'<g class="{cls}" data-id="{c["id"]}" tabindex="0" role="button" aria-label="{esc(c["id"])}">'
                 f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="7"/>'
                 f'<text class="nn" x="{n["x"] + n["w"] / 2}" y="{n["y"] + 18}" text-anchor="middle">{esc(c["id"])}</text>'
                 f'<text class="ns" x="{n["x"] + n["w"] / 2}" y="{n["y"] + 33}" text-anchor="middle">{len(c["funcs"])} fn, core {esc(c["core"].split(" ")[0])}</text>'
                 f'</g>')
    p.append('</svg>')
    return "".join(p)


# ---------------------------------------------------------------- sections
def chips(ids, cls="chip"):
    if not ids:
        return '<span class="text-body-secondary small">none</span>'
    return " ".join(f'<a class="{cls}" href="#c-{i}">{esc(i)}</a>' for i in sorted(ids))


def cards():
    used_by = {n: set() for n in C}
    notified_by = {n: set() for n in C}
    for c in D.COMPONENTS:
        for t in c["uses"]:
            used_by[t].add(c["id"])
        for t in c["notifies"]:
            notified_by[t].add(c["id"])
    out = []
    for li, lname in enumerate(D.LAYERS):
        out.append(f'<h3 class="h5 mt-4 layer-h">{esc(lname)}</h3>')
        for c in [x for x in D.COMPONENTS if x["layer"] == li]:
            badges = f'<span class="badge text-bg-secondary">core {esc(c["core"])}</span>'
            if c["untrusted"]:
                badges += ' <span class="badge text-bg-danger">untrusted input</span>'
            t_rows = "".join(
                f"<tr><td><code>{esc(n)}</code></td><td>{esc(k)}</td><td>{esc(d)}</td></tr>" for n, k, d in c["types"])
            types = (f'<h5 class="h6 mt-3">Types</h5><div class="table-responsive"><table class="table table-sm table-striped">'
                     f'<thead><tr><th>Name</th><th>Kind</th><th>Meaning</th></tr></thead><tbody>{t_rows}</tbody></table></div>'
                     if c["types"] else "")
            f_rows = "".join(f"<tr><td><code>{esc(s)}</code></td><td>{esc(d)}</td></tr>" for s, d in c["funcs"])
            notes = ("<ul class='small mb-0'>" + "".join(f"<li>{esc(n)}</li>" for n in c["notes"]) + "</ul>") if c["notes"] else ""
            ext = ", ".join(esc(e) for e in c["ext"]) if c["ext"] else "none"
            out.append(
                f'<article class="card mb-3 comp" id="c-{c["id"]}" data-search="{esc(c["id"] + " " + c["purpose"] + " " + " ".join(s for s, _ in c["funcs"]))}">'
                f'<div class="card-header d-flex flex-wrap gap-2 align-items-center">'
                f'<strong class="fs-6"><code>{esc(c["id"])}</code></strong>{badges}'
                f'<span class="ms-auto small"><a href="report.html#{c["anchor"]}">design section</a> &middot; <a href="#map">map</a></span></div>'
                f'<div class="card-body"><p>{esc(c["purpose"])}</p>'
                f'<div class="row g-3 small"><div class="col-md-6"><div class="rel-k">Calls</div>{chips(c["uses"])}</div>'
                f'<div class="col-md-6"><div class="rel-k">Called by</div>{chips(used_by[c["id"]])}</div>'
                f'<div class="col-md-6"><div class="rel-k">Notifies (registered callback)</div>{chips(c["notifies"], "chip chip-cb")}</div>'
                f'<div class="col-md-6"><div class="rel-k">Notified by</div>{chips(notified_by[c["id"]], "chip chip-cb")}</div></div>'
                f'{types}'
                f'<h5 class="h6 mt-3">Functions</h5><div class="table-responsive"><table class="table table-sm table-striped fn">'
                f'<thead><tr><th>Signature</th><th>What it does</th></tr></thead><tbody>{f_rows}</tbody></table></div>'
                f'<div class="small mt-2"><span class="rel-k">External</span> {ext}</div>'
                f'{"<div class=small mt-2><span class=rel-k>Notes</span>" + notes + "</div>" if notes else ""}'
                f'</div></article>')
    return "\n".join(out)


def flows():
    out = []
    for fl in D.FLOWS:
        rows = []
        for i, (a, b, fn, note) in enumerate(fl["steps"], 1):
            kind = "callback" if b in C[a]["notifies"] else ("internal" if a == b else "call")
            tag = ' <span class="badge text-bg-info">callback</span>' if kind == "callback" else ""
            rows.append(f'<tr><td>{i}</td><td><a href="#c-{a}">{esc(a)}</a></td><td>&rarr;</td>'
                        f'<td><a href="#c-{b}">{esc(b)}</a></td><td><code>{esc(fn)}</code>{tag}</td><td>{esc(note)}</td></tr>')
        out.append(f'<h3 class="h5 mt-4" id="flow-{fl["id"]}">{esc(fl["title"])}</h3>'
                   f'<div class="table-responsive"><table class="table table-sm table-striped">'
                   f'<thead><tr><th>#</th><th>From</th><th></th><th>To</th><th>Function</th><th>Notes</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table></div>')
    return "\n".join(out)


def matrix():
    ids = [c["id"] for c in D.COMPONENTS]
    head = "".join(f'<th class="mx-h"><a href="#c-{i}">{esc(i)}</a></th>' for i in ids)
    body = []
    for c in D.COMPONENTS:
        cells = []
        for t in ids:
            if t in c["uses"]:
                cells.append('<td class="mx-c" title="calls">C</td>')
            elif t in c["notifies"]:
                cells.append('<td class="mx-b" title="notifies">B</td>')
            else:
                cells.append("<td></td>")
        body.append(f'<tr><th class="mx-r"><a href="#c-{c["id"]}">{esc(c["id"])}</a></th>{"".join(cells)}</tr>')
    return (f'<div class="table-responsive"><table class="mx"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def checks():
    n_fn = sum(len(c["funcs"]) for c in D.COMPONENTS)
    n_steps = sum(len(f["steps"]) for f in D.FLOWS)
    n_calls = sum(1 for e in EDGES if e["k"] == "call")
    n_cb = len(EDGES) - n_calls
    rows = [
        ("Components and functions", f"{len(D.COMPONENTS)} components, {n_fn} functions, {len(FN)} unique names"),
        ("Relationships", f"{n_calls} calls and {n_cb} registered callbacks"),
        ("Layering", "Every call goes to the same or a lower layer; every callback goes strictly upward"),
        ("Call graph", "Acyclic"),
        ("Call flows", f"{len(D.FLOWS)} flows, {n_steps} steps; every step follows a declared relationship and names a real function"),
        ("Design links", "Every component links to a section anchor that exists in LIBRA.md"),
        ("Reachability", "Every component is called by, or notified by, at least one other component" if not NOTES else "Not referenced by any other component: " + ", ".join(NOTES)),
    ]
    out = "".join(f'<tr><td><span class="badge text-bg-success">pass</span></td><td>{esc(a)}</td><td>{esc(b)}</td></tr>' for a, b in rows)
    return (f'<div class="table-responsive"><table class="table table-sm"><tbody>{out}</tbody></table></div>'
            + (f'<p class="small mb-1">Entry points: nothing calls these, because they are driven by events, the host or the user.</p><p class="small">{" ".join("<code>" + esc(i) + "</code>" for i in NOTES)}</p>' if NOTES else ""))


def open_points():
    rows = "".join(f"<tr><td><strong>{esc(a)}</strong></td><td>{esc(b)}</td></tr>" for a, b in D.OPEN_POINTS)
    return f'<div class="table-responsive"><table class="table table-sm table-striped"><tbody>{rows}</tbody></table></div>'


nav = "".join(f'<a class="nav-link" href="#{i}">{esc(t)}</a>' for i, t in
              [("map", "Map"), ("components", "Components"), ("flows", "Call flows"), ("matrix", "Matrix"),
               ("checks", "Checks"), ("open", "Open points")])

PAGE = r"""<!doctype html>
<html lang="en" data-bs-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Libra: Software Map</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  :root { --accent:#1f4e79; --accent-soft:#e8f0f8; --accent2:#b4531a; }
  [data-bs-theme="dark"] { --accent:#7fb2e5; --accent-soft:#1b2733; --accent2:#e8a064; }
  html { scroll-behavior:smooth; scroll-padding-top:4.5rem; }
  body { font-size:.95rem; line-height:1.55; }
  main { max-width:1180px; margin:0 auto; padding:0 1.2rem 4rem; }
  .navbar { border-bottom:1px solid var(--bs-border-color); background:var(--bs-tertiary-bg); }
  .navbar .brand { font-weight:700; color:var(--accent); letter-spacing:.02em; }
  h1,h2 { color:var(--accent); }
  h2 { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--bs-border-color); }
  .layer-h { color:var(--bs-secondary-color); text-transform:uppercase; letter-spacing:.06em; font-size:.8rem; }
  code { color:var(--bs-code-color); }
  thead th { background:var(--accent-soft); color:var(--accent); white-space:nowrap; }
  table { font-size:.86rem; }
  table.fn td:first-child { white-space:normal; word-break:break-word; min-width:18rem; }
  .callout { border-left:4px solid var(--accent); background:var(--accent-soft); padding:.8rem 1rem; border-radius:0 .4rem .4rem 0; }
  .rel-k { font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; color:var(--bs-secondary-color); }
  .chip { display:inline-block; border:1px solid var(--bs-border-color); border-radius:.3rem; padding:0 .45rem; margin:0 .2rem .2rem 0; text-decoration:none; font-size:.8rem; background:var(--bs-body-bg); }
  .chip-cb { border-style:dashed; border-color:var(--accent); }
  .comp:target { outline:2px solid var(--accent); }

  /* the map */
  .mapbox { border:1px solid var(--bs-border-color); border-radius:.5rem; padding:.6rem; background:var(--bs-body-bg); overflow-x:auto; }
  .map-svg { width:100%; min-width:760px; height:auto; display:block; }
  .band { stroke:var(--bs-border-color); stroke-width:1; }
  .b0 { fill:var(--bs-tertiary-bg); } .b1 { fill:var(--bs-body-bg); }
  .bandlbl { fill:var(--bs-secondary-color); font-size:11px; font-weight:700; letter-spacing:.05em; text-transform:uppercase; }
  .node { cursor:pointer; }
  .node rect { fill:var(--bs-body-bg); stroke:var(--bs-body-color); stroke-width:1.4; }
  .node.untrusted rect { stroke:#c0392b; stroke-width:2; }
  .node .nn { fill:var(--bs-body-color); font-size:13px; font-weight:700; }
  .node .ns { fill:var(--bs-secondary-color); font-size:10px; }
  .node:hover rect, .node:focus rect { fill:var(--accent-soft); outline:none; }
  .node.sel rect { fill:var(--accent); stroke:var(--accent); }
  .node.sel .nn, .node.sel .ns { fill:#fff; }
  .node.rel rect { stroke:var(--accent); stroke-width:2.2; }
  .node.dim { opacity:.3; }
  .e { fill:none; stroke-width:1.6; }
  .e-out { stroke:var(--bs-body-color); } .e-cb { stroke:var(--accent); stroke-dasharray:6 4; }
  .e-in { stroke:var(--accent2); } .e-incb { stroke:var(--accent2); stroke-dasharray:6 4; }
  .mk-out { fill:var(--bs-body-color); } .mk-cb { fill:var(--accent); }
  .mk-in, .mk-incb { fill:var(--accent2); }
  .legend { font-size:.8rem; display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; margin-top:.6rem; color:var(--bs-secondary-color); }
  .legend svg { vertical-align:middle; margin-right:.3rem; }
  #sel { min-height:5.5rem; }

  /* matrix */
  table.mx { border-collapse:collapse; font-size:.72rem; }
  table.mx td, table.mx th { border:1px solid var(--bs-border-color); text-align:center; padding:0; min-width:1.5rem; height:1.5rem; }
  table.mx .mx-h { height:5.5rem; vertical-align:bottom; background:var(--bs-tertiary-bg); }
  table.mx .mx-h a { writing-mode:vertical-rl; transform:rotate(180deg); text-decoration:none; padding:.2rem 0; display:inline-block; }
  table.mx .mx-r { text-align:right; padding:0 .4rem; background:var(--bs-tertiary-bg); white-space:nowrap; }
  table.mx .mx-r a { text-decoration:none; }
  .mx-c { background:var(--accent); color:#fff; font-weight:700; }
  .mx-b { background:var(--accent-soft); color:var(--accent); font-weight:700; outline:1px dashed var(--accent); outline-offset:-3px; }
  @media print { .navbar, #q { display:none !important; } }
</style>
</head>
<body>
<nav class="navbar sticky-top navbar-expand">
  <div class="container-fluid" style="max-width:1180px">
    <span class="brand me-4">LIBRA &middot; software map</span>
    <div class="navbar-nav flex-wrap">{{NAV}}</div>
    <button class="btn btn-sm btn-outline-secondary ms-auto" id="themeToggle" type="button">Theme</button>
  </div>
</nav>
<main>
<header class="pt-4 pb-2">
  <h1 class="display-6">Libra software map</h1>
  <p class="lead mb-2">The components, types, functions and relationships of the Libra firmware, derived from the
    <a href="report.html#software-architecture">Software architecture</a> section.</p>
  <div class="callout">
    <strong>Status: draft, a proposed design.</strong> Nothing is built. The firmware is C on ESP-IDF, so a "class" is a
    <em>component</em>: a header, an opaque handle or struct, and a set of <code>lb_*</code> functions.
    Signatures are sketches, not final. Generated from <code>tools/softmap_data.py</code> by
    <code>tools/build_softmap.py</code>, which refuses to build if the data breaks the layering rules.
  </div>
</header>

<h2 id="map">Map</h2>
<p>Click a component to draw its relationships. The map has the six layers of the architecture, top to bottom.
  Red outlines mark components that handle untrusted input.</p>
<div class="mapbox">{{MAP}}</div>
<div class="legend">
  <span><svg width="34" height="10"><line x1="0" y1="5" x2="34" y2="5" class="e e-out"/></svg>calls (selected component calls this)</span>
  <span><svg width="34" height="10"><line x1="0" y1="5" x2="34" y2="5" class="e e-in"/></svg>called by</span>
  <span><svg width="34" height="10"><line x1="0" y1="5" x2="34" y2="5" class="e e-cb"/></svg>notifies (registered callback, upward)</span>
  <span><svg width="34" height="10"><line x1="0" y1="5" x2="34" y2="5" class="e e-incb"/></svg>notified by</span>
</div>
<div id="sel" class="card card-body mt-3 small">Select a component on the map.</div>

<h2 id="conventions">Conventions</h2>
<ul>
  <li><strong>Component</strong> = <code>firmware/components/&lt;name&gt;/</code> with a public header <code>include/lb_&lt;name&gt;.h</code>. Everything public is prefixed <code>lb_</code>.</li>
  <li><strong>Calls go down.</strong> A component may call the same layer or a lower one, never higher. The call graph has no cycles.</li>
  <li><strong>Callbacks go up.</strong> Lower layers reach higher ones only through a handler the higher layer registered (<code>lb_*_set_*</code>). The transports and drivers work this way.</li>
  <li><strong>Errors</strong> are returned as <code>lb_err_t</code>. Anything that parses untrusted input (<code>qrparse</code>, <code>usb</code>, <code>openpgp</code>, <code>fido</code>, <code>storage</code>, <code>ble</code>, <code>qr</code>, <code>xch</code>, <code>usbhost</code>) validates every length and is fuzzed on the host.</li>
  <li><strong>Secrets</strong> live in internal RAM where practical and are zeroized after use. Logs never contain secrets or PINs.</li>
  <li><strong>Approval</strong> is only ever granted by <code>session</code>. No other component decides whether a request is approved.</li>
</ul>

<h2 id="components">Components</h2>
<input id="q" class="form-control mb-3" type="search" placeholder="Filter components and functions (for example: sign, counter, usb)">
<div id="cards">{{CARDS}}</div>
<p id="none" class="text-body-secondary" hidden>No component matches.</p>

<h2 id="flows">Call flows</h2>
<p>Each step is one call from one component into another, checked against the declared relationships at build time.</p>
{{FLOWS}}

<h2 id="matrix">Dependency matrix</h2>
<p>Row = the caller, column = the target. <strong>C</strong> is a direct call, <strong>B</strong> is a registered callback.</p>
{{MATRIX}}

<h2 id="checks">Checks (at build time)</h2>
{{CHECKS}}

<h2 id="open">Open points</h2>
{{OPEN}}
</main>

<script>
(function () {
  const root = document.documentElement;
  try { const s = localStorage.getItem("libra-theme"); if (s) root.setAttribute("data-bs-theme", s);
        else if (matchMedia("(prefers-color-scheme: dark)").matches) root.setAttribute("data-bs-theme", "dark"); } catch (e) {}
  document.getElementById("themeToggle").onclick = () => {
    const n = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", n); try { localStorage.setItem("libra-theme", n); } catch (e) {}
  };

  const NODES = {{NODES}}, EDGES = {{EDGES}}, PITCH = {{PITCH}}, TOP = {{TOP}}, NH = {{NH}}, CGAP = {{CGAP}}, LEFT = {{LEFT}}, NW = {{NW}};
  const INFO = {{INFO}};
  const svg = document.getElementById("map"), g = document.getElementById("edges");
  const ns = "http://www.w3.org/2000/svg";
  const below = r => TOP + r * PITCH + NH + (PITCH - NH) / 2;   // channel under row r
  const above = r => TOP + r * PITCH - (PITCH - NH) / 2;        // channel over row r
  const gutter = (a, b) => {
    const mid = (a.col + (a.span - 1) / 2 + b.col + (b.span - 1) / 2) / 2;
    const k = Math.min(6, Math.floor(mid) + 1);
    return LEFT + k * (NW + CGAP) - CGAP / 2;
  };
  function route(a, b, lane) {
    const off = ((lane % 6) - 2.5) * 3, cxa = a.x + a.w / 2 + off * 2, cxb = b.x + b.w / 2 + off * 2;
    let pts;
    if (b.row > a.row) {
      const y1 = below(a.row) + off, y2 = above(b.row) + off;
      pts = Math.abs(y1 - y2) < 1 ? [[cxa, a.y + a.h], [cxa, y1], [cxb, y1], [cxb, b.y]]
        : [[cxa, a.y + a.h], [cxa, y1], [gutter(a, b) + off, y1], [gutter(a, b) + off, y2], [cxb, y2], [cxb, b.y]];
    } else if (b.row < a.row) {
      const y1 = above(a.row) + off, y2 = below(b.row) + off;
      pts = Math.abs(y1 - y2) < 1 ? [[cxa, a.y], [cxa, y1], [cxb, y1], [cxb, b.y + b.h]]
        : [[cxa, a.y], [cxa, y1], [gutter(a, b) + off, y1], [gutter(a, b) + off, y2], [cxb, y2], [cxb, b.y + b.h]];
    } else {
      const y1 = below(a.row) + off;
      pts = [[cxa, a.y + a.h], [cxa, y1], [cxb, y1], [cxb, b.y + b.h]];
    }
    return pts.map(p => p.join(",")).join(" ");
  }
  function line(a, b, cls, mk, lane) {
    const pl = document.createElementNS(ns, "polyline");
    pl.setAttribute("class", "e " + cls); pl.setAttribute("points", route(NODES[a], NODES[b], lane));
    pl.setAttribute("marker-end", "url(#" + mk + ")"); g.appendChild(pl);
  }
  const chip = id => '<a class="chip" href="#c-' + id + '">' + id + '</a>';
  function select(id) {
    g.innerHTML = "";
    document.querySelectorAll(".node").forEach(n => n.classList.remove("sel", "rel", "dim"));
    if (!id) { document.getElementById("sel").textContent = "Select a component on the map."; return; }
    const rel = new Set([id]); let lane = 0;
    const out = [], inn = [], cbo = [], cbi = [];
    EDGES.forEach(e => {
      if (e.f === id) { line(id, e.t, e.k === "call" ? "e-out" : "e-cb", e.k === "call" ? "m-out" : "m-cb", lane++); rel.add(e.t); (e.k === "call" ? out : cbo).push(e.t); }
      if (e.t === id) { line(e.f, id, e.k === "call" ? "e-in" : "e-incb", e.k === "call" ? "m-in" : "m-incb", lane++); rel.add(e.f); (e.k === "call" ? inn : cbi).push(e.f); }
    });
    document.querySelectorAll(".node").forEach(n => {
      const nid = n.dataset.id;
      if (nid === id) n.classList.add("sel"); else if (rel.has(nid)) n.classList.add("rel"); else n.classList.add("dim");
    });
    const list = a => a.length ? a.map(chip).join(" ") : '<span class="text-body-secondary">none</span>';
    document.getElementById("sel").innerHTML = '<div><strong><code>' + id + '</code></strong> &mdash; ' + INFO[id] + ' <a href="#c-' + id + '">Details</a></div>' +
      '<div class="row g-2 mt-1"><div class="col-md-3"><span class="rel-k">Calls</span><br>' + list(out) + '</div>' +
      '<div class="col-md-3"><span class="rel-k">Called by</span><br>' + list(inn) + '</div>' +
      '<div class="col-md-3"><span class="rel-k">Notifies</span><br>' + list(cbo) + '</div>' +
      '<div class="col-md-3"><span class="rel-k">Notified by</span><br>' + list(cbi) + '</div></div>';
  }
  let cur = null;
  document.querySelectorAll(".node").forEach(n => {
    const act = () => { cur = cur === n.dataset.id ? null : n.dataset.id; select(cur); };
    n.addEventListener("click", act);
    n.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } });
  });
  svg.addEventListener("click", e => { if (e.target === svg || e.target.classList.contains("band")) { cur = null; select(null); } });

  const q = document.getElementById("q"), none = document.getElementById("none");
  q.addEventListener("input", () => {
    const v = q.value.trim().toLowerCase(); let shown = 0;
    document.querySelectorAll(".comp").forEach(c => { const ok = !v || c.dataset.search.toLowerCase().includes(v); c.hidden = !ok; if (ok) shown++; });
    document.querySelectorAll(".layer-h").forEach(h => { let n = h.nextElementSibling, any = false; while (n && n.classList.contains("comp")) { if (!n.hidden) any = true; n = n.nextElementSibling; } h.hidden = !any; });
    none.hidden = shown > 0;
  });
  window.__select = select;
})();
</script>
</body>
</html>
"""

info = {c["id"]: c["purpose"].replace("`", "") for c in D.COMPONENTS}
page = (PAGE.replace("{{NAV}}", nav).replace("{{MAP}}", map_svg()).replace("{{CARDS}}", cards())
        .replace("{{FLOWS}}", flows()).replace("{{MATRIX}}", matrix()).replace("{{CHECKS}}", checks())
        .replace("{{OPEN}}", open_points())
        .replace("{{NODES}}", json.dumps(NODES)).replace("{{EDGES}}", json.dumps([dict(f=e["f"], t=e["t"], k=e["k"]) for e in EDGES]))
        .replace("{{PITCH}}", str(PITCH)).replace("{{TOP}}", str(TOP)).replace("{{NH}}", str(NH))
        .replace("{{CGAP}}", str(CGAP)).replace("{{LEFT}}", str(LEFT)).replace("{{NW}}", str(NW))
        .replace("{{INFO}}", json.dumps(info)))
OUT.write_text(page)
print(f"wrote {OUT} ({len(page) // 1024} KB, {len(D.COMPONENTS)} components, "
      f"{sum(len(c['funcs']) for c in D.COMPONENTS)} functions, {len(EDGES)} relationships, {len(D.FLOWS)} flows)")
