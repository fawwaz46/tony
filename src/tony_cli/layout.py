"""The deterministic layer: line numbers, spans, and tags, decided from the diff.

This is the single place those decisions run. The payload carries the result,
and every renderer — the local page and the hosted viewer are the same
TypeScript bundle — consumes it without re-deriving anything. See DESIGN.md,
"Ground truth": the model can name a line range, it can never supply the
contents of one, and it never decides where a note lands.
"""

import json
import re

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


def kindFor(claimed, span):
    """What the tag says, decided by the diff rather than by the model.

    A model that inserts a guard ahead of existing code often calls that
    "changed" — true of the behaviour, false of the lines, and the reader ends up
    hunting an all-green block for the thing that was replaced. The diff already
    knows. "removed" is left alone: those runs are deletions by definition.
    """
    if claimed == "removed" or not span or len(span) < 3:
        return claimed or "changed"
    return "changed" if span[2] else "added"


def layout(body, items, gaps=True):
    """One file as ordered blocks: diff rows, with notes above the line they describe.

    `items` are dicts of {"k": "note"|"risk"|"skip", "n": index, "data": obj},
    where `n` indexes back into the payload's own annotations, risks or skips
    array.

    Blocks are either {"k": "row", "cls", "g", "text"} or
    {"k": "note"|"risk"|"skip", "n", "span", "tag"}.
    """
    runs = changedRuns(body) if body else []

    # Where a note lands.
    #
    # A note that is the only thing said about a run describes that whole run,
    # so it belongs at the run's first line — the model naming a line partway in
    # splits the very block it is explaining.
    #
    # A run with SEVERAL notes is the opposite case: an added file is one
    # contiguous run from line 1 to its end, and the three notes inside it are
    # describing three different parts. Snapping those together would stack them
    # at the top and throw away the only positional information there is. So
    # only a sole note moves.
    resolved = []
    perRun = {}
    for item in items:
        line = item["data"].get("line")
        claimed = int(line) if isinstance(line, (int, float)) else 0
        span = spanFor(claimed, runs) if runs else None
        resolved.append((item, span, claimed))
        if span in runs:
            perRun[span] = perRun.get(span, 0) + 1

    pending = {}
    covered = set()
    for item, span, claimed in resolved:
        if span in runs and item["k"] in COVERING:
            covered.add(span)
        alone = span in runs and perRun[span] == 1
        pending.setdefault(span[0] if alone else claimed, []).append(("note", item, span))

    # A run nothing explained. The promise is that every changed block is
    # accounted for, and a review that quietly covers two thirds of a diff is
    # indistinguishable from one that covers all of it — which is the failure
    # worth making impossible to miss. The gap is placed like any other note,
    # at the first line of the run it marks.
    if gaps:
        for run in runs:
            if run not in covered:
                pending.setdefault(run[0], []).append(("gap", None, run))

    def block(entry):
        kind, item, span = entry
        if kind == "gap":
            return {"k": "gap", "span": list(span), "tag": kindFor(None, span)}
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
                blocks += [block(e) for e in pending.pop(anchor)]
            blocks.append({"k": "row", "cls": "h", "g": None, "text": line})
            continue

        if newLine is not None and newLine in pending:
            blocks += [block(e) for e in pending.pop(newLine)]

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
        blocks += [block(e) for e in pending.pop(anchor)]

    return blocks


# Files nobody reads and nobody should be asked to explain. Decided here, from
# the path alone, rather than left to the model — "skip lockfiles" as a prompt
# instruction is a judgment call, and a judgment call is what put 4000 lines of
# package-lock.json into a coverage denominator.
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock",
    "go.sum", "flake.lock",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".snap", ".lock")

# Directories whose contents are built, not written. A project that keeps hand
# written source in one of these loses annotations on it — the file is still
# listed with its line counts, so nothing disappears, and the alternative is
# every reviewer paying for a vendored dependency tree.
SKIP_DIRS = (
    "node_modules", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit",
    "vendor", "target", "__pycache__", ".venv", "venv", "coverage", ".terraform",
)


def isSkippable(path):
    """True for generated files that are not worth an annotation."""
    parts = (path or "").split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


# What can account for a run of changed code. An annotation explains it; a
# skip says why it does not need explaining. A risk does neither — it warns
# about code it assumes you have already had explained — so a run carrying
# only a risk is still a run nobody explained. It used to satisfy coverage,
# which made "note the danger" a way to pass without saying what the code did.
COVERING = ("note", "skip")


def runCoverage(body, items):
    """(total runs, unexplained runs) for one file.

    The same resolution `layout` does, without building a page — this is what
    lets the review loop check its own work before anyone reads it.
    """
    runs = changedRuns(body) if body else []
    covered = set()
    for item in items:
        if item["k"] not in COVERING:
            continue
        line = item["data"].get("line")
        claimed = int(line) if isinstance(line, (int, float)) else 0
        span = spanFor(claimed, runs) if runs else None
        if span in runs:
            covered.add(span)
    return runs, [r for r in runs if r not in covered]


def itemsByPath(annotations, risks, skips=()):
    """Annotations, risks and skips per file, keeping their index in the payload."""
    byPath = {}
    for n, a in enumerate(annotations):
        byPath.setdefault(a.get("path"), []).append({"k": "note", "n": n, "data": a})
    for n, r in enumerate(risks):
        if r.get("path"):
            byPath.setdefault(r["path"], []).append({"k": "risk", "n": n, "data": r})
    for n, s in enumerate(skips or ()):
        if s.get("path"):
            byPath.setdefault(s["path"], []).append({"k": "skip", "n": n, "data": s})
    return byPath
