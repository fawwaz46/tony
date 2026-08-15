import fnmatch
import os
import re
import subprocess

# directories never worth reading — vendored code, build output, vcs internals
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".astro", "target", "vendor", ".mypy_cache", ".pytest_cache",
}

MAX_FILE_CHARS = 60_000
MAX_RESULTS = 200

def getDiff (repoPath: str, base=None, head="HEAD") -> str:
    try:
        root = resolveRepo(repoPath)
        base = base or resolveBase(root)
    except ValueError as e:
        return str(e)
    
    result = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        cwd = root,
        capture_output=True, text=True,
        )
    
    if result.returncode != 0:
        return f"getDiff failed: {result.stderr}"
    return result.stdout

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
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("/")[-1]

    for name in ("main", "master"):
        for ref in (f"refs/remotes/origin/{name}", f"refs/heads/{name}"):
            probe = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                cwd=root, capture_output=True, text=True,
            )
            if probe.returncode == 0:
                return name

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
