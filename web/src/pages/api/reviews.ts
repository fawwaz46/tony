/**
 * Upload one review from the CLI.
 *
 * The CLI sends the payload as plain JSON over TLS; this route seals it under
 * the server key before it reaches the blob store (see server/crypto.ts). A
 * few summary fields are lifted out and kept in Postgres so the dashboard can
 * list reviews without opening every blob.
 *
 * Bounds, because an upload endpoint is otherwise a free file host: login
 * required, a hard size cap, and a per-user hourly rate limit.
 */
import type { APIRoute } from "astro";
import { put } from "@vercel/blob";
import { seal } from "../../server/crypto";
import { fail, migrate, sql, userForToken, withDatabase } from "../../server/db";
import { capped } from "../../server/safe";

export const prerender = false;

const MAX_BYTES = 1_000_000; // payloads run ~30KB; generous, not open
const PER_HOUR = 60;

const randomId = () =>
  [...crypto.getRandomValues(new Uint8Array(8))]
    .map((b) => "abcdefghjkmnpqrstuvwxyz23456789"[b % 31])
    .join("");

export const POST: APIRoute = async ({ request }) => {
  // Cheap rejections first: no credential and no oversized body ever reaches
  // the database, so an unauthenticated flood costs a header read.
  const auth = request.headers.get("Authorization");
  if (!auth) return fail(401, "login required");

  const body = await request.text();
  if (body.length > MAX_BYTES) return fail(413, "this review is over the size limit");

  let payload: any;
  try {
    payload = JSON.parse(body);
  } catch {
    return fail(400, "not a review payload");
  }
  // Shape check. The renderer treats every payload as hostile, but a store
  // that accepts arbitrary JSON is a store of arbitrary JSON — keep the
  // obvious junk out rather than relying on one layer.
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return fail(400, "not a review payload");
  }
  for (const field of ["files", "annotations", "risks", "impacts", "walkthroughs"]) {
    if (field in payload && !Array.isArray(payload[field])) {
      return fail(400, `${field} must be a list`);
    }
  }

  return withDatabase(async () => {
    await migrate();
    const user = await userForToken(auth);
    if (!user) return fail(401, "login required");

    const recent = await sql`
      SELECT count(*) AS n FROM reviews
      WHERE user_id = ${user.id} AND created_at > now() - interval '1 hour'`;
    if (Number(recent[0].n) >= PER_HOUR) {
      return fail(429, "too many reviews published in the last hour");
    }

    const id = randomId();
    const blob = await put(`reviews/${id}`, await seal(body), {
      access: "public", // ciphertext, unguessable URL, and only ever served through this API
      contentType: "application/octet-stream",
      addRandomSuffix: true,
    });

    await sql`
      INSERT INTO reviews (id, user_id, repo, range, intent, files, annotations, size, blob_url)
      VALUES (${id}, ${user.id},
              ${String(payload.repo ?? "")}, ${String(payload.range ?? "")},
              ${String(payload.intent ?? "")},
              ${Array.isArray(payload.files) ? payload.files.length : 0},
              ${Array.isArray(payload.annotations) ? payload.annotations.length : 0},
              ${body.length}, ${blob.url})`;

    return new Response(JSON.stringify({ id }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
