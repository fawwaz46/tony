"""tony as an MCP server: the agent supplies the intelligence, tony the rest.

The API path in `agent.py` owns a model, pays for it, and drives its own tool
loop. This one owns none of that. It hands the calling agent a diff and the
instruction document; the agent writes the review inside its own context on its
own subscription; tony takes it back to validate, render, and publish.

That trade gives up all control over the model, the harness, and the context
state. What replaces it is the gate at `tony_publish` — nothing becomes a page
until it passes, and a rejection is written as instructions to a reader that can
act on them and try again, on its tokens rather than ours.

Two tools, deliberately. Every extra tool is one more thing to call at the wrong
moment, and tony has nothing else worth exposing: the agent already has better
file and search tools than tony ever shipped.
"""

import os
import secrets
import threading
import time

# The SDK renamed FastMCP to MCPServer in 2.0. The class is the same shape —
# same constructor, same `.tool` decorator, same `.run(transport=...)` — so
# both are accepted rather than pinning tony to a superseded major. A
# dependency floor of `mcp>=1.9` resolves to 2.x on a fresh install and to
# whatever is already there on an upgrade, and both have to work.
try:
    from mcp.server.mcpserver import Context, MCPServer as Server
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import Context, FastMCP as Server

from tony_cli import hosted, install
from tony_cli.anchors import anchorProblems
from tony_cli.layout import isSkippable, itemsByPath, runCoverage
from tony_cli.payload import buildPayload, dumpPayload
from tony_cli.source.local import (
    FAILED, getDiff, isDirty, onlyPaths, resolveBase, resolveRepo, resolveRev,
    splitDiffByFile, splitIntoParts, withoutGeneratedBodies,
)

# What `tony_start` established about the repo, held until `tony_publish` needs
# it. The diff is the reason: an agent should not have to hand back a document
# it was already given, and a page must be rendered against the exact diff the
# review was written from — not against whatever `git diff` says several minutes
# of tool calls later.
#
# Process-local and unbounded, which is right for a stdio server: it lives and
# dies with one agent session, and a session that starts thousands of reviews
# has a different problem.
SESSIONS = {}

# Parts of one review are published by separate subagents, which can call in
# at the same moment. Only the bookkeeping on a split session is guarded — the
# single-part path never shares a session between callers.
PARTS_LOCK = threading.Lock()

# The most diff, in characters, one agent is handed to review. Past this the
# diff is split by file and each part goes to its own subagent. Roughly 40k
# tokens: room left in a 200k window for the instructions, the files the agent
# opens, the greps for impacts, and the review it writes. A diff that fills the
# window does not fail cleanly — the harness compacts it mid-review, and the
# annotations written after that are written from a summary of the code.
PART_CHARS = 150_000

def approvalNeeded(link, again=False):
    """What the agent is told when this machine has no token yet."""
    lead = (
        "tony: still waiting for the user to approve tony."
        if again else
        "tony: this machine is not signed in to tony yet, so there is nowhere to publish."
    )
    return (
        f"{lead}\n\n"
        "  Show the user this link and code, exactly:\n\n"
        f"    Approve tony: {link['url']}\n"
        f"    The page should show the code {link['code']}.\n\n"
        "  Tell them to approve it only if the codes match. Then stop and wait. When\n"
        "  they say they have approved it, call tony_start again with the same\n"
        "  arguments. Do not write the review before then; it would have nowhere to go.\n"
        "  (On their own computer, running `tony login` in a terminal works too.)"
    )


def signIn(harness):
    """None when this machine can publish, else what to tell the agent.

    A machine with a token is done. Otherwise it is either waiting on a link it
    already started, which this collects if approved, or it starts one. The
    link is the way in for sandboxes, which have no browser for `tony login`.
    """
    if hosted.savedToken():
        return None, ""
    if hosted.pendingLink():
        status, detail = hosted.collectLink()
        if status == "approved":
            return None, detail
        if status == "pending":
            return approvalNeeded(hosted.pendingLink(), again=True), ""
        if status == "error":
            return f"tony: could not check the approval link: {detail}\n  Try tony_start again.", ""
        # Expired or already spent: start a fresh one below.
    link, problem = hosted.startLink(agent=(harness[0] if harness else "") or "")
    if problem:
        return (
            f"tony: this machine is not signed in, and {problem}\n"
            "  Ask the user to run `tony login`, or try tony_start again.", ""
        )
    return approvalNeeded(link), ""


def parseRange(spec):
    """'main...HEAD' -> ('main', 'HEAD'). 'main' -> ('main', 'HEAD'). None -> (None, 'HEAD')."""
    if not spec:
        return None, "HEAD"
    if "..." in spec:
        base, _, head = spec.partition("...")
        return base or None, head or "HEAD"
    return spec, "HEAD"


def workingTreeProblem(root, head):
    """Why this tree cannot be reviewed as it stands, or None.

    Every line tony renders is read from the working tree and numbered against
    the new side of the diff. If the tree is not that revision, those numbers
    point at other code and the page is wrong in a way its reader cannot see.
    """
    wanted = resolveRev(root, head)
    if wanted is None:
        return f"cannot resolve revision {head!r}."
    if wanted != resolveRev(root, "HEAD"):
        return (
            f"{head} is not checked out, so the code on disk is not the code being "
            f"reviewed. Ask the developer to run `git checkout {head}` first."
        )
    if isDirty(root):
        return (
            "the working tree has uncommitted changes. tony reviews committed work "
            "and reads the code it shows from disk, so uncommitted edits would make "
            "those lines lie. Ask the developer to commit or stash first."
        )
    return None


def startReview(path=None, range=None, harness=("", ""), sessionId=None, part=None):
    """Set up a review and return what the agent needs to write it.

    `harness` is (name, version) of the agent on the other end of this
    connection, for the provenance record — see `harnessOf`.

    With `sessionId` and `part`, returns one part of a review that an earlier
    call split — see `partReview`.
    """
    # Checked first, and deliberately before anything expensive: an agent that
    # writes a full review and only then learns it cannot be published has
    # spent the user's context for nothing.
    blocked, justApproved = signIn(harness)
    if blocked:
        return blocked

    if sessionId or part:
        return partReview(sessionId, part)

    # Asked here rather than at the command line: `tony mcp` runs for a whole
    # agent session and prints to a stderr nobody reads, so the only way this
    # machine's owner hears about a release is through the agent talking to
    # them. The request overlaps the git work below and nothing waits on it.
    check = install.startUpdateCheck()

    repoPath = os.path.abspath(path or os.getcwd())
    try:
        root = resolveRepo(repoPath)
    except ValueError as e:
        return f"tony: {e}"

    base, head = parseRange(range)
    if base is None:
        try:
            base = resolveBase(root)
        except ValueError as e:
            return f"tony: {e}"

    problem = workingTreeProblem(root, head)
    if problem:
        return f"tony: {problem}"

    diff = getDiff(root, base, head)
    if diff.startswith(FAILED):
        return f"tony: {diff}"
    if not diff.strip():
        return (
            f"tony: {base}...{head} has no changes to review. Check the range — a "
            "branch that is already merged shows nothing against its base."
        )

    # Fetched, never assumed. The document and the validator behind
    # `tony_publish` are one contract, and they are only guaranteed to agree
    # when both came from the same place at the same moment.
    served, problem = hosted.fetchInstructions()
    if problem:
        return (
            f"tony: could not fetch the review instructions — {problem}\n"
            "  Nothing was started. Try again when the network is back."
        )

    sid = secrets.token_hex(8)
    SESSIONS[sid] = {
        "root": root, "base": base, "head": head, "diff": diff,
        "instructions": served["version"],
        # Everything the provenance record needs that is only knowable here:
        # who is calling, how big the thing they were handed is, and when they
        # were handed it. See `provenanceOf`.
        "harness": harness,
        "startedAt": time.time(),
        "diffLines": diff.count("\n") + 1,
        "diffFiles": len(splitDiffByFile(diff)),
    }

    # What the agent reads is not what the page is built from. It gets each
    # hunk grown to its enclosing function, which is the thing it would
    # otherwise open the file to see, and it gets generated files without their
    # bodies. Both trade a larger single tool result for far fewer file reads —
    # and every avoided read was also a turn that re-sent the whole diff again.
    forAgent = getDiff(root, base, head, wholeFunctions=True)
    if forAgent.startswith(FAILED):
        forAgent = diff
    forAgent = withoutGeneratedBodies(forAgent)

    header = (
        f"sessionId: {sid}\n"
        f"repository: {os.path.basename(root)} at {root}\n"
        f"range: {base}...{head}\n"
        f"{accountLine(justApproved)}"
        f"{updateLine(check)}\n"
    )

    split = splitIntoParts(forAgent, PART_CHARS)
    if len(split) > 1:
        SESSIONS[sid]["document"] = served["document"]
        SESSIONS[sid]["parts"] = [{
            "paths": set(paths),
            "diff": onlyPaths(diff, set(paths)),
            "forAgent": onlyPaths(forAgent, set(paths)),
            "attempts": 0, "review": None, "gaps": [], "model": "",
        } for paths in split]
        return header + dispatch(sid, split)

    return (
        f"{header}"
        f"{served['document']}\n\n"
        "--- THE DIFF ---\n\n"
        f"{forAgent}"
    )


# --- large diffs, in parts -------------------------------------------------
#
# Under agent-native the diff is spent out of the reviewer's own context
# window, so a big enough change is not expensive, it is impossible: the
# harness compacts partway through and the rest of the review is written from a
# summary. So past PART_CHARS the review is split by file, each part goes to a
# fresh subagent with a context of its own, and tony merges what they publish.
#
# The split sessions live in SESSIONS like any other, which assumes the
# subagents reach the same `tony mcp` process as whoever called tony_start.
# Harnesses that run subagents share their parent's MCP connections, so they do.

def dispatch(sid, split):
    """What the agent that called tony_start does with a diff too big for it."""
    listed = "\n".join(
        f"  part {n} — {len(paths)} file{'' if len(paths) == 1 else 's'}: "
        + (paths[0] if len(paths) == 1 else f"{paths[0]} … {paths[-1]}")
        for n, paths in enumerate(split, 1)
    )
    return (
        f"This diff is too large to review well in one context, so tony has split "
        f"it into {len(split)} parts.\n\n"
        f"{listed}\n\n"
        "Do not review it yourself. For EACH part, start a fresh subagent with "
        "this task, in parallel if you can:\n\n"
        f'  "Call tony_start with sessionId {sid} and part <n>. Follow the '
        "instructions it returns, review only that part, and call tony_publish "
        "with the same sessionId and part. When it is accepted, report back the "
        'one-sentence intent you wrote."\n\n'
        "When every part has been accepted, call tony_publish yourself with "
        f'sessionId {sid}, no part, and review {{"intent": "..."}} — one sentence '
        "for the whole change, written from the intents the subagents reported. "
        "That publishes the page and returns its URL.\n\n"
        "If you are yourself a subagent and cannot start subagents of your own, "
        "stop here and return this whole message to the agent that started you: "
        "it has to hand out the parts."
    )


def partReview(sessionId, part):
    """One part of a split review: the instructions, and that part's diff."""
    session = SESSIONS.get(sessionId) if sessionId else None
    if session is None or not session.get("parts"):
        return (
            "tony: no such multi-part review. `sessionId` and `part` only go "
            "together when an earlier tony_start split its diff into parts. To "
            "begin a review, call tony_start with neither."
        )
    parts = session["parts"]
    if not isinstance(part, int) or not 1 <= part <= len(parts):
        return f"tony: `part` must be a number from 1 to {len(parts)}."

    n, total = part, len(parts)
    return (
        f"sessionId: {sessionId}\n"
        f"part: {n} of {total}\n"
        f"repository: {os.path.basename(session['root'])} at {session['root']}\n"
        f"range: {session['base']}...{session['head']}\n\n"
        f"You are reviewing part {n} of {total} of one large diff. Other agents "
        "are reviewing the rest in their own contexts, and tony merges the parts "
        "into one page.\n\n"
        "- Annotations, skips and anchored risks go only in the files of this "
        "part — the diff below is exactly those files. tony_publish refuses "
        "anything anchored in another part's files.\n"
        "- Impacts and walkthroughs may reach anywhere in the repository. An "
        "impact still must not point at a changed file, including one in "
        "another part.\n"
        "- Walkthroughs only for flows whose changed steps are mostly in this "
        "part's files. A flow that starts in another part's files is that "
        "reviewer's to trace, so the merged page shows each flow once.\n"
        "- `intent` is one sentence on what this part does. When tony_publish "
        "accepts the part, report that sentence back to whoever started you.\n\n"
        f"Call tony_publish with sessionId {sessionId} and part {n}.\n\n"
        f"{session['document']}\n\n"
        "--- THE DIFF ---\n\n"
        f"{parts[n - 1]['forAgent']}"
    )


def publishPart(session, sessionId, review, part, model):
    """Validate one part and hold it until the rest arrive."""
    parts = session["parts"]
    if not isinstance(part, int) or not 1 <= part <= len(parts):
        return f"tony: `part` must be a number from 1 to {len(parts)}."
    p = parts[part - 1]

    problems = validate(review)
    if problems:
        return rejection(problems, part)
    # Against the whole diff, so an impact on a file in another part is still
    # an impact on a changed file — then against this part, so two reviewers
    # never explain the same file.
    problems = (anchorProblems(review, session["diff"], session["root"])
                + outsidePart(review, p["paths"], part))
    if problems:
        return rejection(problems, part)

    gaps = coverageGaps(p["diff"], review)
    if gaps:
        p["attempts"] += 1
        if p["attempts"] < MAX_ATTEMPTS:
            return coverageRejection(gaps, p["attempts"], part)

    p["review"], p["gaps"], p["model"] = review, gaps, (model or "").strip()
    left = [str(i) for i, q in enumerate(parts, 1) if q["review"] is None]
    shortfall = (
        f" with {len(gaps)} block{'' if len(gaps) == 1 else 's'} still "
        f"unexplained after {MAX_ATTEMPTS} attempts — the page will mark them"
        if gaps else ""
    )
    return (
        f"Part {part} of {len(parts)} accepted{shortfall}. Report your one-sentence "
        "intent back to whoever started you; there is nothing else to do."
        + (f" Parts still outstanding: {', '.join(left)}." if left else
           f" It was the last part: the agent that started you now calls "
           f"tony_publish with sessionId {sessionId} and no part to publish the page.")
    )


def outsidePart(review, paths, part):
    """Everything this part anchored in a file that belongs to another part."""
    problems = []
    for field in ("annotations", "skips", "risks"):
        for i, item in enumerate(review.get(field) or []):
            if isinstance(item, dict) and item.get("path") and item["path"] not in paths:
                problems.append(
                    f"{field}[{i}] is anchored in {item['path']}, which belongs to "
                    f"another part. Part {part} covers only the files in the diff "
                    "you were given — remove it; that file has its own reviewer."
                )
    return problems


def publishWhole(session, review, model):
    """Merge every accepted part under one intent, and publish the page."""
    intent = str((review or {}).get("intent") or "").strip() if isinstance(review, dict) else ""
    if not intent:
        return rejection([
            "`intent` is missing — one sentence on what the whole change "
            "accomplishes, written from the intents the part reviewers reported."
        ])

    parts = session["parts"]
    left = [str(i) for i, p in enumerate(parts, 1) if p["review"] is None]
    if left:
        return (
            f"tony: not published — part{'' if len(left) == 1 else 's'} "
            f"{', '.join(left)} not accepted yet. Wait for those subagents, or "
            "start one for each missing part, then call this again."
        )

    merged = {"intent": intent}
    for field in ("annotations", "risks", "impacts", "skips", "walkthroughs"):
        merged[field] = [x for p in parts for x in (p["review"].get(field) or [])]

    gaps = [g for p in parts for g in p["gaps"]]
    session["attempts"] = sum(p["attempts"] for p in parts)
    model = model or next((p["model"] for p in parts if p["model"]), "")
    return publishPage(session, merged, model, incompleteNotice(gaps) if gaps else "")


def accountLine(justApproved=""):
    """Which account this review publishes to, so a wrong one is caught early."""
    login = justApproved or hosted.savedLogin()
    if not login:
        return ""
    if justApproved:
        return (
            f"account: {login} (just approved). Tell the user this review will publish\n"
            f"  to {login}'s tony account before you start, in case that is not who they meant.\n"
        )
    return f"account: {login}\n"


def updateLine(check):
    """What to tell the agent about a newer tony, or "".

    Written as an instruction because everything else in this response is one,
    and because the failure mode of a bare fact in a tool result is an agent
    that decides to act on it — here, by shelling out to upgrade tony in the
    middle of a review.
    """
    newer = install.pendingUpdate(check)
    if not newer:
        return ""
    current = install.installedVersion() or "an older build"
    return (
        f"\ntony {newer} is out; this machine has {current}. Say so once at the "
        "end, alongside\nthe URL — `tony update` installs it. Do not run it "
        "yourself, and do not let it\ninterrupt the review.\n"
    )


def publishReview(review, sessionId=None, model="", part=None):
    """Validate one review, then render and publish it. Returns text for the agent."""
    session = SESSIONS.get(sessionId) if sessionId else None
    if session is None:
        return (
            "tony: no such review session. Call tony_start first and pass back the "
            "sessionId it returned, unchanged."
        )

    if session.get("parts"):
        with PARTS_LOCK:
            if part:
                return publishPart(session, sessionId, review, part, model)
            return publishWhole(session, review, model)
    if part:
        return (
            "tony: this review was not split into parts. Call tony_publish again "
            "without `part`."
        )

    problems = validate(review)
    if problems:
        return rejection(problems)

    # Then whether any of it points at something real. Separate from the shape
    # checks because they need the diff and the working tree, and separate from
    # coverage because a review naming files that do not exist has not been
    # written against this repository at all.
    problems = anchorProblems(review, session["diff"], session["root"])
    if problems:
        return rejection(problems)

    # Coverage last, because a review that fails the checks above has not been
    # read closely enough for its gaps to mean anything yet.
    gaps = coverageGaps(session["diff"], review)
    incomplete = ""
    if gaps:
        session["attempts"] = session.get("attempts", 0) + 1
        if session["attempts"] < MAX_ATTEMPTS:
            return coverageRejection(gaps, session["attempts"])
        # Out of attempts. Publish what there is rather than nothing — see
        # `incompleteNotice`.
        incomplete = incompleteNotice(gaps)

    return publishPage(session, review, model, incomplete)


def publishPage(session, review, model, incomplete=""):
    """Render a review that has passed the gate, upload it, and say where it went."""
    root, base, head = session["root"], session["base"], session["head"]
    rangeLabel = f"{base or 'default'}...{head}"
    payload = buildPayload(review, session["diff"], root, rangeLabel)
    # Which document this review was written against. The one record that makes
    # "did changing the instructions change anything" answerable later.
    payload["instructions"] = session["instructions"]
    payload["provenance"] = provenanceOf(session, model)

    url, problem = hosted.publish(
        dumpPayload(payload), repo=os.path.basename(root), rangeLabel=rangeLabel,
    )
    if problem:
        return (
            f"tony: the review passed validation but could not be published — {problem}\n"
            "  Nothing is lost: call tony_publish again with the same sessionId."
        )
    return (
        f"Published: {url}\n\n"
        "Give the developer this URL. Do not paste the review into the "
        "conversation — the page is the deliverable." + incomplete
    )


# --- provenance ------------------------------------------------------------
#
# What produced this review. tony no longer owns the model or the loop, so the
# only way to know whether a given agent clears the bar is to record what wrote
# each review and look at the coverage it achieved. That is the whole argument
# for these columns: they are how "which harnesses can we support" stops being
# a guess.
#
# Not recorded, because they are not observable from here: turn count and token
# spend, which happen entirely inside the caller's context. The model is asked
# for rather than measured, and an agent that does not answer leaves it blank.

def harnessOf(ctx):
    """(name, version) of the agent connected to this server, or ("", "").

    MCP clients identify themselves at initialize, which is the one piece of
    provenance nobody has to be asked for. Wrapped in a catch-all because it
    reaches through three layers of SDK object to get there, and a review must
    never fail to publish over a diagnostic field.
    """
    try:
        info = ctx.session.client_params.clientInfo
        return (info.name or "", info.version or "")
    except Exception:
        return ("", "")


def provenanceOf(session, model=""):
    """The record of what wrote this review, assembled at publish."""
    harness, version = session.get("harness") or ("", "")
    return {
        "harness": harness,
        "harnessVersion": version,
        # Self-reported: nothing in the protocol carries it, so the tool asks
        # and the instructions say to answer. Blank is a real answer too — it
        # says the agent was not told to, or would not.
        "model": (model or "").strip()[:120],
        "retries": session.get("attempts", 0),
        "seconds": max(0, round(time.time() - session.get("startedAt", time.time()))),
        "diffLines": session.get("diffLines", 0),
        "diffFiles": session.get("diffFiles", 0),
    }


# --- coverage --------------------------------------------------------------

# A run this short is a moved import, a whitespace fix, a bumped constant.
# Demanding prose for it is how a gate manufactures padding, which is the one
# thing the instructions spend the most words forbidding.
MIN_RUN = 3

# How many gaps to name before the list stops being something to act on.
MAX_LISTED = 20

# How many times one session is sent back to fill gaps before tony publishes
# what it has. The retries are the point of the gate — they are cheap, and they
# are what makes an agent go back and explain what it skipped. Refusing forever
# is not: the developer spent a context window on this, and a page that shows
# its own gaps is worth more to them than a message saying they got nothing.
MAX_ATTEMPTS = 3


def coverageGaps(diff, review):
    """Runs of changed code that nothing in this review accounts for.

    Returns [(path, start, end)]. A run is accounted for by an annotation that
    explains it or by a skip that says why it needs no explaining — not by a
    risk, which warns about code it assumes has already been explained.
    """
    byPath = itemsByPath(
        review.get("annotations") or [],
        review.get("risks") or [],
        review.get("skips") or [],
    )
    gaps = []
    for f in splitDiffByFile(diff):
        if f["binary"] or isSkippable(f["path"]) or not f["body"]:
            continue
        _, missed = runCoverage(f["body"], byPath.get(f["path"], []))
        for start, end, _ in missed:
            if end - start + 1 >= MIN_RUN:
                gaps.append((f["path"], start, end))
    return gaps


def coverageRejection(gaps, attempt, part=None):
    """A refusal naming every block, because the reader has to go fix them."""
    shown = gaps[:MAX_LISTED]
    listed = "\n".join(
        f"  {path}:{start}-{end}   ({end - start + 1} lines)" for path, start, end in shown
    )
    more = f"\n  ... and {len(gaps) - len(shown)} more" if len(gaps) > len(shown) else ""
    left = MAX_ATTEMPTS - attempt
    return (
        f"tony: not published — {len(gaps)} block"
        f"{'' if len(gaps) == 1 else 's'} of changed code that nothing explains.\n\n"
        f"{listed}{more}\n\n"
        "Every changed block needs one of two things: an annotation anchored "
        "inside it, or\n"
        "an entry in `skips` saying why it needs no explaining — generated "
        "output, a mechanical\n"
        "rename, vendored code. A skip is shown to the reader, so give a real "
        "reason.\n\n"
        "Do not pad. An annotation that restates the syntax is worse than a "
        "skip that is honest.\n\n"
        f"Then call tony_publish again with the same sessionId{again(part)}. "
        f"{left} attempt{'' if left == 1 else 's'} left."
    )


def incompleteNotice(gaps):
    """What to say when we publish a review that still has holes in it.

    The page marks every one of them — a dashed block where the code is, and a
    count per file — so this is not a bad review passed off as a good one. It is
    an honest one, and honestly labelled, which is worth more than a refusal
    after the developer has already paid for the work.
    """
    return (
        f"\n\nPublished with {len(gaps)} block"
        f"{'' if len(gaps) == 1 else 's'} still unexplained, after "
        f"{MAX_ATTEMPTS} attempts. The page marks each one, so the reader can "
        "see what was not covered.\nTell the developer that, and that a "
        "narrower range would get a fuller review."
    )


# --- validation ------------------------------------------------------------
#
# Shape only: is this the right kind of object, with the fields each kind of
# annotation requires. Whether any of it points at a real place is `anchors.py`,
# and whether it accounts for the whole diff is `coverageGaps`. All three share
# the contract set here: every problem is one sentence naming the exact place it
# went wrong, phrased as an instruction, because what reads it is a model
# deciding what to change — not a person reading a diagnostic.

KINDS = ("added", "changed", "removed")

# Which fields each kind must carry, and which it must not. The asymmetry is the
# point: a `prev` on an "added" annotation means a previous version was invented,
# which is worse than leaving it out.
REQUIRED = {"added": ("now",), "changed": ("prev", "now", "impact"),
            "removed": ("prev", "impact")}
FORBIDDEN = {"added": ("prev", "impact"), "changed": (), "removed": ("now",)}


def validate(review):
    """Everything wrong with this review object, as instructions. Empty means good."""
    if not isinstance(review, dict):
        return [f"`review` must be an object, not {type(review).__name__}."]

    problems = []
    if not str(review.get("intent") or "").strip():
        problems.append(
            "`intent` is missing — one sentence on what the change accomplishes."
        )

    annotations = review.get("annotations")
    if annotations is None:
        problems.append(
            "`annotations` is missing. It is the entire walkthrough; an empty "
            "array is only right for a change with nothing to explain."
        )
    elif not isinstance(annotations, list):
        problems.append("`annotations` must be an array.")
    else:
        for i, note in enumerate(annotations):
            problems += annotationProblems(i, note)

    for field in ("risks", "impacts", "walkthroughs", "skips"):
        value = review.get(field)
        if value is not None and not isinstance(value, list):
            problems.append(f"`{field}` must be an array, or left out entirely.")

    for i, skip in enumerate(review.get("skips") or []):
        if not isinstance(skip, dict):
            problems.append(f"skips[{i}] must be an object.")
            continue
        for field in ("path", "line", "why"):
            if not skip.get(field) and skip.get(field) != 0:
                problems.append(f"skips[{i}] has no `{field}`.")
    return problems


def annotationProblems(i, note):
    """What is wrong with one annotation, named by where the agent can find it."""
    if not isinstance(note, dict):
        return [f"annotations[{i}] must be an object."]

    where = f"annotations[{i}]"
    if note.get("path"):
        where += f" ({note['path']}:{note.get('line', '?')})"

    problems = [f"{where} has no `{field}`."
                for field in ("path", "line", "title")
                if not note.get(field) and note.get(field) != 0]

    kind = note.get("kind")
    if kind not in KINDS:
        return problems + [
            f"{where} has kind {kind!r}. It must be one of: {', '.join(KINDS)}."
        ]

    problems += [f'{where} is "{kind}", which requires a `{field}`.'
                 for field in REQUIRED[kind]
                 if not str(note.get(field) or "").strip()]
    problems += [f'{where} is "{kind}", which must not have a `{field}` — remove it.'
                 for field in FORBIDDEN[kind] if note.get(field)]
    return problems


def again(part):
    """How a retry names what it is retrying."""
    return f" and part {part}" if part else ""


def rejection(problems, part=None):
    """A refusal that can be acted on: what is wrong, then what to do about it."""
    listed = "\n".join(f"  - {p}" for p in problems)
    count = f"{len(problems)} problem{'' if len(problems) == 1 else 's'}"
    return (
        f"tony: not published — {count} to fix.\n\n{listed}\n\n"
        f"Fix exactly these and call tony_publish again with the same sessionId{again(part)}. "
        "Nothing else about the review needs to change, and the diff has not moved."
    )


# --- the server ------------------------------------------------------------
#
# These descriptions are what `--help` used to be. Nothing else tells an agent
# that "review this with tony" means calling a tool rather than reading the diff
# and summarising it in the chat — which it can do, badly, for free. So they say
# what tony produces that a summary does not, and when not to bother.

START_DESCRIPTION = """\
Start a tony review of a git diff. Returns the diff, the instructions for writing \
the review, and a sessionId to pass to tony_publish.

Use this whenever someone asks for a review, a walkthrough, or an explanation of a \
branch, a PR, or a range of commits — and whenever they say "tony". What it produces \
is a published page: every hunk annotated, a blast radius of files outside the diff \
that the change reaches, and steppable runtime walkthroughs. That is a different \
artefact from a summary in the chat, and it is the one the reader keeps.

Do the review in a FRESH SUBAGENT, not in the session that wrote the code. An agent \
reviewing its own work explains what it meant to do; a clean context sees only what \
is actually there, which is what the reader is going to have to live with. Spawn a \
subagent, have it call tony_start and tony_publish, and report back the URL.

A large diff comes back split into parts rather than as one diff, because it is \
too big for one context to review well. The response says what to do: each part \
goes to its own fresh subagent, which calls tony_start and tony_publish with the \
sessionId and its part; then one tony_publish without a part publishes the page.

Expect to read files. The instructions returned will tell you to open every changed \
file in full and grep for consumers of anything whose shape changed — that is where \
the blast radius comes from, and it cannot be had from the diff alone."""

PUBLISH_DESCRIPTION = """\
Validate and publish a finished tony review. Returns the URL of the published page.

`review` is the object described by the instructions tony_start gave you. \
`sessionId` is the one it returned, unchanged. `model` is the model identifier you \
are running as, if you know it — it is recorded with the review and never shown to \
the reader.

This validates before it publishes anything. A rejection lists the specific gaps — \
missing annotations, unexplained hunks, fields that do not match the kind — and \
nothing is lost when it happens: fix those items and call this again with the same \
sessionId. The diff does not move between attempts.

Call it once, when the whole review is written. The one exception is a review \
tony_start split into parts: each part is published with its `part` number, and \
then once more without one, with only the overall `intent`, to publish the page."""


def buildServer():
    server = Server("tony")

    # `ctx` is injected by the SDK and kept out of the tool's schema, so the
    # agent never sees it. It is how the server learns which harness is calling.
    @server.tool(name="tony_start", description=START_DESCRIPTION)
    def tony_start(path: str = "", range: str = "", sessionId: str = "",
                   part: int = 0, ctx: Context = None) -> str:
        """
        Args:
            path: Repository path, or any directory inside it. Defaults to the
                working directory.
            range: What to diff, in git's range syntax — "main...HEAD". A bare
                branch name means "that branch...HEAD". Omit for the repo's
                default branch.
            sessionId: Only to fetch one part of a review tony_start split.
                Leave empty to begin a review.
            part: Which part to fetch, with sessionId. Leave 0 otherwise.
        """
        return startReview(path or None, range or None, harness=harnessOf(ctx),
                           sessionId=sessionId or None, part=part or None)

    @server.tool(name="tony_publish", description=PUBLISH_DESCRIPTION)
    def tony_publish(review: dict, sessionId: str, model: str = "",
                     part: int = 0) -> str:
        """
        Args:
            review: The review object, matching the schema tony_start supplied.
            sessionId: The id from tony_start, unchanged.
            model: The model you are running as, as its API identifier — for
                example "claude-opus-5". Recorded with the review so tony can
                tell which models write good ones. Leave empty if you do not
                know it; never guess.
            part: The part number, when publishing one part of a split
                review. Leave 0 to publish a whole review, or to publish the
                page once every part is in.
        """
        return publishReview(review, sessionId, model, part or None)

    return server


def serve(argv=None):
    """Run the MCP server on stdio until the client disconnects."""
    buildServer().run(transport="stdio")
    return 0
