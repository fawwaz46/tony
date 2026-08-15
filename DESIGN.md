# tony — design system

The spec for tony's review page. `src/tony/render.py` is the current implementation; this file
is the contract, and the reference for rebuilding the page in TypeScript for the web app.

Values here are transcribed from the shipping CSS, not idealised. If the two disagree, the CSS
is wrong.

---

## The one rule

**The accent means `changed`. Nothing else may use it.**

Colour is information. `#c89f6d` camel marks code the diff altered, and carries no decorative,
navigational, or state meaning anywhere. Selection, focus, and hover are carried by contrast and
hairlines instead — see *State*.

This rule has already been broken once and cost a rewrite: the accent was doing duty as both
"changed" and "selected tab", which made the page unreadable as information. Do not reintroduce
it in the port.

---

## Ground truth: what the renderer decides, not the model

The page is generated from one JSON block the model emits, but the model is never trusted with
anything the diff can answer. Preserve this split in any rebuild.

| Decided by the diff (deterministic) | Supplied by the model |
|---|---|
| Line numbers and spans (`changedRuns` / `spanFor`) | Prose: intent, annotations, why |
| The `added` / `changed` / `removed` tag (`kindFor`) | Which lines matter, and their order |
| The code shown, read from disk at the reviewed revision | Step sequence and state tables |
| File order, statuses, +/− counts (`splitDiffByFile`) | Which files are impacted, and how |

The model can name a line range. It can never supply the contents of one.

---

## Palette

Dark by design, not by preference — Behold's ground is `#000` and the page commits to it. There
is no light mode and no `prefers-color-scheme` branch. Paint every colour explicitly.

### Surfaces — the whole ramp lives inside 24 points of lightness

| Token | Value | Role |
|---|---|---|
| `--ground` | `#000000` | Page. Behold black, non-negotiable. |
| `--s1` | `#0a0a0a` | Hunk bodies, code windows, state panels |
| `--s2` | `#111110` | Hunk headers, code-window headers |
| `--s3` | `#171614` | Hover, highlighted lines, impact hits |

Surfaces warm very slightly as they lift, to sit with the warm grey and the camel.

### Hairlines — depth is a surface step plus a rule step, never a shadow

| Token | Value | Role |
|---|---|---|
| `--rule` | `#1e1d1b` | Standard 1px divider. The default. |
| `--rule-2` | `#2b2825` | Emphasised: buttons, badges, quiet borders |
| `--rule-3` | `#3a3631` | Strong: focus rings, active markers |

**No `box-shadow` anywhere.** No card borders where a hairline will do.

### Text — four tiers, not two

| Token | Value | Role |
|---|---|---|
| `--ink` | `#ffffff` | Headlines, file paths, the current step's prose |
| `--ink-2` | `#c9c5bf` | Body text, annotation prose, diff lines |
| `--ink-3` | `#8f8b86` | Behold warm grey. Labels, secondary meta. |
| `--ink-4` | `#5f5b55` | Gutters, markers, counts, disabled |

Opacity is not a substitute for a tier. Pick the tier.

### Semantic

| Token | Value | Role |
|---|---|---|
| `--accent` / `--accent-line` / `--accent-bg` | `#c89f6d` / `#5c4a30` / `#14100a` | **changed** — annotations, phase tags, changed state values |
| `--pos` / `--pos-bg` | `#7fb069` / `#0b1209` | Added lines |
| `--neg` / `--neg-bg` | `#ff8081` / `#170b0c` | Removed lines, risks, `breaks` |
| `--info` / `--info-bg` / `--info-line` | `#8fb3cc` / `#0c141c` / `#1e3445` | `behavior-change` in blast radius |

Camel was chosen against acid yellow because it does not compete with the green and red a diff
needs, and pushed toward tan because a true brown goes muddy on `#000` at 11px. It sits next to
`--neg` in state tables; the hue and saturation gap is what keeps them apart.

---

## Type

**ABC Favorit** and **ABC Favorit Mono** (Dinamo). Brand, not preference. Five faces ship as
woff2 and are base64'd into the page so it is one self-contained file offline.

```
--sans: 'Favorit', system-ui, -apple-system, sans-serif
--mono: 'Favorit Mono', ui-monospace, SFMono-Regular, Menlo, monospace
```

Weights: 400 regular, **500 Book — the emphasis weight**, 700 bold. Reach for 500 before 700;
Book is the step that says "important" without shouting.

`font-variant-numeric: tabular-nums` globally. Every number on this page sits in a column.

### Scale

| Role | Size | Weight | Tracking | Notes |
|---|---|---|---|---|
| Masthead `h1` | `clamp(1.25rem, 2.3vw, 1.65rem)` | 700 | `-.042em`, word `-.09em` | lh 1.2, max 52ch |
| Walkthrough title | `1.35rem` | 700 | `-.038em`, word `-.07em` | |
| Step prose (`.say`) | `1.05rem` | 400 | `-.008em` | lh 1.5, max 60ch |
| Body | `15px` | 400 | 0 | lh 1.55 |
| Annotation prose | `.85rem` | 400 | 0 | lh 1.55, max 64ch |
| Diff / code line | `.75rem` mono | 400 | 0 | lh 1.5 |
| Section eyebrow, tabs | `.68rem` mono | 500 | **`+.16em`** | uppercase, bracketed |
| Caption, chips | `.62rem` mono | 500 | `+.16em` | uppercase |
| Brand mark | `.72rem` mono | 500 | `+.22em` | uppercase |

**Tracking runs opposite by size**: negative on display type, positive on small uppercase mono.
A tight headline and a loose eyebrow are the same decision.

Measure caps: 52ch headline, 64ch annotation, 60ch step prose. Never let prose run the full
76rem.

---

## Layout

- Page max width `76rem`, body padding `0 2rem 6rem`.
- **Radius is `0`.** The shipping CSS contains zero `border-radius` declarations. Corners are
  tight, never friendly.
- Masthead `2.75rem` top padding, hairline under, `1.5rem` to the tabs.
- File rows are hairline-separated, `.6rem` vertical padding — dense, scannable.
- Annotations indent to `4.4rem` so their text aligns with the code, past the gutter.
- Gutter `3.4rem`, right-aligned, `--ink-4`.

---

## Studio markers

The devices that keep this from looking like every other diff viewer. They belong in the dense
areas, not only the chrome.

- **`[01]` indices** on file rows, blast-radius rows, and walkthrough step dots. Zero-padded,
  mono, `--ink-4`. Never a bare dot.
- **Bracketed uppercase eyebrows** for every section header: `[ FILE CHANGES ]`,
  `[ WALKTHROUGH 01 / 02 ]`, `[ STATE ]`. Brackets are `--rule-3` on tabs, drawn with
  `::before`/`::after`.
- **Hairlines instead of boxes** wherever the box is not load-bearing.
- **Tabular numerals** everywhere numbers align.

---

## State — contrast and hairlines, never the accent

| State | Treatment |
|---|---|
| Selected tab | `--ink` text + 1px `--ink` bottom border |
| Selected step dot | Inverted: `--ink` background, `--ground` text |
| Hover (row) | Lift to `--s1` |
| Hover (control) | Border to `--rule-3`, text to `--ink` |
| Focus | `1px solid --rule-3`, offset 2px |
| Disabled | `--rule-3` text, `--rule` border |
| Highlighted code line | `--s3` background + `inset 2px 0 0 --rule-3` |

The inset bar rather than a background wash is what lets a highlighted line stay readable.

---

## Components

**File row** — `[01]` · status (3 letters, semantic colour) · path (`--ink`) · annotation count
badge · `+n −n` with zero counts dropped to `--ink-4`. Open rows get a hairline under the
summary.

**Annotation** — sits inline above the lines it explains, accent-tinted with accent hairlines
top and bottom, sticky to the left edge so it survives horizontal scroll. Title is an uppercase
mono eyebrow in accent; the kind tag and line range follow in `--ink-4`. Multi-pane
(Prev / New / Changes) only when the model supplied more than one pane; a plain insertion gets
flat prose and no tabs.

**Code window** (walkthroughs) — header naming the file on `--s2`, body on `--s1`, requested
lines highlighted, two lines of padding either side, read from disk.

**State table** — `[ STATE ]` eyebrow, key on its own line in `--ink-4`, `before → after` with
the before struck through in `--ink-4` and the after in accent. Three entries maximum.

**Blast radius** — whole impacted files, worst-first (`breaks` → `behavior-change` →
`compatible`). The worst file opens by default and its own scroll box is framed to the affected
line; the page itself never scrolls.

---

## Do / Don't

**Do**
- Let the diff decide anything the diff can decide.
- Use Book (500) for emphasis before reaching for Bold.
- Separate sections by lifting a surface, not by adding a gap. The dark canvas is the whitespace.
- Give every border, surface, and disabled state its own deliberate token step.

**Don't**
- Use the accent for anything except *changed*.
- Add a `border-radius`, anywhere.
- Add a `box-shadow` — depth is surface plus hairline.
- Use opacity where a text tier exists.
- Let prose run wider than its measure cap.
- Ship a light mode. This design is dark or it is nothing.

---

## Inheritance

Behold (`website/src/styles/global.css`) supplies the typeface, `#000`, `#0a0a0a`, `#8f8b86`,
and `#ff8081`. Linear supplies the mechanics: the surface + hairline depth ladder, four text
tiers, state-by-contrast, and opposite-signed tracking by size. Linear's radius scale, its
"never use true black" rule, and its accent policy are deliberately rejected — see the UI
direction section of `nextSteps.md` for why.
