/**
 * The renderer must survive a hostile payload.
 *
 * This is not hypothetical: any account can POST an arbitrary payload to
 * /api/reviews and send the link to a colleague, who opens it signed in. A
 * field that skips escaping is stored XSS running in that reader's session on
 * our origin. An earlier version of render.ts escaped the obviously-textual
 * fields and interpolated numbers and class names raw, which was exploitable
 * through `additions`, gutter numbers, `impact.line`, and `phase`.
 *
 * Run: node test/render.xss.mjs   (also runs in CI)
 */
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { JSDOM } from "jsdom";

const BUNDLE = new URL("./.xss-bundle.js", import.meta.url).pathname;
const ENTRY = new URL("./.xss-entry.ts", import.meta.url).pathname;

import { writeFileSync } from "node:fs";
writeFileSync(
  ENTRY,
  `import { renderReview } from "../src/renderer/render";\n` +
    `(globalThis as any).__run = (r: any, p: any) => renderReview(r, p);\n`,
);
execFileSync("./node_modules/.bin/esbuild", [
  ENTRY, "--bundle", "--format=iife", `--outfile=${BUNDLE}`,
]);

// Every string field carries a breakout attempt; every numeric field carries a
// string, which is how the original bug slipped through type annotations.
const ATTR = '"><img src=x onerror=alert(1)>';
const TAG = "</script><script>alert(2)</script>";

const hostile = {
  v: 1,
  repo: ATTR,
  range: TAG,
  intent: ATTR,
  annotations: [{ path: ATTR, line: ATTR, title: ATTR, kind: ATTR, prev: ATTR, now: TAG, impact: ATTR }],
  risks: [{ path: ATTR, line: ATTR, text: TAG }],
  impacts: [{ path: "x.py", line: ATTR, kind: ATTR, why: TAG, symbol: ATTR, fromPath: ATTR }],
  impactWindows: { "x.py": { start: ATTR, lines: [TAG], truncated: false, total: ATTR } },
  walkthroughs: [
    {
      title: TAG,
      trigger: ATTR,
      whatChanged: ATTR,
      steps: [
        {
          say: TAG,
          phase: ATTR,
          path: ATTR,
          state: { [ATTR]: TAG },
          window: { start: ATTR, lines: [TAG], hot: [ATTR, ATTR], truncated: false, total: 1 },
        },
      ],
    },
  ],
  files: [
    {
      path: "a.py",
      oldPath: ATTR,
      status: ATTR,
      binary: false,
      additions: ATTR,
      deletions: ATTR,
      blocks: [
        { k: "row", cls: ATTR, g: ATTR, text: TAG },
        { k: "note", n: 0, span: [ATTR, ATTR, false], tag: ATTR },
        { k: "note", n: 999, span: null, tag: ATTR }, // index past the array
      ],
    },
  ],
};

const dom = new JSDOM('<body><div id="r"></div></body>', { runScripts: "outside-only" });
dom.window.eval(readFileSync(BUNDLE, "utf8"));
dom.window.__run(dom.window.document.getElementById("r"), hostile);
const d = dom.window.document;

rmSync(BUNDLE, { force: true });
rmSync(ENTRY, { force: true });

const injected = d.querySelectorAll("img, script, iframe, [onerror], [onload], [onclick]");
const problems = [];
if (injected.length) problems.push(`${injected.length} element(s) injected from the payload`);
// The page must still be usable, not merely inert.
if (!d.querySelector("h1")) problems.push("page did not render");
if (!d.querySelectorAll("details.file").length) problems.push("files did not render");

if (problems.length) {
  console.error("FAIL:", problems.join("; "));
  process.exit(1);
}
console.log("ok — hostile payload rendered with nothing injected");
