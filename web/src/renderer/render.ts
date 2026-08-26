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
export type NoteRef = { k: "note" | "risk"; n: number; span: Span | null; tag: string };
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

function renderFiles(files: any[], annotations: any[], risks: any[]): string {
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
        inner = '<p class="bin">Binary — not shown.</p>';
      } else if (blocks.length === 0) {
        inner = '<p class="bin">No textual changes.</p>';
      } else {
        const rows = blocks
          .map((b) =>
            b.k === "row"
              ? `<div class="l ${cls(b.cls)}"><span class="g">${b.g == null ? "" : num(b.g)}</span>${esc(b.text) || "&nbsp;"}</div>`
              : b.k === "gap"
              ? renderGap(b.span)
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

function renderWalkthroughs(walkthroughs: any[]): string {
  if (walkthroughs.length === 0) return "";
  const intro =
    '<div class="wintro"><p><b>These are traces, not diagrams.</b> Each one follows a single real ' +
    "scenario from the moment it starts, one step at a time. The code shown is read straight from " +
    "your files.</p><p>Use <b>next</b> to advance. Before you press it, say what you think happens " +
    "next — that guess is what makes the step stick.</p></div>";

  return (
    intro +
    walkthroughs
      .map((w, idx) => {
        const steps: any[] = w.steps ?? [];
        if (steps.length === 0) return "";
        const seen: string[] = [];
        for (const st of steps) if (st.path && !seen.includes(st.path)) seen.push(st.path);
        const nNew = steps.filter((st) => (st.phase || "same") !== "same").length;
        const ofN = walkthroughs.length > 1 ? ` / ${pad2(walkthroughs.length)}` : "";
        const chips =
          seen.map((p) => `<span class="chip">${esc(p.split("/").pop())}</span>`).join("") +
          (nNew > 0 ? `<span class="chip hot">${nNew} of ${steps.length} steps are new</span>` : "");
        const changed = w.whatChanged
          ? `<p class="wchg"><span class="tl">What changed</span> ${esc(w.whatChanged)}</p>`
          : "";

        const dots = steps
          .map((st, i) => {
            const phase = st.phase || "same";
            return `<button class="dot ${cls(phase)}" data-w="${idx}" data-s="${i}" aria-label="Step ${i + 1}"${i === 0 ? ' aria-current="true"' : ""}>${pad2(i + 1)}</button>`;
          })
          .join("");

        const panels = steps
          .map((st, i) => {
            const phase = st.phase || "same";
            const tag = PHASE_LABEL[phase] ? `<span class="ph ${cls(phase)}">${PHASE_LABEL[phase]}</span>` : "";
            return (
              `<div class="stepPanel${i === 0 ? " on" : ""}" data-w="${idx}" data-s="${i}">` +
              `<p class="say">${esc(st.say)}${tag}</p>` +
              `<div class="split">${renderCodeWindow(st)}${renderState(st.state)}</div></div>`
            );
          })
          .join("");

        return `
<section class="wt" data-w="${idx}" data-n="${steps.length}">
  <header class="wth">
    <p class="cap">[ walkthrough ${pad2(idx + 1)}${ofN} ]</p>
    <h3>${esc(w.title || "Walkthrough")}</h3>
    <p class="trig"><span class="tl">Starts when</span> ${esc(w.trigger)}</p>
    ${changed}
    <div class="covers">${chips}</div>
  </header>
  <div class="dots">${dots}</div>
  <div class="panels">${panels}</div>
  <div class="wtnav">
    <button class="wprev" data-w="${idx}" disabled>&#8249; back</button>
    <span class="wpos" data-w="${idx}">step 1 of ${steps.length}</span>
    <button class="wnext" data-w="${idx}">next &#8250;</button>
  </div>
</section>`;
      })
      .join("")
  );
}

// ---- the page -------------------------------------------------------------

export function renderReview(root: HTMLElement, review: Payload): void {
  const files = review.files ?? [];
  const annotations = review.annotations ?? [];
  const risks = review.risks ?? [];
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
<nav class="tabs-main">
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">${files.length}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"${reached ? "" : " disabled"}>Blast radius <span class="c">${reached}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"${walkthroughs.length ? "" : " disabled"}>How it works <span class="c">${walkthroughs.length}</span></button>
</nav>
<div id="pane-files">
  <div class="flayout">
    ${renderTree(files)}
    <div class="fmain">${renderFiles(files, annotations, risks)}</div>
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

  // Top-level tabs.
  root.querySelectorAll<HTMLElement>(".mt").forEach((b) =>
    b.addEventListener("click", () => {
      const t = b.dataset.t;
      root.querySelectorAll(".mt").forEach((x) =>
        x.setAttribute("aria-selected", String((x as HTMLElement).dataset.t === t)),
      );
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

  // Walkthrough player: one step at a time.
  root.querySelectorAll<HTMLElement>(".wt").forEach((wt) => {
    const n = Number(wt.dataset.n);
    let at = 0;
    const show = () => {
      wt.querySelectorAll<HTMLElement>(".stepPanel").forEach((p) =>
        p.classList.toggle("on", Number(p.dataset.s) === at),
      );
      wt.querySelectorAll<HTMLElement>(".dot").forEach((d) =>
        d.toggleAttribute("aria-current", Number(d.dataset.s) === at),
      );
      wt.querySelector(".wpos")!.textContent = `step ${at + 1} of ${n}`;
      (wt.querySelector(".wprev") as HTMLButtonElement).disabled = at === 0;
      (wt.querySelector(".wnext") as HTMLButtonElement).disabled = at === n - 1;
    };
    const go = (i: number) => {
      at = Math.max(0, Math.min(n - 1, i));
      show();
    };
    (wt.querySelector(".wprev") as HTMLElement).onclick = () => go(at - 1);
    (wt.querySelector(".wnext") as HTMLElement).onclick = () => go(at + 1);
    wt.querySelectorAll<HTMLElement>(".dot").forEach((d) => {
      d.onclick = () => go(Number(d.dataset.s));
    });
    show();
  });

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
