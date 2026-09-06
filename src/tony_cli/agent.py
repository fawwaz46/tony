"""The `tony` command.

tony does not review anything itself. The reviewing happens inside whatever
coding agent the developer already pays for, over the MCP server in
`mcp_server.py` — the agent reads the diff, writes the review, and hands it
back to be validated and published. So this module is a dispatcher: accounts,
agent wiring, and the installer. Everything a person types.

The old path — tony owning an Anthropic key and driving its own tool loop —
is gone. See `mcp_server.py` for what replaced it.
"""

import sys

from tony_cli import hosted, install

USAGE = """\
tony — explains a git diff to whoever now owns it.

  tony connect [host ...]        connect tony to your coding agent
  tony login                     sign in, so reviews have somewhere to publish
  tony logout                    sign out on this machine
  tony mcp                       run the MCP server on stdio (agents call this)
  tony update                    update to the latest release
  tony uninstall                 delete tony, its login, and every saved review
  tony --version                 what is installed

To review something, ask your agent: "review this branch with tony".

  https://tony-cli.com
"""


# Commands that must not carry the notice. `update` and `uninstall` are about
# the installed version already and would be talking over themselves; `mcp`
# speaks a protocol on stdio and has no terminal to say anything to — it tells
# the agent instead, in `mcp_server.startReview`.
NO_NOTICE = ("update", "uninstall", "mcp")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else None

    # Started before the command, collected after it: the round trip to PyPI
    # overlaps whatever the command was going to do anyway, so the only run
    # that ever waits on it is one that finishes in under half a second.
    check = None if command in NO_NOTICE else install.startUpdateCheck()
    code = dispatch(argv, command)
    if check:
        notice = install.updateNotice(check)
        if notice:
            # stderr, so it never lands in the middle of output being piped
            # somewhere that expected only the command's own.
            print(notice, file=sys.stderr)
    return code


def dispatch(argv, command):
    """Run one command and return its exit code. Everything a person types."""
    if command in (None, "help", "-h", "--help"):
        # No arguments is not an error: it is someone who just installed tony
        # and wants to know what to type next. That is `tony connect`.
        print(USAGE)
        return 0

    if command in ("--version", "-V", "version"):
        print(f"tony {install.installedVersion() or 'unknown'}")
        return 0

    if command == "login":
        return hosted.login(argv[1:])
    if command == "logout":
        return hosted.logout()

    # Imported here, not at the top: it pulls in the MCP SDK, and `tony` as a
    # CLI should not pay that import on every run to serve one subcommand.
    if command == "mcp":
        from tony_cli.mcp_server import serve
        return serve(argv[1:])
    if command == "connect":
        from tony_cli import mcp_config
        return mcp_config.connect(argv[1:])

    # The obvious wrong guess, and one worth answering.
    if command == "install":
        print("tony: tony is already installed — you want `tony connect`, which\n"
              "      registers it with your coding agent.", file=sys.stderr)
        return 2
    if command == "update":
        return install.update(argv[1:])
    if command == "uninstall":
        from tony_cli.uninstall import uninstall
        return uninstall(argv[1:])

    # A range or a repository path — what tony used to take directly. Someone
    # typing it has an older tony's habits, so say where the reviewing went.
    print(
        f"tony: unknown command {command!r}.\n\n"
        "  tony no longer reviews on its own. Run `tony connect` once, then ask\n"
        "  your coding agent to review the branch and it will call tony for you.\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
