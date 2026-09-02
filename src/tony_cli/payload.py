"""The upload payload: everything the hosted page needs, and nothing else.

The local page can read the repo, so it shows whole files for free. Anything that
leaves the machine cannot: it carries only windows of source around the lines a
reader is actually sent to. That is both the smaller payload and the smaller
exposure — on httpx, showing one affected line used to mean uploading a whole
build script.

Absolute paths never travel. The masthead gets the repo's name, not its location
on someone's disk.
"""

import json
import os
from datetime import datetime, timezone

from tony_cli.layout import isSkippable, itemsByPath, layout, runCoverage
from tony_cli.source.local import confine, splitDiffByFile

VERSION = 1

# Impacts are read in place, so they need room to make sense; walkthrough steps
# are narrated line by line and only need their own neighbours.
IMPACT_PAD = 20
STEP_PAD = 2


def readLines(repoPath, path):
    """The file's lines, or None if it cannot be read or sits outside the repo.

    Every path here was named by the model, and the model reads untrusted repo
    content — the threat `confine` was written for. The tool calls were already
    confined; these reads matter more, not less, because what they return is
    uploaded rather than merely shown to the model.
    """
    inside = confine(repoPath, path)
    if inside is None:
        return None
    try:
        with open(inside, encoding="utf-8") as fh:
            return fh.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return None


def lineNumber(value):
    """A 1-indexed line number the model supplied, or None if it is not one.

    The model can name a line; it cannot be trusted to name an integer. An
    unparseable value here used to raise straight out of `buildPayload`, which
    runs after the review has already been paid for.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def windowFor(src, start, end, pad):
    """A slice of source around [start, end], 1-indexed, clamped to the file.

    Returns the slice plus where it sits, so the page can number the lines
    correctly without possessing the rest of the file.
    """
    if src is None or start is None or end is None:
        return None
    lo = max(1, start - pad)
    hi = min(len(src), end + pad)
    if hi < lo:
        return None
    return {
        "start": lo,
        "lines": src[lo - 1:hi],
        "truncated": lo > 1 or hi < len(src),
        "total": len(src),
    }


def impactWindows(impacts, repoPath):
    """One window per impacted file, covering every impact site in it.

    Sites in one file are usually close together, so a single window spanning
    them beats one window each — fewer bytes, and the reader keeps the context
    between two nearby sites.
    """
    byPath = {}
    for imp in impacts:
        if imp.get("path"):
            byPath.setdefault(imp["path"], []).append(imp)

    windows = {}
    for path, group in byPath.items():
        src = readLines(repoPath, path)
        anchors = [n for n in (lineNumber(i.get("line")) for i in group) if n is not None]
        if not anchors:
            anchors = [1]
        windows[path] = windowFor(src, min(anchors), max(anchors), IMPACT_PAD)
    return windows


def stepWindows(walkthroughs, repoPath):
    """Attach the real source to each walkthrough step, read from disk."""
    cache = {}
    out = []
    for w in walkthroughs:
        steps = []
        for st in w.get("steps") or []:
            path, lines = st.get("path"), st.get("lines")
            window = None
            # `lines` is meant to be [start, end]; anything else is the model
            # not following the schema, which costs this step its window and
            # nothing more.
            if path and isinstance(lines, list) and lines:
                if path not in cache:
                    cache[path] = readLines(repoPath, path)
                start = lineNumber(lines[0])
                end = lineNumber(lines[-1])
                window = windowFor(cache[path], start, end, STEP_PAD)
                if window:
                    window["hot"] = [start, end]
            steps.append({**st, "window": window})
        out.append({**w, "steps": steps})
    return out


def laidOutFiles(diff, annotations, risks):
    """Files carrying resolved blocks instead of a raw diff body.

    The viewer receives rows with their line numbers already assigned and notes
    with their span and tag already decided, so it parses no diffs and settles
    no line numbers. That is the whole point: one implementation of the
    deterministic layer, in Python, with the payload as the boundary.
    """
    byPath = itemsByPath(annotations, risks)
    out = []
    for f in splitDiffByFile(diff):
        skip = f["binary"] or isSkippable(f["path"])
        runs, missed = ([], []) if skip else runCoverage(f["body"], byPath.get(f["path"], []))
        # Lines, not runs. A run is whatever the diff made contiguous — an added
        # file is one run of 500 lines — so counting runs says nothing about how
        # much code went unexplained.
        out.append({
            "changedLines": sum(r[1] - r[0] + 1 for r in runs),
            "unexplainedLines": sum(r[1] - r[0] + 1 for r in missed),
            "unexplained": len(missed),
            "path": f["path"],
            "oldPath": f["oldPath"],
            "status": f["status"],
            "binary": f["binary"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "blocks": layout(f["body"], byPath.get(f["path"], []), gaps=not skip) if f["body"] else [],
        })
    return out


def buildPayload(data, diff, repoPath, rangeLabel=""):
    """The whole review as one JSON-serialisable dict, with no repo access needed.

    `data` is the review already parsed. It arrives that way from `tony_publish`,
    which is handed an object; the API path finds it inside a fenced block first.
    Parsing here instead would mean this function silently produced a page with
    no annotations whenever it was given something that was already a dict —
    which looks exactly like a review that found nothing to say.
    """
    impacts = data.get("impacts") or []
    annotations = data.get("annotations") or []
    risks = data.get("risks") or []
    files = laidOutFiles(diff, annotations, risks)

    return {
        "v": VERSION,
        "repo": os.path.basename(os.path.abspath(repoPath)),
        "range": rangeLabel,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "intent": data.get("intent") or "",
        "files": files,
        "coverage": {
            "changedLines": sum(f["changedLines"] for f in files),
            "unexplainedLines": sum(f["unexplainedLines"] for f in files),
        },
        "annotations": annotations,
        "risks": risks,
        "impacts": impacts,
        "impactWindows": impactWindows(impacts, repoPath),
        "walkthroughs": stepWindows(data.get("walkthroughs") or [], repoPath),
    }


def dumpPayload(payload):
    return json.dumps(payload, separators=(",", ":"))
