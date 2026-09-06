import os
import re
import subprocess

from tony_cli.layout import isSkippable

# A diff and a failure are both strings, so callers that only look at the
# return value cannot tell them apart — an empty-range check reads "not a git
# repository" as "there are changes". The prefix is what makes them separable.
FAILED = "getDiff failed: "


def getDiff(repoPath: str, base=None, head="HEAD", wholeFunctions=False) -> str:
    """The diff as text, or a message starting with FAILED.

    The reviewing agent reads this straight out of a tool result, so a failure
    has to stay human-readable rather than raise.

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
        "no master. Ask for an explicit range instead, like \"main...HEAD\"."
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
