# Tony — handoff prompt

Paste everything below into a fresh conversation.

---

I'm building **tony**, a command-line tool that explains a git diff to the person who now
owns the code. Repo is at `/Users/fawwazabayomi/Downloads/tony`. Read `nextSteps.md` first —
it has the full decision history, including things that were built and deliberately cut.

## Who it's for

Someone who generated the code with an LLM and didn't write a line of it. Assume they do not
know the codebase, the framework, the naming conventions, or necessarily how to read the
syntax. The goal is that they build a real mental model of what their AI just built, without
reading code for hours. It is **not** a code review tool — risks are a secondary, opt-in
feature.

## How it works today

`tony` runs a multi-turn tool loop directly against the Anthropic Messages API (no
framework). The model gets four tools that let it verify claims against the actual repo,
then emits **one JSON block**; a deterministic Python renderer owns all layout and produces
a self-contained HTML page.

```
src/tony/agent.py          SYSTEM prompt, 4 tool schemas, TOOLS dispatcher, runTool,
                           review() loop with API error handling, main() with argparse
src/tony/source/local.py   getDiff, resolveRepo, resolveBase, readFile, globFiles,
                           grepFiles, splitDiffByFile, fileId
src/tony/render.py         parseReview, renderFiles, renderImpacts, renderWalkthroughs,
                           renderPage + the HTML TEMPLATE
pyproject.toml             installs `tony` as a command (pip install -e .)
nextSteps.md               decisions, rationale, backlog
```

Run it:

```
cd <any repo>
tony [path] [base...head] [-v] [-m MODEL] [--max-tokens N]
```

Exit codes: 0 ok, 1 API failure, 2 bad input. `.env` in the tony repo holds
`ANTHROPIC_API_KEY` and is found from the module path, so it works from any cwd.

Test repo that everything has been developed against:
`/Users/fawwazabayomi/Downloads/website`, branch `desktop-tweaks` vs `main` (8 files,
+48/-13, Astro + React + TypeScript).

## The output page — three tabs

1. **File changes** — the diff per file, GitHub style, with annotations inline above the
   lines they explain. Modified code gets **Prev / New / Changes** panes; pure additions get
   a flat note. Line ranges are computed from the diff by `changedRuns`/`spanFor`, never
   trusted to the model. Risks are opt-in behind a header toggle.
2. **Blast radius** — files the change reaches that are **not** in the diff. Whole file
   shown, annotated at affected lines, each classified `breaks` / `behavior-change` /
   `compatible`. Sticky `< >` stepper walks every impact site across all files.
3. **How it works** — steppable runtime walkthroughs. Each traces one concrete scenario
   ("you click the speaker button", "someone pastes the link in Slack") step by step, showing
   the real source lines **read from disk**, a small state table, and one plain sentence per
   step. Steps tagged new / changed / removed. Header carries `whatChanged`, file chips, and
   how many steps are new.

## Decisions already made — please don't relitigate

- **The model emits data, the renderer owns layout.** Cut output ~90% and made it testable.
- **Code shown is always read from disk**, never from the model. It can name a line range,
  not the contents.
- **Mermaid was built and cut.** It drew repo structure, which barely changes between diffs,
  so every review got the same generic picture. Rule that replaced it: draw runtime
  mechanism, not structure.
- **Free-form HTML widgets were built and cut.** The model reinvented the interaction every
  run. Interaction quality is what determines whether anyone learns, so the player became
  renderer code and the model only supplies the trace.
- **Prediction checkpoints were built and cut** as friction. If they return, non-gating.
- **CI / GitHub App is scrapped.** CLI → hosted page only.
- Research behind the walkthrough design (don't re-derive): Naps et al. engagement taxonomy,
  notional machines, the self-explanation effect, Mayer's segmenting principle, and Multiple
  Coordinated Views (2025). Cited in `nextSteps.md`.

## What I want to build next, in order

**1. Wire `--html`.** This is the blocking gap. `renderPage()` currently has to be called by
hand — `tony` just prints raw JSON. Make the page the default output, `--json` for raw.
Write to `.tony/` in the repo, print the path, open it.

**2. Restyle to the real design direction.** See the UI section of `nextSteps.md`. Short
version: ABC Favorit + Favorit Mono (Behold's typeface), `#000` ground, `#0a0a0a` surface,
`#8f8b86` warm grey, `#C89F6D` camel accent. Studio chrome, dense quiet interior, with some
studio language pushed into the dense parts: `[01]` markers, bracketed uppercase mono section
headers, hairline rules instead of card borders, tabular numerals, near-zero radius. The
accent means exactly one thing — *changed* — and has no decorative use.

**3. Run it on a non-Astro repo.** Everything has been tested on one TypeScript branch. A
Python repo will expose prompt assumptions that this one hides.

**4. Then the web app.** TypeScript + React or Astro on Vercel. `tony` uploads the review and
prints a URL like `https://tony.dev/r/8f3ka92m`, the way `gh pr create` prints a PR link.
`render.py` becomes the reference spec for what to rebuild. Privacy needs deciding first —
blast radius currently ships whole files, which is the biggest payload and the biggest
exposure.

## Housekeeping worth doing along the way

- Dead code, all confirmed zero-caller: `MERMAID_FENCE` and the diagrams path in
  `render.py`; `parseManifest`, `checkManifest`, `nodeId`, `baseNodeId`, `VARIANTS` in
  `local.py`; the `markdown` package in the venv.
- The SYSTEM prompt still has a **NODES section** asking for a `nodes` array nothing
  consumes — costs tokens on every run.
- `src/tests/` is empty. `changedRuns`, `spanFor`, `splitDiffByFile`, and `codeWindow` are
  pure functions with fiddly off-by-one edges. `codeWindow` silently showing the wrong lines
  is the failure that would quietly destroy trust in the walkthroughs.

## How I like to work

Be concise. Show me the thing rather than describing it — publish the generated page as an
artifact so I can look at it. Push back when I'm wrong, and tell me what you actually
verified versus what you assumed.

Start by reading `nextSteps.md`, `src/tony/agent.py`, and `src/tony/render.py`, then do #1.
