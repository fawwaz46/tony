"""Does this review point at things that exist?

The shape checks in `mcp_server.validate` ask whether a review is the right
kind of object. These ask the harder question: every path, line and symbol in
it names a place in the repository, and a model writing prose about code is
perfectly capable of naming a place that is not there. Nothing downstream
catches it — the renderer reads whatever range it is given, so an invented line
range becomes a confident screenful of the wrong code, which is worse output
than no review at all.

Everything here is decided from the diff and from disk, never from the review.
The working tree is guaranteed to match the revision under review — that is
what `workingTreeProblem` refuses on — so a file that is not on disk is a file
that does not exist.

Anchors are checked by the same rule the page resolves them with: `spanFor`
takes an anchor to the run containing it, or failing that to the next one down
the file. So an anchor a line or two above its block is fine — that is what the
instructions ask for — and an anchor past the last changed line in the file
resolves to nothing at all. The two rules have to agree: an anchor this module
allows and coverage then cannot resolve would be rejected for a gap somewhere
else in the file, which sends the agent to fix the wrong thing.
"""

import os
import re

from tony_cli.layout import changedRuns
from tony_cli.source.local import confine, splitDiffByFile

IMPACT_KINDS = ("breaks", "behavior-change", "compatible")
REACHES = ("changed", "downstream")
PHASES = ("same", "new", "changed", "removed")

# What the instructions ask for: between three and seven steps. Fewer is not a
# trace, more is a lecture — and both are things the agent was told before it
# wrote one.
MIN_STEPS, MAX_STEPS = 3, 7

# The most `state` entries a step may carry, also from the instructions. The
# page renders them side by side and a fourth column does not fit.
MAX_STATE = 3

# A mirror annotation is the one place the instructions ask for a path inside
# prose: "Mirrors src/httpx/_parsers.py line for line. Read the annotations
# there." That path is a claim about the diff and is checked as one. Prose is
# not otherwise scanned for paths — too many honest sentences name a file that
# is not in the change.
MIRROR = re.compile(r"\b(?:mirrors?|same as|see|read the annotations in)\s+"
                    r"[`'\"]?([\w./-]+\.[A-Za-z0-9]{1,6})", re.IGNORECASE)


def anchorProblems(review, diff, root):
    """Everything in this review that points somewhere it should not.

    Returns a list of instructions, in the same voice as the shape checks: each
    one names the exact place and what to do about it, because a model is what
    reads them.
    """
    files = {f["path"]: f for f in splitDiffByFile(diff)}
    repo = Repo(root, files)

    problems = []
    for i, note in enumerate(review.get("annotations") or []):
        if isinstance(note, dict):
            problems += inDiff(f"annotations[{i}]", note, repo)
            problems += mirrorProblems(f"annotations[{i}]", note, repo)
    for i, skip in enumerate(review.get("skips") or []):
        if isinstance(skip, dict):
            problems += inDiff(f"skips[{i}]", skip, repo)
    for i, risk in enumerate(review.get("risks") or []):
        # A risk may float free of the diff — the instructions say to omit both
        # fields when it does — so only an anchored one is checked.
        if isinstance(risk, dict) and risk.get("path"):
            problems += inDiff(f"risks[{i}]", risk, repo)

    for i, impact in enumerate(review.get("impacts") or []):
        problems += impactProblems(i, impact, repo)
    for i, walk in enumerate(review.get("walkthroughs") or []):
        problems += walkthroughProblems(i, walk, repo)
    return problems


class Repo:
    """The diff and the working tree, answering the questions this module asks.

    A small object rather than four arguments passed everywhere, and it caches
    line counts: a walkthrough with seven steps in one file would otherwise
    read that file seven times.
    """

    def __init__(self, root, files):
        self.root = root
        self.files = files
        self._runs = {}
        self._lines = {}

    def changed(self, path):
        """True when this exact path is one of the changed files."""
        return path in self.files

    def region(self, path):
        """(first, last) changed line in the new file, or None for no hunks."""
        if path not in self._runs:
            body = (self.files.get(path) or {}).get("body") or ""
            runs = changedRuns(body)
            self._runs[path] = (runs[0][0], runs[-1][1]) if runs else None
        return self._runs[path]

    def lineCount(self, path):
        """Lines in the file on disk, or None when it is not a readable file.

        `confine` first: every path here came out of a model, and a review that
        asks how long `../../.ssh/id_rsa` is gets no answer.
        """
        if path in self._lines:
            return self._lines[path]

        count = None
        target = confine(self.root, path) if path else None
        if target and os.path.isfile(target):
            try:
                with open(target, "rb") as fh:
                    count = sum(1 for _ in fh) or 1
            except OSError:
                count = None
        self._lines[path] = count
        return count


def lineNumber(value):
    """`value` as a line number, or None if it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number >= 1 else None


def inDiff(where, item, repo):
    """An item that must be anchored in a changed file, checked against it."""
    path = item.get("path")
    if not path:
        return []  # `validate` already says this; saying it twice helps nobody.

    if not repo.changed(path):
        near = nearest(path, repo.files)
        hint = f" Did you mean {near}?" if near else ""
        return [
            f"{where} is anchored at {path}, which is not one of the changed "
            f"files.{hint} Anchor it in a file this diff touches, or remove it."
        ]

    line = lineNumber(item.get("line"))
    if line is None:
        return [f"{where} has line {item.get('line')!r}, which is not a line number."]

    region = repo.region(path)
    if region is None:
        return []  # A binary or rename-only file has no lines to be wrong about.
    first, last = region
    # Only the far end is an error. An anchor above its block resolves forward
    # to the block, which is what the instructions ask for and what the page
    # does; one past the last changed line resolves to nothing.
    if line > last:
        return [
            f"{where} is anchored at {path}:{line}, past the last changed line "
            f"in that file — the changes are between {first} and {last}. Anchor "
            "it inside the block it describes."
        ]
    return []


def mirrorProblems(where, note, repo):
    """A "same change, other copy" annotation must name a copy that is real.

    The mirror note is the one annotation that carries no explanation of its
    own — it sends the reader somewhere else. If that somewhere else is not in
    the change, the reader follows it to nothing and the code in front of them
    is never explained by anybody.
    """
    text = " ".join(str(note.get(field) or "") for field in ("now", "prev", "impact"))
    for referenced in MIRROR.findall(text):
        if repo.changed(referenced) or referenced == note.get("path"):
            continue
        near = nearest(referenced, repo.files)
        hint = f" Did you mean {near}?" if near else ""
        return [
            f"{where} sends the reader to {referenced}, which is not in this "
            f"change.{hint} Point at the copy that is annotated in full, or "
            "explain this file on its own."
        ]
    return []


def impactProblems(i, impact, repo):
    """One blast-radius entry: a real file, outside the diff, that a real annotation reaches."""
    where = f"impacts[{i}]"
    if not isinstance(impact, dict):
        return [f"{where} must be an object."]

    problems = [f"{where} has no `{field}`."
                for field in ("symbol", "fromPath", "path", "line", "why")
                if not impact.get(field) and impact.get(field) != 0]
    if problems:
        return problems

    kind = impact.get("kind")
    if kind not in IMPACT_KINDS:
        problems.append(
            f"{where} has kind {kind!r}. It must be one of: {', '.join(IMPACT_KINDS)}."
        )

    path = impact["path"]
    if repo.changed(path):
        return problems + [
            f"{where} points at {path}, which is in the diff. Impacts are for "
            "files the change reaches from outside; a changed file is covered "
            "by its own annotations."
        ]

    count = repo.lineCount(path)
    if count is None:
        return problems + [
            f"{where} points at {path}, which is not a file in this repository. "
            "Every impact is a place you read — remove this one or name the file "
            "you actually read."
        ]

    line = lineNumber(impact.get("line"))
    if line is None:
        problems.append(f"{where} has line {impact.get('line')!r}, which is not a line number.")
    elif line > count:
        problems.append(
            f"{where} points at {path}:{line}, and that file is {count} lines "
            "long. Read it and give the line that uses the symbol."
        )

    fromPath = impact["fromPath"]
    if not repo.changed(fromPath):
        problems.append(
            f"{where} says `{impact['symbol']}` comes from {fromPath}, which is "
            "not a changed file. `fromPath` is the file in the diff that the "
            "symbol lives in."
        )
    return problems


def walkthroughProblems(i, walk, repo):
    """One walkthrough: the right shape, and every step reading real lines.

    The steps are the part worth checking hardest. Each one puts a range of a
    real file on the page, read from disk at render time, so a range past the
    end of a file is a step the reader is shown as empty — and a step the agent
    invented rather than traced.
    """
    where = f"walkthroughs[{i}]"
    if not isinstance(walk, dict):
        return [f"{where} must be an object."]

    problems = []
    if walk.get("reach") not in REACHES:
        problems.append(
            f"{where} has reach {walk.get('reach')!r}. It must be "
            f'"changed" for a flow this diff altered, or "downstream" for one it '
            "reaches through an impact."
        )
    problems += [f"{where} has no `{field}`."
                 for field in ("title", "trigger", "whatChanged")
                 if not str(walk.get(field) or "").strip()]

    steps = walk.get("steps")
    if not isinstance(steps, list):
        return problems + [f"{where} has no `steps` array."]
    if not MIN_STEPS <= len(steps) <= MAX_STEPS:
        problems.append(
            f"{where} has {len(steps)} steps. A walkthrough runs "
            f"{MIN_STEPS} to {MAX_STEPS} — fewer is not a trace, more is a lecture."
        )

    for j, step in enumerate(steps):
        problems += stepProblems(f"{where}.steps[{j}]", step, repo)
    return problems


def stepProblems(where, step, repo):
    """One step of a trace."""
    if not isinstance(step, dict):
        return [f"{where} must be an object."]

    problems = []
    if not str(step.get("say") or "").strip():
        problems.append(f"{where} has no `say` — one sentence on what happens here.")

    phase = step.get("phase")
    if phase is not None and phase not in PHASES:
        problems.append(
            f"{where} has phase {phase!r}. It must be one of: {', '.join(PHASES)}."
        )

    state = step.get("state")
    if state is not None and not isinstance(state, dict):
        problems.append(f"{where} has a `state` that is not an object.")
    elif isinstance(state, dict) and len(state) > MAX_STATE:
        problems.append(
            f"{where} has {len(state)} `state` entries. Keep it to {MAX_STATE} — "
            "the reader is shown them side by side."
        )

    lines, path = step.get("lines"), step.get("path")
    # A step outside the codebase — a browser behaviour, a third-party call —
    # carries neither. One without the other is a step nothing can be read for.
    if lines is None and not path:
        return problems
    if not path:
        return problems + [f"{where} has `lines` but no `path`."]
    if lines is None:
        return problems + [
            f"{where} names {path} but no `lines`. Give the range the reader "
            "should see, or drop the path for a step that happens outside the code."
        ]

    if not isinstance(lines, list) or len(lines) != 2:
        return problems + [f"{where} has `lines` that is not a [start, end] pair."]
    start, end = lineNumber(lines[0]), lineNumber(lines[1])
    if start is None or end is None:
        return problems + [f"{where} has `lines` {lines!r}, which are not line numbers."]
    if start > end:
        return problems + [f"{where} has lines [{start}, {end}] — the start is after the end."]

    count = repo.lineCount(path)
    if count is None:
        return problems + [
            f"{where} traces {path}, which is not a file in this repository. "
            "Trace what the code does; never invent a step."
        ]
    if end > count:
        problems.append(
            f"{where} shows {path}:{start}-{end}, and that file is {count} lines "
            "long. Read the file and give the range this step really runs in."
        )
    return problems


def nearest(path, files):
    """The changed file most likely meant by `path`, or None.

    Same basename is nearly always the answer: a model writing `invoices.py`
    for `billing/invoices.py` is the common miss, and naming the file it should
    have written turns a rejection into a one-token fix.
    """
    name = (path or "").rsplit("/", 1)[-1]
    matches = [p for p in files if p.rsplit("/", 1)[-1] == name and p != path]
    return matches[0] if len(matches) == 1 else None
