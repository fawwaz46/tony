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

from tony.render import itemsByPath, layout, parseReview
from tony.source.local import splitDiffByFile

VERSION = 1

# Impacts are read in place, so they need room to make sense; walkthrough steps
# are narrated line by line and only need their own neighbours.
IMPACT_PAD = 20
STEP_PAD = 2


def readLines(repoPath, path):
    try:
        with open(os.path.join(repoPath, path), encoding="utf-8") as fh:
            return fh.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return None


def windowFor(src, start, end, pad):
    """A slice of source around [start, end], 1-indexed, clamped to the file.

    Returns the slice plus where it sits, so the page can number the lines
    correctly without possessing the rest of the file.
    """
    if src is None:
        return None
    lo = max(1, int(start) - pad)
    hi = min(len(src), int(end) + pad)
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
        anchors = [int(i["line"]) for i in group if isinstance(i.get("line"), (int, float))]
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
            if path and lines:
                if path not in cache:
                    cache[path] = readLines(repoPath, path)
                start = int(lines[0])
                end = int(lines[-1] if len(lines) > 1 else lines[0])
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
        out.append({
            "path": f["path"],
            "oldPath": f["oldPath"],
            "status": f["status"],
            "binary": f["binary"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "blocks": layout(f["body"], byPath.get(f["path"], [])) if f["body"] else [],
        })
    return out


def buildPayload(review, diff, repoPath, rangeLabel=""):
    """The whole review as one JSON-serialisable dict, with no repo access needed."""
    data = parseReview(review)
    impacts = data.get("impacts") or []
    annotations = data.get("annotations") or []
    risks = data.get("risks") or []

    return {
        "v": VERSION,
        "repo": os.path.basename(os.path.abspath(repoPath)),
        "range": rangeLabel,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "intent": data.get("intent") or "",
        "files": laidOutFiles(diff, annotations, risks),
        "annotations": annotations,
        "risks": risks,
        "impacts": impacts,
        "impactWindows": impactWindows(impacts, repoPath),
        "walkthroughs": stepWindows(data.get("walkthroughs") or [], repoPath),
    }


def dumpPayload(payload):
    return json.dumps(payload, separators=(",", ":"))
