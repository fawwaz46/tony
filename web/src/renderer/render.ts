/**
 * The one renderer.
 *
 * Takes a payload (built by src/tony_cli/payload.py) and renders the whole
 * review page into a root element. The local self-contained page and the
 * hosted /r/<id> page both call `renderReview` — there is no second
 * implementation to drift.
 *
 * Nothing here decides layout facts. Line numbers, spans, and the
 * added/changed/removed tag arrive resolved in the payload — see DESIGN.md,
 * "Ground truth". If you find yourself re-deriving a line number here, the
 * fix belongs in the payload, not in this file.
 */

export type Span = [start: number, end: number, hadDeletion: boolean];
export type Row = { k: "row"; cls: "a" | "d" | "c" | "h"; g: number | null; text: string };
export type NoteRef = { k: "note" | "risk" | "skip"; n: number; span: Span | null; tag: string };
export type Gap = { k: "gap"; span: Span; tag: string };
export type Block = Row | NoteRef | Gap;

export type Window = {
  start: number;
  lines: string[];
  truncated: boolean;
  total: number;
  hot?: [number, number];
} | null;

export interface Payload {
  v: number;
  repo: string;
  range: string;
  createdAt: string;
  intent: string;
  files: any[];
  annotations: any[];
  risks: any[];
  skips?: any[];
  impacts: any[];
  coverage?: { changedLines: number; unexplainedLines: number };
  impactWindows: Record<string, Window>;
  walkthroughs: any[];
}

const KIND_LABEL: Record<string, string> = {
  breaks: "Breaks",
  "behavior-change": "Behaves differently",
  compatible: "Compatible",
};
const KIND_ORDER: Record<string, number> = { breaks: 0, "behavior-change": 1, compatible: 2 };
const PHASE_LABEL: Record<string, string> = {
  new: "new",
  changed: "changed",
  removed: "no longer happens",
  same: "",
};

/**
 * Everything interpolated into markup goes through one of these two.
 *
 * A payload is not trustworthy input. Any account can upload one and send the
 * link to someone else, so a field that skips escaping is stored XSS running
 * in the reader's session. `esc` for anything textual, `num` for anything the
 * payload claims is a number — a "line number" arriving as a string is exactly
 * the case that bit us.
 */
const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const num = (v: unknown, fallback = 0): number => {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
};

/** A class name from the payload, reduced to characters that cannot escape an attribute. */
const cls = (v: unknown) => String(v ?? "").replace(/[^a-zA-Z0-9_-]/g, "");

const fileId = (path: string) => path.replace(/[^A-Za-z0-9]/g, "_");
const pad2 = (n: number) => String(n).padStart(2, "0");

function lineLabel(span: Span | null): string {
  if (!span) return "";
  const start = num(span[0]);
  const end = num(span[1]);
  const label = start === end ? `line ${start}` : `lines ${start}–${end}`;
  return `<span class="ln">${label}</span>`;
}

// ---- annotations ----------------------------------------------------------

const PANES = [
  ["prev", "Prev"],
  ["now", "New"],
  ["impact", "Changes"],
] as const;

let seq = 0;

function renderGap(span: Span): string {
  return `<div class="gap"><span class="gl">${lineLabel(span)}</span><span class="gt">not explained</span></div>`;
}

/**
 * A block the review declined to explain, and why.
 *
 * Rendered where the code is, not hidden, because its whole job is to let the
 * reader tell a block that was considered and dismissed from one that was
 * missed. A gap says "nobody explained this"; a skip says "here is why nobody
 * needed to", and the reader is owed the difference.
 */
function renderSkip(item: any, span: Span | null): string {
  return (
    `<div class="ann skip"><p class="t">Not explained${lineLabel(span)}</p>` +
    `<p class="n">${esc(item.why || "")}</p></div>`
  );
}

function renderNote(item: any, kind: "note" | "risk", span: Span | null, tag: string): string {
  if (kind === "risk") {
    return `<div class="ann risk"><p class="t">Potential risk${lineLabel(span)}</p><p class="n">${esc(item.text)}</p></div>`;
  }
  const title = esc(item.title || "Note");
  const panes = PANES.filter(([key]) => item[key]).map(([key, label]) => ({ key, label, text: item[key] }));

  // A plain addition has nothing to compare against — no tabs, just the text.
  if (panes.length <= 1) {
    const body = panes[0]?.text ?? item.note ?? "";
    return `<div class="ann"><p class="t">${title}${lineLabel(span)}</p><p class="n">${esc(body)}</p></div>`;
  }

  const g = ++seq;
  const tabs = panes
    .map(
      (p, i) =>
        `<button class="pt" data-g="${g}" data-p="${p.key}" aria-selected="${i === 0}">${p.label}</button>`,
    )
    .join("");
  const bodies = panes
    .map(
      (p, i) =>
        `<p class="n pane" data-g="${g}" data-p="${p.key}"${i === 0 ? "" : " hidden"}>${esc(p.text)}</p>`,
    )
    .join("");
  return (
    `<div class="ann"><p class="t">${title}<span class="k">${esc(tag.toUpperCase())}</span>${lineLabel(span)}</p>` +
    `<div class="tabs">${tabs}</div>${bodies}</div>`
  );
}

// ---- file changes ---------------------------------------------------------

function renderFiles(files: any[], annotations: any[], risks: any[], skips: any[]): string {
  return files
    .map((f, idx) => {
      const i = idx + 1;
      const blocks: Block[] = f.blocks ?? [];
      const noteCount = blocks.filter((b) => b.k === "note" || b.k === "risk").length;
      const gapCount = blocks.filter((b) => b.k === "gap").length;
      // A note index out of range would otherwise render "undefined".
      const safeNote = (i: number, source: any[]) => source[i] ?? {};
      let inner: string;
      if (f.binary) {
        inner = '<p class="bin">Binary file, not shown.</p>';
      } else if (blocks.length === 0) {
        inner = '<p class="bin">No textual changes.</p>';
      } else {
        const rows = blocks
          .map((b) =>
            b.k === "row"
              ? `<div class="l ${cls(b.cls)}"><span class="g">${b.g == null ? "" : num(b.g)}</span>${esc(b.text) || "&nbsp;"}</div>`
              : b.k === "gap"
              ? renderGap(b.span)
              : b.k === "skip"
              ? renderSkip(safeNote(num(b.n), skips), b.span)
              : renderNote(
                  safeNote(num(b.n), b.k === "risk" ? risks : annotations),
                  b.k === "risk" ? "risk" : "note",
                  b.span,
                  String(b.tag ?? ""),
                ),
          )
          .join("");
        inner = `<div class="hunk">${rows}</div>`;
      }
      const renamed = f.oldPath ? `<span class="from">from ${esc(f.oldPath)}</span>` : "";
      const badge = noteCount > 0 ? `<span class="nb">${noteCount}</span>` : "";
      const gapBadge = num(f.unexplainedLines) > 0
        ? `<span class="gb">${num(f.unexplainedLines)} lines unexplained</span>` : "";
      // One file is on screen at a time, so this is a section that is shown or
      // hidden — not a <details> to expand. A disclosure triangle here would
      // promise a collapse that the tree already does better, and forty stacked
      // summaries is the scrolling this replaced.
      return `
<section class="file" id="file-${fileId(f.path)}"${idx === 0 ? "" : " hidden"}>
  <div class="fhead">
    <span class="ix">[${pad2(i)}]</span>
    <span class="st ${esc(f.status)}">${esc(String(f.status).slice(0, 3))}</span>
    <span class="fp">${esc(f.path)}</span>${renamed}
    ${badge}${gapBadge}
    <span class="cnt"><b class="${num(f.additions) ? "pos" : "z"}">+${num(f.additions)}</b> <b class="${num(f.deletions) ? "neg" : "z"}">&minus;${num(f.deletions)}</b></span>
  </div>
  ${inner}
</section>`;
    })
    .join("");
}

// ---- file tree ------------------------------------------------------------

/* A long review is a very long page. The tree is how you find one file in it
   without scrolling past forty others: only what the diff touched, folders
   nested, click to jump. Nothing here is a second source of truth — every row
   points at a <details> that renderFiles already wrote. */

type TreeNode = {
  name: string;
  dir: boolean;
  children: TreeNode[];
  file?: any;
  index?: number;
};

const STATUS_MARK: Record<string, string> = {
  added: "+",
  deleted: "\u2212",
  renamed: "\u2192",
};

export function buildTree(files: any[]): TreeNode[] {
  const root: TreeNode = { name: "", dir: true, children: [] };

  files.forEach((f, idx) => {
    // A path is untrusted text: "" and "a//b" both produce empty segments that
    // would otherwise become nameless folders.
    const parts = String(f?.path ?? "").split("/").filter(Boolean);
    if (parts.length === 0) return;
    let at = root;
    parts.slice(0, -1).forEach((segment) => {
      let next = at.children.find((c) => c.dir && c.name === segment);
      if (!next) {
        next = { name: segment, dir: true, children: [] };
        at.children.push(next);
      }
      at = next;
    });
    at.children.push({
      name: parts[parts.length - 1],
      dir: false,
      children: [],
      file: f,
      index: idx + 1,
    });
  });

  // A folder that only ever contains one folder is a corridor, not a choice.
  // Collapsing the chain into "src/renderer" is what keeps a deep monorepo
  // path from costing five rows of indentation to walk.
  const collapse = (node: TreeNode): TreeNode => {
    node.children = node.children.map(collapse);
    while (node.dir && node.children.length === 1 && node.children[0].dir) {
      const only = node.children[0];
      node.name = `${node.name}/${only.name}`;
      node.children = only.children;
    }
    return node;
  };

  const sort = (nodes: TreeNode[]): TreeNode[] => {
    nodes.forEach((n) => sort(n.children));
    // Folders first, then files: the shape people expect from a file browser,
    // and it keeps the corridors at the top where they read as structure.
    nodes.sort((a, b) =>
      a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1,
    );
    return nodes;
  };

  // The root is not a row, so it is never collapsed into — doing so would fold
  // a whole top-level folder away and leave its files looking unparented.
  return sort(root.children.map(collapse));
}

function renderTreeNodes(nodes: TreeNode[]): string {
  return nodes
    .map((node) => {
      if (node.dir) {
        return `
<li class="td">
  <button class="tdh" type="button" aria-expanded="true">
    <span class="tw" aria-hidden="true"></span><span class="tnm">${esc(node.name)}</span>
  </button>
  <ul class="tsub">${renderTreeNodes(node.children)}</ul>
</li>`;
      }
      const f = node.file ?? {};
      const status = String(f.status ?? "");
      const mark = STATUS_MARK[status] ?? "\u00b1";
      // The full path drives filtering, so typing "src/renderer" finds a file
      // whose own name never contains it.
      const search = esc(String(f.path ?? "").toLowerCase());
      return `
<li class="tfl" data-search="${search}">
  <button class="tfb" type="button" data-target="file-${fileId(String(f.path ?? ""))}"${node.index === 1 ? " aria-current" : ""}>
    <span class="ti ${cls(status)}" aria-hidden="true">${mark}</span>
    <span class="tnm">${esc(node.name)}</span>
    ${num(f.unexplainedLines) ? `<span class="tg" title="${num(f.unexplainedLines)} lines unexplained">\u25cf</span>` : ""}
    <span class="tct"><b class="${num(f.additions) ? "pos" : "z"}">+${num(f.additions)}</b> <b class="${num(f.deletions) ? "neg" : "z"}">&minus;${num(f.deletions)}</b></span>
  </button>
</li>`;
    })
    .join("");
}

function renderTree(files: any[]): string {
  const nodes = buildTree(files);
  if (nodes.length === 0) return "";
  return `
<aside class="tree" aria-label="Changed files">
  <div class="tfil">
    <input type="search" id="treeFilter" placeholder="Filter files\u2026" aria-label="Filter files" autocomplete="off">
  </div>
  <ul class="tn">${renderTreeNodes(nodes)}</ul>
  <p class="tnone" hidden>No files match.</p>
</aside>`;
}

// ---- blast radius ---------------------------------------------------------

function renderImpactNote(imp: any): string {
  const kind = imp.kind ?? "behavior-change";
  let origin = "";
  if (imp.symbol) {
    origin = `<span class="via">via <code>${esc(imp.symbol)}</code>${imp.fromPath ? ` in ${esc(imp.fromPath)}` : ""}</span>`;
  }
  return (
    `<div class="ann imp ${esc(kind)}"><p class="t">${esc(KIND_LABEL[kind] ?? kind)}${origin}</p>` +
    `<p class="n">${esc(imp.why)}</p></div>`
  );
}

function renderImpacts(impacts: any[], windows: Record<string, Window>): string {
  const byPath = new Map<string, any[]>();
  for (const imp of impacts) {
    if (!imp.path) continue;
    if (!byPath.has(imp.path)) byPath.set(imp.path, []);
    byPath.get(imp.path)!.push(imp);
  }
  const worstOf = (group: any[]) => Math.min(...group.map((i) => KIND_ORDER[i.kind] ?? 1));

  // Worst first: a reader who opens one file should open the one that breaks.
  const ordered = [...byPath.entries()].sort((a, b) => worstOf(a[1]) - worstOf(b[1]));

  return ordered
    .map(([path, group], idx) => {
      const i = idx + 1;
      const worst = Object.keys(KIND_ORDER).find((k) => KIND_ORDER[k] === worstOf(group))!;
      const win = windows[path] ?? null;
      const at = new Map<number, any[]>();
      for (const imp of group) {
        const line = num(imp.line, 1);
        if (!at.has(line)) at.set(line, []);
        at.get(line)!.push(imp);
      }
      const sites = group
        .slice()
        .sort((a, b) => (a.line ?? 1) - (b.line ?? 1))
        .map(
          (imp) =>
            `<a class="jump ${cls(imp.kind)}" href="#imp-${fileId(path)}-${num(imp.line, 1)}">line ${num(imp.line, 1)}</a>`,
        )
        .join(" ");

      let body: string;
      if (!win) {
        body = '<p class="bin">Source not available for this file.</p>';
      } else {
        const start = num(win.start, 1);
        const before = Math.max(0, start - 1);
        const lastShown = start + win.lines.length - 1;
        const after = Math.max(0, num(win.total) - lastShown);
        const parts: string[] = [];
        if (before > 0)
          parts.push(
            `<div class="l c elide"><span class="g"></span>… ${before} earlier line${before === 1 ? "" : "s"}</div>`,
          );
        win.lines.forEach((text, n) => {
          const lineNo = start + n;
          for (const imp of at.get(lineNo) ?? []) parts.push(renderImpactNote(imp));
          const hit = at.has(lineNo) ? " hit" : "";
          parts.push(
            `<div class="l c${hit}" id="imp-${fileId(path)}-${lineNo}"><span class="g">${lineNo}</span>${esc(text) || "&nbsp;"}</div>`,
          );
        });
        if (after > 0)
          parts.push(
            `<div class="l c elide"><span class="g"></span>… ${after} later line${after === 1 ? "" : "s"}</div>`,
          );
        body = parts.join("");
      }

      return `
<details class="file impacted ${worst}" id="impact-${fileId(path)}"${i === 1 ? " open" : ""}>
  <summary>
    <span class="ix">[${pad2(i)}]</span>
    <span class="st ${worst}">${esc(KIND_LABEL[worst] ?? worst)}</span>
    <span class="fp">${esc(path)}</span>
    <span class="nb">${group.length}</span>
    <span class="cnt">not edited</span>
  </summary>
  <div class="jumps">${group.length} impact site${group.length === 1 ? "" : "s"}: ${sites}</div>
  <div class="hunk full">${body}</div>
</details>`;
    })
    .join("");
}

/** Whether the reader has asked for less motion. Every animation checks this. */
function calm(): boolean {
  return globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
}

// ---- walkthroughs ---------------------------------------------------------

function renderCodeWindow(st: any): string {
  const win: Window = st.window ?? null;
  if (!win) return '<div class="cw none">happens outside the codebase</div>';
  const hotStart = num(win.hot?.[0], 0);
  const hotEnd = num(win.hot?.[1], -1);
  const rows = win.lines
    .map((text, n) => {
      const lineNo = num(win.start, 1) + n;
      const hot = lineNo >= hotStart && lineNo <= hotEnd ? " hot" : "";
      return `<div class="l c${hot}"><span class="g">${lineNo}</span>${esc(text) || "&nbsp;"}</div>`;
    })
    .join("");
  return `<div class="cw"><div class="cwh">${esc(st.path)}</div><div class="hunk">${rows}</div></div>`;
}

function renderState(state: Record<string, unknown> | undefined): string {
  const entries = Object.entries(state ?? {}).slice(0, 3);
  if (entries.length === 0) return "";
  const rows = entries
    .map(([k, v]) => {
      const val = String(v);
      if (val.includes("->")) {
        const [was, , now] = ((): [string, string, string] => {
          const i = val.indexOf("->");
          return [val.slice(0, i), "->", val.slice(i + 2)];
        })();
        return (
          `<div class="sv"><span class="sk">${esc(k)}</span><span class="was">${esc(was.trim())}</span>` +
          `<span class="to">→</span><span class="now">${esc(now.trim())}</span></div>`
        );
      }
      return `<div class="sv"><span class="sk">${esc(k)}</span><span class="now">${esc(val)}</span></div>`;
    })
    .join("");
  return `<div class="state"><p class="cap">[ state ]</p>${rows}</div>`;
}

// A flow is drawn as a sequence: one lane per actor, an arrow from each step
// to the next. The model names the actor; the arrows are not the model's to
// draw — they follow from the order of the steps, so a diagram can never show
// a hop the trace does not take.

const REACH_LABEL: Record<string, string> = {
  new: "new flow",
  changed: "changed",
  removed: "removed flow",
  downstream: "reached, not changed",
};

/** The lane a step runs in: its actor, else its file, else outside the code. */
function actorOf(st: any): string {
  const named = typeof st.actor === "string" ? st.actor.trim() : "";
  if (named) return named;
  if (st.path) return String(st.path).split("/").pop() || String(st.path);
  return "outside";
}

/** Whether before/after are two different, complete sequences worth switching between. */
function hasTwoVersions(steps: any[]): boolean {
  const before = steps.filter((st) => (st.phase || "same") !== "new").length;
  const after = steps.filter((st) => (st.phase || "same") !== "removed").length;
  return before > 0 && after > 0 && (before !== steps.length || after !== steps.length);
}

function renderFlowIndex(walkthroughs: any[]): string {
  const rows = walkthroughs
    .map((w, idx) => {
      const steps: any[] = w.steps ?? [];
      const strip = steps
        .map((st) => `<i class="${cls(st.phase || "same")}"></i>`)
        .join("");
      const reach = REACH_LABEL[w.reach] ?? "";
      return (
        `<button class="fi" data-w="${idx}"${idx === 0 ? ' aria-current="true"' : ""}>` +
        `<span class="ix">${pad2(idx + 1)}</span>` +
        `<span class="ft">${esc(w.title || "Walkthrough")}</span>` +
        `<span class="fr ${cls(w.reach || "changed")}">${esc(reach)}</span>` +
        `<span class="strip" aria-hidden="true">${strip}</span>` +
        `<span class="fn">${steps.length} steps</span></button>`
      );
    })
    .join("");
  return (
    `<div class="flows-head"><p class="cap">[ flows · ${walkthroughs.length} ]</p>` +
    `<p class="fhint">Each flow follows one real scenario, one step at a time. ` +
    `Guess what happens before you press next.</p></div>` +
    `<div class="findex"><span class="fimark" aria-hidden="true"></span>${rows}</div>`
  );
}

function renderFlow(w: any, idx: number, total: number): string {
  const steps: any[] = w.steps ?? [];
  if (steps.length === 0) return "";

  const actors: string[] = [];
  for (const st of steps) {
    const a = actorOf(st);
    if (!actors.includes(a)) actors.push(a);
  }

  const lanes = actors
    .map((a, i) => `<div class="lane" style="grid-column:${i + 2}" title="${esc(a)}">${esc(a)}</div>`)
    .join("");

  // Arrows are positioned by script, because which step precedes which
  // depends on whether the reader is looking at the flow before or after.
  const rows = steps
    .map((st, i) => {
      const phase = st.phase || "same";
      return (
        `<button class="srow ${cls(phase)}" data-s="${i}" data-a="${actors.indexOf(actorOf(st))}" ` +
        `style="--a:${actors.indexOf(actorOf(st))};view-transition-name:f${idx}s${i}" ` +
        `aria-label="Step ${i + 1}: ${esc(st.say)}">` +
        `<span class="sn">${pad2(i + 1)}</span>` +
        `<span class="track"><span class="arrow"></span><span class="node"></span>` +
        `<span class="slab">${esc(st.say)}</span></span></button>`
      );
    })
    .join("");

  const panels = steps
    .map((st, i) => {
      const phase = st.phase || "same";
      const tag = PHASE_LABEL[phase] ? `<span class="ph ${cls(phase)}">${PHASE_LABEL[phase]}</span>` : "";
      return (
        `<div class="stepPanel" data-s="${i}">` +
        `<p class="where"><span class="sn">${pad2(i + 1)}</span><span class="in">${esc(actorOf(st))}</span>${tag}</p>` +
        `<p class="say">${esc(st.say)}</p>` +
        `<div class="split">${renderCodeWindow(st)}${renderState(st.state)}</div></div>`
      );
    })
    .join("");

  const versions = hasTwoVersions(steps)
    ? `<div class="seg" role="group" aria-label="Which version of the flow">` +
      `<button data-mode="before">Before</button>` +
      `<button data-mode="diff" aria-pressed="true">Both</button>` +
      `<button data-mode="after">After</button></div>`
    : "";

  const reach = REACH_LABEL[w.reach] ?? "";
  // Previous / next flow, in the eyebrow and again under the step panel: by
  // the time someone has stepped to the end, the top has scrolled away.
  const fnav =
    total > 1
      ? `<span class="fnav"><button class="fgo" data-to="${idx - 1}"${idx === 0 ? " disabled" : ""}>&#8249; Previous flow</button>` +
        `<button class="fgo" data-to="${idx + 1}"${idx === total - 1 ? " disabled" : ""}>Next flow &#8250;</button></span>`
      : "";
  return `
<section class="wt" data-w="${idx}"${idx === 0 ? "" : " hidden"} style="--lanes:${actors.length}">
  <header class="wth">
    <div class="wtt">
      <p class="cap">[ flow ${pad2(idx + 1)} / ${pad2(total)} ]<span class="fr ${cls(w.reach || "changed")}">${esc(reach)}</span>${fnav}</p>
      <h3>${esc(w.title || "Walkthrough")}</h3>
      <div class="wmeta">
        <p><span class="tl">Starts when</span>${esc(w.trigger)}</p>
        ${w.whatChanged ? `<p><span class="tl">What changed</span>${esc(w.whatChanged)}</p>` : ""}
      </div>
    </div>
  </header>
  <div class="wtbar">
    ${versions}
    <button class="wplay" aria-pressed="false">Play</button>
    <span class="wpos">step 1 of ${steps.length}</span>
    <button class="wprev" disabled>&#8249; Back</button>
    <button class="wnext">Next &#8250;</button>
  </div>
  <div class="seq"><div class="seqin">
    <div class="lanes">${lanes}</div>
    <div class="rows">${rows}</div>
  </div></div>
  <div class="panels">${panels}</div>
  ${fnav ? `<div class="fnavb">${fnav}</div>` : ""}
</section>`;
}

function renderWalkthroughs(walkthroughs: any[]): string {
  const flows = walkthroughs.filter((w) => (w.steps ?? []).length > 0);
  if (flows.length === 0) return "";
  return (
    (flows.length > 1 ? renderFlowIndex(flows) : "") +
    flows.map((w, i) => renderFlow(w, i, flows.length)).join("")
  );
}

/**
 * The flow player. One step at a time, with the arrow into the current step
 * drawn as it is reached, and a switch between the flow as it was and as it
 * is. Re-laying out the rows for a version goes through a view transition
 * where the browser has one, so steps that survive slide to their new place
 * and the ones that do not fade — which is the change, shown.
 */
function initFlows(root: HTMLElement): void {
  const still = calm();
  const flows = [...root.querySelectorAll<HTMLElement>(".wt")];
  const players = flows.map((wt) => {
    const rows = [...wt.querySelectorAll<HTMLElement>(".srow")];
    const panels = [...wt.querySelectorAll<HTMLElement>(".stepPanel")];
    const play = wt.querySelector<HTMLButtonElement>(".wplay")!;
    const lanes = wt.querySelectorAll(".lane").length;
    let mode = "diff";
    let at = 0;
    let timer: ReturnType<typeof setInterval> | undefined;

    const visible = () =>
      rows.filter((r) => {
        const ph = r.classList.contains("new") ? "new" : r.classList.contains("removed") ? "removed" : "";
        return !(mode === "before" && ph === "new") && !(mode === "after" && ph === "removed");
      });

    const layout = () => {
      const shown = visible();
      rows.forEach((r) => (r.hidden = !shown.includes(r)));
      // Each arrow runs from the lane of the step before it in THIS version.
      shown.forEach((r, i) => {
        const to = Number(r.dataset.a);
        const from = i === 0 ? to : Number(shown[i - 1].dataset.a);
        r.style.setProperty("--from", String(Math.min(from, to)));
        r.style.setProperty("--span", String(Math.abs(to - from)));
        r.classList.toggle("left", from > to);
        r.classList.toggle("self", from === to);
        r.classList.toggle("rt", from === to && to > (lanes - 1) / 2);
        // The lifelines the label sits between: an arrow's own two, or for a
        // step that stays put, its lane and the neighbour it hangs toward.
        // A lone lane has no neighbour and runs to the edge.
        const gap = from !== to ? Math.abs(to - from) : lanes === 1 ? 0.5 : 1;
        r.style.setProperty("--gap", String(gap));
      });
    };

    const show = (animate: boolean) => {
      const shown = visible();
      at = Math.max(0, Math.min(shown.length - 1, at));
      const cur = shown[at];
      shown.forEach((r, i) => {
        r.classList.toggle("past", i < at);
        r.classList.toggle("future", i > at);
        r.toggleAttribute("aria-current", i === at);
        if (i === at && animate && !still) {
          r.classList.remove("draw");
          void r.offsetWidth; // restart the draw animation
          r.classList.add("draw");
        }
      });
      panels.forEach((p) => p.classList.toggle("on", p.dataset.s === cur?.dataset.s));
      wt.querySelector(".wpos")!.textContent = `step ${at + 1} of ${shown.length}`;
      wt.querySelector<HTMLButtonElement>(".wprev")!.disabled = at === 0;
      wt.querySelector<HTMLButtonElement>(".wnext")!.disabled = at === shown.length - 1;
    };

    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
      play.setAttribute("aria-pressed", "false");
      play.textContent = "Play";
    };
    const go = (i: number, fromPlayer = false) => {
      if (!fromPlayer) stop();
      at = i;
      show(true);
    };

    wt.querySelector<HTMLElement>(".wprev")!.onclick = () => go(at - 1);
    wt.querySelector<HTMLElement>(".wnext")!.onclick = () => go(at + 1);
    rows.forEach((r) => (r.onclick = () => go(visible().indexOf(r))));
    play.onclick = () => {
      if (timer !== undefined) return stop();
      if (at >= visible().length - 1) at = -1;
      play.setAttribute("aria-pressed", "true");
      play.textContent = "Pause";
      go(at + 1, true);
      timer = setInterval(() => {
        if (at >= visible().length - 1) return stop();
        go(at + 1, true);
      }, 2600);
    };

    wt.querySelectorAll<HTMLButtonElement>(".seg button").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.mode === mode) return;
        stop();
        const current = visible()[at];
        const apply = () => {
          mode = b.dataset.mode!;
          wt.querySelectorAll(".seg button").forEach((x) =>
            x.setAttribute("aria-pressed", String(x === b)),
          );
          layout();
          // Stay on the same step if it exists in this version.
          const idx = visible().indexOf(current);
          at = idx >= 0 ? idx : Math.min(at, visible().length - 1);
          show(false);
        };
        const doc = document as any;
        if (!still && typeof doc.startViewTransition === "function") doc.startViewTransition(apply);
        else apply();
      };
    });

    layout();
    show(false);
    return { wt, go: (d: number) => go(at + d), stop };
  });

  // One flow on screen at a time, chosen from the index or stepped to from
  // the flow itself — the index has usually scrolled out of sight by then.
  // The index marks the selected flow with one bar that slides between rows,
  // rather than one per row that blinks. Placed from the row's own box, so it
  // is re-placed whenever the index changes size: rows that wrap on a phone,
  // and the tab going from hidden (no size at all) to shown.
  const index = root.querySelector<HTMLElement>(".findex");
  const mark = root.querySelector<HTMLElement>(".fimark");
  const place = (animate: boolean) => {
    const row = root.querySelector<HTMLElement>(".fi[aria-current]");
    if (!index || !mark || !row || !index.offsetHeight) return;
    const inset = Math.min(11, row.offsetHeight / 4);
    mark.classList.toggle("slide", animate && !still);
    mark.style.transform = `translateY(${row.offsetTop + inset}px)`;
    mark.style.height = `${row.offsetHeight - inset * 2}px`;
  };
  if (index && typeof ResizeObserver === "function") {
    new ResizeObserver(() => place(false)).observe(index);
  }

  const showFlow = (w: string, scroll: boolean) => {
    const target = players.find((p) => p.wt.dataset.w === w);
    if (!target) return;
    players.forEach((p) => {
      p.stop();
      p.wt.hidden = p !== target;
    });
    root.querySelectorAll<HTMLElement>(".fi").forEach((x) =>
      x.toggleAttribute("aria-current", x.dataset.w === w),
    );
    place(true);
    if (scroll) target.wt.scrollIntoView?.({ block: "start", behavior: still ? "auto" : "smooth" });
  };
  root.querySelectorAll<HTMLElement>(".fi").forEach((b) => {
    b.onclick = () => showFlow(b.dataset.w!, false);
  });
  root.querySelectorAll<HTMLButtonElement>(".fgo").forEach((b) => {
    b.onclick = () => showFlow(b.dataset.to!, true);
  });

  document.addEventListener("keydown", (e) => {
    const pane = document.getElementById("pane-walk");
    if (!pane || pane.hidden) return;
    if ((e.target as HTMLElement)?.closest?.("input, textarea")) return;
    const p = players.find((x) => !x.wt.hidden);
    if (!p) return;
    if (e.key === "ArrowRight") p.go(1);
    if (e.key === "ArrowLeft") p.go(-1);
  });
}

// ---- the page -------------------------------------------------------------

export function renderReview(root: HTMLElement, review: Payload): void {
  const files = review.files ?? [];
  const annotations = review.annotations ?? [];
  const risks = review.risks ?? [];
  const skips = review.skips ?? [];
  const impacts = (review.impacts ?? []).filter((i: any) => i.path);
  const walkthroughs = review.walkthroughs ?? [];
  const windows = review.impactWindows ?? {};

  const reached = new Set(impacts.map((i: any) => i.path)).size;
  // num() per file, not just on the total: `0 + "<img…>"` concatenates.
  const adds = files.reduce((n: number, f: any) => n + num(f.additions), 0);
  const dels = files.reduce((n: number, f: any) => n + num(f.deletions), 0);
  const loose = risks.filter((r: any) => !r.path);
  // Surfaced next to the counts rather than buried: a review with holes in it
  // must not look like a complete one.
  const gaps = num(review.coverage?.unexplainedLines);
  const gapPct = Math.round((100 * gaps) / Math.max(num(review.coverage?.changedLines), 1));

  const looseHtml = loose.length
    ? `<section class="loose"><h2>Risks outside the diff</h2><ul>${loose
        .map((r: any) => `<li>${esc(r.text)}</li>`)
        .join("")}</ul></section>`
    : "";

  root.innerHTML = `
<div class="wrap">
<header>
  <div class="mh">
    <span class="brand">tony</span>
    <span class="rng">${esc(review.range)}</span>
    <span class="repo">${esc(review.repo)}</span>
  </div>
  <h1>${esc(review.intent || "No summary produced.")}</h1>
  <div class="meta">
    <span>${files.length} files</span>
    <span><b class="pos">+${adds}</b> <b class="neg">&minus;${dels}</b></span>
    <span>${annotations.length} annotations</span>
    <label class="toggle"><input type="checkbox" id="riskToggle"> potential risks (${risks.length})</label>
    ${gaps > 0 ? `<span class="gsum">${gaps} of ${num(review.coverage?.changedLines)} changed lines unexplained (${gapPct}%)</span>` : ""}
  </div>
</header>
${looseHtml}
<nav class="tabs-main"><span class="tabmark" aria-hidden="true"></span>
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">${files.length}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"${reached ? "" : " disabled"}>Blast radius <span class="c">${reached}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"${walkthroughs.length ? "" : " disabled"}>How it works <span class="c">${walkthroughs.length}</span></button>
</nav>
<div id="pane-files">
  <div class="flayout">
    ${renderTree(files)}
    <div class="fmain">${renderFiles(files, annotations, risks, skips)}</div>
  </div>
</div>
<div id="pane-blast" hidden>
  <div class="stepper" id="stepper">
    <button id="prevImp" aria-label="Previous impact">&#8249;</button>
    <span id="impPos">impact 1 of ${impacts.length}</span>
    <button id="nextImp" aria-label="Next impact">&#8250;</button>
    <span class="sh" id="impWhere"></span>
  </div>
  ${renderImpacts(impacts, windows)}
</div>
<div id="pane-walk" hidden>${renderWalkthroughs(walkthroughs)}</div>
</div>`;

  wire(root);
}

// ---- behaviour ------------------------------------------------------------

function wire(root: HTMLElement): void {
  const byId = (id: string) => root.querySelector<HTMLElement>(`#${id}`)!;

  // Top-level tabs. The selected one is underlined by a single mark that
  // slides between them, placed from the tab's own box and re-placed when the
  // bar changes size (a phone, or the page first laying out).
  const tabBar = root.querySelector<HTMLElement>(".tabs-main");
  const tabMark = root.querySelector<HTMLElement>(".tabmark");
  const still = calm();
  const placeTab = (animate: boolean) => {
    const tab = root.querySelector<HTMLElement>('.mt[aria-selected="true"]');
    if (!tabBar || !tabMark || !tab || !tabBar.offsetWidth) return;
    // The first tab has no left padding; the mark spans the label either way.
    tabMark.classList.toggle("slide", animate && !still);
    tabMark.style.transform = `translateX(${tab.offsetLeft}px)`;
    tabMark.style.width = `${tab.offsetWidth}px`;
  };
  placeTab(false);
  if (tabBar && typeof ResizeObserver === "function") {
    new ResizeObserver(() => placeTab(false)).observe(tabBar);
  }
  root.querySelectorAll<HTMLElement>(".mt").forEach((b) =>
    b.addEventListener("click", () => {
      const t = b.dataset.t;
      root.querySelectorAll(".mt").forEach((x) =>
        x.setAttribute("aria-selected", String((x as HTMLElement).dataset.t === t)),
      );
      placeTab(true);
      byId("pane-files").hidden = t !== "files";
      byId("pane-blast").hidden = t !== "blast";
      byId("pane-walk").hidden = t !== "walk";
    }),
  );

  // ---- file tree ----------------------------------------------------------

  const tree = root.querySelector<HTMLElement>(".tree");
  if (tree) {
    const rows = Array.from(tree.querySelectorAll<HTMLElement>(".tfb"));
    const sections = Array.from(root.querySelectorAll<HTMLElement>("#pane-files .file"));

    // The tree is sorted alphabetically; the file shown first is the diff's
    // first. Those two orders disagree constantly, so the starting position
    // comes from the row actually marked current, not from an assumed zero.
    let current = Math.max(0, rows.findIndex((r) => r.hasAttribute("aria-current")));

    // One file on screen at a time. A forty-file diff is thousands of lines of
    // page, and the tree is only navigation if the thing it navigates to is
    // the thing you end up looking at.
    const showFile = (index: number) => {
      const button = rows[index];
      if (!button) return;
      const wanted = button.dataset.target;
      sections.forEach((section) => {
        section.hidden = section.id !== wanted;
      });
      rows.forEach((r, i) => r.toggleAttribute("aria-current", i === index));
      current = index;
      // The previous file may have been scrolled deep; the next one must start
      // at its own top rather than halfway down.
      root.querySelector("#pane-files")?.scrollIntoView?.({ block: "start" });
    };

    rows.forEach((button, index) => {
      button.addEventListener("click", () => showFile(index));
    });

    // Same bracket keys the blast-radius stepper uses, so stepping through a
    // review is one idiom rather than two.
    document.addEventListener("keydown", (e) => {
      if (byId("pane-files").hidden) return;
      const target = e.target as HTMLElement | null;
      if (target && target.tagName === "INPUT") return;  // typing in the filter
      if (e.key === "]") showFile(Math.min(rows.length - 1, current + 1));
      if (e.key === "[") showFile(Math.max(0, current - 1));
    });

    // Folders collapse. The chevron is CSS on aria-expanded, so the attribute
    // is the state — there is no second flag to drift from it.
    tree.querySelectorAll<HTMLElement>(".tdh").forEach((head) => {
      head.addEventListener("click", () => {
        const open = head.getAttribute("aria-expanded") === "true";
        head.setAttribute("aria-expanded", String(!open));
        const sub = head.nextElementSibling as HTMLElement | null;
        if (sub) sub.hidden = open;
      });
    });

    const filter = tree.querySelector<HTMLInputElement>("#treeFilter");
    const empty = tree.querySelector<HTMLElement>(".tnone");
    filter?.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      let hits = 0;

      tree.querySelectorAll<HTMLElement>(".tfl").forEach((li) => {
        const match = !q || (li.dataset.search ?? "").includes(q);
        li.hidden = !match;
        if (match) hits++;
      });

      // A folder with nothing visible under it is noise; one with a hit must be
      // open, or the match it is hiding may as well not have been found.
      tree.querySelectorAll<HTMLElement>(".td").forEach((dir) => {
        const visible = dir.querySelector(".tfl:not([hidden])") !== null;
        dir.hidden = !visible;
        if (q && visible) {
          dir.querySelector(".tdh")?.setAttribute("aria-expanded", "true");
          const sub = dir.querySelector<HTMLElement>(".tsub");
          if (sub) sub.hidden = false;
        }
      });

      if (empty) empty.hidden = hits > 0;

      // Filtering is navigation too: if the file on screen is no longer in the
      // list, show the first one that is, rather than leaving the reader
      // looking at a file the tree no longer offers.
      if (hits > 0 && rows[current]?.parentElement?.hidden) {
        const first = rows.findIndex((r) => !r.parentElement?.hidden);
        if (first >= 0) showFile(first);
      }
    });
  }

  initFlows(root);

  // An impacted file opens scrolled to its first affected line — scroll the
  // file's own box, never the page.
  function frame(d: Element) {
    const box = d.querySelector<HTMLElement>(".hunk.full");
    const hit = d.querySelector<HTMLElement>(".l.hit");
    if (box && hit) box.scrollTop = Math.max(0, hit.offsetTop - box.clientHeight / 3);
  }
  root.querySelectorAll<HTMLDetailsElement>("#pane-blast details.impacted").forEach((d) => {
    if (d.open) frame(d);
    d.addEventListener("toggle", () => {
      if (d.open) frame(d);
    });
  });

  // Walk impact sites with the < > arrows.
  const SITES = [...root.querySelectorAll<HTMLElement>("#pane-blast .l.hit")];
  let at = -1;
  function goto(i: number) {
    if (!SITES.length) return;
    at = (i + SITES.length) % SITES.length;
    const el = SITES[at];
    (el.closest("details") as HTMLDetailsElement).open = true;
    SITES.forEach((s) => s.classList.remove("focus"));
    el.classList.add("focus");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    byId("impPos").textContent = `impact ${at + 1} of ${SITES.length}`;
    const f = el.closest("details")!.querySelector(".fp");
    byId("impWhere").textContent = f ? f.textContent! : "";
  }
  byId("prevImp")?.addEventListener("click", () => goto(at - 1));
  byId("nextImp")?.addEventListener("click", () => goto(at + 1));
  document.addEventListener("keydown", (e) => {
    if (byId("pane-blast").hidden) return;
    if (e.key === "]") goto(at + 1);
    if (e.key === "[") goto(at - 1);
  });

  // Prev / New / Changes panes inside one annotation.
  root.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>(".pt");
    if (!b) return;
    const g = b.dataset.g;
    const p = b.dataset.p;
    root.querySelectorAll<HTMLElement>(`.pt[data-g="${g}"]`).forEach((x) =>
      x.setAttribute("aria-selected", String(x.dataset.p === p)),
    );
    root.querySelectorAll<HTMLElement>(`.pane[data-g="${g}"]`).forEach((x) => {
      x.hidden = x.dataset.p !== p;
    });
  });

  // Risks are opt-in — this is a tool for understanding, not a review gate.
  const rt = byId("riskToggle") as HTMLInputElement;
  document.body.classList.add("risks-off");
  rt.addEventListener("change", () => document.body.classList.toggle("risks-off", !rt.checked));
}
