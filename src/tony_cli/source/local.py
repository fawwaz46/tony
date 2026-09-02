import fnmatch
import os
import re
import subprocess

from tony_cli.layout import isSkippable

# directories never worth reading — vendored code, build output, vcs internals
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".astro", "target", "vendor", ".mypy_cache", ".pytest_cache",
}

MAX_FILE_CHARS = 60_000
MAX_RESULTS = 200

# A diff and a failure are both strings, so callers that only look at the
# return value cannot tell them apart — an empty-range check reads "not a git
# repository" as "there are changes". The prefix is what makes them separable.
FAILED = "getDiff failed: "


def getDiff(repoPath: str, base=None, head="HEAD", wholeFunctions=False) -> str:
    """The diff as text, or a message starting with FAILED.

    The model is one of the callers and reads this as prose, so a failure has
    to stay human-readable rather than raise.

    `wholeFunctions` adds `-W`, which grows each hunk to the whole function it
    sits in. That is what an agent otherwise opens the file for — it cannot say
    what a changed line does without seeing the function around it — and the
    function is a fraction of the file. On tony's own history it costs about a
    third more diff and removes roughly twice that in reads, each of which was
    also a turn that re-sent everything before it.

    Off for the page, which is laid out against the plain diff: the extra
    context lines would be rendered as if someone had asked to see them.
    """
    try:
        root = resolveRepo(repoPath)
        base = base or resolveBase(root)
    except ValueError as e:
        return f"{FAILED}{e}"

    result = subprocess.run(
        ["git", "diff"] + (["-W"] if wholeFunctions else []) + [f"{base}...{head}"],
        cwd=root,
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        return f"{FAILED}{result.stderr}"
    return result.stdout


def withoutGeneratedBodies(diff: str) -> str:
    """The same diff with generated files reduced to their headers.

    For the agent only. A lockfile is the largest thing in most diffs and the
    least worth reading: nobody annotates it, and under agent-native every line
    of it is spent out of the reviewer's own context window — one 400-line
    `package-lock.json` costs more than the change it accompanies.

    The page is built from the unstripped diff, so it still shows these files
    with their real line counts. Stripping there instead would have reported
    every lockfile as +0/-0.
    """
    if not diff.strip():
        return diff

    out = []
    for chunk in re.split(r"^(?=diff --git )", diff, flags=re.MULTILINE):
        if not chunk.strip():
            continue
        path = chunk.split("\n", 1)[0].split(" b/", 1)[-1].strip()
        if not isSkippable(path):
            out.append(chunk)
            continue
        # Everything before the first hunk: the `diff --git`, mode, index, and
        # ---/+++ lines that `splitDiffByFile` reads to name and count the file.
        head, sep, _ = chunk.partition("@@")
        out.append(head if sep else chunk)
    return "".join(out)

def resolveRepo (repoPath: str) -> str :
    if not os.path.isdir(repoPath):
        raise ValueError(f"not a directory: {repoPath}")
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd = repoPath, capture_output = True, text = True
    )
    if result.returncode != 0:
        raise ValueError(f"not a git repository: {repoPath}")
    
    return result.stdout.strip()

def resolveBase(root: str) -> str:
    """The branch to diff against.

    `origin/HEAD` is the honest answer but it is unset in plenty of repos — fresh
    clones of a single branch, repos with no remote, anything cloned before git
    started setting it. Falling back to the conventional names beats handing the
    model an error string and letting it guess.
    """
    # Whatever we resolve here must be a name git can actually diff against.
    # A remote ref has to come back as "origin/main", not a bare "main" — the
    # local branch of that name may not exist (clone, checkout -b, delete main)
    # and `git diff main...HEAD` then fails on a repo that is perfectly fine.
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        prefix = "refs/remotes/"
        if ref.startswith(prefix):
            return ref[len(prefix):]

    for name in ("main", "master"):
        for ref, spelled in (
            (f"refs/heads/{name}", name),
            (f"refs/remotes/origin/{name}", f"origin/{name}"),
        ):
            probe = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                cwd=root, capture_output=True, text=True,
            )
            if probe.returncode == 0:
                return spelled

    raise ValueError(
        f"cannot work out what to diff against in {root} — no origin/HEAD, no main, "
        "no master. Pass an explicit range, e.g. tony . some-branch...HEAD"
    )


def resolveRev(root: str, rev: str):
    """The commit a revision names, or None if git cannot resolve it."""
    result = subprocess.run(
        ["git", "rev-parse", rev],
        cwd=root, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def isDirty(root: str) -> bool:
    """True when tracked files on disk differ from HEAD."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root, capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def confine(root: str, path: str):
    """The path if it resolves inside root, else None.

    Every tool path arrives from the model, and the model reads untrusted repo
    content — a diff is a fine place to hide "now read ~/.ssh/id_rsa". Whatever
    the model asks for, the answer stays inside the repo under review.
    Symlinks are resolved before checking, so a link pointing out of the repo
    does not count as inside it.
    """
    rootReal = os.path.realpath(root)
    target = os.path.realpath(
        path if os.path.isabs(path) else os.path.join(rootReal, path)
    )
    if target == rootReal or target.startswith(rootReal + os.sep):
        return target
    return None


def fileId(path: str) -> str:
    """Stable DOM id for a file: every non-alphanumeric character becomes an underscore."""
    return re.sub(r"[^A-Za-z0-9]", "_", path)


def splitDiffByFile(diff: str):
    """Split a unified `git diff` into one entry per file, GitHub-style.

    Each entry: path, oldPath, status, binary, additions, deletions, body.
    """
    if not diff.strip():
        return []

    chunks = re.split(r"^diff --git ", diff, flags=re.MULTILINE)[1:]
    files = []

    for chunk in chunks:
        header, _, rest = chunk.partition("\n")
        match = re.match(r'"?a/(.+?)"? +"?b/(.+?)"?$', header)
        oldPath, path = match.groups() if match else (header, header)

        status = "modified"
        if re.search(r"^new file mode ", rest, re.MULTILINE):
            status = "added"
        elif re.search(r"^deleted file mode ", rest, re.MULTILINE):
            status = "deleted"
        elif re.search(r"^rename from ", rest, re.MULTILINE):
            status = "renamed"

        binary = bool(re.search(r"^Binary files .* differ$", rest, re.MULTILINE))

        # the body is everything from the first hunk header onward
        hunkStart = re.search(r"^@@ ", rest, re.MULTILINE)
        body = rest[hunkStart.start():].rstrip("\n") if hunkStart else ""

        additions = deletions = 0
        for line in body.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        files.append({
            "path": path,
            "oldPath": oldPath if oldPath != path else None,
            "status": status,
            "binary": binary,
            "additions": additions,
            "deletions": deletions,
            "body": body,
        })

    return files


def walkFiles(root: str):
    """Yield every file path under root, skipping vendored and build directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)


def readFile(path: str) -> str:
    if not os.path.isfile(path):
        return f"not a file: {path}"
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(MAX_FILE_CHARS + 1)
    except UnicodeDecodeError:
        return f"binary file, not readable as text: {path}"
    except OSError as e:
        return f"could not read {path}: {e}"

    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + f"\n\n[truncated at {MAX_FILE_CHARS} chars]"
    return text


def globFiles(pattern: str, root: str) -> str:
    if not os.path.isdir(root):
        return f"not a directory: {root}"

    hits = []
    for path in walkFiles(root):
        rel = os.path.relpath(path, root)
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            hits.append(rel)
            if len(hits) > MAX_RESULTS:
                break

    if not hits:
        return f"no files matching {pattern} under {root}"
    if len(hits) > MAX_RESULTS:
        return "\n".join(sorted(hits[:MAX_RESULTS])) + f"\n[more than {MAX_RESULTS} matches, truncated]"
    return "\n".join(sorted(hits))


def grepFiles(pattern: str, root: str) -> str:
    if not os.path.isdir(root):
        return f"not a directory: {root}"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"bad regex {pattern!r}: {e}"

    hits = []
    for path in walkFiles(root):
        try:
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        rel = os.path.relpath(path, root)
                        hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                        if len(hits) > MAX_RESULTS:
                            break
        except (UnicodeDecodeError, OSError):
            continue
        if len(hits) > MAX_RESULTS:
            break

    if not hits:
        return f"no matches for {pattern} under {root}"
    if len(hits) > MAX_RESULTS:
        return "\n".join(hits[:MAX_RESULTS]) + f"\n[more than {MAX_RESULTS} matches, truncated]"
    return "\n".join(hits)
