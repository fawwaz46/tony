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

# The SDK renamed FastMCP to MCPServer in 2.0. The class is the same shape —
# same constructor, same `.tool` decorator, same `.run(transport=...)` — so
# both are accepted rather than pinning tony to a superseded major. A
# dependency floor of `mcp>=1.9` resolves to 2.x on a fresh install and to
# whatever is already there on an upgrade, and both have to work.
try:
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import FastMCP as Server

from tony_cli import hosted
from tony_cli.layout import isSkippable, itemsByPath, runCoverage
from tony_cli.page import renderPage
from tony_cli.payload import buildPayload, dumpPayload
from tony_cli.source.local import (
    FAILED, getDiff, isDirty, resolveBase, resolveRepo, resolveRev,
    splitDiffByFile, withoutGeneratedBodies,
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

NOT_LOGGED_IN = """\
tony: this machine is not logged in, so there is nowhere to publish to.

  Ask the developer to run `tony login` — it takes one browser approval — then
  call tony_start again. Do not write the review until that is done; it would
  have nowhere to go."""


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


def startReview(path=None, range=None):
    """Set up a review and return what the agent needs to write it."""
    # Checked first, and deliberately before anything expensive: an agent that
    # writes a full review and only then learns it cannot be published has
    # spent the user's context for nothing.
    if not hosted.savedToken():
        return NOT_LOGGED_IN

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
    }

    # What the agent reads is not what the page is built from. It gets each
    # hunk grown to its enclosing function, which is the thing it would
    # otherwise open the file to see, and it gets generated files without their
    # bodies. Both trade a larger single tool result for far fewer file reads —
    # and every avoided read was also a turn that re-sent the whole diff again.
    forAgent = getDiff(root, base, head, wholeFunctions=True)
    if forAgent.startswith(FAILED):
        forAgent = diff

    return (
        f"sessionId: {sid}\n"
        f"repository: {os.path.basename(root)} at {root}\n"
        f"range: {base}...{head}\n\n"
        f"{served['document']}\n\n"
        "--- THE DIFF ---\n\n"
        f"{withoutGeneratedBodies(forAgent)}"
    )


def publishReview(review, sessionId=None):
    """Validate one review, then render and publish it. Returns text for the agent."""
    session = SESSIONS.get(sessionId) if sessionId else None
    if session is None:
        return (
            "tony: no such review session. Call tony_start first and pass back the "
            "sessionId it returned, unchanged."
        )

    problems = validate(review)
    if problems:
        return rejection(problems)

    # Coverage last, because a review that fails the shape check has not been
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

    root, base, head = session["root"], session["base"], session["head"]
    rangeLabel = f"{base or 'default'}...{head}"
    payload = buildPayload(review, session["diff"], root, rangeLabel)
    # Which document this review was written against. The one record that makes
    # "did changing the instructions change anything" answerable later.
    payload["instructions"] = session["instructions"]

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


def coverageRejection(gaps, attempt):
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
        f"Then call tony_publish again with the same sessionId. "
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
# Shape only, so far. Coverage, anchor, and reference checks are the rest of the
# gate. What they will share is the contract set here: every problem is one
# sentence naming the exact place it went wrong, phrased as an instruction,
# because what reads it is a model deciding what to change — not a person
# reading a diagnostic.

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


def rejection(problems):
    """A refusal that can be acted on: what is wrong, then what to do about it."""
    listed = "\n".join(f"  - {p}" for p in problems)
    count = f"{len(problems)} problem{'' if len(problems) == 1 else 's'}"
    return (
        f"tony: not published — {count} to fix.\n\n{listed}\n\n"
        "Fix exactly these and call tony_publish again with the same sessionId. "
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

Expect to read files. The instructions returned will tell you to open every changed \
file in full and grep for consumers of anything whose shape changed — that is where \
the blast radius comes from, and it cannot be had from the diff alone."""

PUBLISH_DESCRIPTION = """\
Validate and publish a finished tony review. Returns the URL of the published page.

`review` is the object described by the instructions tony_start gave you. \
`sessionId` is the one it returned, unchanged.

This validates before it publishes anything. A rejection lists the specific gaps — \
missing annotations, unexplained hunks, fields that do not match the kind — and \
nothing is lost when it happens: fix those items and call this again with the same \
sessionId. The diff does not move between attempts.

Call it once, when the whole review is written. It is not incremental."""


def buildServer():
    server = Server("tony")

    @server.tool(name="tony_start", description=START_DESCRIPTION)
    def tony_start(path: str = "", range: str = "") -> str:
        """
        Args:
            path: Repository path, or any directory inside it. Defaults to the
                working directory.
            range: What to diff, in git's range syntax — "main...HEAD". A bare
                branch name means "that branch...HEAD". Omit for the repo's
                default branch.
        """
        return startReview(path or None, range or None)

    @server.tool(name="tony_publish", description=PUBLISH_DESCRIPTION)
    def tony_publish(review: dict, sessionId: str) -> str:
        """
        Args:
            review: The review object, matching the schema tony_start supplied.
            sessionId: The id from tony_start, unchanged.
        """
        return publishReview(review, sessionId)

    return server


def serve(argv=None):
    """Run the MCP server on stdio until the client disconnects."""
    buildServer().run(transport="stdio")
    return 0
