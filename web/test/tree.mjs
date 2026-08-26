/**
 * The file tree's shape.
 *
 * The tree is the only navigation a forty-file review has, so the failures that
 * matter are structural: a path that vanishes, a folder that swallows a file, a
 * corridor of single-child directories costing five rows of indentation to walk
 * past. Rendering is covered by render.xss.mjs; this is about the shape.
 *
 * Run: node test/tree.mjs   (also runs in CI)
 */
import { execFileSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import assert from "node:assert/strict";

const BUNDLE = new URL("./.tree-bundle.mjs", import.meta.url).pathname;
const ENTRY = new URL("./.tree-entry.ts", import.meta.url).pathname;

writeFileSync(ENTRY, `export { buildTree } from "../src/renderer/render";\n`);
execFileSync("./node_modules/.bin/esbuild", [
  ENTRY, "--bundle", "--format=esm", `--outfile=${BUNDLE}`,
]);
const { buildTree } = await import(BUNDLE);

const at = (nodes, name) => nodes.find((n) => n.name === name);
const names = (nodes) => nodes.map((n) => n.name);
const files = (paths) => paths.map((path) => ({ path, status: "modified" }));

// A corridor of single-child folders reads as one row, not five.
{
  const tree = buildTree(files(["apps/mobile/src/hooks/usePrayer.ts"]));
  assert.deepEqual(names(tree), ["apps/mobile/src/hooks"]);
  assert.deepEqual(names(tree[0].children), ["usePrayer.ts"]);
}

// It stops collapsing where the path actually branches.
{
  const tree = buildTree(files([
    "apps/mobile/src/hooks/a.ts",
    "apps/mobile/src/machines/b.ts",
  ]));
  assert.deepEqual(names(tree), ["apps/mobile/src"]);
  assert.deepEqual(names(tree[0].children), ["hooks", "machines"]);
}

// A folder holding both a file and a folder must not be collapsed into either.
{
  const tree = buildTree(files(["src/index.ts", "src/lib/util.ts"]));
  assert.deepEqual(names(tree), ["src"]);
  assert.deepEqual(names(tree[0].children), ["lib", "index.ts"]);
}

// Folders first, then files, each alphabetical.
{
  const tree = buildTree(files(["z.ts", "a.ts", "beta/x.ts", "alpha/y.ts"]));
  assert.deepEqual(names(tree), ["alpha", "beta", "a.ts", "z.ts"]);
}

// Every file reaches a leaf, and keeps the diff's numbering.
{
  const paths = ["a/b/c.ts", "a/d.ts", "e.ts"];
  const tree = buildTree(files(paths));
  const leaves = [];
  const walk = (nodes) => nodes.forEach((n) => (n.dir ? walk(n.children) : leaves.push(n)));
  walk(tree);
  assert.equal(leaves.length, paths.length);
  assert.deepEqual(leaves.map((l) => l.index).sort((x, y) => x - y), [1, 2, 3]);
  leaves.forEach((l) => assert.ok(l.file, "leaf carries its file entry"));
}

// Untrusted paths: empty and doubled separators must not become nameless folders.
{
  const tree = buildTree([
    { path: "" },
    { path: "a//b.ts" },
    { path: "/leading.ts" },
    {},
  ]);
  const walk = (nodes) => nodes.forEach((n) => {
    assert.notEqual(n.name, "", "no nameless node");
    walk(n.children);
  });
  walk(tree);
  assert.deepEqual(names(tree), ["a", "leading.ts"]);
  assert.deepEqual(names(at(tree, "a").children), ["b.ts"]);
}

// A review with no files renders no tree at all rather than an empty frame.
assert.deepEqual(buildTree([]), []);

// ---- behaviour, against a real DOM ----------------------------------------

import { JSDOM } from "jsdom";

const VIEW = new URL("./.tree-view.mjs", import.meta.url).pathname;
const VENTRY = new URL("./.tree-view-entry.ts", import.meta.url).pathname;
writeFileSync(VENTRY, `export { renderReview } from "../src/renderer/render";\n`);
execFileSync("./node_modules/.bin/esbuild", [
  VENTRY, "--bundle", "--format=esm", `--outfile=${VIEW}`,
]);
const { renderReview } = await import(VIEW);

const dom = new JSDOM("<div id=root></div>");
// wire() binds a document-level key handler, so the module needs the globals a
// browser would have given it.
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.document = dom.window.document;
const doc = dom.window.document;
const root = doc.getElementById("root");

renderReview(root, {
  v: 1, repo: "r", range: "main...x", intent: "i",
  files: files([
    "apps/mobile/src/hooks/a.ts",
    "apps/mobile/src/machines/b.ts",
    "src/index.ts",
  ]),
  annotations: [], risks: [], impacts: [], impactWindows: {}, walkthroughs: [],
});

const rows = [...doc.querySelectorAll(".tfb")];
assert.equal(rows.length, 3, "one row per changed file");

const shown = () =>
  [...doc.querySelectorAll("#pane-files .file")].filter((f) => !f.hidden);

// Every row must reach the section it names. A dead row is worse than no tree.
rows.forEach((b) =>
  assert.ok(doc.getElementById(b.dataset.target), `${b.dataset.target} exists`),
);

// One file on screen, never all of them — this is the whole point of the pane.
assert.equal(shown().length, 1, "exactly one file visible");
assert.equal(shown()[0].id, rows[0].dataset.target, "the first file is the one shown");
assert.ok(rows[0].hasAttribute("aria-current"), "its row starts current");

// Clicking swaps which file is on screen. The marking must survive a DOM with
// no scrollIntoView — it did not, once.
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
click(rows[1]);
assert.equal(shown().length, 1);
assert.equal(shown()[0].id, rows[1].dataset.target, "clicked file is shown");
assert.ok(rows[1].hasAttribute("aria-current"));
assert.equal(doc.querySelectorAll(".tfb[aria-current]").length, 1, "one row current");

// Bracket keys step files, the same idiom the blast-radius stepper uses.
const key = (k) =>
  doc.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: k, bubbles: true }));
key("]");
assert.equal(shown()[0].id, rows[2].dataset.target, "] moves to the next file");
key("]");
assert.equal(shown()[0].id, rows[2].dataset.target, "] stops at the last file");
key("[");
assert.equal(shown()[0].id, rows[1].dataset.target, "[ moves back");

// Filtering hides non-matches and prunes folders left with nothing in them.
const filter = doc.getElementById("treeFilter");
const type = (value) => {
  filter.value = value;
  filter.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
};
const visibleFiles = () =>
  [...doc.querySelectorAll(".tfl")].filter((li) => !li.hidden)
    .map((li) => li.querySelector(".tnm").textContent);

type("machines");
assert.deepEqual(visibleFiles(), ["b.ts"]);
assert.ok(
  [...doc.querySelectorAll(".td")].filter((d) => !d.hidden)
    .every((d) => d.querySelector(".tfl:not([hidden])")),
  "no folder left visible with nothing under it",
);

// A path segment that appears in no filename still finds its files.
type("apps/mobile");
assert.deepEqual(visibleFiles().sort(), ["a.ts", "b.ts"]);

// Filtering the shown file out of the list must move the view to one still in
// it, not leave the reader on a file the tree no longer offers.
click(rows[2]);                       // src/index.ts
assert.equal(shown()[0].id, rows[2].dataset.target);
type("machines");
assert.equal(shown()[0].id, rows[1].dataset.target, "view followed the filter");
assert.ok(rows[1].hasAttribute("aria-current"));

type("nothing-matches-this");
assert.deepEqual(visibleFiles(), []);
assert.equal(doc.querySelector(".tnone").hidden, false, "empty state shown");
assert.equal(shown().length, 1, "a dead filter does not blank the page");

type("");
assert.equal(visibleFiles().length, 3, "clearing the filter restores every row");
assert.equal(doc.querySelector(".tnone").hidden, true);

// The tree sorts alphabetically, the diff does not. When those orders disagree
// the keys must still start from the file actually on screen.
{
  const d2 = new JSDOM("<div id=root></div>");
  globalThis.document = d2.window.document;
  const r2 = d2.window.document.getElementById("root");
  renderReview(r2, {
    v: 1, repo: "r", range: "main...x", intent: "i",
    files: files(["z.ts", "alpha/y.ts"]),   // diff order; tree shows alpha first
    annotations: [], risks: [], impacts: [], impactWindows: {}, walkthroughs: [],
  });

  const r2rows = [...d2.window.document.querySelectorAll(".tfb")];
  const r2shown = () =>
    [...d2.window.document.querySelectorAll("#pane-files .file")].filter((f) => !f.hidden);

  assert.equal(r2rows[0].querySelector(".tnm").textContent, "y.ts", "tree sorted");
  assert.equal(r2shown()[0].id, r2rows[1].dataset.target, "diff's first file shown");
  assert.ok(r2rows[1].hasAttribute("aria-current"));

  d2.window.document.dispatchEvent(
    new d2.window.KeyboardEvent("keydown", { key: "[", bubbles: true }),
  );
  assert.equal(r2shown()[0].id, r2rows[0].dataset.target, "[ stepped from the shown file");
  globalThis.document = doc;
}

[ENTRY, BUNDLE, VENTRY, VIEW].forEach((f) => rmSync(f, { force: true }));
console.log("ok — file tree collapses corridors, sorts, and drives a one-file view");
