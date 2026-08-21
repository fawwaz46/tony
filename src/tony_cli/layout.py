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


def layout(body, items):
    """One file as ordered blocks: diff rows, with notes above the line they describe.

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


def itemsByPath(annotations, risks):
    """Annotations and risks grouped per file, keeping their index in the payload arrays."""
    byPath = {}
    for n, a in enumerate(annotations):
        byPath.setdefault(a.get("path"), []).append({"k": "note", "n": n, "data": a})
    for n, r in enumerate(risks):
        if r.get("path"):
            byPath.setdefault(r["path"], []).append({"k": "risk", "n": n, "data": r})
    return byPath
