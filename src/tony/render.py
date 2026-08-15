"""Turn a structured review plus a raw diff into one self-contained HTML page.

The model emits one JSON block; everything the reader sees is laid out here,
not by the model.
"""

import html
import json
import os
import re

from tony.fonts import fontFaces
from tony.source.local import fileId, splitDiffByFile

JSON_FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parseReview(review):
    """Pull the JSON block out of a raw review. A malformed block yields {}."""
    match = JSON_FENCE.search(review)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def layout(body, items):
    """One file as ordered blocks: diff rows, with notes above the line they describe.

    This is the single place the deterministic layer runs. The local HTML page
    and the upload payload both consume the result, so the hosted viewer cannot
    disagree with the local page about a line number — neither of them computes
    one. See DESIGN.md, "Ground truth".

    `items` are dicts of {"k": "note"|"risk", "n": index, "data": obj}, where
    `n` indexes back into the payload's own annotations or risks array.

    Blocks are either {"k": "row", "cls", "g", "text"} or
    {"k": "note"|"risk", "n", "span", "tag"}.
    """
    runs = changedRuns(body) if body else []

    pending = {}
    for item in items:
        line = item["data"].get("line")
        anchor = int(line) if isinstance(line, (int, float)) else 0
        pending.setdefault(anchor, []).append(item)

    def note(anchor, item):
        span = spanFor(anchor, runs) if runs else None
        return {
            "k": item["k"],
            "n": item["n"],
            "span": list(span) if span else None,
            "tag": kindFor(item["data"].get("kind"), span),
        }

    blocks = []
    newLine = None

    for line in body.split("\n"):
        header = HUNK_HEADER.match(line)
        if header:
            newLine = int(header.group(1))
            # anything anchored before this hunk that never matched, flush here
            for anchor in sorted(k for k in pending if k < newLine):
                blocks += [note(anchor, i) for i in pending.pop(anchor)]
            blocks.append({"k": "row", "cls": "h", "g": None, "text": line})
            continue

        if newLine is not None and newLine in pending:
            blocks += [note(newLine, i) for i in pending.pop(newLine)]

        if line.startswith("+"):
            cls, gutter = "a", newLine
            newLine = (newLine or 0) + 1
        elif line.startswith("-"):
            cls, gutter = "d", None
        else:
            cls, gutter = "c", newLine
            if newLine is not None:
                newLine += 1

        blocks.append({"k": "row", "cls": cls, "g": gutter, "text": line})

    for anchor in sorted(pending):
        blocks += [note(anchor, i) for i in pending.pop(anchor)]

    return blocks


def renderBlocks(blocks, annotations, risks):
    """Blocks to HTML. Decides nothing — every span and tag arrived already resolved."""
    out = []
    for b in blocks:
        if b["k"] == "row":
            num = b["g"] if b["g"] is not None else ""
            out.append(
                f'<div class="l {b["cls"]}"><span class="g">{num}</span>'
                f'{html.escape(b["text"]) or "&nbsp;"}</div>'
            )
        else:
            source = risks if b["k"] == "risk" else annotations
            out.append(renderNote(source[b["n"]], b["k"], b.get("span"), b.get("tag")))
    return "".join(out)


def changedRuns(body):
    """Map each contiguous run of changed lines to its new-file span.

    Returns a list of (start, end, hadDeletion) in new-file line numbers.
    Deletion-only runs collapse to a single position, since they occupy no line
    in the new file. `hadDeletion` is what lets the page tell an insertion from a
    replacement without taking the model's word for it.
    """
    runs = []
    newLine = None
    run = None

    for line in body.split("\n"):
        header = HUNK_HEADER.match(line)
        if header:
            if run:
                runs.append(tuple(run))
                run = None
            newLine = int(header.group(1))
            continue
        if newLine is None:
            continue

        if line.startswith("+"):
            if run:
                run[1] = newLine
            else:
                run = [newLine, newLine, False]
            newLine += 1
        elif line.startswith("-"):
            if run:
                run[2] = True
            else:
                run = [newLine, newLine, True]
        else:
            if run:
                runs.append(tuple(run))
                run = None
            newLine += 1

    if run:
        runs.append(tuple(run))
    return runs


def spanFor(anchor, runs):
    """The changed run an annotation refers to: the one containing it, else the next."""
    for run in runs:
        if run[0] <= anchor <= run[1]:
            return run
    later = [r for r in runs if r[0] >= anchor]
    return later[0] if later else (anchor, anchor, False)


PANES = [("prev", "Prev"), ("now", "New"), ("impact", "Changes")]

_seq = iter(range(1, 10_000))


def renderSpan(span):
    """'lines 14-18' / 'line 14' — tells the reader which lines the note is about."""
    if not span:
        return ""
    start, end = span[0], span[1]
    label = f"line {start}" if start == end else f"lines {start}\u2013{end}"
    return f'<span class="ln">{label}</span>'


def kindFor(claimed, span):
    """What the tag says, decided by the diff rather than by the model.

    A model that inserts a guard ahead of existing code often calls that
    "changed" \u2014 true of the behaviour, false of the lines, and the reader ends up
    hunting an all-green block for the thing that was replaced. The diff already
    knows. "removed" is left alone: those runs are deletions by definition.
    """
    if claimed == "removed" or not span or len(span) < 3:
        return claimed or "changed"
    return "changed" if span[2] else "added"


def renderNote(a, kind="note", span=None, tag=None):
    """An annotation. Multi-pane when the change replaced something, flat when it is new."""
    if kind == "risk":
        return (
            f'<div class="ann risk"><p class="t">Potential risk{renderSpan(span)}</p>'
            f'<p class="n">{html.escape(a.get("text") or "")}</p></div>'
        )

    title = html.escape(a.get("title") or "Note")
    panes = [(key, label, a.get(key)) for key, label in PANES if a.get(key)]

    # A plain addition has nothing to compare against — no tabs, just the text.
    if len(panes) <= 1:
        body = panes[0][2] if panes else (a.get("note") or "")
        return (
            f'<div class="ann"><p class="t">{title}{renderSpan(span)}</p>'
            f'<p class="n">{html.escape(body)}</p></div>'
        )

    n = next(_seq)
    tabs, bodies = [], []
    for i, (key, label, text) in enumerate(panes):
        on = ' aria-selected="true"' if i == 0 else ' aria-selected="false"'
        tabs.append(
            f'<button class="pt" data-g="{n}" data-p="{key}"{on}>{label}</button>'
        )
        bodies.append(
            f'<p class="n pane" data-g="{n}" data-p="{key}"'
            f'{"" if i == 0 else " hidden"}>{html.escape(text)}</p>'
        )

    kindLabel = html.escape((tag or kindFor(a.get("kind"), span)).upper())
    return (
        f'<div class="ann"><p class="t">{title}'
        f'<span class="k">{kindLabel}</span>{renderSpan(span)}</p>'
        f'<div class="tabs">{"".join(tabs)}</div>{"".join(bodies)}</div>'
    )


def itemsByPath(annotations, risks):
    """Annotations and risks grouped per file, keeping their index in the payload arrays."""
    byPath = {}
    for n, a in enumerate(annotations):
        byPath.setdefault(a.get("path"), []).append({"k": "note", "n": n, "data": a})
    for n, r in enumerate(risks):
        if r.get("path"):
            byPath.setdefault(r["path"], []).append({"k": "risk", "n": n, "data": r})
    return byPath


def renderFiles(files, annotations, risks):
    byPath = itemsByPath(annotations, risks)

    out = []
    for n, f in enumerate(files, 1):
        fid = fileId(f["path"])
        items = byPath.get(f["path"], [])
        blocks = layout(f["body"], items) if f["body"] else []
        count = len(items)
        badge = f'<span class="nb">{count}</span>' if count else ""
        renamed = (
            f'<span class="from">from {html.escape(f["oldPath"])}</span>'
            if f["oldPath"] else ""
        )

        if f["binary"]:
            inner = '<p class="bin">Binary — not shown.</p>'
        elif not f["body"]:
            inner = '<p class="bin">No textual changes.</p>'
        else:
            inner = f'<div class="hunk">{renderBlocks(blocks, annotations, risks)}</div>'

        openAttr = "" if (f["binary"] or not items) else " open"
        out.append(f"""
<details class="file" id="file-{fid}" data-node="{fid}"{openAttr}>
  <summary>
    <span class="ix">[{n:02d}]</span>
    <span class="st {f['status']}">{f['status'][:3]}</span>
    <span class="fp">{html.escape(f['path'])}</span>{renamed}
    {badge}
    <span class="cnt"><b class="{'pos' if f['additions'] else 'z'}">+{f['additions']}</b> <b class="{'neg' if f['deletions'] else 'z'}">&minus;{f['deletions']}</b></span>
  </summary>
  {inner}
</details>""")
    return "".join(out)


PHASE_LABEL = {"new": "new", "changed": "changed", "removed": "no longer happens", "same": ""}


def codeWindow(repoPath, path, lines):
    """The real source for a step, read from disk so it cannot be fabricated."""
    if not path or not lines:
        return '<div class="cw none">happens outside the codebase</div>'
    try:
        with open(os.path.join(repoPath, path), encoding="utf-8") as fh:
            src = fh.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return f'<div class="cw none">could not read {html.escape(path)}</div>'

    start = max(1, int(lines[0]))
    end = min(len(src), int(lines[-1] if len(lines) > 1 else lines[0]))
    pad = 2
    lo, hi = max(1, start - pad), min(len(src), end + pad)

    rows = []
    for i in range(lo, hi + 1):
        hot = " hot" if start <= i <= end else ""
        rows.append(
            f'<div class="l c{hot}"><span class="g">{i}</span>'
            f'{html.escape(src[i - 1]) or "&nbsp;"}</div>'
        )
    return (
        f'<div class="cw"><div class="cwh">{html.escape(path)}</div>'
        f'<div class="hunk">{"".join(rows)}</div></div>'
    )


def renderState(state):
    if not state:
        return ""
    rows = []
    for k, v in list(state.items())[:3]:
        v = str(v)
        if "->" in v:
            was, _, now = v.partition("->")
            val = (f'<span class="was">{html.escape(was.strip())}</span>'
                   f'<span class="to">\u2192</span>'
                   f'<span class="now">{html.escape(now.strip())}</span>')
        else:
            val = f'<span class="now">{html.escape(v)}</span>'
        rows.append(f'<div class="sv"><span class="sk">{html.escape(str(k))}</span>{val}</div>')
    return f'<div class="state"><p class="cap">[ state ]</p>{"".join(rows)}</div>'


def renderWalkthrough(w, repoPath, idx, total=1):
    steps = w.get("steps") or []
    if not steps:
        return ""

    ofN = f" / {total:02d}" if total > 1 else ""
    changed = w.get("whatChanged")
    changedLine = (
        f'<p class="wchg"><span class="tl">What changed</span> {html.escape(changed)}</p>'
        if changed else ""
    )
    seen = []
    for st in steps:
        if st.get("path") and st["path"] not in seen:
            seen.append(st["path"])
    chips = "".join(
        f'<span class="chip">{html.escape(pth.split("/")[-1])}</span>' for pth in seen
    )
    nNew = sum(1 for st in steps if (st.get("phase") or "same") != "same")
    newCount = (
        f'<span class="chip hot">{nNew} of {len(steps)} steps are new</span>'
        if nNew else ""
    )

    dots, panels = [], []
    for i, st in enumerate(steps):
        phase = st.get("phase") or "same"
        dots.append(
            f'<button class="dot {phase}" data-w="{idx}" data-s="{i}" '
            f'aria-label="Step {i + 1}"{" aria-current=\"true\"" if i == 0 else ""}>'
            f'{i + 1:02d}</button>'
        )
        tag = PHASE_LABEL.get(phase, "")
        tagHtml = f'<span class="ph {phase}">{tag}</span>' if tag else ""
        panels.append(
            f'<div class="stepPanel{" on" if i == 0 else ""}" data-w="{idx}" data-s="{i}">'
            f'<p class="say">{html.escape(st.get("say") or "")}{tagHtml}</p>'
            f'<div class="split">{codeWindow(repoPath, st.get("path"), st.get("lines"))}'
            f'{renderState(st.get("state"))}</div></div>'
        )

    return f'''
<section class="wt" data-w="{idx}" data-n="{len(steps)}">
  <header class="wth">
    <p class="cap">[ walkthrough {idx + 1:02d}{ofN} ]</p>
    <h3>{html.escape(w.get("title") or "Walkthrough")}</h3>
    <p class="trig"><span class="tl">Starts when</span> {html.escape(w.get("trigger") or "")}</p>
    {changedLine}
    <div class="covers">{chips}{newCount}</div>
  </header>
  <div class="dots">{"".join(dots)}</div>
  <div class="panels">{"".join(panels)}</div>
  <div class="wtnav">
    <button class="wprev" data-w="{idx}" disabled>&#8249; back</button>
    <span class="wpos" data-w="{idx}">step 1 of {len(steps)}</span>
    <button class="wnext" data-w="{idx}">next &#8250;</button>
  </div>
</section>'''


def renderWalkthroughs(walkthroughs, repoPath):
    if not walkthroughs:
        return ""
    intro = (
        '<div class="wintro"><p><b>These are traces, not diagrams.</b> Each one follows a '
        'single real scenario from the moment it starts, one step at a time. The code shown '
        'is read straight from your files.</p>'
        '<p>Use <b>next</b> to advance. Before you press it, say what you think happens '
        'next — that guess is what makes the step stick.</p></div>'
    )
    return intro + "".join(
        renderWalkthrough(w, repoPath, i, len(walkthroughs))
        for i, w in enumerate(walkthroughs)
    )


KIND_LABEL = {
    "breaks": "Breaks",
    "behavior-change": "Behaves differently",
    "compatible": "Compatible",
}
KIND_ORDER = {"breaks": 0, "behavior-change": 1, "compatible": 2}


def renderImpactNote(imp):
    kind = imp.get("kind") or "behavior-change"
    label = KIND_LABEL.get(kind, kind)
    sym = imp.get("symbol")
    src = imp.get("fromPath")
    origin = ""
    if sym:
        origin = f'<span class="via">via <code>{html.escape(sym)}</code>'
        origin += f' in {html.escape(src)}' if src else ""
        origin += "</span>"
    return (
        f'<div class="ann imp {kind}">'
        f'<p class="t">{html.escape(label)}{origin}</p>'
        f'<p class="n">{html.escape(imp.get("why") or "")}</p></div>'
    )


def renderImpactFile(path, source, impacts, n=1):
    """A whole consuming file, with annotations sitting at the lines that are affected."""
    byLine = {}
    for imp in impacts:
        line = imp.get("line")
        anchor = int(line) if isinstance(line, (int, float)) else 1
        byLine.setdefault(anchor, []).append(imp)

    rows = []
    if source is None:
        rows.append('<p class="bin">Could not read this file.</p>')
    else:
        for i, line in enumerate(source.split("\n"), 1):
            for imp in byLine.get(i, []):
                rows.append(renderImpactNote(imp))
            hit = " hit" if i in byLine else ""
            rows.append(
                f'<div class="l c{hit}" id="imp-{fileId(path)}-{i}">'
                f'<span class="g">{i}</span>{html.escape(line) or "&nbsp;"}</div>'
            )

    worst = min((KIND_ORDER.get(i.get("kind"), 1) for i in impacts), default=1)
    worstKind = next(k for k, v in KIND_ORDER.items() if v == worst)

    jumps = "".join(
        f'<a class="jump {i.get("kind","")}" '
        f'href="#imp-{fileId(path)}-{int(i.get("line") or 1)}">'
        f'line {int(i.get("line") or 1)}</a>'
        for i in sorted(impacts, key=lambda x: int(x.get("line") or 1))
    )

    # Files are ordered worst-first, so opening the first one puts the most
    # consequential impact on screen instead of a list that reads as empty.
    return f"""
<details class="file impacted {worstKind}" id="impact-{fileId(path)}"{" open" if n == 1 else ""}>
  <summary>
    <span class="ix">[{n:02d}]</span>
    <span class="st {worstKind}">{html.escape(KIND_LABEL.get(worstKind, worstKind))}</span>
    <span class="fp">{html.escape(path)}</span>
    <span class="nb">{len(impacts)}</span>
    <span class="cnt">not edited</span>
  </summary>
  <div class="jumps">{len(impacts)} impact site{"s" if len(impacts) != 1 else ""}: {jumps}</div>
  <div class="hunk full">{"".join(rows)}</div>
</details>"""


def renderImpacts(impacts, repoPath):
    if not impacts:
        return "", 0

    byPath = {}
    for imp in impacts:
        if imp.get("path"):
            byPath.setdefault(imp["path"], []).append(imp)

    if not byPath:
        return "", 0

    blocks = []
    ordered = sorted(
        byPath,
        key=lambda p: min(KIND_ORDER.get(i.get("kind"), 1) for i in byPath[p]),
    )
    for n, path in enumerate(ordered, 1):
        try:
            with open(os.path.join(repoPath, path), encoding="utf-8") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError):
            source = None
        blocks.append(renderImpactFile(path, source, byPath[path], n))

    return (
        '<section class="impacts">' + "".join(blocks)
        + "</section>",
        len(byPath),
    )


def renderPage(review, diff, repoPath, title="tony", rangeLabel=""):
    data = parseReview(review)
    files = splitDiffByFile(diff)

    annotations = data.get("annotations") or []
    risks = data.get("risks") or []
    impacts = data.get("impacts") or []
    impactsHtml, nreached = renderImpacts(impacts, repoPath)

    loose = [r for r in risks if not r.get("path")]
    looseHtml = ""
    if loose:
        items = "".join(f'<li>{html.escape(r.get("text", ""))}</li>' for r in loose)
        looseHtml = f'<section class="loose"><h2>Risks outside the diff</h2><ul>{items}</ul></section>'

    walks = data.get("walkthroughs") or []

    return TEMPLATE.format(
        title=html.escape(title),
        fontface=fontFaces(),
        repo=html.escape(repoPath),
        range=html.escape(rangeLabel),
        intent=html.escape(data.get("intent") or "No summary produced."),
        nfiles=len(files),
        adds=sum(f["additions"] for f in files),
        dels=sum(f["deletions"] for f in files),
        nann=len(annotations),
        nrisks=len(risks),
        nreached=nreached,
        nimpacts=len([i for i in impacts if i.get("path")]),
        nwalk=len(walks),
        walkdis="" if walks else " disabled",
        blastdis="" if nreached else " disabled",
        impacts=impactsHtml,
        walkthroughs=renderWalkthroughs(walks, repoPath),
        loose=looseHtml,
        files=renderFiles(files, annotations, risks),
    )


TEMPLATE = """<title>{title}</title>
<style>
{fontface}
/* Dark by design, not by preference: Behold's ground is #000 and the page commits to it.
   Depth is a surface step plus a hairline step — never a shadow.
   The accent means exactly one thing: changed. Selection and focus use contrast instead. */
:root {{
  --ground:#000000; --s1:#0a0a0a; --s2:#111110; --s3:#171614;
  --rule:#1e1d1b; --rule-2:#2b2825; --rule-3:#3a3631;
  --ink:#ffffff; --ink-2:#c9c5bf; --ink-3:#8f8b86; --ink-4:#5f5b55;
  --accent:#c89f6d; --accent-line:#5c4a30; --accent-bg:#14100a;
  --pos:#7fb069; --pos-bg:#0b1209; --neg:#ff8081; --neg-bg:#170b0c;
  --info:#8fb3cc; --info-bg:#0c141c; --info-line:#1e3445;
  --sans:'Favorit',system-ui,-apple-system,sans-serif;
  --mono:'Favorit Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}}
*{{box-sizing:border-box}}
html{{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}}
body{{margin:0;padding:0 2rem 6rem;background:var(--ground);color:var(--ink-2);
  font:400 15px/1.55 var(--sans);font-variant-numeric:tabular-nums}}
.wrap{{max-width:76rem;margin:0 auto}}
.mono,code{{font-family:var(--mono)}}
::selection{{background:var(--rule-3);color:var(--ink)}}

/* ---- chrome: the studio treatment ---- */
header{{padding:2.75rem 0 1.25rem;border-bottom:1px solid var(--rule);margin-bottom:1.5rem}}
.mh{{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem}}
.brand{{font-family:var(--mono);font-weight:500;font-size:.72rem;letter-spacing:.22em;
  text-transform:uppercase;color:var(--ink)}}
.mh .rng,.mh .repo{{font-family:var(--mono);font-size:.7rem;letter-spacing:.02em;color:var(--ink-4)}}
.mh .rng{{color:var(--ink-3)}}
.mh .repo{{margin-left:auto;word-break:break-all}}
h1{{font-size:clamp(1.25rem,2.3vw,1.65rem);font-weight:700;letter-spacing:-.042em;
  word-spacing:-.09em;line-height:1.2;margin:0 0 1.5rem;max-width:52ch;text-wrap:balance;
  color:var(--ink)}}
.meta{{display:flex;flex-wrap:wrap;gap:.4rem 1.5rem;font-family:var(--mono);
  font-size:.7rem;color:var(--ink-4);align-items:center}}
.meta b{{font-weight:500}}
.meta .pos{{color:var(--pos)}} .meta .neg{{color:var(--neg)}}

/* Section headers and tabs are eyebrows: uppercase mono, positive tracking, bracketed. */
.tabs-main{{display:flex;gap:0;border-bottom:1px solid var(--rule);margin-bottom:1.25rem}}
.mt{{font:500 .68rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  background:none;border:0;border-bottom:1px solid transparent;color:var(--ink-4);
  padding:.9rem 1.15rem;cursor:pointer;display:flex;align-items:center;gap:.6rem;
  margin-bottom:-1px}}
.mt:first-child{{padding-left:0}}
.mt::before{{content:"[";color:var(--rule-3)}}
.mt::after{{content:"]";color:var(--rule-3)}}
.mt:hover:not(:disabled){{color:var(--ink-3)}}
.mt[aria-selected="true"]{{color:var(--ink);border-bottom-color:var(--ink)}}
.mt[aria-selected="true"]::before,.mt[aria-selected="true"]::after{{color:var(--ink-4)}}
.mt:disabled{{color:var(--rule-3);cursor:default}}
.mt:focus-visible{{outline:1px solid var(--rule-3);outline-offset:-1px}}
.mt .c{{font-size:.68rem;color:var(--ink-4);letter-spacing:.06em}}
.mt[aria-selected="true"] .c{{color:var(--ink-3)}}

h2{{font:500 .68rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-3);margin:0 0 1rem}}
.loose{{margin-bottom:2.5rem;border-left:1px solid var(--neg);padding-left:1.25rem}}
.loose ul{{margin:0;padding-left:1.1rem}}
.loose li{{margin-bottom:.5rem;font-size:.875rem;color:var(--ink-2);max-width:60ch}}

/* ---- file rows: hairlines, not cards ---- */
.file{{border-bottom:1px solid var(--rule);background:var(--ground)}}
.file:first-child{{border-top:1px solid var(--rule)}}
.file summary{{display:flex;align-items:center;gap:.85rem;padding:.6rem .25rem;cursor:pointer;
  font-family:var(--mono);font-size:.75rem;flex-wrap:wrap;list-style:none;color:var(--ink-3)}}
.file summary::-webkit-details-marker{{display:none}}
.file summary:hover{{background:var(--s1)}}
.file[open] summary{{border-bottom:1px solid var(--rule)}}
.ix{{color:var(--ink-4);letter-spacing:.06em;font-size:.7rem;flex:none}}
.st{{font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-4);flex:none}}
.st.added{{color:var(--pos)}}
.st.deleted{{color:var(--neg)}}
.fp{{flex:1;min-width:0;word-break:break-all;color:var(--ink)}}
.from{{color:var(--ink-4);font-size:.7rem}}
.nb{{font-size:.62rem;color:var(--ink-3);border:1px solid var(--rule-2);padding:.2em .5em;
  line-height:1}}
.cnt{{font-size:.7rem;white-space:nowrap;color:var(--ink-4)}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .z{{color:var(--ink-4);font-weight:400}}

/* ---- the dense interior ---- */
.hunk{{overflow-x:auto;background:var(--s1);border-bottom:1px solid var(--rule)}}
.l{{font-family:var(--mono);font-size:.75rem;line-height:1.5;white-space:pre;
  min-width:max-content;padding-right:1rem;color:var(--ink-2)}}
.g{{display:inline-block;width:3.4rem;padding-right:1rem;text-align:right;color:var(--ink-4);
  user-select:none;-webkit-user-select:none}}
.l.h{{background:var(--s2);color:var(--ink-4);padding-top:.25rem;padding-bottom:.25rem;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}}
.file[open] .hunk > .l.h:first-child{{border-top:0}}
.l.a{{background:var(--pos-bg);color:var(--ink)}}
.l.d{{background:var(--neg-bg);color:var(--ink-3)}}
.bin{{margin:0;padding:.9rem .25rem;color:var(--ink-4);font-size:.8rem;
  border-bottom:1px solid var(--rule)}}

/* Annotations carry the accent because they mark changed code. Nothing else may. */
.ann{{background:var(--accent-bg);border-top:1px solid var(--accent-line);
  border-bottom:1px solid var(--accent-line);padding:.75rem 1rem .75rem 4.4rem;
  white-space:normal;font-family:var(--sans);min-width:auto;position:sticky;left:0}}
.ann.risk{{background:var(--neg-bg);border-color:var(--neg-bg)}}
.ann .t{{margin:0 0 .5rem;font:500 .65rem/1.4 var(--mono);letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);display:flex;align-items:center;
  gap:.6rem;flex-wrap:wrap}}
.ann.risk .t{{color:var(--neg)}}
.ann .ln{{font-size:.62rem;letter-spacing:.06em;color:var(--ink-4);text-transform:none}}
.ann .k{{font-size:.58rem;letter-spacing:.1em;color:var(--ink-4)}}
.ann .n{{margin:0;font-size:.85rem;line-height:1.55;color:var(--ink-2);max-width:64ch}}
.tabs{{display:flex;gap:1rem;margin-bottom:.6rem}}
.pt{{font:500 .62rem/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
  background:none;cursor:pointer;border:0;border-bottom:1px solid transparent;
  padding:0 0 .25rem;color:var(--ink-4)}}
.pt:hover{{color:var(--ink-3)}}
.pt[aria-selected="true"]{{color:var(--ink);border-bottom-color:var(--ink-3)}}
.pt:focus-visible{{outline:1px solid var(--rule-3);outline-offset:2px}}
.risks-off .ann.risk{{display:none}}
.toggle{{display:flex;align-items:center;gap:.5rem;font-family:var(--mono);
  font-size:.7rem;color:var(--ink-4);cursor:pointer;user-select:none}}
.toggle:hover{{color:var(--ink-3)}}
.toggle input{{accent-color:var(--ink-3);margin:0}}

/* ---- blast radius ---- */
.impacts{{margin-top:0}}
.file.impacted .st.breaks{{color:var(--neg)}}
.file.impacted .st.behavior-change{{color:var(--info)}}
.file.impacted .st.compatible{{color:var(--ink-4)}}
.jumps{{padding:.6rem .25rem;font-family:var(--mono);font-size:.68rem;color:var(--ink-4);
  display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--rule)}}
.jump{{color:var(--info);text-decoration:none;border-bottom:1px solid transparent}}
.jump:hover{{border-bottom-color:currentColor}}
.jump.breaks{{color:var(--neg)}}
.jump.compatible{{color:var(--ink-3)}}
.hunk.full{{max-height:34rem;overflow-y:auto}}
.l.hit{{background:var(--s3)}}
.l.focus{{background:var(--s3);box-shadow:inset 2px 0 0 var(--ink-3)}}
.ann.imp{{background:var(--info-bg);border-color:var(--info-line)}}
.ann.imp .t{{color:var(--info)}}
.ann.imp.breaks{{background:var(--neg-bg);border-color:var(--neg-bg)}}
.ann.imp.breaks .t{{color:var(--neg)}}
.ann.imp.compatible{{background:var(--s2);border-color:var(--rule)}}
.ann.imp.compatible .t{{color:var(--ink-3)}}
.ann .via{{font-weight:400;text-transform:none;letter-spacing:.01em;color:var(--ink-4);
  font-size:.68rem}}
.stepper{{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:.75rem;
  background:var(--ground);border-bottom:1px solid var(--rule);padding:.7rem .25rem;
  margin-bottom:0;font-family:var(--mono);font-size:.7rem;color:var(--ink-4)}}
.stepper button{{font:400 .8rem/1 var(--mono);background:none;border:1px solid var(--rule-2);
  color:var(--ink-3);cursor:pointer;padding:.25em .6em}}
.stepper button:hover{{border-color:var(--rule-3);color:var(--ink)}}
.stepper .sh{{color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}

/* ---- walkthroughs ---- */
.wintro{{border-left:1px solid var(--rule-2);padding:.1rem 0 .1rem 1.25rem;margin-bottom:1.25rem;
  max-width:64ch}}
.wintro p{{margin:0 0 .6rem;font-size:.875rem;color:var(--ink-3)}}
.wintro p:last-child{{margin:0}}
.wintro b{{color:var(--ink-2);font-weight:500}}
.tl{{font-family:var(--mono);font-size:.6rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-4);margin-right:.6rem}}
.wt{{border-top:1px solid var(--rule);padding:1.25rem 0 2.5rem}}
.wth{{margin-bottom:1.5rem}}
.cap{{font:500 .62rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-4);margin:0 0 .8rem}}
.wth h3{{margin:0 0 .5rem;font-size:1.35rem;font-weight:700;letter-spacing:-.038em;
  word-spacing:-.07em;color:var(--ink)}}
.trig{{margin:0;color:var(--ink-3);font-size:.9rem}}
.wchg{{margin:.5rem 0 0;font-size:.9rem;color:var(--ink-2)}}
.covers{{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1rem}}
.chip{{font-family:var(--mono);font-size:.62rem;letter-spacing:.06em;color:var(--ink-4);
  border:1px solid var(--rule);padding:.2em .5em}}
.chip.hot{{color:var(--accent);border-color:var(--accent-line)}}
.dots{{display:flex;gap:.4rem;margin-bottom:1.25rem;flex-wrap:wrap}}
.dot{{font:400 .62rem/1 var(--mono);letter-spacing:.06em;min-width:2.1rem;height:1.9rem;
  border:1px solid var(--rule);background:none;color:var(--ink-4);cursor:pointer;padding:0 .35em}}
.dot:hover{{border-color:var(--rule-3);color:var(--ink-3)}}
.dot.new,.dot.changed{{border-color:var(--accent-line);color:var(--accent)}}
.dot.removed{{border-style:dashed;text-decoration:line-through}}
.dot[aria-current]{{background:var(--ink);border-color:var(--ink);color:var(--ground)}}
.dot:focus-visible{{outline:1px solid var(--rule-3);outline-offset:2px}}
.panels{{display:grid;margin-bottom:1.25rem}}
.stepPanel{{grid-area:1 / 1;visibility:hidden}}
.stepPanel.on{{visibility:visible}}
.say{{margin:0 0 1rem;font-size:1.05rem;line-height:1.5;max-width:60ch;color:var(--ink);
  letter-spacing:-.008em}}
.ph{{font-family:var(--mono);font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;
  margin-left:.7rem;color:var(--accent);white-space:nowrap;font-weight:500}}
.ph.removed{{color:var(--neg)}}
.ph.same{{display:none}}
.split{{display:grid;grid-template-columns:1fr 15rem;gap:1.25rem;align-items:start}}
@media (max-width:52rem){{.split{{grid-template-columns:1fr}}}}
.cw{{border:1px solid var(--rule);min-width:0;background:var(--s1)}}
.cwh{{font-family:var(--mono);font-size:.65rem;color:var(--ink-4);padding:.45rem .7rem;
  background:var(--s2);border-bottom:1px solid var(--rule);word-break:break-all}}
.cw .hunk{{background:none;border:0}}
.cw.none{{padding:.9rem;color:var(--ink-4);font-size:.8rem;font-family:var(--mono)}}
.l.hot{{background:var(--s3);box-shadow:inset 2px 0 0 var(--rule-3);color:var(--ink)}}
.state{{border:1px solid var(--rule);padding:.8rem .85rem;background:var(--s1)}}
.state .cap{{margin:0 0 .7rem}}
.sv{{font-family:var(--mono);font-size:.7rem;margin-bottom:.7rem;line-height:1.5}}
.sv:last-child{{margin-bottom:0}}
.sk{{color:var(--ink-4);display:block;margin-bottom:.15rem}}
.sv .was{{color:var(--ink-4);text-decoration:line-through}}
.sv .to{{color:var(--ink-4);margin:0 .35em}}
.sv .now{{color:var(--accent)}}
.wtnav{{display:flex;align-items:center;gap:1rem;font-family:var(--mono);font-size:.7rem;
  color:var(--ink-4)}}
.wtnav button{{font:500 .65rem/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;
  background:none;color:var(--ink-3);border:1px solid var(--rule-2);padding:.5rem .9rem;
  cursor:pointer}}
.wtnav button:hover:not(:disabled){{border-color:var(--ink-3);color:var(--ink)}}
.wtnav button:disabled{{color:var(--rule-3);border-color:var(--rule);cursor:default}}
</style>

<div class="wrap">
<header>
  <div class="mh">
    <span class="brand">tony</span>
    <span class="rng">{range}</span>
    <span class="repo">{repo}</span>
  </div>
  <h1>{intent}</h1>
  <div class="meta">
    <span>{nfiles} files</span>
    <span><b class="pos">+{adds}</b> <b class="neg">&minus;{dels}</b></span>
    <span>{nann} annotations</span>
    <label class="toggle"><input type="checkbox" id="riskToggle"> potential risks ({nrisks})</label>
  </div>
</header>

{loose}
<nav class="tabs-main">
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">{nfiles}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"{blastdis}>Blast radius <span class="c">{nreached}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"{walkdis}>How it works <span class="c">{nwalk}</span></button>
</nav>

<div id="pane-files">{files}</div>
<div id="pane-blast" hidden>
  <div class="stepper" id="stepper">
    <button id="prevImp" aria-label="Previous impact">&#8249;</button>
    <span id="impPos">impact 1 of {nimpacts}</span>
    <button id="nextImp" aria-label="Next impact">&#8250;</button>
    <span class="sh" id="impWhere"></span>
  </div>
  {impacts}
</div>
<div id="pane-walk" hidden>{walkthroughs}</div>
</div>

<script>
// Top-level tabs.
document.querySelectorAll(".mt").forEach(b => b.addEventListener("click", () => {{
  const t = b.dataset.t;
  document.querySelectorAll(".mt").forEach(x => x.setAttribute("aria-selected", x.dataset.t === t));
  document.getElementById("pane-files").hidden = t !== "files";
  document.getElementById("pane-blast").hidden = t !== "blast";
  document.getElementById("pane-walk").hidden = t !== "walk";
}}));

// Walkthrough player: one step at a time.
document.querySelectorAll(".wt").forEach(wt => {{
  const n = +wt.dataset.n;
  let at = 0;

  const q = sel => wt.querySelectorAll(sel);
  const show = () => {{
    q(".stepPanel").forEach(p => p.classList.toggle("on", +p.dataset.s === at));
    q(".dot").forEach(d => d.toggleAttribute("aria-current", +d.dataset.s === at));
    wt.querySelector(".wpos").textContent = "step " + (at + 1) + " of " + n;
    wt.querySelector(".wprev").disabled = at === 0;
    wt.querySelector(".wnext").disabled = at === n - 1;
  }};
  const go = i => {{ at = Math.max(0, Math.min(n - 1, i)); show(); }};

  wt.querySelector(".wprev").onclick = () => go(at - 1);
  wt.querySelector(".wnext").onclick = () => go(at + 1);
  q(".dot").forEach(d => d.onclick = () => go(+d.dataset.s));

  show();
}});

// An impacted file is shown whole, but the reason it is here may be 100 lines
// down. Scroll the file's own box to the first affected line — never the page,
// which would throw the reader into the middle of a file they have not met yet.
function frame(d) {{
  const box = d.querySelector(".hunk.full"), hit = d.querySelector(".l.hit");
  if (box && hit) box.scrollTop = Math.max(0, hit.offsetTop - box.clientHeight / 3);
}}
document.querySelectorAll("#pane-blast details.impacted").forEach(d => {{
  if (d.open) frame(d);
  d.addEventListener("toggle", () => {{ if (d.open) frame(d); }});
}});

// Walk impact sites with the < > arrows.
const SITES = [...document.querySelectorAll("#pane-blast .l.hit")];
let at = -1;
function goto(i) {{
  if (!SITES.length) return;
  at = (i + SITES.length) % SITES.length;
  const el = SITES[at];
  el.closest("details").open = true;
  SITES.forEach(s => s.classList.remove("focus"));
  el.classList.add("focus");
  el.scrollIntoView({{behavior: "smooth", block: "center"}});
  document.getElementById("impPos").textContent =
    "impact " + (at + 1) + " of " + SITES.length;
  const f = el.closest("details").querySelector(".fp");
  document.getElementById("impWhere").textContent = f ? f.textContent : "";
}}
const pv = document.getElementById("prevImp"), nx = document.getElementById("nextImp");
if (pv) pv.onclick = () => goto(at - 1);
if (nx) nx.onclick = () => goto(at + 1);
document.addEventListener("keydown", e => {{
  if (document.getElementById("pane-blast").hidden) return;
  if (e.key === "]") goto(at + 1);
  if (e.key === "[") goto(at - 1);
}});

// Prev / New / Changes panes inside one annotation.
document.addEventListener("click", e => {{
  const b = e.target.closest(".pt");
  if (!b) return;
  const g = b.dataset.g, p = b.dataset.p;
  document.querySelectorAll('.pt[data-g="' + g + '"]').forEach(x =>
    x.setAttribute("aria-selected", x.dataset.p === p));
  document.querySelectorAll('.pane[data-g="' + g + '"]').forEach(x =>
    x.hidden = x.dataset.p !== p);
}});

// Risks are opt-in — this is a tool for understanding, not a review gate.
const rt = document.getElementById("riskToggle");
document.body.classList.add("risks-off");
rt.addEventListener("change", () =>
  document.body.classList.toggle("risks-off", !rt.checked));
</script>
"""
