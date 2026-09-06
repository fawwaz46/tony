# tony

**Your AI wrote the code. tony explains what now exists.**

tony turns a git diff into a review page for the person who now owns the code —
often someone who didn't type a line of it. Not a linter, not a code-review
gate: it builds your mental model of the change, fast.

tony does not call a model. It runs inside the coding agent you already pay for:
you ask the agent to review a branch, it calls tony over MCP, tony hands it the
diff and the standard the review has to meet, checks the answer against the
diff, and publishes the page.

Every review page has three tabs:

1. **File changes** — the diff per file, with plain-language annotations sitting
   inline above the lines they explain. Modified code gets Prev / New / Changes
   panes; line numbers are computed from the diff, never trusted to the model.
2. **Blast radius** — files the change reaches that are *not* in the diff, each
   consumer classified breaks / behavior-change / compatible, shown at the
   affected lines.
3. **How it works** — steppable runtime walkthroughs. One concrete scenario
   ("you run `export --resume` after a crash") traced step by step, showing the
   real source lines read from your disk, a small state table, and one plain
   sentence per step.

## Install

```sh
curl -fsSL https://tony-cli.com/install.sh | sh
```

or, if you already use uv or pipx:

```sh
uv tool install tony-cli     # or: pipx install tony-cli
```

Either way you get a `tony` command on your PATH.

## Set up

Two commands, once per machine:

```sh
tony connect                 # register tony with Claude Code, Codex, Cursor, Amp
tony login                   # sign in, so reviews have somewhere to publish
```

Then restart your agent and ask it, in words:

> review this branch with tony

The agent calls `tony_start`, reads the diff and whatever files it needs,
writes the review, and calls `tony_publish`. What comes back is a URL. Reviews
are published to your account; the page is the deliverable, so the agent hands
you the link rather than pasting the review into the chat.

tony reviews **committed** work: the page shows code straight from disk, so the
working tree has to match the revision under review.

## Commands

`tony --help` prints this list.

| Command | What it does |
|---|---|
| `tony connect [host ...]` | Write the MCP config for Claude Code, Codex, Cursor, or Amp. Named hosts only, or all four it finds. |
| `tony login` / `tony logout` | Your account on the tony site. Publishing needs it; nothing else does. |
| `tony mcp` | Run the MCP server on stdio. Your agent runs this, not you. |
| `tony update` | Upgrade to the latest release, using whichever of uv, pipx or pip installed tony. Checks PyPI first and tells you if you're already current. |

Every command asks PyPI whether there is a newer release and says so on the way
out; the request runs alongside the command, so nothing waits on it, and a
review started through the MCP server tells the agent instead of a terminal
nobody is watching. It never installs anything by itself.

| `tony uninstall` | Delete tony and everything it wrote — see [Uninstall](#uninstall). |
| `tony --version` | The installed version. |
| `tony --help` | This list. |

`tony uninstall` takes `--yes` (`-y`) to skip the confirmation and `--no-scan` to
limit it to the current repo instead of searching your home directory.

Both `tony update` and the installer resolve from PyPI explicitly, so a machine
pointed at an internal mirror can't decide what `tony-cli` is.

## Uninstall

```sh
tony uninstall
```

Removing the package by itself would leave the parts worth removing: your login
token in `~/.tony`, and — from versions before tony went agent-native — an API
key beside it and a `.tony/` directory of past reviews inside every repository
you ran tony in, which hold source code. `tony uninstall` lists everything it
found, waits for you to type `yes`, deletes it, then removes the package with
whichever of uv, pipx, or pip installed it.

It searches your home directory for stray review directories; `--no-scan`
limits it to the current repository, and `--yes` skips the prompt.

## Development

```sh
pip install -e ".[dev]"      # the CLI, with pytest
python -m pytest             # the deterministic layer's tests
cd web && npm install
npm run dev                  # the site; /dev renders src/fixtures/review.json
```

The renderer is `web/src/renderer/render.ts`, and the site is the only thing
that runs it. The Python side decides all layout facts (line numbers, spans,
added/changed tags) in `src/tony_cli/layout.py` and ships them in the payload;
the renderer never re-derives them. `DESIGN.md` is the visual contract.

The site deploys to Vercel and needs `DATABASE_URL` (Neon Postgres),
`BLOB_READ_WRITE_TOKEN` (Vercel Blob), and `GITHUB_CLIENT_ID` (an OAuth app
with device flow enabled).
