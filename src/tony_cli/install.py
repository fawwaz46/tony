"""How this copy of tony was installed, and how to change it.

`tony --update` and `tony uninstall` both have to answer the same question
first: which tool put this here? Guessing from PATH picks whichever installer
the user happens to also have, so both read the receipt the installer left at
the root of the environment tony is actually running from.
"""

import os
import subprocess
import sys

import httpx

PKG = "tony-cli"

# The same pinning install.sh does, for the same reason: both installers honour
# an ambient index setting, so on a machine pointed at an internal mirror an
# update would pull whatever that mirror serves under the name `tony-cli`.
INDEX = "https://pypi.org/simple"
RELEASES = "https://pypi.org/pypi/tony-cli/json"


def indexEnv():
    env = dict(os.environ)
    env["UV_INDEX_URL"] = INDEX
    env["UV_DEFAULT_INDEX"] = INDEX
    env["PIP_INDEX_URL"] = INDEX
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
        return ["uv", "tool", "upgrade", "--refresh", PKG]
    if kind == "pipx":
        return ["pipx", "upgrade", PKG, "--pip-args=--no-cache-dir"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", PKG]


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


def latestVersion(timeout=10):
    """The newest version PyPI serves, or None if it cannot be asked.

    Worth one request: without it there is nothing to check the upgrade
    against, and every installer exits 0 for "already at latest" — which is
    indistinguishable from "upgraded" unless you knew the target beforehand.
    """
    try:
        response = httpx.get(RELEASES, timeout=timeout)
        if response.status_code != 200:
            return None
        return ((response.json() or {}).get("info") or {}).get("version")
    except Exception:
        return None


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
    if latest and before and latest == before:
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
