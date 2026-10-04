/**
 * The instruction document the CLI hands to a calling agent.
 *
 * It lives here rather than in the pip package because it is the only lever
 * tony has left on review quality: it owns no model, no harness, and no context
 * window, so what the agent is told is the whole of the contract. Shipping it
 * in the client would mean the bar could only move at the speed of releases,
 * and that installs which never update would keep writing to a contract this
 * server has since tightened — being rejected by rules their document never
 * stated.
 *
 * Same reasoning as config.ts: the CLI ships nothing it would have to be
 * re-released to change.
 *
 * `version` is the content hash. It goes back to the client, into the review's
 * provenance, and answers the question no other record can — which document
 * produced this review, and did changing it help.
 *
 * The validator, though, does ship in the client, so the document and the
 * validator can disagree: an install that predates `reach: "new"` would reject
 * every review written to a document that asks for it. A client names the
 * contract its validator enforces in `X-Tony-Contract` and gets that document.
 * One that names none predates the header and gets contract 1, which it can
 * check. Drop a contract once nothing installed still asks for it.
 */
import type { APIRoute } from "astro";
import { createHash } from "node:crypto";
import current from "../../instructions/review.md?raw";
import v1 from "../../instructions/review.v1.md?raw";

export const prerender = false;

const served = (document: string) => {
  const version = createHash("sha256").update(document).digest("hex").slice(0, 12);
  return { document, version, etag: `"${version}"` };
};

// Contract 2: flows — `reach` new/removed, `actor`, up to ten steps, no cap.
const CONTRACTS: Record<string, ReturnType<typeof served>> = {
  "1": served(v1),
  "2": served(current),
};

export const GET: APIRoute = ({ request }) => {
  const { document, version, etag } =
    CONTRACTS[request.headers.get("x-tony-contract") ?? "1"] ?? CONTRACTS["2"];

  // The client caches by ETag and revalidates on every review, so the common
  // response is 304 and a few hundred bytes rather than 13 KB.
  if (request.headers.get("if-none-match") === etag) {
    return new Response(null, { status: 304, headers: { ETag: etag, Vary: "X-Tony-Contract" } });
  }
  return new Response(JSON.stringify({ version, document }), {
    headers: {
      "Content-Type": "application/json",
      ETag: etag,
      // Revalidate every time. The point of serving this is that a change
      // reaches every agent on its next review, which a max-age would defeat.
      "Cache-Control": "no-cache",
      // Two documents at one URL: a shared cache must key on which was asked for.
      Vary: "X-Tony-Contract",
    },
  });
};
