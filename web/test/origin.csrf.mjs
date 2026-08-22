/**
 * The CSRF check must let the site's own requests through and stop everyone
 * else, and the site origin must never be downgraded to http on a public host.
 *
 * Both halves have already been wrong in production. `Astro.url.origin` behind
 * Vercel's proxy is the internal address, so the OAuth redirect_uri pointed at
 * localhost and login could not complete. The replacement compared Origin
 * only, which refuses the site's own sign-out form: a `<form>` POST is a
 * navigation, and under a `no-referrer` policy the browser serialises its
 * Origin as the literal string "null".
 *
 * Run: node test/origin.csrf.mjs   (also runs in CI)
 */
import { execFileSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";

const BUNDLE = new URL("./.origin-bundle.mjs", import.meta.url).pathname;
const ENTRY = new URL("./.origin-entry.ts", import.meta.url).pathname;

// Both units come from the real modules; a hand-rolled copy of the rule would
// keep passing after the middleware changed.
writeFileSync(
  ENTRY,
  `export { siteOrigin } from "../src/server/safe";\n` +
    `export { sameSite } from "../src/middleware";\n`,
);
execFileSync("./node_modules/.bin/esbuild", [
  ENTRY, "--bundle", "--format=esm", `--outfile=${BUNDLE}`, "--log-level=error",
]);
const { siteOrigin, sameSite } = await import(BUNDLE);
rmSync(BUNDLE, { force: true });
rmSync(ENTRY, { force: true });

const problems = [];
const check = (name, got, want) => {
  if (got !== want) problems.push(`${name}: got ${got}, want ${want}`);
};

// --- siteOrigin -----------------------------------------------------------
const origin = (headers, configured, fallback) => {
  if (configured) process.env.TONY_SITE_URL = configured;
  else delete process.env.TONY_SITE_URL;
  return siteOrigin(new Request("https://internal.local/x", { headers }), fallback);
};

check("configured wins, normalised",
  origin({ host: "preview.vercel.app" }, "https://tony-cli.com/", "https://localhost"),
  "https://tony-cli.com");
// A value that is not an absolute http(s) origin is a misconfiguration; using
// it verbatim would refuse every state-changing request.
check("configured without a scheme is ignored",
  origin({ "x-forwarded-host": "tony-cli.com" }, "tony-cli.com", "https://localhost"),
  "https://tony-cli.com");
check("forwarded proto is honoured",
  origin({ "x-forwarded-host": "a.com", "x-forwarded-proto": "https,http" }, "", "https://localhost"),
  "https://a.com");
// The downgrade that would put the OAuth code on the wire in cleartext and
// drop Secure from the session cookie.
check("public host without a forwarded proto stays https",
  origin({ "x-forwarded-host": "tony-cli.com" }, "", "http://localhost"),
  "https://tony-cli.com");
check("the dev server is still http",
  origin({ host: "localhost:4321" }, "", "http://localhost:4321"),
  "http://localhost:4321");

// --- the CSRF decision ----------------------------------------------------
process.env.TONY_SITE_URL = "https://tony-cli.com";
const allowed = (headers) =>
  sameSite(new Request("https://tony-cli.com/api/auth/signout", { method: "POST", headers }),
           "https://tony-cli.com");

for (const [name, headers, want] of [
  ["sign-out form: Origin null, same-origin", { origin: "null", "sec-fetch-site": "same-origin" }, true],
  ["dashboard delete: real Origin", { origin: "https://tony-cli.com", "sec-fetch-site": "same-origin" }, true],
  ["attacker form: Origin null, cross-site", { origin: "null", "sec-fetch-site": "cross-site" }, false],
  ["attacker fetch: foreign Origin", { origin: "https://evil.example", "sec-fetch-site": "cross-site" }, false],
  ["attacker, no Sec-Fetch-Site", { origin: "https://evil.example" }, false],
  ["old browser, same-origin form", { origin: "https://tony-cli.com" }, true],
  ["the CLI: neither header", {}, true],
]) {
  check(name, allowed(headers), want);
}

if (problems.length) {
  console.error("FAIL:\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log("ok — origin resolved without downgrade, CSRF matrix as expected");
