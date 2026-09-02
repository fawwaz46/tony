import argparse
import json
import os
import sys
import webbrowser

import anthropic
from dotenv import load_dotenv
from tony_cli import hosted, install
from tony_cli.layout import parseReview
from tony_cli.page import renderPage
from tony_cli.payload import buildPayload, dumpPayload
from tony_cli.source.local import (
    FAILED, confine, getDiff, globFiles, grepFiles, isDirty, readFile,
    resolveBase, resolveRepo, resolveRev,
)

# The key comes from the environment first, then from ~/.tony/.env — a home
# that is not inside any repo, so it can never be committed by accident.
# Never from the repo being reviewed: tony should not be reading secrets out
# of a project it is also summarising to an API.
if not os.environ.get("ANTHROPIC_API_KEY"):
    load_dotenv(os.path.expanduser(os.path.join("~", ".tony", ".env")))

MISSING_KEY = """\
tony: ANTHROPIC_API_KEY is not set.

  tony reviews your diff with Claude, which needs an Anthropic API key.
  Get one at https://console.anthropic.com/settings/keys, then either:

    export ANTHROPIC_API_KEY=sk-ant-...        # this shell only

    mkdir -p ~/.tony && \\
      echo 'ANTHROPIC_API_KEY=sk-ant-...' >> ~/.tony/.env    # every shell

  A typical review costs well under a dollar; a very large diff costs more."""

SYSTEM = """You explain code changes to the developer who is about to own them — often someone who did not type this code, because an AI wrote it. Your job is to build their mental map of what now exists, fast.

Never pad, and never say the same thing twice. Explaining what a block of code does is not padding — that is the job. What you must not do is transcribe syntax: "sets `retries` to 3" tells the reader nothing the line did not. Say what the code does when it runs: "tries each upload up to three times before giving up on it and moving to the next". Describe the mechanism, not the motivation — why it was worth doing belongs in `impact`, not here.

You have file and search tools. Use them before you write anything — read the changed files in full, and grep for consumers of anything whose shape changed. Never describe code you did not read.

Your entire output is ONE fenced ```json block. No prose outside the fence — nothing before it, nothing after it.

THE JSON BLOCK

{
  "intent": "One sentence. What this change accomplishes, in plain language.",
  "annotations": [
    {"path": "billing/invoices.py", "line": 84, "title": "Idempotent invoice creation",
     "kind": "changed",
     "prev": "Every call inserted a new row unconditionally, so a client that retried a timed-out request created a second invoice.",
     "now": "Looks up the caller-supplied idempotency key first and returns the existing invoice when the key has been seen before.",
     "impact": "Retries stop double-billing customers. Anything that counted invoice rows to measure volume now sees fewer of them."},
    {"path": "billing/models.py", "line": 31, "title": "Idempotency key column",
     "kind": "added",
     "now": "The unique column the lookup depends on. Existing rows keep NULL, which the unique index permits, so old data needs no backfill."}
  ],
  "risks": [
    {"path": "billing/invoices.py", "line": 90,
     "text": "The key lookup and the insert are not one transaction, so two simultaneous retries can still race past each other and both insert."}
  ]
}

ANNOTATIONS — these are the entire walkthrough. Everything the reader learns, they learn here.

COVERAGE — this is the rule that matters most. Every hunk in the diff must be explained. Walk the diff hunk by hunk and account for all of it. If one hunk contains several distinct changes, write several annotations against it. Leaving a hunk unannotated is a failure, not concision. The only things you may skip are lockfiles, generated code, and binary assets. There should never be blocks of code that aren't annotated. The developer reading through needs everything to be annotated so that they could read end to end and understand. This is an alternative to reading code.

MIRRORED FILES — repositories often keep two copies of the same code: a sync and an async version of one module, a generated client beside its source, the same fix applied to several platform-specific copies. When two or more changed files receive substantively the same change, do NOT explain it twice.

Pick the copy a reader is most likely to open — the sync one, the hand-written one, the one the tests import — and annotate it in full. For each remaining copy, emit exactly ONE annotation:

{"path": "src/ahttpx/_parsers.py", "line": 227, "title": "Same change, async copy",
 "kind": "added",
 "now": "Mirrors src/httpx/_parsers.py line for line, with async/await. Read the annotations there."}

Anchor it at the first changed line in that file. Do not restate the explanation, and do not write a `prev` or `impact` for it. Two files count as mirrors when the change is the same idea in both, even if the syntax differs — an `async def` against a `def`, an `await` against a plain call. They are NOT mirrors merely because both were touched by the same PR.

Assume the reader did not write this code and cannot necessarily read this syntax fluently. Do not assume they know the language's idioms, the framework's conventions, or what any given API call does. When code does something non-obvious — a hook, a ref, a directive, a lifecycle behaviour, an operator whose meaning is not literal — say what it does mechanically, in the same sentence, without a detour.

FIELDS
- `path` is repo-relative. `line` is a line number in the NEW file that the annotation sits above — the first line of the code it describes. For a pure deletion, use the line where the removed code used to begin.
- `title`: at most six words. A label, not a sentence.
- `kind`: one of "added", "changed", "removed".
  - "added" — this code is new; nothing was replaced.
  - "changed" — this code replaces behaviour that already existed.
  - "removed" — this code is gone and nothing took its place.
- `now`: what this code does when it runs, mechanically, in plain language — what the function does, what the loop iterates over and what it does to each item, what a condition decides. Enough that someone who cannot read this language fluently does not have to. As many sentences as the code needs and no more; a three-line assignment needs one, a twenty-line loop may need four. Required for "added" and "changed". Omit for "removed".
- `prev`: how it worked before — the actual old mechanism, not "it did not exist". One or two sentences. Required for "changed" and "removed". NEVER include it for "added", and never invent it: if you did not read the old version, go read it before writing the annotation.
- `impact`: what the difference means in practice — what now behaves differently for a user, a caller, or a build. This is the only field for consequences; keep them out of `now`. One or two sentences. Required for "changed" and "removed". Omit for "added".

The reader reads `prev`, `now`, and `impact` as three separate panes, so each must stand alone. Do not write `now` as a continuation of `prev`, and do not repeat the same sentence across two fields.

Order annotations by file, then by line.

IMPACTS — files this change reaches that are NOT in the diff.

A diff shows what was edited. It cannot show what breaks. After you have written the annotations, grep for every consumer of anything whose shape changed — a signature, a prop, an export, a schema, a config key, a route, an environment variable — and record each place that now behaves differently.

{"impacts": [
  {"symbol": "createInvoice", "fromPath": "billing/invoices.py",
   "path": "dashboard/src/api/billing.ts", "line": 112, "kind": "behavior-change",
   "why": "Calls the endpoint without an idempotency key, so it now takes the new code path where the server generates one per request."}
]}

- `symbol` is the changed thing this file depends on. It must match something you described in an annotation, so the two can be linked.
- `fromPath` is the file the symbol lives in — one of the changed files.
- `path` and `line` locate the consuming code. `line` is the line in that file that depends on the symbol. Verify it by reading the file; never guess.
- `kind` is one of:
  - "breaks" — this will fail to compile, or throw, or 404. Something is now wrong.
  - "behavior-change" — it still works, but does something different than before.
  - "compatible" — it consumes the changed thing and is fine. Say so explicitly; this is the common case and the reader needs to know you checked.
- `why` is one sentence: what this file does with the changed thing, and what is different for it now. Not a restatement of the annotation.

RULES
- Only files NOT present in the diff. A file that was edited is covered by its annotations.
- One entry per consuming site. If a file uses the changed symbol in three places and all three are affected, that is three entries.
- Report "compatible" consumers too. A blast radius that lists only problems teaches the reader nothing about coverage, and they cannot tell "no impact" from "did not look".
- Never list a file you did not read. If a consumer might exist that you could not confirm, say so in `risks` instead of inventing an impact.
- An empty list is valid when nothing outside the diff depends on what changed.

RISKS — genuine ones only, and only where you can name the failing path. These are shown behind a toggle and are not the point of the output.
- `text` is one sentence. What breaks, concretely.
- Anchor to `path` and `line` when the risk lives in the diff. Omit both when it does not.
- An empty list is a valid answer. Never manufacture risks, and never restate an annotation as a risk.

WALKTHROUGHS — a steppable trace of what the code DOES at runtime.

The reader has no working model of how this program executes. They cannot get one from reading the code, and a static picture of boxes and arrows will not give them one either. What builds it is following a single concrete scenario, one step at a time, watching state change.

Write at most two. Zero is correct when the change has no runtime behaviour — a copy edit, a rename, a config bump. Never write one that merely restates the annotations.

Put them in the `walkthroughs` array:

{"walkthroughs": [
  {
    "title": "Resuming a crashed export",
    "trigger": "You run `export --resume` after the previous run died partway",
    "whatChanged": "Before this diff a resumed export started over from the first record instead of picking up where it stopped.",
    "steps": [
      {"say": "The CLI reads the checkpoint file the previous run left behind, which records the last record it managed to write.",
       "path": "exporter/checkpoint.py", "lines": [22, 30],
       "state": {"lastWritten": "4180", "cursor": "0"},
       "phase": "new"},
      {"say": "The database cursor opens at that position instead of at zero, so nothing already exported is fetched a second time.",
       "path": "exporter/run.py", "lines": [57, 61],
       "state": {"cursor": "0 -> 4180"},
       "phase": "changed"}
    ]
  }
]}

FIELDS
- `title`: at most six words, naming the scenario.
- `trigger`: one sentence describing what the user or system does to start it. Concrete and physical — "you click X", "a link is pasted into Slack", "the page finishes loading" — never "the function is invoked".
- `whatChanged`: ONE sentence naming what this diff altered about THIS flow specifically, written so it makes sense before the reader has stepped through anything. This is the reason the walkthrough exists — if you cannot write it, the walkthrough does not belong.
- `steps`: in execution order. Between three and seven. Fewer than three is not a trace; more than seven is a lecture.
- `say`: ONE sentence, plain language, about what happens at this step and why. No jargon unless you define it in the same clause. Do not narrate the syntax — explain the effect.
- `path` and `lines`: `[start, end]` in the CURRENT file, the code responsible for this step. The reader is shown these exact lines, read from disk, so verify them. `lines` may be omitted for a step that happens outside the codebase (a browser behaviour, a third-party fetch), in which case omit `path` too.
- `state`: a small map of what is true at this step. Use `"before -> after"` when the step changes something. Keep to three entries or fewer, and name things as the code names them so the reader can connect the two. Omit when nothing observable changes.
- `phase`: "same" if this step happened before this diff too, "new" if the change introduced it, "changed" if the step existed but now behaves differently, "removed" if the change deleted it. Include "removed" steps in execution order where they used to run — seeing what no longer happens is how the reader understands the change.

RULES
- One scenario per walkthrough. Do not merge two unrelated flows.
- Trace what the code actually does. Read the files. Never guess at a line range or invent a step.
- Prefer the scenario the change most affects. If the diff alters what happens when a link is shared, trace a link being shared.
- Plain language throughout. The reader does not know what a hook, a ref, a prop, or a build step is unless you tell them in passing.

RULES
- Valid JSON. No comments, no trailing commas. Escape newlines inside strings.
- Skip lockfiles, generated code, and binary assets. Do not annotate them.
- If the whole diff is trivial, return the intent, an empty annotations array, and stop.
"""

GET_DIFF_TOOL = {
    "name": "getDiff",
    "description": (
        "Gets the diffs for a local repository. Returns the diff between the base "
        "branch and head as text. Accepts any path inside the repo - it resolves to "
        "the repo root automatically. Returns an error string if the path is not a "
        "git repository or the revisions are invalid."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "repoPath": {
                "type": "string",
                "description": "Absolute path to the repository, or any directory inside it.",
            },
            "base": {
                "type": "string",
                "description": "Branch to diff against. Omit to use the repo's default branch.",
            },
            "head": {
                "type": "string",
                "description": "Revision to diff. Defaults to HEAD.",
            },
        },
        "required": ["repoPath"],
    },
}
READ_TOOL = {
    "name": "readFile",
    "description": (
        "Read a file's full contents. Use this to verify what a diff hunk only hints at. "
        "Returns the text, or an error string if the path is not a readable text file. "
        "Long files are truncated with a marker."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file.",
            },
        },
        "required": ["path"],
    },
}

GLOB_TOOL = {
    "name": "globFiles",
    "description": (
        "Find files by name pattern. Matches against both the path relative to root and "
        "the bare filename. Skips .git, node_modules, and build output. Returns one "
        "relative path per line."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '*.py', '*.go', or 'src/**/*.ts'.",
            },
            "root": {
                "type": "string",
                "description": "Absolute path of the directory to search from.",
            },
        },
        "required": ["pattern", "root"],
    },
}

GREP_TOOL = {
    "name": "grepFiles",
    "description": (
        "Search file contents for a Python regex. This is how you find callers, imports, "
        "and references to a changed symbol. Skips .git, node_modules, and build output. "
        "Returns matching lines as 'relative/path:lineno: text'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Python regular expression to search for.",
            },
            "root": {
                "type": "string",
                "description": "Absolute path of the directory to search in.",
            },
        },
        "required": ["pattern", "root"],
    },
}

ALL_TOOLS = [GET_DIFF_TOOL, READ_TOOL, GLOB_TOOL, GREP_TOOL]

TOOLS = {
    "getDiff": getDiff,
    "readFile": readFile,
    "globFiles": globFiles,
    "grepFiles": grepFiles,
}

# Which argument of each tool names a path that must stay inside the repo.
PATH_ARGS = {"getDiff": "repoPath", "readFile": "path", "globFiles": "root", "grepFiles": "root"}


def runTool(name, toolInput, root):
    func = TOOLS.get(name)
    if func is None:
        return f"unknown tool: {name}"

    # Tool inputs come from the model, and the model reads untrusted repo
    # content. Whatever it asks for, it gets nothing outside the repo under
    # review — there is no legitimate reason to read anywhere else, and the
    # results of these calls are sent off-machine in the next API request.
    arg = PATH_ARGS.get(name)
    if arg and arg in toolInput:
        inside = confine(root, str(toolInput[arg]))
        if inside is None:
            return f"refused: {toolInput[arg]} is outside the repository under review"
        toolInput = {**toolInput, arg: inside}

    try:
        return func(**toolInput)
    except Exception as e:
        return f"tool error:{e}"

DEFAULT_MODEL = "claude-opus-5"
# Streaming, so this is not bounded by how long one HTTP response may take.
# A review of a large diff has to annotate every hunk, and the old 16k ceiling
# truncated exactly the reviews that needed the most room.
DEFAULT_MAX_TOKENS = 64000

# How many times the model may come back for more tools before we stop paying.
# A review of a large diff settles well inside this; a model that has started
# looping never does, and every turn costs another request.
MAX_TURNS = 30


def parseRange(spec):
    """'main...HEAD' -> ('main', 'HEAD'). 'main' -> ('main', 'HEAD'). None -> (None, 'HEAD')."""
    if not spec:
        return None, "HEAD"
    if "..." in spec:
        base, _, head = spec.partition("...")
        return base or None, head or "HEAD"
    return spec, "HEAD"


def buildPrompt(repoPath, base, head):
    prompt = f"Review the diff for the repository at {repoPath}"
    if base:
        prompt += f", diffing {base}...{head}"
    return prompt


def review(repoPath, base=None, head="HEAD", model=DEFAULT_MODEL,
           maxTokens=DEFAULT_MAX_TOKENS, verbose=False):
    """Run the review loop.

    Returns (code, text, diff): 0 on success, non-zero on failure. `text` is the
    model's final message; `diff` is the diff the model actually reviewed, kept
    from its own getDiff call so the page renders the same change it read.
    """
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": buildPrompt(repoPath, base, head)}]
    diff = ""
    text = ""

    for _ in range(MAX_TURNS):
        try:
            # Streaming because `max_tokens` is large: a non-streaming request
            # has to deliver the whole answer within one HTTP timeout, and a
            # long review does not. It costs nothing and changes no output.
            #
            # `cache_control` caches the longest stable prefix — the system
            # prompt, the tool list, and the diff, which is usually most of the
            # request. Every turn after the first re-reads it at a tenth of the
            # price instead of paying full freight to send it again.
            with client.messages.stream(
                model=model,
                max_tokens=maxTokens,
                system=SYSTEM,
                messages=messages,
                tools=ALL_TOOLS,
                cache_control={"type": "ephemeral"},
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APIStatusError as e:
            print(f"tony: API error {e.status_code}: {e.message}", file=sys.stderr)
            return 1, text, diff
        except anthropic.APIConnectionError as e:
            print(f"tony: could not reach the API: {e}", file=sys.stderr)
            return 1, text, diff

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "max_tokens":
            print(
                f"tony: response hit the {maxTokens}-token limit and was cut off. "
                "Re-run with a larger --max-tokens.",
                file=sys.stderr,
            )
            text = "\n".join(b.text for b in response.content if b.type == "text")
            return 1, text, diff

        if response.stop_reason != "tool_use":
            text = "\n".join(b.text for b in response.content if b.type == "text")
            return 0, text, diff

        results = []
        if verbose:
            u = response.usage
            print(
                f"[usage] in={u.input_tokens} out={u.output_tokens} "
                f"cache_write={getattr(u, 'cache_creation_input_tokens', 0)} "
                f"cache_read={getattr(u, 'cache_read_input_tokens', 0)}",
                file=sys.stderr,
            )

        for block in response.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"[{block.name}] {block.input}", file=sys.stderr)
                result = runTool(block.name, block.input, repoPath)
                if block.name == "getDiff" and result.lstrip().startswith("diff --git "):
                    diff = result
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": results})

    print(
        f"tony: the review kept asking for more files after {MAX_TURNS} rounds and "
        "was stopped. Try a narrower range.",
        file=sys.stderr,
    )
    return 1, text, diff


def checkWorkingTree(root, head):
    """Every line of code tony shows is read from the working tree.

    Annotations, walkthrough code windows, and whole blast-radius files are all
    numbered against the NEW side of the diff. If the working tree is not that
    revision, those line numbers point at different code and the page is wrong
    in a way the reader cannot see. Returns a problem string, or None if clean.
    """
    wanted = resolveRev(root, head)
    if wanted is None:
        return f"cannot resolve revision {head!r}"

    if wanted != resolveRev(root, "HEAD"):
        return (
            f"{head} is not checked out, so the code on disk is not the code being "
            f"reviewed and every line tony showed you could be wrong.\n"
            f"       Run `git checkout {head}` first, or pass --stale to accept "
            "mismatched line numbers."
        )
    if isDirty(root):
        return (
            "the working tree has uncommitted changes. tony reviews committed work, "
            "and shows code straight from disk —\n       uncommitted edits would make "
            "those lines lie. Commit or stash first (`git stash` restores with "
            "`git stash pop`),\n       or pass --stale to accept possibly-wrong lines."
        )
    return None


def viewerFixture():
    """`web/src/fixtures/local.json` in tony's own checkout, if there is one.

    Only exists when tony is installed from source (`pip install -e .`), which is
    the case while the viewer is being built. Returns None for a plain install.

    Deliberately not `review.json`, which is tracked and ships as the homepage
    demo: this file holds a review of whatever repo `--viewer` was run in, so
    it is gitignored and must stay that way.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(
        os.path.join(here, "..", "..", "web", "src", "fixtures", "local.json")
    )
    return path if os.path.isdir(os.path.dirname(path)) else None


def reportPath(repoPath, base, head, ext="html"):
    """Where this review lands: `.tony/<base>...<head>.html` inside the repo."""
    stamp = f"{base or 'default'}...{head}".replace("/", "-").replace(" ", "-")
    return os.path.join(repoPath, ".tony", f"{stamp}.{ext}")


def saveRaw(path, text, diff):
    """Keep the model's answer and the diff it read, so the page can be rebuilt for free."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"review": text, "diff": diff}, fh)


def loadRaw(path):
    """The saved review and diff, or (None, None) if the file is not one."""
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        return saved["review"], saved["diff"]
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def writeReport(path, page):
    outDir = os.path.dirname(path)
    os.makedirs(outDir, exist_ok=True)
    # Reviews are disposable and belong to the reader, not the repo's history.
    ignore = os.path.join(outDir, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("*\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    # Account commands, dispatched before argparse so `tony login` does not
    # read as a repository path.
    if argv[:1] == ["login"]:
        return hosted.login()
    if argv[:1] == ["logout"]:
        return hosted.logout()
    if argv[:1] == ["whoami"]:
        return hosted.whoami()
    if argv[:1] == ["unpublish"]:
        if len(argv) != 2:
            print("usage: tony unpublish <id>", file=sys.stderr)
            return 2
        return hosted.unpublish(argv[1])
    # Imported here, not at the top: it pulls in the MCP SDK, and `tony` as a
    # CLI should not pay that import on every run to serve one subcommand.
    if argv[:1] == ["mcp"]:
        from tony_cli.mcp_server import serve
        return serve(argv[1:])
    if argv[:1] == ["install"]:
        from tony_cli import mcp_config
        return mcp_config.install(argv[1:])
    if argv[:1] == ["update"]:
        return install.update(argv[1:])
    if argv[:1] == ["uninstall"]:
        from tony_cli.uninstall import uninstall
        return uninstall(argv[1:])

    parser = argparse.ArgumentParser(
        prog="tony",
        description="Review a git diff for impact, not line-by-line.",
        epilog=(
            "commands:\n"
            "  tony <path> [BASE...HEAD]      review a diff — the default\n"
            "  tony install [host ...]        register the MCP server with your agent\n"
            "  tony mcp                       run the MCP server on stdio\n"
            "  tony update                    update to the latest release\n"
            "  tony uninstall                 delete tony, its key, and every saved review\n"
            "  tony --version                 what is installed\n"
            "\n"
            "  https://tony-cli.com\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path", nargs="?", default=os.getcwd(),
        help="Repository path, or any directory inside it (default: current directory).",
    )
    parser.add_argument(
        "range", nargs="?", default=None, metavar="BASE...HEAD",
        help=(
            "What to diff, in git's range syntax: 'main...HEAD'. A bare branch name "
            "means 'that branch...HEAD'. Omit to use the repo's default branch."
        ),
    )
    parser.add_argument(
        "--model", "-m", default=DEFAULT_MODEL,
        help=f"Model to review with (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, dest="maxTokens",
        help=f"Response token ceiling (default: {DEFAULT_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Log every tool call to stderr, to see what the review actually checked.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="asJson",
        help="Print the raw JSON review to stdout instead of writing a page.",
    )
    parser.add_argument(
        "--no-open", action="store_false", dest="openPage",
        help="Write the page but do not open it in a browser.",
    )
    # Reviews stay on this machine unless asked otherwise. Publishing used to be
    # the default, which put a GitHub account in front of a first run: `tony`
    # with no account printed an error and never reviewed anything. Sharing is a
    # separate act, and it is opt-in until it can be relied on end to end.
    parser.add_argument(
        "--publish", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--local", action="store_true",
        help=argparse.SUPPRESS,  # now the default; accepted so it never breaks
    )
    parser.add_argument(
        "--payload", nargs="?", const=True, default=False, metavar="PATH",
        help="Write the upload payload (windowed source, no absolute paths). "
             "Defaults to sitting next to the page; give a PATH to put it elsewhere.",
    )
    parser.add_argument(
        "--viewer", action="store_true",
        help="Write the payload straight into the local Astro viewer and reload it there.",
    )
    parser.add_argument(
        "--stale", action="store_true",
        help="Review a revision that is not checked out. The code shown comes from the "
             "working tree, so line numbers may not match the diff.",
    )
    parser.add_argument(
        "--replay", action="store_true",
        help="Rebuild the page from the last saved review for this range, without calling the API.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"tony {install.installedVersion() or 'unknown'}",
    )
    args = parser.parse_args(argv)

    if args.maxTokens < 1:
        print(f"tony: --max-tokens must be at least 1, not {args.maxTokens}.",
              file=sys.stderr)
        return 2

    # Checked before the review rather than after: --viewer is asking for the
    # payload to land somewhere that does not exist on a plain install, and
    # finding that out afterwards means having paid for a review to be told so.
    if args.viewer and not viewerFixture():
        print("tony: --viewer needs tony installed from source — there is no "
              "viewer to load into.", file=sys.stderr)
        return 2

    base, head = parseRange(args.range)
    repoPath = os.path.abspath(args.path)

    try:
        root = resolveRepo(repoPath)
    except ValueError as e:
        print(f"tony: {e}", file=sys.stderr)
        return 2

    # Resolve the base here rather than leaving it to the model, so the run is
    # reproducible and the reader is told what it was compared against.
    if base is None:
        try:
            base = resolveBase(root)
        except ValueError as e:
            print(f"tony: {e}", file=sys.stderr)
            return 2

    rawPath = reportPath(root, base, head, ext="json")

    problem = checkWorkingTree(root, head)
    if problem:
        if args.stale:
            print(f"tony: warning — {problem.splitlines()[0]}", file=sys.stderr)
        else:
            print(f"tony: {problem}", file=sys.stderr)
            return 2

    # Checked before the review runs — discovering it afterwards would waste an
    # API call the user already paid for.
    publishing = args.publish and not args.asJson
    if publishing and not hosted.savedToken():
        print(
            "tony: publishing needs an account.\n\n"
            "    tony login          # once, with GitHub\n\n"
            "  Or drop --publish to keep this review on your machine.\n",
            file=sys.stderr,
        )
        return 2

    if args.replay:
        if not os.path.exists(rawPath):
            print(f"tony: nothing saved for this range at {rawPath}", file=sys.stderr)
            return 2
        text, diff = loadRaw(rawPath)
        if text is None:
            print(f"tony: the saved review at {rawPath} could not be read. "
                  "Re-run without --replay.", file=sys.stderr)
            return 2
    else:
        # An empty range is the most common harmless mistake — a branch already
        # merged, or a typo'd base. Catch it here rather than after paying for a
        # review of nothing.
        probe = getDiff(root, base, head)
        if probe.startswith(FAILED):
            print(f"tony: {probe}", file=sys.stderr)
            return 2
        if not probe.strip():
            print(
                f"tony: {base}...{head} has no changes to review.\n"
                "       Check the range — a branch that is already merged shows "
                "nothing against its base.",
                file=sys.stderr,
            )
            return 2

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(MISSING_KEY, file=sys.stderr)
            return 2

        print(f"tony: reviewing {base or 'default branch'}...{head} in {root}", file=sys.stderr)
        code, text, diff = review(root, base, head, args.model, args.maxTokens, args.verbose)
        if code != 0:
            return code

    if args.asJson:
        print(text)
        return 0

    if not diff:
        # The model answered without ever pulling the diff, so there is nothing to
        # lay a page out against. The review itself is still worth handing back.
        print("tony: no diff was fetched during the review — printing raw output.",
              file=sys.stderr)
        print(text)
        return 1

    if not parseReview(text):
        # The model's answer had no usable JSON block — usually a response that
        # hit the token ceiling. A page built from it would show a bare diff and
        # look like a successful run. Fail loudly and keep the raw text instead.
        keep = reportPath(root, base, head, ext="raw.txt")
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(
            "tony: the review came back unparseable, so no page was written.\n"
            f"      The raw output is at {keep}. If it looks cut off, re-run "
            "with a larger --max-tokens.",
            file=sys.stderr,
        )
        return 1

    rangeLabel = f"{base or 'default'}...{head}"
    payloadJson = dumpPayload(buildPayload(parseReview(text), diff, root, rangeLabel))

    path = reportPath(root, base, head)
    page = renderPage(payloadJson, title=f"tony — {os.path.basename(root)}")
    writeReport(path, page)
    if not args.replay:
        saveRaw(rawPath, text, diff)

    if args.payload or args.viewer:
        targets = []
        if args.payload is True:
            targets.append(reportPath(root, base, head, ext="payload.json"))
        elif args.payload:
            targets.append(os.path.abspath(args.payload))
        if args.viewer:
            targets.append(viewerFixture())

        for target in targets:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(payloadJson)
            print(f"tony: {target}")

        if args.viewer:
            print("tony: loaded into the viewer — npm run dev in web/, then refresh.")

    # The local page is written either way: it costs nothing, works offline, and
    # is the fallback when publishing fails so a paid-for review is never lost.
    target = f"file://{path}"

    if publishing:
        url, problem = hosted.publish(
            payloadJson, repo=os.path.basename(root), rangeLabel=rangeLabel,
        )
        if problem:
            print(f"tony: could not publish — {problem}", file=sys.stderr)
            print(f"tony: the review is still here: {path}", file=sys.stderr)
        else:
            print(url)
            target = url
    else:
        print(f"tony: {path}")
    if args.openPage:
        webbrowser.open(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
