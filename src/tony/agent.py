import argparse
import json
import os
import subprocess
import sys
import tempfile
import webbrowser

import anthropic
from dotenv import load_dotenv
from tony.payload import buildPayload, dumpPayload
from tony.render import renderPage
from tony.source.local import (
    getDiff, globFiles, grepFiles, isDirty, readFile, resolveBase, resolveRepo,
    resolveRev,
)

# tony runs from inside whatever repo it is reviewing, so the key has to be found
# from the module's own location, not the cwd.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

SYSTEM = """You explain code changes to the developer who is about to own them — often someone who did not type this code, because an AI wrote it. Your job is to build their mental map of what now exists, fast.

Be ruthlessly concise. A developer scanning your output should understand the change in under a minute. Never write an essay. Never restate what the code plainly says. Never pad.

You have file and search tools. Use them before you write anything — read the changed files in full, and grep for consumers of anything whose shape changed. Never describe code you did not read.

Your entire output is ONE fenced ```json block. No prose outside the fence — nothing before it, nothing after it.

THE JSON BLOCK

{
  "intent": "One sentence. What this change accomplishes, in plain language.",
  "annotations": [
    {"path": "src/layouts/Layout.astro", "line": 22, "title": "Per-page canonical URL",
     "kind": "changed",
     "prev": "Every page reported the site root as its own address, so a shared /mac link claimed to be the homepage.",
     "now": "Builds the address from the current page's path, so each page advertises where it actually lives.",
     "impact": "Link previews now resolve per page. Platforms key share counts on this value, so counts tied to the old address detach."},
    {"path": "src/pages/mac.astro", "line": 10, "title": "Mac-specific preview card",
     "kind": "added",
     "now": "First consumer of the new props: the Mac page serves /mac-og.png with its own headline instead of the generic card."}
  ],
  "risks": [
    {"path": "src/layouts/Layout.astro", "line": 31,
     "text": "The new 1800x945 dimensions apply to all five pages, but four still serve a 1200x630 image."}
  ]
}

ANNOTATIONS — these are the entire walkthrough. Everything the reader learns, they learn here.

COVERAGE — this is the rule that matters most. Every hunk in the diff must be explained. Walk the diff hunk by hunk and account for all of it. If one hunk contains several distinct changes, write several annotations against it. Leaving a hunk unannotated is a failure, not concision. The only things you may skip are lockfiles, generated code, and binary assets.

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
- `now`: what the code does after this change, and how. One or two sentences. Required for "added" and "changed". Omit for "removed".
- `prev`: how it worked before — the actual old mechanism, not "it did not exist". One or two sentences. Required for "changed" and "removed". NEVER include it for "added", and never invent it: if you did not read the old version, go read it before writing the annotation.
- `impact`: what the difference means in practice — what now behaves differently for a user, a caller, or a build. One or two sentences. Required for "changed" and "removed". Omit for "added".

The reader reads `prev`, `now`, and `impact` as three separate panes, so each must stand alone. Do not write `now` as a continuation of `prev`, and do not repeat the same sentence across two fields.

Order annotations by file, then by line.

IMPACTS — files this change reaches that are NOT in the diff.

A diff shows what was edited. It cannot show what breaks. After you have written the annotations, grep for every consumer of anything whose shape changed — a signature, a prop, an export, a schema, a config key, a route, an environment variable — and record each place that now behaves differently.

{"impacts": [
  {"symbol": "Props", "fromPath": "src/layouts/Layout.astro",
   "path": "src/pages/index.astro", "line": 3, "kind": "behavior-change",
   "why": "Renders inside Layout, so it now emits the new 1800x945 image dimensions for an image that has not changed."}
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
    "title": "Turning the sound on",
    "trigger": "You click the speaker button in the corner of the video",
    "whatChanged": "Before this diff there was no way to turn the sound on at all — the video was permanently silent.",
    "steps": [
      {"say": "The button's click handler runs. It is the only thing on the page that can change the sound.",
       "path": "src/components/MacAppSection.tsx", "lines": [14, 16],
       "state": {"isMuted": "true", "video.muted": "true"},
       "phase": "new"},
      {"say": "It flips the remembered setting, then reaches into the actual video element and unmutes it directly.",
       "path": "src/components/MacAppSection.tsx", "lines": [17, 19],
       "state": {"isMuted": "true -> false", "video.muted": "true -> false"},
       "phase": "new"}
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
                "description": "Glob pattern, e.g. '*.astro' or 'src/**/*.ts'.",
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

def runTool(name, toolInput):
    func = TOOLS.get(name)
    if func is None:
        return f"unknown tool: {name}"
    try:
        return func(**toolInput)
    except Exception as e:
        return f"tool error:{e}"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16384


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

    while True:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=maxTokens,
                system=SYSTEM,
                messages=messages,
                tools=ALL_TOOLS,
            )
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

        if response.stop_reason != "tool_use":
            text = "\n".join(b.text for b in response.content if b.type == "text")
            return 0, text, diff

        results = []
        for block in response.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"[{block.name}] {block.input}", file=sys.stderr)
                result = runTool(block.name, block.input)
                if block.name == "getDiff" and result.lstrip().startswith("diff --git "):
                    diff = result
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": results})


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
            f"reviewed.\n       Run `git checkout {head}` first, or pass --stale to "
            "review it anyway."
        )
    if isDirty(root):
        return (
            "the working tree has uncommitted changes, so some lines shown may not "
            "match the diff.\n       Commit or stash them, or pass --stale to continue."
        )
    return None


def viewerFixture():
    """`web/src/fixtures/review.json` in tony's own checkout, if there is one.

    Only exists when tony is installed from source (`pip install -e .`), which is
    the case while the viewer is being built. Returns None for a plain install.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(
        os.path.join(here, "..", "..", "web", "src", "fixtures", "review.json")
    )
    return path if os.path.isdir(os.path.dirname(path)) else None


def publish(page, name="tony"):
    """Deploy one self-contained page to Vercel and return its URL.

    The page carries its own CSS, fonts and data, so hosting is one static file
    and there is nothing to store server-side. Each review is its own immutable
    deployment: Vercel keeps them, so no database ever has to.

    Deployments inherit the account's protection setting. Under Vercel
    Authentication the link opens for the account owner and nobody else, which
    is a dashboard toggle, not a code change.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Vercel names the project after the directory, so all reviews land in one.
        site = os.path.join(tmp, name)
        os.makedirs(site)
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page)

        try:
            result = subprocess.run(
                ["vercel", "deploy", "--yes"],
                cwd=site, capture_output=True, text=True, timeout=300,
            )
        except FileNotFoundError:
            return None, "the vercel CLI is not installed — npm i -g vercel"
        except subprocess.TimeoutExpired:
            return None, "vercel deploy timed out after 5 minutes"

        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()
            return None, tail[-1] if tail else "vercel deploy failed"

        # Recent CLI versions report a JSON object on stdout; older ones print
        # the bare URL. Take the structured answer when it is there.
        url = None
        try:
            url = json.loads(result.stdout).get("deployment", {}).get("url")
        except (json.JSONDecodeError, AttributeError):
            url = next(
                (ln.strip() for ln in reversed(result.stdout.splitlines())
                 if ln.strip().startswith("https://")),
                None,
            )
        return (url, None) if url else (None, "vercel deploy printed no URL")


def reportPath(repoPath, base, head, ext="html"):
    """Where this review lands: `.tony/<base>...<head>.html` inside the repo."""
    stamp = f"{base or 'default'}...{head}".replace("/", "-").replace(" ", "-")
    return os.path.join(repoPath, ".tony", f"{stamp}.{ext}")


def saveRaw(path, text, diff):
    """Keep the model's answer and the diff it read, so the page can be rebuilt for free."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"review": text, "diff": diff}, fh)


def loadRaw(path):
    with open(path, encoding="utf-8") as fh:
        saved = json.load(fh)
    return saved["review"], saved["diff"]


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
    parser = argparse.ArgumentParser(
        prog="tony",
        description="Review a git diff for impact, not line-by-line.",
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
    parser.add_argument(
        "--publish", action="store_true",
        help="Deploy the page to Vercel and print its URL.",
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
    args = parser.parse_args(argv)

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

    if args.replay:
        if not os.path.exists(rawPath):
            print(f"tony: nothing saved for this range at {rawPath}", file=sys.stderr)
            return 2
        text, diff = loadRaw(rawPath)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("tony: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
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

    path = reportPath(root, base, head)
    page = renderPage(
        text, diff, root,
        title=f"tony — {os.path.basename(root)}",
        rangeLabel=f"{base or 'default'}...{head}",
    )
    writeReport(path, page)
    if not args.replay:
        saveRaw(rawPath, text, diff)

    if args.payload or args.viewer:
        blob = dumpPayload(buildPayload(text, diff, root, f"{base}...{head}"))

        targets = []
        if args.payload is True:
            targets.append(reportPath(root, base, head, ext="payload.json"))
        elif args.payload:
            targets.append(os.path.abspath(args.payload))
        if args.viewer:
            fixture = viewerFixture()
            if fixture:
                targets.append(fixture)
            else:
                print("tony: no viewer found — --viewer needs tony installed from source.",
                      file=sys.stderr)

        for target in targets:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(blob)
            print(f"tony: {target}")

        if args.viewer and viewerFixture():
            print("tony: loaded into the viewer — npm run dev in web/, then refresh.")

    if args.publish:
        url, problem = publish(page)
        if problem:
            print(f"tony: could not publish — {problem}", file=sys.stderr)
        else:
            print(f"tony: {url}")

    print(f"tony: {path}")
    if args.openPage:
        webbrowser.open(f"file://{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
