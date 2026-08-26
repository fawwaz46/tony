# tony

**Your AI wrote the code. tony explains what now exists.**

tony is a CLI that turns a git diff into a review page for the person who now
owns the code — often someone who didn't type a line of it. Not a linter, not a
code-review gate: it builds your mental model of the change, fast.

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

## Use

```sh
cd your-repo
tony main...my-branch        # review a branch against main
tony                         # review the default branch...HEAD
```

The page is written to `.tony/` inside the repo (gitignored automatically) and
opens in your browser. It's one self-contained HTML file — fonts, styles, and
data inlined — so it works offline and forever.

tony needs an Anthropic API key (`ANTHROPIC_API_KEY`, or `~/.tony/.env`). The
first run tells you exactly where to get one and where to put it. tony reviews
**committed** work: it shows code straight from disk, so the working tree must
match the revision under review.

Every command and flag is listed under [Commands](#commands).

## Commands

`tony --help` prints this list. Everything below works from anywhere inside a
git repo unless noted.

### Reviewing

```sh
tony                          # default branch...HEAD, in the current repo
tony main...my-branch         # an explicit range
tony my-branch                # shorthand for my-branch...HEAD
tony ../other-repo main...x   # any path inside another repo
```

The range is git's own `BASE...HEAD` syntax. With no range, tony diffs against
`origin/HEAD` — what the remote calls its default branch — falling back to
`main`, then `master`.

| Flag | What it does |
|---|---|
| `--local` | Keep the review on this machine. No account needed, nothing uploaded; you get the self-contained page in `.tony/` instead of a link. |
| `--json` | Print the raw review JSON to stdout and exit. Writes no page, uploads nothing, needs no account. |
| `--no-open` | Write the page but don't open a browser. For CI, or over SSH. |
| `--stale` | Review a revision that isn't checked out, or with a dirty tree. Code is read from disk, so line numbers may not match the diff — tony refuses by default for that reason. |
| `--replay` | Rebuild the page from the last saved review for this range, without calling the API. Free; use it after a tony upgrade to re-render an old review. |
| `-v`, `--verbose` | Log every tool call to stderr, so you can see which files the review actually read before it drew conclusions. |
| `-m`, `--model` | Model to review with. Defaults to `claude-opus-5`. |
| `--max-tokens` | Response ceiling, default `64000`. Raise it if a review comes back cut off. |

### Sharing

| Command | What it does |
|---|---|
| `tony login` | Sign in to tony-cli.com with GitHub's device flow. Once per machine. |
| `tony logout` | Revoke this machine's token server-side, then delete it locally. |
| `tony whoami` | Which GitHub account this machine is signed in as. |
| `tony unpublish <id>` | Take one published review down. The id is the last part of its URL. |

Publishing is the default when you're signed in. `--local` opts out per run.

### Managing tony

| Command | What it does |
|---|---|
| `tony update` | Upgrade to the latest release, using whichever of uv, pipx or pip installed tony. Checks PyPI first and tells you if you're already current. |
| `tony uninstall` | Delete tony and everything it wrote — see [Uninstall](#uninstall). |
| `tony --version` | The installed version. |
| `tony --help` | Every command and flag. |

`tony uninstall` takes `--yes` (`-y`) to skip the confirmation and `--no-scan` to
limit it to the current repo instead of searching your home directory.

Both `tony update` and the installer resolve from PyPI explicitly, so a machine
pointed at an internal mirror can't decide what `tony-cli` is.

## Share a review

```sh
tony login                   # once — GitHub device flow
tony main...my-branch        # publishing is the default
tony: https://tony-cli.com/r/8f3ka92m
```

**Who can read a published review:** anyone signed in who has the link. Review
ids are random, so the link is what grants access — treat it like a password.
`tony unpublish <id>` removes a review at any time.

**What the site can read:** everything in the review. The payload is uploaded
over TLS and encrypted at rest under a key the server holds, so a leak of the
stored blobs yields nothing — but we can open a review, and so can any lawful
demand made to us. Do not publish from a repository you could not share with
us. An earlier design encrypted on your machine and kept the key in the link's
fragment; that was dropped deliberately when reading moved behind an account
and a history of past reviews became part of the product, since both need the
server to be able to open a review.

Local review needs no account and never leaves the machine: `tony --local`.

## Uninstall

```sh
tony uninstall
```

Removing the package by itself would leave the parts worth removing: your
`ANTHROPIC_API_KEY` and site login in `~/.tony`, and a `.tony/` directory of
past reviews inside every repository you ran tony in — those hold source code.
`tony uninstall` revokes the site token, lists everything it found and waits
for you to type `yes`, deletes it, then removes the package with whichever of
uv, pipx, or pip installed it.

It searches your home directory for stray review directories; `--no-scan`
limits it to the current repository, and `--yes` skips the prompt. Reviews you
published to the site are separate — take those down with `tony unpublish <id>`
before uninstalling, or they stay up.

## Development

```sh
pip install -e ".[dev]"      # the CLI, with pytest
python -m pytest             # the deterministic layer's tests
cd web && npm install
npm run build:viewer         # rebuild the renderer bundle the CLI embeds
npm run dev                  # the site; /dev renders src/fixtures/review.json
```

Two flags exist only for this loop, and only work from a source checkout:

| Flag | What it does |
|---|---|
| `--viewer` | Write the payload straight into the local Astro viewer and reload it there, so you can iterate on the renderer against a real review. |
| `--payload [PATH]` | Write the upload payload — windowed source, no absolute paths — next to the page, or to `PATH`. |

There is exactly one renderer — `web/src/renderer/render.ts` — used by both
the local page and the hosted site. The Python side decides all layout facts
(line numbers, spans, added/changed tags) in `src/tony_cli/layout.py` and ships
them in the payload; the renderer never re-derives them. `DESIGN.md` is the
visual contract.

The site deploys to Vercel and needs `DATABASE_URL` (Neon Postgres),
`BLOB_READ_WRITE_TOKEN` (Vercel Blob), and `GITHUB_CLIENT_ID` (an OAuth app
with device flow enabled).
