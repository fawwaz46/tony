"""`tony uninstall` — remove tony and everything it has left on the machine.

Removing the package alone leaves behind the things that actually matter: an
ANTHROPIC_API_KEY in ~/.tony/.env, a token in ~/.tony/credentials.json that is
still valid server-side, and a .tony/ directory inside every repository tony
was ever run in. Those directories hold reviews, and reviews hold source — so
the scattered ones are the part worth being thorough about, and the part a
`pipx uninstall` was never going to find.

Order matters. The site token is revoked before the file holding it is deleted,
or it stays valid forever on a machine that can no longer present it to log
out. The package is removed last, because that pulls this module's own code out
from under the running interpreter.
"""

import os
import shutil
import sys

from tony_cli import hosted
from tony_cli.install import installer, isSourceCheckout, uninstallCommand

HOME = os.path.expanduser("~")

# Directories a home-directory scan must not descend into. Dependency and cache
# trees are enormous and cannot contain a repo someone reviewed, and skipping
# them is the difference between a scan that takes a second and one that looks
# like a hang.
SKIP = {
    ".git", "node_modules", "Library", "Applications", ".cache", ".npm",
    ".venv", "venv", "site-packages", ".Trash", "__pycache__",
}

# Deep enough to reach the checkouts people actually keep (~/src/work/repo/...),
# shallow enough that the walk stays bounded on a large home directory.
MAX_DEPTH = 6


def configDir():
    """`~/.tony` — the API key and the site token, not tied to any repo."""
    return hosted.CONFIG_DIR


def reportDirs(scan=True):
    """Every `.tony/` review directory this can find, nearest first.

    The current repo is always checked, because that is where someone standing
    when they type this most likely has one. The home scan finds the rest —
    tony keeps no registry of the repos it has reviewed, and inventing one that
    writes on every run to serve an uninstall nobody may ever type is a worse
    trade than a bounded walk at the moment of deletion.
    """
    # The config dir is deleted deliberately elsewhere. Standing in the home
    # directory, it is also what `./.tony` resolves to — listing it in both
    # places means deleting it twice and reporting a failure for the second.
    config = os.path.realpath(configDir())
    found = []

    def offer(path):
        path = os.path.realpath(path)
        if path != config and path not in found:
            found.append(path)

    here = os.path.join(os.getcwd(), ".tony")
    if os.path.isdir(here):
        offer(here)
    if not scan:
        return found

    for root, dirs, _ in os.walk(HOME, topdown=True):
        depth = root[len(HOME):].count(os.sep)
        if depth >= MAX_DEPTH:
            dirs[:] = []
            continue
        # Symlinked trees can leave the home directory entirely, and following
        # one would put paths outside it on a deletion list.
        dirs[:] = [d for d in dirs if d not in SKIP and not os.path.islink(os.path.join(root, d))]
        if ".tony" in dirs:
            dirs.remove(".tony")  # nothing to find underneath it
            offer(os.path.join(root, ".tony"))
    return found


def humanSize(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.0f}{unit}"
        total /= 1024
    return f"{total:.0f}TB"


def remove(path):
    try:
        shutil.rmtree(path)
        return True
    except OSError as e:
        print(f"tony: could not remove {path}: {e}", file=sys.stderr)
        return False


def uninstall(argv):
    """Returns an exit code. Prints its own messages — this is a command."""
    assumeYes = "--yes" in argv or "-y" in argv
    scan = "--no-scan" not in argv

    unknown = [a for a in argv if a not in ("--yes", "-y", "--no-scan")]
    if unknown:
        print("usage: tony uninstall [--yes] [--no-scan]", file=sys.stderr)
        return 2

    config = configDir()
    hasConfig = os.path.isdir(config)
    if scan:
        print("tony: looking for reviews left in repositories...", file=sys.stderr)
    reports = reportDirs(scan)

    kind = installer()
    command = uninstallCommand(kind)
    source = isSourceCheckout()

    print("\nThis will delete:\n")
    if hasConfig:
        print(f"  {config}")
        print("      your ANTHROPIC_API_KEY and your login for the tony site")
    for path in reports:
        print(f"  {path}  ({humanSize(path)})")
    if not hasConfig and not reports:
        print("  (nothing — tony has written nothing to this machine)")
    print()
    if source:
        print(f"Then: nothing. This is a source checkout at {sys.prefix};")
        print("      removing the package would delete your working tree, so it stays.")
    elif os.name == "nt":
        print(f"Then: {' '.join(command)}")
        print("      Windows cannot delete a running program, so run that yourself after.")
    else:
        print(f"Then: {' '.join(command)}")
    print()

    if not assumeYes:
        if not sys.stdin.isatty():
            print("tony: refusing to delete without a terminal to confirm at. "
                  "Pass --yes if you mean it.", file=sys.stderr)
            return 2
        try:
            answer = input("Type 'yes' to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\ntony: cancelled.", file=sys.stderr)
            return 1
        if answer != "yes":
            print("tony: cancelled. Nothing was deleted.")
            return 1

    # Revoke before deleting the file that holds the token, so a copy taken off
    # this machine earlier cannot outlive the uninstall.
    if hosted.savedToken():
        hosted.logout()

    ok = True
    if hasConfig:
        ok = remove(config) and ok
    for path in reports:
        ok = remove(path) and ok

    if not ok:
        # Removing the package now would strip the only thing that knows where
        # the leftovers are. Leave tony installed so this can be retried.
        print("tony: some files could not be removed, so tony has been left "
              "installed — fix the errors above and run this again.",
              file=sys.stderr)
        return 1

    if source:
        print("tony: local data removed. The checkout itself is yours to delete.")
        return 0

    if os.name == "nt":
        print("tony: local data removed. Finish with:")
        print(f"    {' '.join(command)}")
        return 0

    print(f"tony: local data removed. Removing the package with {kind}...")
    sys.stdout.flush()
    try:
        # execvp, not a subprocess: the uninstaller deletes the files this
        # interpreter is running from, so there must be nothing left for it to
        # import afterwards. Replacing the process means the uninstaller's own
        # exit status becomes tony's.
        os.execvp(command[0], command)
    except OSError as e:
        print(f"tony: could not run {command[0]}: {e}", file=sys.stderr)
        print(f"tony: finish with: {' '.join(command)}", file=sys.stderr)
        return 1
