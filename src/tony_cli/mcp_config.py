"""Registering `tony mcp` with the agent harnesses that can run it.

One binary, one server, and a different config file per host — each with its own
path, its own format, and its own name for the same idea. This module knows
those four shapes and nothing else.

Every write merges into whatever is already there. These files hold the user's
other servers and, in Codex's and Amp's case, unrelated settings; a rewrite that
dropped them would be a far worse bug than failing to install.
"""

import json
import os
import shutil
import sys

from tony_cli import hosted

# The command a host will run. `tony` from PATH when tony was installed as a
# tool, and the absolute path to this interpreter's tony otherwise — a host
# started from a GUI does not inherit the shell's PATH, and "tony" alone is the
# most common reason a server shows up dead.
def command():
    onPath = shutil.which("tony")
    if onPath:
        return onPath
    local = os.path.join(os.path.dirname(sys.executable), "tony")
    return local if os.path.exists(local) else "tony"


def home(*parts):
    return os.path.expanduser(os.path.join("~", *parts))


# Where each host keeps its user-level server list, and under which key. Three
# of the four are JSON with the same nesting; Codex is TOML and handled apart.
JSON_HOSTS = {
    "claude": (home(".claude.json"), ["mcpServers"]),
    "cursor": (home(".cursor", "mcp.json"), ["mcpServers"]),
    "amp": (home(".config", "amp", "settings.json"), ["amp.mcpServers"]),
}

CODEX = home(".codex", "config.toml")

HOSTS = list(JSON_HOSTS) + ["codex"]

# What each host calls itself, for output someone has to read.
LABELS = {"claude": "Claude Code", "cursor": "Cursor", "amp": "Amp", "codex": "Codex"}


def readJson(path):
    """The file's contents as a dict, or {} if it is absent or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def writeJson(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


def installJson(path, keys, exe):
    """Add tony to one JSON host's server map. Returns (state, detail).

    `keys` is the path to the map — a single key for every host so far, but
    Amp's is a literal dotted name rather than a nesting, so it is a list to
    keep the two from being confused.
    """
    body = readJson(path)
    parent = body
    for key in keys[:-1]:
        parent = parent.setdefault(key, {})
        if not isinstance(parent, dict):
            return "failed", f"{path} has a {key} that is not an object"

    servers = parent.setdefault(keys[-1], {})
    if not isinstance(servers, dict):
        return "failed", f"{path} has a {keys[-1]} that is not an object"

    entry = {"command": exe, "args": ["mcp"]}
    if servers.get("tony") == entry:
        return "already", f"already connected  ({path})"
    servers["tony"] = entry
    writeJson(path, body)
    return "wrote", f"connected  ({path})"


def installCodex(exe):
    """Add tony to Codex's TOML config, appending rather than reformatting.

    Returns (state, detail), like `installJson`.

    Codex's file is hand-edited TOML with comments in it. Parsing and re-emitting
    would work and would also silently strip every one of those comments, so the
    table is appended as text and an existing one is left alone — the honest
    trade for not owning a TOML writer.
    """
    table = f'[mcp_servers.tony]\ncommand = "{exe}"\nargs = ["mcp"]\n'
    try:
        with open(CODEX, encoding="utf-8") as fh:
            existing = fh.read()
    except OSError:
        existing = ""

    if "[mcp_servers.tony]" in existing:
        return "already", f"already connected  ({CODEX})"

    os.makedirs(os.path.dirname(CODEX), exist_ok=True)
    separator = "" if not existing or existing.endswith("\n\n") else \
        "\n" if existing.endswith("\n") else "\n\n"
    with open(CODEX, "a", encoding="utf-8") as fh:
        fh.write(separator + table)
    return "wrote", f"connected  ({CODEX})"


def install(argv=None):
    """`tony install [host ...]` — register the MCP server, then say what is next.

    This is the whole of setup for most people, so it does not stop at writing
    files. Someone who has just run it does not know that an agent reads its
    tool list only at startup, or that publishing needs an account — and both
    of those turn into "tony does not work" if nobody says them here.
    """
    argv = argv or []
    wanted = [h for h in argv if not h.startswith("-")]
    unknown = [h for h in wanted if h not in HOSTS]
    if unknown:
        print(f"tony: unknown host{'s' if len(unknown) > 1 else ''}: "
              f"{', '.join(unknown)}. Known: {', '.join(HOSTS)}.", file=sys.stderr)
        return 2

    # No host named means all of them. Registering with an agent that is not
    # installed costs one unused entry in a file; making someone name their
    # harness costs them the command working at all.
    targets = wanted or HOSTS
    exe = command()

    print("\n  Connecting tony to your agents\n")
    results = []
    for host in targets:
        try:
            if host == "codex":
                result = installCodex(exe)
            else:
                path, keys = JSON_HOSTS[host]
                result = installJson(path, keys, exe)
        except OSError as e:
            result = ("failed", str(e))
        results.append((host, result))
        state, detail = result
        mark = "x" if state == "failed" else "+"
        print(f"    {mark} {LABELS[host]:<12} {detail}")

    if all(state == "failed" for _, (state, _) in results):
        print("\ntony: nothing could be registered. The paths above are where "
              "each agent expects to find tony.", file=sys.stderr)
        return 1

    nextSteps(hosted.savedToken() is not None)
    return 0


def nextSteps(signedIn):
    """The two things that are not files, and are not optional."""
    print("\n  Next\n")
    print("    1.  Restart your agent.")
    print("        It reads its list of tools once, when it starts — until then")
    print("        it has never heard of tony.\n")

    if signedIn:
        print("    2.  Ask it to review something:\n")
        print("            review this branch with tony\n")
        print("        This machine is already signed in.")
    else:
        print("    2.  Sign in, so reviews have somewhere to go:\n")
        print("            tony login\n")
        print("        It opens a browser and tells you when the terminal is ready.")
        print("        Then ask your agent:\n")
        print("            review this branch with tony")
    print(f"\n  Docs: {hosted.apiBase()}/docs\n")
