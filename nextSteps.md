# tony — what's next

Live work only. Finished work is in git history; visual and architectural decisions are in
[DESIGN.md](DESIGN.md). Nothing here is a log — if an item is done, delete it.

---

## Must fix — review quality on large diffs

Measured on a 493 KB / 12,338-line / 64-file diff (2026-08-22, the whole repo history in one
review). It completed — 16 turns, 7 minutes, $2.71 — but the output was hard to read.

1. **Annotation density collapses.** 84 annotations for 12k lines, and many changes had none.
   The system prompt demands every hunk be explained *and* says "be ruthlessly concise, never
   pad"; on a large diff those fight and concision wins. Coverage has to win instead, or the
   prompt needs a density floor that scales with hunk count.
2. **The walkthrough cap is a literal constant.** `agent.py` says "Write at most two." Two is
   right for a PR and absurd for 10 commits. Scale with diff size.
3. **Annotations landed in the wrong places — cause not yet established.** That run used
   `--stale` against a dirty tree, which is exactly the condition `checkWorkingTree` refuses
   by default: the diff came from the commits, the code windows from disk. Settle this before
   spending prompt effort — `git stash && tony . <range> --local` on a clean tree tells you
   whether the misplacement is real or an artefact of the flag.

## Must fix — reading a large review

The page is one long scroll. At 64 files that does not work.

- **Paginate or tab the file list by the role a file plays** rather than diff order. Roles
  should be derived deterministically from the path (source / test / config / generated /
  assets / docs, and by top-level package), not supplied by the model — see DESIGN.md
  "Ground truth". The model already ignores lockfiles correctly; the renderer should not be
  showing them at the same weight as source.
- Mirror files still sort above the file their "same change" note points at. Ordering the
  fully-annotated copy first would read better.

## Cost and context on very large diffs

The real target is AI-generated PRs of 40k+ lines, ~3x the run above. Extrapolated from it:

| | 12k lines (measured) | 40k lines (extrapolated) |
|---|---|---|
| peak context | 300K tok | ~970K tok — at the 1M window |
| turns | 16 | ~50 — over `MAX_TURNS = 30` |
| cost | $2.71 | ~$28 |

Cost grows roughly quadratically: context grows *and* turn count grows. In order of effort:

1. **Filter generated files in `getDiff`.** `package-lock.json` was 3,961 of 7,956 insertions
   in that run — half the diff, shipped into context on all 16 turns, for output the prompt
   correctly discards. Lockfiles, `dist/`, minified assets. Pure savings, no quality risk.
2. **Context editing** — `context_management: {edits: [{type: "clear_tool_uses_20250919"}]}`
   drops stale tool results. Whole files the model read are what inflate context to 300K.
   Attacks the quadratic term directly.
3. **Chunk the diff** — review file groups in separate conversations, merge the payloads.
   `splitDiffByFile` already gives the seam. Makes cost linear and removes both ceilings.
   A day's work; the two above may make it unnecessary.

Baseline worth keeping: prompt caching is live and measured at **7.9x** on that run
(4.2M cache-reads vs 49K writes). `tony -v` prints the usage line — `cache_read` should be
large from turn two.

## Pending fixes

1. **Source is read from the working tree, not the reviewed revision.** `readFile` and the
   payload windows read from disk. `checkWorkingTree` makes this safe by refusing when the
   tree does not match, but the assumption is untouched. `git show <rev>:<path>` removes the
   checkout requirement entirely — and would remove the `--stale` ambiguity in item 3 above.
   Touches the model's tool contract, so it is the riskiest change outstanding.
2. **No cap on diff size.** `getDiff` returns the whole diff at full cost. Related to the
   filtering item above.

## Ops

- **Run the `tokens.expires_at` migration against a real database once.** Added 2026-08-22,
  never executed — there is no local Postgres. It runs inside `withDatabase`, so a failure
  surfaces as a 503 that reads like an outage.
- **Blob retention.** Nothing expires. Rows and blobs live until someone runs
  `tony unpublish`, and nobody will. Storage is the only cost that grows with use.
- **Rate limit on review reads.** Any signed-in account can fetch any review by id — stated
  design, the id is the capability — but that route has no throttle, so it is a free
  enumeration oracle.

## If tony ever pays for inference

Currently users bring their own `ANTHROPIC_API_KEY` and tony costs nothing to run beyond
hosting. If that changes for a test group:

- **Never ship the key in the CLI.** Anything on a user's machine is extractable.
- The workable shape is a proxy: CLI -> tony's `/api/review` (authenticated with the token it
  already has) -> Anthropic, key server-side. Tool calls still run locally; the server only
  relays messages. That is also where per-user metering and a kill switch live.
- Per-user caps before access, not after. One tester reviewing a monorepo daily is real money
  at $3 a review.

## Backlog

- **temporal coupling** — mine `git log` for files that change together without importing each
  other. Catches cross-language pairs, config/consumer links, schema+migration+serializer
  trios. One pass: `git log --format="%H" --name-only --since="1 year ago"`, count pair
  co-occurrence, exclude commits touching 50+ files. Pitch: "you changed `auth/session.py`;
  the last 14 times someone did, they also changed `mobile/api_client.ts` — you haven't."
- **tree-sitter** — real symbol extraction instead of grep, language-agnostic. Proper blast
  radius.

Dropped, not deferred: the **CI / GitHub App version** and **"pi for diffs"**. Tony is a local
CLI that publishes a page. That is the whole product surface.

---

Research that shaped this, worth not re-deriving:
Naps et al. engagement taxonomy (viewing alone teaches little; responding and changing are
where effectiveness jumps), notional machines (novices lack a model of runtime, not syntax),
self-explanation effect (high leverage but must be prompted), Mayer segmenting principle
(user-paced steps beat one continuous presentation), and Multiple Coordinated Views 2025
(synchronised code + state + plain language beats any single view).
