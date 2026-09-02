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
 */
import type { APIRoute } from "astro";
import { createHash } from "node:crypto";
import document from "../../instructions/review.md?raw";

export const prerender = false;

const version = createHash("sha256").update(document).digest("hex").slice(0, 12);
const etag = `"${version}"`;

export const GET: APIRoute = ({ request }) => {
  // The client caches by ETag and revalidates on every review, so the common
  // response is 304 and a few hundred bytes rather than 13 KB.
  if (request.headers.get("if-none-match") === etag) {
    return new Response(null, { status: 304, headers: { ETag: etag } });
  }
  return new Response(JSON.stringify({ version, document }), {
    headers: {
      "Content-Type": "application/json",
      ETag: etag,
      // Revalidate every time. The point of serving this is that a change
      // reaches every agent on its next review, which a max-age would defeat.
      "Cache-Control": "no-cache",
    },
  });
};
