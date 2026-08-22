/**
 * Compression sits between the payload and the encryption, and both edges
 * matter.
 *
 * The upload limit is measured on compressed bytes, so the ratio is what
 * decides whether a large review can publish at all. And a limit checked only
 * against what arrived is not a limit: gzip turns kilobytes on the wire into
 * gigabytes in memory unless inflation is bounded too.
 *
 * Run: node test/compress.mjs   (also runs in CI)
 */
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";

const BUNDLE = new URL("./.compress-bundle.mjs", import.meta.url).pathname;
execFileSync("./node_modules/.bin/esbuild", [
  new URL("../src/server/compress.ts", import.meta.url).pathname,
  "--bundle", "--format=esm", `--outfile=${BUNDLE}`, "--log-level=error",
]);
const { gzip, gunzip, isGzip, TooLarge } = await import(BUNDLE);
rmSync(BUNDLE, { force: true });

const CAP = 10_000_000;
const problems = [];
const check = (name, cond) => { if (!cond) problems.push(name); };

// A real payload, not a synthetic one — repetitive filler compresses far
// better than actual review JSON and would flatter the ratio.
const fixture = readFileSync(new URL("../src/fixtures/review.json", import.meta.url));
const packed = await gzip(new Uint8Array(fixture));
check("a real payload round-trips byte for byte",
  Buffer.from(await gunzip(packed, CAP)).equals(fixture));
check("a real payload compresses at least 3:1", fixture.length / packed.length >= 3);

check("gzip is recognised", isGzip(packed));
// Blobs written before compression existed must still open.
check("plain JSON is not mistaken for gzip", !isGzip(new Uint8Array(fixture)));
check("a one-byte input does not read past the end", !isGzip(new Uint8Array([0x1f])));

// The ceiling is the point: small on the wire, enormous inflated.
let threw = null;
try {
  await gunzip(await gzip(new Uint8Array(50_000_000)), CAP);
} catch (e) {
  threw = e;
}
check("a gzip bomb is refused", threw instanceof TooLarge);
check("output just under the cap is accepted",
  (await gunzip(await gzip(new Uint8Array(CAP - 1_000_000)), CAP)).length === CAP - 1_000_000);

if (problems.length) {
  console.error("FAIL:\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log(
  `ok — payload round-trips at ${(fixture.length / packed.length).toFixed(1)}:1, bomb refused`,
);
