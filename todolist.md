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

- [x] **`tony mcp`** — MCP server over stdio, two tools:
      `tony_start(range)` → diff + instruction document + repo root;
      `tony_publish(json)` → validate, render, upload, return URL.
- [x] **Serve the instruction document from the server**, not the client. It's
      the versioned contract for output quality — you want to change it without
      shipping a client release. Cache it locally with an ETag.
- [x] **`tony connect`** writes MCP config for Claude Code, Codex, Cursor, Amp.
      One binary, one server, per-host config file.
- [x] **Write the tool descriptions carefully.** "review this with tony" only
      works if the agent knows when to reach for tony instead of summarizing the
      diff itself. This is the new `--help`, and it deserves the same effort the
      system prompt got.
- [x] **Review in a fresh subagent, not the writing session.** Instructed in
      START_DESCRIPTION; whether it actually happens is still unverified —
      §3's provenance is what will say. The agent that
      wrote the code explains what it *meant*; a clean context sees only what it
      *wrote*.
- [x] **Dropped `tony review`** (the API-key path) outright, 2026-09-05. The
      whole loop, the SYSTEM prompt, the four model tools, and the `anthropic`
      and `python-dotenv` dependencies are gone. `tony` is now a dispatcher:
      connect, login, mcp, update, uninstall.
- [x] **`--local` is gone with it.** The local renderer (`page.py`, `fonts.py`,
      the bundled `viewer.js`/`viewer.css`) had no other caller, so it went too.
      There is no free tier and no no-account first run today: `tony_start`
      refuses without a login. If the free tier comes back it is a render step
      inside `tony_publish`, not a second brain — `git show b1064e5:src/tony_cli/page.py`
      is the starting point.

## 2 — Validation (the quality floor)

This is what replaces owning the loop. All of it is deterministic and runs at
publish — but in the local MCP server, not on the site. `POST /api/reviews`
still accepts any payload that parses, so the gate is enforced against a lazy
model, which is the actual adversary, and not against a determined user. Moving
it behind the API is a real piece of work (the validator needs the diff, and the
diff never leaves the machine today) and is not scheduled.

- [x] **Coverage validation.** Walk the hunks in the diff, check each has an
      annotation. Below threshold → reject with the specific gaps:
      `12 hunks unannotated: billing/invoices.py:84-96, … — add annotations and
      call tony_publish again.` The agent retries on its own tokens.
      Baseline to beat: 8.6% of lines unexplained. Done — `coverageGaps`, in
      lines rather than runs, three attempts and then it publishes what it has
      with the gaps marked on the page.
- [x] **Anchor and reference validation** (2026-09-05, `anchors.py`). Anchors
      resolve the way the page resolves them, annotation and skip paths are
      files in the diff, impact paths are real files outside it, walkthrough
      ranges fit inside the file they name, mirror notes point at a copy that
      is really in the change. Not checked: `symbol` against the annotation
      text — the deterministic half of that is `fromPath`, which is checked.
- [x] **Schema validation** with useful errors, not a stack trace. The error text
      is read by a model — write it as instructions, not as a diagnostic.
- [x] **Retry budget** so a bad agent can't loop forever against the endpoint.
      Three attempts on coverage; the shape and anchor checks are unlimited
      because they are cheap and deterministic.

**Paused:** server-side fallback (tony generates with your own key after two
failed validations). Revisit only if rejection rates turn out high — the
provenance data in §3 will say.

## 3 — Record what produced each review

- [x] **Provenance columns** (2026-09-05): harness and harness version from the
      MCP client identity, model self-reported by the agent, instruction
      document version, retries, wall time, diff lines and files, changed and
      unexplained lines. Turn count and token spend are NOT recorded — they
      happen inside the caller's context and nothing here can see them. There
      is no fallback to record.
- [x] **Internal dashboard** (2026-09-06, `/admin`) — by harness, by model, by
      diff size, by instruction document version, plus the last thirty reviews.
      Gated on `users.is_admin`, which nothing in the product sets: turn it on
      with `UPDATE users SET is_admin = true WHERE login = '...'`. A visitor
      who is not an admin gets a 404, because a refusal is an advertisement.
- [ ] **Act on it**: warn on connect from a harness/model that scores badly,
      or refuse below a floor.

## 4 — Hosted work

- [x] **Review authorization** (2026-09-06, `7a51a1f`) — settled the other
      way: the link is the capability. Any signed-in account with the id can
      read, ids are ~79 bits, and reads are throttled at 240/account/hour so the
      route is not an enumeration oracle. DELETE is owner-only. Per-review
      visibility comes back only with orgs, which are parked.
- [x] **Retention and deletion** (2026-10-04, `web/src/server/retention.ts`).
      Reviews expire 30 days after publishing: refused at read past the
      window, and swept (blob, then row) 25 at a time after each upload — no
      cron. Self-serve account deletion on `/reviews` (`DELETE /api/account`,
      browser session only) removes every blob and cascades the rest. `/privacy`
      says both.
- [ ] **A security page.** Teams with private repos will ask before they buy.
      Sealed-at-rest, TLS, access model, retention, subprocessors.

## 6 — Carried over from nextSteps.md, re-scoped by the pivot

- [x] **Large-diff chunking** (2026-10-04). Past `PART_CHARS` (150k chars of
      agent diff, ~40k tokens) `tony_start` splits by file and returns a
      dispatch message instead of the diff; one fresh subagent per part calls
      `tony_start`/`tony_publish` with `sessionId` + `part`, each part is
      validated and coverage-gated on its own files, and a final
      `tony_publish` with only `intent` merges and publishes one page. Assumes
      subagents share the parent's `tony mcp` process. Not yet run against a
      real large diff in a real harness.
- [x] **Annotation density on large diffs.** The instructions now say coverage
      beats concision outright, the gate enforces it, and chunking keeps each
      reviewer's slice small enough that the two stop fighting.
- [x] **Filter generated files** (`2d615ac`). `withoutGeneratedBodies` strips
      lockfiles, build dirs and minified assets from what the agent reads;
      the page still lists them with real line counts.
- [ ] **Renderer work is unchanged** — pagination, role-based file grouping,
      mirror ordering. Still yours, still client-side, unaffected by the pivot.

## 7 — Positioning and docs

- [x] **README, install.sh, and the homepage no longer mention an API key**
      (2026-09-05), and the homepage flow is the agent-native one: install,
      `tony connect && tony login`, then "review this branch with tony" typed
      at the agent. Nothing on the site still describes a CLI that reviews.
- [ ] **Find the gate.** The structural weakness: tony is optional reading, so
      nothing breaks when someone cancels. Candidates — required review artifact
      on PRs touching flagged paths, an acknowledgement trail of who read a
      change, assigned onboarding reviews. This is the retention problem and
      it's worth more than any feature on this list.

---

## Parked — pricing, orgs, reader flags (scrapped for the MVP, 2026-10-04)

Not being worked on. Kept so the thinking isn't re-derived if it comes back.

- **Billing.** Stripe, plans, seats, upgrade at the point of wanting — the
  moment someone has a review and nothing to send.
- **Free/paid boundary.** There is no free tier right now — publishing needs
  an account and there is nothing else to do. Either bring back a local
  render inside `tony_publish`, or make free a metered number of hosted
  reviews. Paid = persistence, teammates, history, access control.
- **Per-plan rate limits.** The existing 60/hour is one global number.
- **Pricing page.** $100/seat is at the high end for dev tooling — the
  pitch has to be depth (blast radius, runtime walkthroughs, full coverage)
  against a free bundled PR summary, not "we also explain the diff".
- **Orgs and teams.** Org accounts, membership, invites, per-review
  visibility (private / org / link). Repo-scoped permissions after that.
- **Migration** for reviews published before ACLs exist — only needed once orgs do.
- **Let readers mark annotations wrong.** A flag on each annotation, stored
  against the review and its provenance row — the only signal for whether an
  annotation is *true* rather than merely present. Flag rate per model would
  decide which harnesses to support.
