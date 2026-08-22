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

Useful flags: `--replay` rebuilds the page from the last run without calling
the API, `--json` prints the raw review, `-v` logs every file the model
actually read, `--stale` overrides the clean-tree check.

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

## Development

```sh
pip install -e ".[dev]"      # the CLI, with pytest
python -m pytest             # the deterministic layer's tests
cd web && npm install
npm run build:viewer         # rebuild the renderer bundle the CLI embeds
npm run dev                  # the site; /dev renders src/fixtures/review.json
```

There is exactly one renderer — `web/src/renderer/render.ts` — used by both
the local page and the hosted site. The Python side decides all layout facts
(line numbers, spans, added/changed tags) in `src/tony_cli/layout.py` and ships
them in the payload; the renderer never re-derives them. `DESIGN.md` is the
visual contract.

The site deploys to Vercel and needs `DATABASE_URL` (Neon Postgres),
`BLOB_READ_WRITE_TOKEN` (Vercel Blob), and `GITHUB_CLIENT_ID` (an OAuth app
with device flow enabled).
