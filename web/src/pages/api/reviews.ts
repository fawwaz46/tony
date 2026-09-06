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
import { TooLarge, gunzip, gzip, isGzip } from "../../server/compress";
import { encryptionConfigured, seal } from "../../server/crypto";
import { fail, migrate, sql, userForToken, withDatabase } from "../../server/db";
import { blobToken } from "../../server/env";
import { capped, counted } from "../../server/safe";

export const prerender = false;

// What may arrive, measured on the wire — so a compressed upload spends this
// budget on compressed bytes and fits roughly ten times the review.
const MAX_UPLOAD_BYTES = 1_000_000; // payloads run ~30KB gzipped; generous, not open
// What it may become once inflated. Without this the wire limit bounds
// nothing: a gzip bomb is small to send and enormous to hold.
const MAX_PAYLOAD_BYTES = 10_000_000;
const PER_HOUR = 60;

// The summary columns are read back into every dashboard row, so they are
// bounded independently of the payload: within one 1MB upload a single
// `intent` could otherwise carry the whole megabyte into that list.
const REPO_MAX = 200;
const RANGE_MAX = 200;
const INTENT_MAX = 2_000;
// Provenance strings are identifiers — a client name, a version, a model id, a
// content hash — not prose. Anything longer is not one.
const NAME_MAX = 120;

// The id IS the capability: anyone signed in who has the link may read the
// review, which is the whole point of publishing one. So it has to be a
// credential, not a name. Eight characters of this alphabet is about 40 bits —
// guessable by someone willing to spend a weekend on it, especially against a
// route with no throttle. Sixteen is about 79 bits, which is not.
//
// Existing eight-character ids keep working; they are already out in links
// that people have sent, and the read throttle in `[id].ts` is what covers
// them.
const ID_LENGTH = 16;

const randomId = () =>
  [...crypto.getRandomValues(new Uint8Array(ID_LENGTH))]
    .map((b) => "abcdefghjkmnpqrstuvwxyz23456789"[b % 31])
    .join("");

export const POST: APIRoute = async ({ request }) => {
  // Cheap rejections first: no credential and no oversized body ever reaches
  // the database, so an unauthenticated flood costs a header read.
  const auth = request.headers.get("Authorization");
  if (!auth) return fail(401, "login required");

  // Every stored review is sealed, so a deployment without the key cannot keep
  // one. Refusing here names the missing setting in the log instead of failing
  // later as an unexplained error, and costs the caller nothing to be told.
  if (!encryptionConfigured()) {
    console.error("TONY_ENCRYPTION_KEY is not set; refusing to accept a review");
    return fail(503, "this server is not configured to store reviews yet");
  }

  // Bytes, not text: the CLI gzips before upload, and older CLIs still send
  // plain JSON. The magic bytes say which, so neither needs a flag day.
  const wire = new Uint8Array(await request.arrayBuffer());
  if (wire.length > MAX_UPLOAD_BYTES) {
    return fail(413, "this review is over the size limit");
  }

  let raw: Uint8Array;
  try {
    raw = isGzip(wire) ? await gunzip(wire, MAX_PAYLOAD_BYTES) : wire;
  } catch (e) {
    if (e instanceof TooLarge) return fail(413, "this review is over the size limit");
    return fail(400, "not a review payload");
  }
  const body = new TextDecoder().decode(raw);

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
    // Private: the bytes are ciphertext, but the only supported way in is
    // through this API, which checks a session. A publicly addressable object
    // would make the login gate one of two doors instead of the only one, and
    // both readers below already pass `access: "private"`.
    // Compress, then encrypt — ciphertext does not compress, so the other
    // order saves nothing. A Blob rather than the raw Uint8Array `seal`
    // returns: that is the byte container `put` accepts, and it carries the
    // content type.
    const stored = await seal(await gzip(raw));
    const sealed = new Blob([stored as BlobPart], { type: "application/octet-stream" });
    const blob = await put(`reviews/${id}`, sealed, {
      access: "private",
      contentType: "application/octet-stream",
      addRandomSuffix: true,
      ...blobToken(),
    });

    // Both are objects out of an uploaded payload, so neither is trusted for
    // anything beyond what `capped` and `counted` will pass through.
    const from = (payload.provenance ?? {}) as Record<string, unknown>;
    const cover = (payload.coverage ?? {}) as Record<string, unknown>;

    await sql`
      INSERT INTO reviews (id, user_id, repo, range, intent, files, annotations, size, blob_path,
                           harness, harness_version, model, instructions,
                           retries, seconds, diff_lines, diff_files,
                           changed_lines, unexplained_lines)
      VALUES (${id}, ${user.id},
              ${capped(payload.repo, REPO_MAX)}, ${capped(payload.range, RANGE_MAX)},
              ${capped(payload.intent, INTENT_MAX)},
              ${Array.isArray(payload.files) ? payload.files.length : 0},
              ${Array.isArray(payload.annotations) ? payload.annotations.length : 0},
              ${raw.length}, ${blob.pathname},
              ${capped(from.harness, NAME_MAX)}, ${capped(from.harnessVersion, NAME_MAX)},
              ${capped(from.model, NAME_MAX)}, ${capped(payload.instructions, NAME_MAX)},
              ${counted(from.retries)}, ${counted(from.seconds)},
              ${counted(from.diffLines)}, ${counted(from.diffFiles)},
              ${counted(cover.changedLines)}, ${counted(cover.unexplainedLines)})`;

    return new Response(JSON.stringify({ id }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
