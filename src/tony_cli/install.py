"""How this copy of tony was installed, and how to change it.

`tony update` and `tony uninstall` both have to answer the same question
first: which tool put this here? Guessing from PATH picks whichever installer
the user happens to also have, so both read the receipt the installer left at
the root of the environment tony is actually running from.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

import httpx

PKG = "tony-cli"

# The same pinning install.sh does, for the same reason: both installers honour
# an ambient index setting, so on a machine pointed at an internal mirror an
# update would pull whatever that mirror serves under the name `tony-cli`.
INDEX = "https://pypi.org/simple"

# The project's page on that same index, asked for as JSON (PEP 691). Not
# pypi.org/pypi/<name>/json — that one is CDN-cached and runs minutes behind a
# release, so it will call a version "latest" that an installer has already
# moved past, and report "already on the latest version" to someone who is not.
PROJECT = f"{INDEX}/{PKG}/"
SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"


def indexEnv():
    """The environment an upgrade runs in: our index, and nobody's cache.

    Both settings are environment variables rather than command-line flags on
    purpose. `uv tool upgrade` has no `--refresh` — passing one is a usage
    error that fails the upgrade outright — and which cache flags each
    installer accepts moves between versions. These names are stable.
    """
    env = dict(os.environ)
    env["UV_INDEX_URL"] = INDEX
    env["UV_DEFAULT_INDEX"] = INDEX
    env["PIP_INDEX_URL"] = INDEX
    # A cache minutes stale resolves to the release before the one just made,
    # then reports "already at latest" and exits 0.
    env["UV_NO_CACHE"] = "1"
    env["PIP_NO_CACHE_DIR"] = "1"
    return env


def isSourceCheckout():
    """True when running from `pip install -e .` in tony's own repo.

    Neither updating nor uninstalling may touch a working tree: one would
    overwrite uncommitted work, the other would delete it.
    """
    pkg = os.path.dirname(os.path.abspath(__file__))
    return os.path.exists(os.path.join(pkg, "..", "..", "pyproject.toml"))


def installer():
    """'uv', 'pipx', or 'pip' — whichever environment tony is running from."""
    if os.path.exists(os.path.join(sys.prefix, "uv-receipt.toml")):
        return "uv"
    if os.path.exists(os.path.join(sys.prefix, "pipx_metadata.json")):
        return "pipx"
    return "pip"


def uninstallCommand(kind):
    if kind == "uv":
        return ["uv", "tool", "uninstall", PKG]
    if kind == "pipx":
        return ["pipx", "uninstall", PKG]
    return [sys.executable, "-m", "pip", "uninstall", "-y", PKG]


def updateCommand(kind):
    """The upgrade, told to ignore its own cache.

    Every one of these caches the index, and a cache that is minutes stale
    resolves to the version before the one just released — then reports
    "already at latest" and exits 0. An update that runs once a month should
    pay for a fresh lookup rather than confidently do nothing.
    """
    if kind == "uv":
        return ["uv", "tool", "upgrade", PKG]
    if kind == "pipx":
        return ["pipx", "upgrade", PKG]
    return [sys.executable, "-m", "pip", "install", "--upgrade", PKG]


def installedVersion():
    """The running version, or None if the metadata is not there to read."""
    try:
        from importlib.metadata import version
        return version(PKG)
    except Exception:
        return None


def installedOnDisk():
    """The version the environment's metadata records, re-read from disk.

    `installedVersion` answers from what this interpreter imported at startup,
    which is precisely the version an upgrade just replaced. The dist-info
    directory on disk is the only thing in this process that knows what is
    actually installed now.
    """
    import glob
    import sysconfig

    purelib = sysconfig.get_paths().get("purelib")
    if not purelib:
        return None
    found = glob.glob(os.path.join(purelib, "tony_cli-*.dist-info"))
    if not found:
        return None
    name = os.path.basename(sorted(found)[-1])
    return name[len("tony_cli-"):-len(".dist-info")] or None


def _release(version):
    """A sortable key for a plain release, or None for anything else.

    Pre-releases and dev builds sort unpredictably as digit tuples — "1.0.0rc1"
    would read as (1, 0, 0, 1) and outrank 1.0.0 — and `tony update` should not
    move anyone onto one.
    """
    if not re.fullmatch(r"\d+(?:\.\d+)*", version or ""):
        return None
    return tuple(int(n) for n in version.split("."))


def latestVersion(timeout=10):
    """The newest release the index offers, or None if it cannot be asked.

    Worth one request: without it there is nothing to check the upgrade
    against, and every installer exits 0 for "already at latest" — which is
    indistinguishable from "upgraded" unless you knew the target beforehand.
    """
    try:
        response = httpx.get(
            PROJECT, timeout=timeout, headers={"Accept": SIMPLE_JSON},
            follow_redirects=True,
        )
        if response.status_code != 200:
            return None
        versions = (response.json() or {}).get("versions") or []
    except Exception:
        return None

    ranked = [(key, v) for v in versions if (key := _release(v))]
    return max(ranked)[1] if ranked else None


# --- "there is a newer tony" -----------------------------------------------
#
# Nobody runs `tony update` on a hunch. The only moment anyone finds out a
# release exists is a moment tony creates, so every run asks — but off the
# critical path: the question goes to a background thread while the command
# does its work, and whatever has come back by the time the command finishes
# gets printed. A slow or dead index costs the run nothing.

CHECK_CACHE = os.path.join(os.path.expanduser("~"), ".tony", "update.json")

# The background request's own timeout. Generous, because nothing waits on it:
# an answer that lands after the command has printed is still saved, and the
# next run says it.
CHECK_TIMEOUT = 5

# How long the command waits at exit for an answer that has not arrived. Short
# enough not to be felt, and missing it is not a loss — the cache below carries
# the previous run's answer.
NOTICE_WAIT = 0.4

# How long a cached answer stays worth repeating. A version that was newest a
# week ago may not be, but saying "0.5.0 is out" about a real release is never
# wrong in a way that matters — and it is what makes the notice show up on the
# run after the one that did the asking.
CACHE_TTL = 7 * 24 * 3600


def savedCheck():
    """The last answer PyPI gave, or None if there isn't a fresh one."""
    try:
        with open(CHECK_CACHE, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict):
        return None
    try:
        checkedAt = float(saved.get("checkedAt") or 0)
    except (TypeError, ValueError):
        return None
    if time.time() - checkedAt > CACHE_TTL:
        return None
    return saved.get("latest") or None


def saveCheck(latest):
    try:
        os.makedirs(os.path.dirname(CHECK_CACHE), mode=0o700, exist_ok=True)
        with open(CHECK_CACHE, "w", encoding="utf-8") as fh:
            json.dump({"latest": latest, "checkedAt": time.time()}, fh)
    except OSError:
        pass  # A cache that cannot be written costs one HTTP request a run.


def startUpdateCheck():
    """Ask the index what the newest release is, without waiting for it.

    Returns a handle for `updateNotice`, or None when there is nothing to ask
    about — a source checkout updates with `git pull`, not from PyPI.
    """
    if isSourceCheckout():
        return None

    answer = {}

    def ask():
        latest = latestVersion(timeout=CHECK_TIMEOUT)
        if latest:
            answer["latest"] = latest
            saveCheck(latest)

    # Daemon: an index that never answers must not hold the process open after
    # the command it was launched alongside has finished.
    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    return thread, answer


def newerVersion(latest, current=None):
    """`latest` if it is a real release ahead of what is installed, else None."""
    here = _release(current if current is not None else (installedVersion() or ""))
    there = _release(latest or "")
    return latest if here and there and there > here else None


def pendingUpdate(handle=None, wait=NOTICE_WAIT):
    """The release this machine could move to, or None. Never raises.

    Waits `wait` seconds on the check `startUpdateCheck` began — no longer,
    because a person is holding a prompt open on the other end of it.
    """
    latest = None
    if handle:
        thread, answer = handle
        try:
            thread.join(wait)
        except RuntimeError:
            pass
        latest = answer.get("latest")
    # Either the request has not landed yet or there was no request: the last
    # run's answer is the next best thing, and it is why this says anything at
    # all on a machine where every run is shorter than one HTTP round trip.
    return newerVersion(latest or savedCheck())


def updateNotice(handle=None, wait=NOTICE_WAIT):
    """One line about a newer release, or ""."""
    newer = pendingUpdate(handle, wait)
    if not newer:
        return ""
    return (f"\ntony: {newer} is out — you have {installedVersion() or 'an older build'}. "
            "Update with `tony update`.")


def update(argv=()):
    """`tony update`. Returns an exit code, prints its own messages."""
    if argv:
        print("usage: tony update", file=sys.stderr)
        return 2

    if isSourceCheckout():
        print(f"tony: this is a source checkout at {sys.prefix} — update it with "
              "`git pull`, not from PyPI.", file=sys.stderr)
        return 2

    kind = installer()
    command = updateCommand(kind)
    before = installedVersion()
    latest = latestVersion()

    # Nothing to do is worth saying out loud. Running the installer anyway
    # prints a wall of its output and exits 0, which reads exactly like a
    # successful upgrade.
    #
    # Ordered, not equal: the index lags a release by minutes, so a machine that
    # just installed the newest version can be ahead of what the index admits
    # exists. Equality treated that as "an upgrade is available", ran one, and
    # reported the no-op as a failure.
    here, there = _release(before or ""), _release(latest or "")
    if here and there and here >= there:
        print(f"tony: already on the latest version ({before}).")
        return 0

    target = f" to {latest}" if latest else ""
    print(f"tony: {before or 'unknown version'}, updating{target} with {kind}...")
    # The installer writes to this same terminal; without a flush its output
    # arrives before the line announcing it.
    sys.stdout.flush()

    try:
        result = subprocess.run(command, env=indexEnv())
    except OSError as e:
        print(f"tony: could not run {command[0]}: {e}", file=sys.stderr)
        print(f"tony: update by hand with: {' '.join(command)}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"tony: {kind} could not update tony.", file=sys.stderr)
        return result.returncode

    # What PyPI calls newest is not what just landed on this machine. An
    # installer resolving against a stale index cache prints "already at latest"
    # for a version that is not the latest, and exits 0 — reporting the upgrade
    # from PyPI's answer turns that into a confident lie.
    after = installedOnDisk()

    if after and before and after == before:
        print(
            f"\ntony: still {after} — {kind} did not install a newer version, "
            f"though PyPI offers {latest or 'a newer one'}.\n"
            f"      Try again in a minute; a release takes a moment to reach "
            f"every mirror.\n",
            file=sys.stderr,
        )
        return 1

    if after and before:
        print(f"\ntony: updated {before} -> {after}.")
    elif after:
        print(f"\ntony: now on {after}.")
    else:
        print("\ntony: the installer finished. Check it with `tony --version`.")
    return 0
