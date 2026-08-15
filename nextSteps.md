currently the agent loads diffs from the currend wd using the subprocess library

what im gonna do now is turn that getDiff into a tool that the agent calls and will be able to use on any directory on my local machine.


what do i want the tool to do:
    agent finds path to the repository locally
    check the branch
    gets the diffs


## what the program needs

- a `repo_path` arg on `getDiff`, passed to `subprocess.run(cwd=...)` — that's what unlocks "any directory"

- a real Anthropic tool definition: `input_schema` with `repo_path`, `base`, `head` (the current tool list omits `input_schema`, so the API will reject it)

- a dispatcher that maps a `tool_use` block name -> the python function, and a loop that appends the `tool_result` back into `messages`

- guards: verify the path exists and is a git repo, resolve the branch instead of hardcoding `main`, cap the returned diff size

## steps

1. **make `getDiff` location-aware** — add `repo_path: str` as the first param, pass `cwd=repo_path` into `subprocess.run`
2. **add a repo check** — run `git rev-parse --show-toplevel` in that cwd first; return a clear error string if it fails so the model gets a usable message instead of a traceback
3. **resolve the branch** — helper that reads the default branch (`git symbolic-ref refs/remotes/origin/HEAD`), falls back to `main` then `master`, so `base` isn't guessed by the agent
4. **swap `check=True` for manual handling** — return `result.stderr` as an error string on nonzero exit; a raised exception kills the loop, a returned string lets the agent retry
5. **truncate the output** — if the diff exceeds ~100k chars, cut it and append a note saying it was truncated
6. **write the tool schema** — `GET_DIFF_TOOL = {"name": "get_diff", "description": ..., "input_schema": {...}}` with `repo_path` required, `base`/`head` optional
7. **build the dispatcher** — `def run_tool(name, tool_input)` with a dict `{"get_diff": getDiff}`, called as `fn(**tool_input)`
8. **fix the agent loop** — append `{"role": "assistant", "content": response.content}`, then `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "content": result}]}`; right now the tool name is printed and nothing is fed back, so the loop spins
9. **break on `stop_reason`** — continue only while `response.stop_reason == "tool_use"`, break otherwise
10. **change the entrypoint** — stop calling `getDiff()` at import time; seed `messages` with the repo path and let the agent call the tool itself

## also

- `claude-opus-4-1` is behind — use `claude-opus-5`
- Read/Glob/Grep have no implementations, so the blast-radius instructions in SYSTEM can't actually execute yet


next steps

what we're going to do is turn this into a cli tool

the next thing is testing the agent loop
after that we are turning it into a cli tool
then vibecoding a web app

[done — CLI shipped, see below. web app is the current focus.]

---

## status — CLI done

`local.py`: `getDiff` / `resolveRepo` / `resolveBase` / `readFile` / `globFiles` / `grepFiles`.
`agent.py`: SYSTEM prompt, four tool schemas, `TOOLS` dispatcher, `runTool`, `review()` loop
with API error handling, `main()` with argparse. `pyproject.toml` installs `tony` as a command.

Usage: `tony [path] [base...head] [-v] [-m MODEL] [--max-tokens N]`.
Exit codes: 0 ok, 1 API failure, 2 bad input.

Verified: all six tools standalone incl. error paths; loop end-to-end with `getDiff` alone.
NOT verified: the model actually using Read/Glob/Grep, the glossary section, the new diagram
rules, parallel tool calls in one turn. Blocked on API credits.

## ~~the page~~ (SUPERSEDED — built, then redesigned; see status at the end)

The output should be a page, not terminal text. Requirements as of now:

1. **Show the diff, organized by file.** Split the raw `git diff` on `diff --git` boundaries
   in Python — deterministic, costs no tokens, and the model never retypes code it might
   paraphrase. The page has two sources: prose + diagrams from the review, hunks straight
   from git.
2. **Interactive diagrams.** Explicitly a tool for *learning how the system changes*, not
   decoration. Mermaid stays as the renderer.
3. **Click a node -> that file's hunks.** This is where 1 and 2 meet: diagram teaches the
   shape, diff shows the lines, bound by file path. Needs no extra generation.

Prerequisite for any click behaviour: **the prompt must emit stable node IDs tied to real
file paths.** True regardless of which drill-down model wins. Do this before the template.

### open question — what a click does beyond showing hunks

- **precomputed drill-down** — review generates everything up front, click reveals. Fast,
  offline, no infrastructure. Ceiling is what fits in one generation.
- **on-demand generation** — click re-runs tony scoped to that node (`--focus <path>`),
  fresh view generated per click. Unbounded depth, needs a local server to run it.

Not exclusive. Precomputed first (template + prompt change, works with today's CLI);
on-demand is the same page plus a server and a `--focus` mode, reusing the same node IDs.

Blast radius drill-down: deferred, coming back to it.

## ~~diagram design~~ (SUPERSEDED — Mermaid was cut entirely, see walkthroughs below)

Layer by abstraction instead of capping node count — C4's idea, one diagram per zoom
level, each legible alone. Three levels:

1. **context** — which subsystems the change touches, what talks to them. 5-8 nodes, no functions.
2. **blast radius** — call graph of changed symbols and consumers, `subgraph` per file. As many nodes as it takes.
3. **shape change** — before/after of a signature, return type, or schema. Usually two small diagrams.

Conventions: every diagram gets a title stating its scope, plus a legend for the notation.
Edges carry verb labels. Explicit `classDef changed fill:#fef3c7,stroke:#d97706` — unstyled
`:::changed` renders identically to unchanged nodes in some themes.

Blast radius gets structured as first/second/third-order impact (the change, what it touches,
what those touch) rather than a flat list of consumers. Reference point: a PR touching 17
files was measured at a 560-file blast radius, 33x.

## ~~interactivity via Mermaid~~ (SUPERSEDED — no Mermaid in the product)

Render the review to a local HTML file, Mermaid `click nodeId` directives on every node,
drill-down context -> blast radius -> shape change. Node click opens the file via a
`vscode://` link. No server, no framework — `webbrowser.open()`.

Mermaid syntax errors render as *nothing*, silently. Validate blocks with `mmdc` and have
the model retry on failure.

## output target — hosted web app (decided)

The CLI should not open a local file. It uploads the review and prints a URL, the way
`gh pr create` prints a PR link. You click it and land on the tony web app.

    $ tony
    tony: reviewing main...desktop-tweaks (8 files)
    tony: https://tony.dev/r/8f3ka92m

Stack: TypeScript + React (or Astro) on Vercel. The renderer moves out of Python — the
web app owns all layout, `render.py` becomes reference for what to rebuild.

### what this changes

1. **Data leaves the machine.** Today everything is local. Uploading means the diff, the
   code windows in walkthroughs, and the WHOLE impacted files in blast radius all go to a
   server. For anyone with a private repo that is a blocker unless it is answered up front:
   what exactly is uploaded, how long it is kept, who can read it. Decide before building.
2. **Payload, not repo.** Upload the structured review plus only the source ranges the page
   needs. Blast radius currently shows whole files, which is the largest chunk and the
   biggest privacy surface — worth revisiting whether it stays whole-file once the code is
   travelling over a network.
3. **Access control.** Unguessable ID (secret-link security, like a Figma share link) or
   real auth. PR links are permissioned; a random ID is not. Fine for v1, name the choice.
4. **Keep a local mode.** `--html` writing a self-contained file stays the escape hatch for
   people who will not upload. It is also the fastest thing to ship and it works offline.
5. **Retention / expiry.** Reviews are disposable. Default TTL beats storing everything.

### rough shape

- `tony` -> runs the loop -> POSTs `{intent, annotations, impacts, walkthroughs, diff, files}`
  to the API -> gets an id -> prints the URL.
- Web app fetches by id, renders the three tabs.
- `--json` keeps raw output for piping. `--html` keeps the offline file.

## UI direction (decided)

Heavily inspired by Behold's own design system plus the studio/neo-brutalist strain.
Approved references:

- **[maxibestof.one/typefaces/favorit](https://maxibestof.one/typefaces/favorit)** and
  **[abcdinamo.com](https://abcdinamo.com/typefaces/favorit)** — ABC Favorit in the wild.
- **[Awwwards brutalism collection](https://www.awwwards.com/websites/brutalism/)** — the
  numbered-card, visible-border, bold-type dialect.
- **[Vercel design language](https://www.setproduct.com/blog/complete-guide-to-blueprint-grid-design)**
  — deliberate grey scale, every border and disabled state on its own step, no accent colours.
- **[awesome-design-md](https://github.com/VoltAgent/awesome-design-md)** — design systems as
  `DESIGN.md` for coding agents. Written: see `DESIGN.md` at the repo root, transcribed from the
  shipping CSS. It is the contract for the web app rebuild.
- **[Linear](https://linear.app/now/how-we-redesigned-the-linear-ui)** plus its
  [DESIGN.md](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/linear.app/DESIGN.md)
  — the density and state model. Notes below.

Rejected: Muzli's 100-portfolio roundup (too scattered to be a reference).

### inherited from Behold

Pulled from `website/src/styles/global.css` and `behold/apps/mobile/global.css`:

- **ABC Favorit** (sans) + **ABC Favorit Mono**. Dinamo. Non-negotiable, it is the brand.
- Ground `#000000`, surface `#0a0a0a`, text `#ffffff`, one warm grey `#8f8b86`,
  muted blue `#1e3445`, destructive `#ff8081`.
- Radius scale tops out at 8px for real surfaces; 2-4px is the working range. Corners are
  tight, never friendly.
- Dark-first. Wide canvas — Behold's container is 1700px.

### inherited from Linear

Linear is the reference for the part Behold does not cover: how a dark, dense, information-heavy
interface stays readable for an hour. Behold gives the brand, Linear gives the mechanics.

**Take these:**

- **Depth is a surface step plus a hairline step, never a shadow.** Their ladder: canvas ->
  surface-1 with a 1px hairline -> surface-2 with a stronger hairline. No drop shadows anywhere
  on dark. This is exactly the "hairline rules instead of card borders" rule already written
  above, with a working mechanism attached.
- **"The dark canvas IS the whitespace."** Sections separate by lifting a surface, not by adding
  a white gap. This is what lets a page stay dense without feeling cramped, and it is the answer
  to the studio-chrome / dense-interior split: the chrome breathes, the interior lifts instead.
- **State is carried by surface and hairline, not by colour.** Hover lifts to the next surface,
  focus is a 2px ring, selection is a contrast shift. This resolves the conflict in the current
  page, where the accent doubles as "selected tab" and as "changed" — under our rule the accent
  cannot do both. Selection moves to a contrast/hairline treatment; camel keeps meaning *changed*
  and only *changed*.
- **Four text tiers, not two.** Their ramp: primary `#f7f8f8`, muted `#d0d6e0`, subtle `#8a8f98`,
  tertiary `#62666d`. We have `#ffffff` and `#8f8b86` and nothing in between, which is why the
  diff gutter, the mono labels, and the annotation body currently fight each other. Derive two
  intermediate warm greys between white and `#8f8b86` rather than reaching for opacity.
- **Four surface steps.** Theirs: `#010102` / `#0f1011` / `#141516` / `#18191a` — the whole ramp
  lives inside 24 points of lightness. Ours starts at `#000000` and `#0a0a0a`; it needs two more
  steps above that, spaced just as tightly.
- **LCH, not HSL, for generating the ramp.** Equal lightness values look equally light to the eye
  across hues, which matters because our greys are warm and the diff green/red are not. Also how
  they got a whole theme out of three variables: base, accent, contrast.
- **Tracking runs opposite by size.** Aggressive negative tracking on display type (≈4% of size at
  80px), *positive* tracking on small eyebrow labels. Our bracketed uppercase mono headers are
  eyebrows — they get positive tracking, and the masthead gets negative.
- **A signature weight between regular and medium.** Linear's 510 does the work of "emphasis
  without shouting". Favorit Book (500) sits in the same slot; use it as the default emphasis
  rather than jumping to Bold.
- **Contrast as a variable, not a constant.** They ship a high-contrast theme off the same tokens.
  Cheap to keep possible if the ramp is generated rather than hand-typed.

**Reject these — they collide with the direction already set:**

- **Their radius scale** (8px buttons, 12–16px cards, pill tabs). Ours is near zero in dense areas
  and 2–4px elsewhere. Corners stay tight.
- **Their "never use true black"** rule. `#010102` with a faint blue tint is their anchor;
  ours is Behold's `#000000` and that is brand, not preference. Keep `#000`, and get the
  separation back through the surface ramp above it.
- **Their accent policy.** Lavender marks brand, CTA, and focus ring. Camel marks *changed*.
  Same discipline, different referent — do not let it drift onto buttons or focus states.
- **Their marketing-page furniture** — oversized cards, screenshot-led sections, 96px section
  gaps. That is the landing-page aesthetic the split above already rules out for the interior.

### the split: studio chrome, tool interior

Landing-page aesthetics applied wholesale to dense UI fail — oversized type and generous
whitespace fight a diff you read for ten minutes. So:

**Chrome gets the full studio treatment** — masthead, tabs, section markers, empty states,
and the eventual marketing page. Big tight-tracked Favorit, bracketed labels, hard rules.

**Interior stays dense and quiet** — diff body, code windows, state tables. Favorit Mono,
tight leading, accent reserved for marking what changed.

**But push some studio language into the dense parts** — this is what would make it not look
like every other diff viewer:

- Bracketed / numbered markers on file rows and walkthrough steps: `[01]` not a bare dot.
- Section headers as wide-tracked uppercase mono in brackets: `[ FILE CHANGES ]`.
- Hairline rules instead of card borders wherever a box is not load-bearing.
- Tabular numerals everywhere numbers align — gutters, counts, state tables.
- Radius near zero in the dense areas; the studio look is square.
- Accent used for exactly one meaning (changed) and nothing else. Colour is information.

### the accent — warm brown

Not acid yellow. A desaturated warm brown/tan, which sits naturally beside Behold's warm
grey `#8f8b86` and — unlike yellow — does not compete with the green/red the diff needs.

Working value: **`#C89F6D` camel**. Alternatives if it reads too light:
`#B08968` clay (softer, more Behold-adjacent), `#A87C4F` toasted (deeper, muddier at
small sizes).

Constraint: on a `#000` ground a true brown goes muddy, so it has to be pushed toward tan
to survive at 11px mono label sizes. Check it against destructive `#ff8081` before
committing — different enough in hue and saturation, but they will sit adjacent in state
tables.

Rule stands regardless of the value: the accent means exactly one thing — changed — and
carries no decorative use anywhere.

## backlog

- **temporal coupling** — mine `git log` for files that change together without importing each
  other. Catches cross-language pairs, config/consumer links, schema+migration+serializer
  trios. One pass: `git log --format="%H" --name-only --since="1 year ago"`, count pair
  co-occurrence, exclude commits touching 50+ files. Pitch: "you changed `auth/session.py`;
  the last 14 times someone did, they also changed `mobile/api_client.ts` — you haven't."
- **tree-sitter** — real symbol extraction instead of grep, language-agnostic. Proper blast radius.

Dropped, not deferred: the **CI / GitHub App version** (2026-08-15) and **"pi for diffs"**.
Tony is a local CLI that publishes a page. That is the whole product surface.

---

## where it actually landed (current)

The page has three tabs, all generated by `render.py` from one JSON block the model emits.

1. **File changes** — the diff per file, GitHub style, with annotations sitting inline above
   the lines they explain. Modified code gets Prev / New / Changes panes; additions get a
   flat note. Line ranges are computed from the diff, not trusted to the model. Risks are
   opt-in behind a header toggle.
2. **Blast radius** — files the change reaches that are NOT in the diff. Whole file shown,
   annotated at the affected lines, classified `breaks` / `behavior-change` / `compatible`.
   Sticky prev/next stepper walks every impact site across all files.
3. **How it works** — steppable runtime walkthroughs. Each is one concrete scenario
   ("you click the speaker button", "someone pastes the link in Slack") traced step by step,
   showing the real source lines read from disk, a small state table, and one plain sentence.
   Steps are tagged new / changed / removed. Header carries `whatChanged`, file chips, and a
   count of how many steps are new.

Mermaid, the free-form HTML widget kit, and the prediction checkpoints were all built and
then cut. Reasons worth keeping:

- **Mermaid** drew repo structure, which barely changes between diffs, so every review got
  the same generic picture. The replacement rule: draw runtime mechanism, not structure.
- **Free-form HTML widgets** let the model reinvent the interaction every run. Interaction
  quality is exactly what determines whether anyone learns, so the player became renderer
  code and the model only supplies the trace.
- **Checkpoints** (predict-then-reveal questions) came out of the engagement research and
  worked, but were cut as friction. If they return, make them non-gating reveals.

### output wiring (done, 2026-08-15)

The page is now the default output. `tony` writes
`.tony/<base>...<head>.html` inside the repo being reviewed, prints the path, and opens it.
`--json` prints the raw JSON review instead; `--no-open` writes without launching a browser.
`review()` returns `(code, text, diff)` — the diff is kept from the model's own `getDiff`
call, so the page lays out exactly the change the model read. If the model somehow answers
without fetching a diff, tony prints the raw review and exits 1 rather than rendering a page
with no files in it.

Fixed along the way: `load_dotenv()` was resolving from the cwd, so the key was only found
when tony ran from its own repo. It now loads `.env` from the module path.

Cut as dead: `MERMAID_FENCE` and the whole node/diagram click path in `render.py`,
`parseManifest` / `checkManifest` / `nodeId` / `baseNodeId` / `VARIANTS` in `local.py`, and
the NODES section of the SYSTEM prompt. `parseReview` now returns just the parsed dict.
The walkthrough intro still promised prediction checkpoints that were cut — reworded.

`src/tests/test_render.py` covers `changedRuns`, `spanFor`, `splitDiffByFile`, and
`codeWindow`, with the clamp and off-by-one edges pinned. 27 tests, `pytest src/tests`.

### the working-tree guard (done, 2026-08-15)

Every line of code tony shows — annotations, walkthrough code windows, whole blast-radius
files — is read from the working tree, while every line NUMBER comes from the new side of the
diff. Reviewing a revision that is not checked out therefore rendered real line numbers over
the wrong code, silently. `checkWorkingTree` now refuses (exit 2) when `head` is not the
checked-out commit or when tracked files are dirty; `--stale` downgrades it to a warning.

The real fix, when tony needs to review arbitrary ranges (the web app, and any CI path):
read contents at the reviewed revision with `git show <rev>:<path>` instead of from disk,
in `readFile`, `codeWindow`, and `renderImpacts`. The guard buys correctness today; it does
not remove the assumption.

### first non-Astro run (done, 2026-08-15)

Target: `encode/httpx` PR #3690, "Add `.wait_ready` to parser for clean server disconnects".
4 files, +51/-6, async networking — real runtime mechanism, not a config bump. Fetched with
`git fetch origin pull/3690/head:pr-3690` (the branch was deleted post-merge, and the PR's base
was `v1`, not `master`).

**Held up better than expected.** Every line anchor was exact: `_parsers.py:227` landed on
`def wait_ready`, `_server.py:35` on the `wait_ready()` call, and both blast-radius anchors
(`scripts/docs:133`, `docs/servers.md:37`) on the literal `server.wait()` line. Python idioms —
`async def`, docstrings, type hints, context managers — were explained mechanically rather than
named. Nothing in the prompt turned out to be secretly TypeScript-shaped, and no code window
failed to read. 14 tool calls, 11 annotations, 5 impacts, 2 walkthroughs.

**The one real failure: mirrored source trees.** httpx ships `src/httpx` and `src/ahttpx` as
sync/async twins — the same 17 added lines in each. The model annotated both, so 10 of 11
annotations are near-identical pairs and the reader reads the entire change twice. It picked
the sync tree for both walkthroughs, which was the right call, so it clearly *knows* they are
twins without saying so.

Worth a prompt rule: when two files receive the same change, annotate one and note that the
other mirrors it. Generalises past this repo — generated clients, sync/async pairs, and
platform-specific copies all produce it. Do this before the web app, since it roughly halves
the payload on any repo shaped this way.

### fixes on top of the httpx run (done, 2026-08-15)

- **The kind tag comes from the diff now.** The model called an inserted guard "changed"
  because the loop's behaviour changed, which is true of the behaviour and false of the lines —
  the reader got a CHANGED tag over an all-green block and went hunting for a replacement that
  did not exist. `changedRuns` now returns `(start, end, hadDeletion)` and `kindFor` decides the
  tag from that. "removed" is never rewritten. Same precedent as line ranges: the diff answers
  it, so the model is not asked.
- **Mirror rule in the prompt.** Verified on httpx: 11 annotations down to 8, both `ahttpx`
  files reduced to a single "Same change, async copy" note, all four files still listed.
- **`resolveBase` falls back.** `origin/HEAD`, then `main`, then `master`, checking both remote
  and local refs; a clear error naming the explicit-range escape hatch when none exist. The CLI
  resolves the base once, up front, so the run is reproducible and the base is reported rather
  than left to the model.
- **Blast radius opens the worst file**, and scrolls that file's own box to the affected line.
  Opening it alone was not enough — a 153-line script opened at line 1 while the impact sat at
  133. The page never scrolls; only the file's box does.
- **Spacing pass**: tighter masthead and tab rhythm, diff leading 1.6 to 1.5, calmer annotation
  padding.

Known wrinkle: files render in diff order, so an alphabetically earlier mirror (`ahttpx`) is
listed above the file it points at (`httpx`). The note names its target, so it reads fine, but
ordering the fully-annotated copy first would read better.

## web app — decisions made (2026-08-15)

- **Payload carries windows, not whole files.** ~20 lines either side of the impact sites in a
  file, one window per file rather than per site. Measured: blast-radius source drops 66%
  (httpx 14.3 KB -> 4.8 KB, website 12.7 KB -> 5.5 KB). A whole payload is 23–29 KB against a
  433 KB local HTML page. Fetch-on-demand for the rest of a file stays open as a later addition.
- **No storage, no TTL, for now.** Nothing is kept server-side, so retention and access control
  are moot until it is. Unguessable-link sharing is the intent when hosting does land.
- **Astro.** The page is text and code; the existing vanilla tab/stepper JS ports directly and
  ships no framework runtime. Moving to Next later costs about a day — page shells and routing —
  because the CSS and the deterministic logic (`changedRuns`, `spanFor`, `kindFor`,
  `splitDiffByFile`, the payload shape) are framework-independent. Lock-in comes from adopting
  framework-specific APIs deeply, not from the choice itself.
- **Absolute paths never leave the machine.** The payload carries the repo's basename; the local
  page still shows the full path in the masthead.

`src/tony/payload.py` builds it. `tony --payload` writes `.tony/<range>.payload.json`, or
`--payload PATH` writes wherever you say. `tony --viewer` writes it straight into
`web/src/fixtures/review.json`, so running tony in any repo swaps what the local viewer is
showing — the fixture lives inside `src/`, so Astro's watcher reloads it with the dev server
running. `viewerFixture()` returns None on a non-source install, where there is no viewer to
load.
`DESIGN.md` at the repo root is the contract for the rebuild.

### the viewer (scaffolded, 2026-08-15)

`web/` — Astro, no framework runtime, reads `src/fixtures/review.json` at build time. When
hosting lands, that import becomes a fetch by id and nothing else on the page changes.

- `web/src/lib/diff.ts` — presentation helpers only. It used to be a port of `changedRuns`,
  `spanFor`, `kindFor`, `diffRows` and `interleave`, which meant two implementations of the
  logic that decides line numbers, and a standing risk of drift showing real line numbers over
  the wrong code. Fixed by moving the boundary rather than by testing the duplication: see
  "one deterministic layer" below.
- `web/src/styles.css` — extracted mechanically from the `render.py` TEMPLATE rather than
  retyped, so the port cannot drift from the design. Fonts are served from `public/fonts`
  instead of base64'd, since a hosted page can cache them.
- Components: `FileChanges`, `Annotation`, `BlastRadius`, `Walkthroughs`. Blast radius renders
  the windowed source with `… N earlier/later lines` markers where the file was cut.

Output: **64 KB HTML, zero JS files** — Astro inlines the small tab/step player. Against
433 KB for the self-contained local page, which carries its fonts inline.

Gotcha worth remembering: the Astro compiler reads `<=` and `<` inside JSX expressions as the
start of a tag. Every comparison belongs in the frontmatter, which is where it reads better
anyway.

### one deterministic layer (done, 2026-08-15)

`layout(body, items)` in `render.py` is now the only place line numbers, spans, and the
added/changed/removed tag are decided. It returns ordered blocks — rows carrying their
gutter number, notes carrying a resolved `span` and `tag` plus an index back into the
payload's own annotations/risks arrays.

Both renderers consume it. `renderBlocks` turns blocks into HTML for the local page; the
payload ships the same blocks so the Astro components map over them. `files[].body` is gone
from the payload — the rows replace it.

This is why it beats testing the two implementations against each other: the hosted page
**cannot** disagree with the local page about a line number, because it does not compute one.
Verified on httpx — the file-changes pane of both renderers agrees on all 126 rows, 3 tags and
10 spans. The panes legitimately differ elsewhere: blast radius is whole-file locally and
windowed in the payload, by design.

Payload grew 22.7 KB -> 27.8 KB for the row metadata. Cheap for deleting a class of bug.

What stays duplicated is markup and CSS, which is real presentation work in two languages.
That only goes away by deleting the Python renderer once hosting exists and `--html` can be
served by a prebuilt single-file bundle — which would add a Node build dependency to a CLI
that installs with pip today. Not yet.

### publishing (done, 2026-08-15) — closes handoff item 4

```
$ tony . origin/v1...HEAD --publish
tony: https://tony-1bed63ede-fabay2-2229s-projects.vercel.app
tony: /path/to/repo/.tony/origin-v1...HEAD.html
```

`publish()` writes the self-contained page into a temp directory named `tony` — Vercel names
the project after the directory, so every review lands in one project — and runs
`vercel deploy --yes`. Each review is its own immutable deployment with its own URL. **Vercel
is the storage, so nothing else has to be**: no database, no ids to mint, no TTL to enforce.

The CLI reports JSON on stdout, so the URL comes from `deployment.url` rather than from
scraping lines; the line-scan stays as a fallback for older versions.

Deliberately NOT the Astro viewer. Astro static-renders the payload into HTML at build time,
so publishing an arbitrary review through it would mean running a Node build per review —
a Node dependency in a CLI that installs with pip. `render.py` already emits a self-contained
page, so for v1 the Python output *is* the artifact. The viewer earns its keep later, when
hosting fetches a payload by id and renders client-side.

**Links currently open only for the account owner.** Every deployment on this Vercel account
inherits Vercel Authentication, so anonymous fetches get the login page — verified, not
assumed. Accepted for v1: the reader of a tony review is the person who ran tony. Turning it
off is Settings -> Deployment Protection -> Vercel Authentication -> Disabled, a dashboard
toggle with no code change either way.

## pending fixes

Known, reproduced, deliberately not fixed yet. None of them block the web app.

1. **No cap on diff size, and truncated JSON fails quietly.** Step 5 of the original plan was
   never built — `getDiff` returns the whole diff, so a large PR enters the context at full
   cost. If the answer then exceeds `--max-tokens`, `parseReview` catches the `JSONDecodeError`,
   returns `{}`, and the page renders with a full diff, no annotations, "No summary produced",
   and **exit 0** — a failed run that looks like a successful one. Cap the diff with a
   truncation marker; make an unparseable review a hard failure that keeps the raw text.
2. **Source is read from the working tree, not the reviewed revision.** `readFile`,
   `codeWindow`, and `renderImpacts` all read from disk. `checkWorkingTree` makes this safe by
   refusing when the tree does not match, but the assumption is untouched. `git show
   <rev>:<path>` removes the checkout requirement entirely. Required for the web app and any CI
   path; touches the model's tool contract, so it is the riskiest change outstanding.
3. **Mirror files sort above the file they point at.** Files render in diff order, so
   `src/ahttpx/…` lands above the `src/httpx/…` copy its "same change" note refers to. Reads
   fine because the note names its target; ordering the fully-annotated copy first would be
   better.

Research that shaped this, worth not re-deriving:
Naps et al. engagement taxonomy (viewing alone teaches little; responding and changing are
where effectiveness jumps), notional machines (novices lack a model of runtime, not syntax),
self-explanation effect (high leverage but must be prompted), Mayer segmenting principle
(user-paced steps beat one continuous presentation), and Multiple Coordinated Views 2025
(synchronised code + state + plain language beats any single view).
