# tony — agent-native + monetization

The pivot: tony stops calling the Anthropic API and becomes something the user's
agent calls. The agent supplies the intelligence and pays for it out of its own
subscription; tony supplies the diff, the instructions, the validation, and the
hosted review. No API key anywhere in the user experience.

Consequences that drive everything below:

- **COGS goes to ~zero.** A review costs storage and bandwidth. Unlimited reviews
  at a flat seat price is affordable, and the competitors who generate
  server-side can't match it without eating real money.
- **The prompt becomes public.** It ships to the agent's context. Accept it; the
  moat is the hosted product, not the text.
- **Quality control moves from the prompt to the gate.** No control over the
  harness, the model, or the context state — so enforce at `tony_publish`
  instead. Reject what doesn't meet the bar and make the agent retry.

Ordering is deliberate: quality floor, then the thing that blocks selling, then
the thing that closes deals, then polish.

---

## 1 — Turn agent-native

- [ ] **`tony mcp`** — MCP server over stdio, two tools:
      `tony_start(range)` → diff + instruction document + repo root;
      `tony_publish(json)` → validate, render, upload, return URL.
- [ ] **Serve the instruction document from the server**, not the client. It's
      the versioned contract for output quality — you want to change it without
      shipping a client release. Cache it locally with an ETag.
- [ ] **`tony install`** writes MCP config for Claude Code, Codex, Cursor, Amp.
      One binary, one server, per-host config file.
- [ ] **Write the tool descriptions carefully.** "review this with tony" only
      works if the agent knows when to reach for tony instead of summarizing the
      diff itself. This is the new `--help`, and it deserves the same effort the
      system prompt got.
- [ ] **Review in a fresh subagent, not the writing session.** The agent that
      wrote the code explains what it *meant*; a clean context sees only what it
      *wrote*. Instruct this in the tool description and verify it happens.
- [ ] **Decide the fate of `tony review`** (the API-key path). Keep as the CI /
      headless entry point, or drop. Not urgent, but it's a maintenance fork.
- [ ] **Keep `--local` as the free tier.** Same renderer, one flag, near-zero
      maintenance. It's the no-account first run and the trust story.

## 2 — Validation (the quality floor)

This is what replaces owning the loop. All of it is deterministic and runs
server-side at publish.

- [ ] **Coverage validation.** Walk the hunks in the diff, check each has an
      annotation. Below threshold → reject with the specific gaps:
      `12 hunks unannotated: billing/invoices.py:84-96, … — add annotations and
      call tony_publish again.` The agent retries on its own tokens.
      Baseline to beat: 8.6% of lines unexplained.
- [ ] **Anchor and reference validation.** Line numbers resolve to real lines in
      the diff, paths exist in the change, blast-radius targets exist on disk,
      mirrored-file annotations point at real mirrors, `symbol` in a blast-radius
      entry matches an annotation.
- [ ] **Schema validation** with useful errors, not a stack trace. The error text
      is read by a model — write it as instructions, not as a diagnostic.
- [ ] **Retry budget** so a bad agent can't loop forever against the endpoint.

**Paused:** server-side fallback (tony generates with your own key after two
failed validations). Revisit only if rejection rates turn out high — the
provenance data in §3 will say.

## 3 — Record what produced each review

- [ ] **Provenance columns**: model, harness, harness version, turn count,
      coverage score, retry count, fallback used, diff size, wall time.
- [ ] **Internal dashboard** over that — which harnesses clear the bar, which
      degrade with diff size, where the fallback fires.
- [ ] **Act on it**: warn on connect from a harness/model that scores badly,
      or refuse below a floor.

## 4 — Hosted work (what blocks monetizing)

- [ ] **Fix review authorization.** `web/src/pages/api/reviews/[id].ts:38` gates
      reads on *any* logged-in account, then fetches by id with no ownership
      check — any tony user with an id can read any review. DELETE is owner-only
      (`:74`); reads aren't. This is a login wall, not access control, and it
      fails the first security review a team with a private repo runs. Fix
      before orgs land — it's a `WHERE user_id =` today and a migration later.
- [ ] **Orgs and teams.** Org accounts, membership, invites, per-review
      visibility (private / org / link). Repo-scoped permissions after that.
- [ ] **Billing.** Stripe, plans, seats, upgrade at the point of wanting — the
      moment someone has a review and nothing to send.
- [ ] **Free/paid boundary.** Free = local render, on disk, no account. Paid =
      the URL, persistence, teammates, history, access control.
- [ ] **Per-plan rate limits.** The existing 60/hour is one global number.
- [ ] **Retention and deletion.** Payloads contain source code. Delete-my-data,
      retention window, and a privacy policy that says what's stored and who can
      read it — including that the server can open reviews.
- [ ] **A security page.** Teams with private repos will ask before they buy.
      Sealed-at-rest, TLS, access model, retention, subprocessors.
- [ ] **Migration** for reviews published before ACLs exist.

## 5 — Let readers mark annotations wrong

- [ ] **Flag control on each annotation** in the review page → stored against the
      review, the annotation, and the provenance row.
- [ ] **Use it as the correctness signal.** Coverage measures completeness; only
      this measures whether the content is *true*. It's the one failure
      validation can't catch, and it's the metric that tells you whether
      tabs 2 and 3 — the differentiated half — are trustworthy.
- [ ] **Feed it back into §3** — flag rate per model is the number that decides
      which harnesses you support.

## 6 — Carried over from nextSteps.md, re-scoped by the pivot

- [ ] **Large-diff chunking is now a correctness requirement, not a cost one.**
      The 40k-line extrapolation (~970K tokens, ~50 turns) used to be your bill;
      under agent-native it's the user's context window, and it will compact or
      fail mid-review. `splitDiffByFile` already gives the seam.
- [ ] **Annotation density collapse on large diffs** is now load-bearing —
      coverage validation will reject exactly those reviews. Fixing the
      concision-vs-coverage fight in the instructions is a §2 dependency.
- [ ] **Filter generated files in `getDiff`.** Lockfiles, `dist/`, minified
      assets. Pure savings, no quality risk, now saves the user's context.
- [ ] **Renderer work is unchanged** — pagination, role-based file grouping,
      mirror ordering. Still yours, still client-side, unaffected by the pivot.

## 7 — Positioning and docs

- [ ] **Rewrite README and the site for agent-native.** Current copy is
      CLI-first and leads with the API key.
- [ ] **Pricing page.** $100/seat is at the high end for dev tooling — the
      pitch has to be depth (blast radius, runtime walkthroughs, full coverage)
      against a free bundled PR summary, not "we also explain the diff".
- [ ] **Find the gate.** The structural weakness: tony is optional reading, so
      nothing breaks when someone cancels. Candidates — required review artifact
      on PRs touching flagged paths, an acknowledgement trail of who read a
      change, assigned onboarding reviews. This is the retention problem and
      it's worth more than any feature on this list.
