/**
 * Serve or delete one review.
 *
 * GET requires a logged-in reader — any account will do, deliberately: the id
 * is the capability, and a link you can send a teammate is the entire point of
 * publishing. It returns decrypted JSON, which is what makes the hosted page
 * possible at all.
 *
 * What makes that stance safe is the pair of things below it. New ids carry
 * about 79 bits (see reviews.ts), and this route is throttled per account —
 * without the throttle, "unguessable" was a claim about one id rather than
 * about a route, and an account could sit and try them by the million for
 * free. That is the difference between a capability and an oracle.
 *
 * DELETE is owner-only.
 */
import type { APIRoute } from "astro";
import { del, get } from "@vercel/blob";
import { gunzip, isGzip } from "../../../server/compress";
import { open } from "../../../server/crypto";
import { blobToken } from "../../../server/env";
import {
  SESSION_COOKIE, fail, migrate, sql, throttle, userForSession, userForToken,
  withDatabase,
} from "../../../server/db";

export const prerender = false;

// Reads per account per hour. A person opening reviews all day does not come
// close; anything that does is walking the id space. In-memory and
// per-instance, so it is a speed bump rather than a wall — but a speed bump
// turns a weekend of guessing into a length of time nobody has.
const READS_PER_HOUR = 240;
const HOUR = 60 * 60 * 1000;

// Matches the ceiling the upload route inflates against.
const MAX_PAYLOAD_BYTES = 10_000_000;

/** Either identity works: a browser session, or the CLI's bearer token. */
async function reader(request: Request, cookies: any) {
  return (
    (await userForSession(cookies.get(SESSION_COOKIE)?.value)) ??
    (await userForToken(request.headers.get("Authorization")))
  );
}

export const GET: APIRoute = async ({ params, request, cookies }) => {
  // No credential at all is answerable without a query.
  if (!cookies.get(SESSION_COOKIE)?.value && !request.headers.get("Authorization")) {
    return fail(401, "login required");
  }

  return withDatabase(async () => {
    await migrate();
    const user = await reader(request, cookies);
    if (!user) return fail(401, "login required");

    // Counted before the row is looked up, so a miss costs an attacker the
    // same budget as a hit and the throttle cannot be walked with wrong ids.
    if (throttle(`read:${user.id}`, READS_PER_HOUR, HOUR)) {
      return fail(429, "too many reviews read in the last hour");
    }

    const rows = await sql`SELECT blob_path FROM reviews WHERE id = ${params.id}`;
    if (!rows.length) return fail(404, "not found");

    const blob = await get(rows[0].blob_path, { access: "private", ...blobToken() });
    if (!blob || blob.statusCode !== 200) return fail(404, "not found");

    // Blobs written before compression are plain JSON under the same
    // encryption, so the magic bytes decide rather than a stored version.
    const plain = await open(await new Response(blob.stream).arrayBuffer());
    const json = isGzip(plain) ? await gunzip(plain, MAX_PAYLOAD_BYTES) : plain;

    return new Response(new TextDecoder().decode(json), {
      headers: {
        "Content-Type": "application/json",
        // Private: it is one user's source code, decrypted.
        "Cache-Control": "private, no-store",
      },
    });
  });
};

export const DELETE: APIRoute = async ({ params, request, cookies }) => {
  if (!cookies.get(SESSION_COOKIE)?.value && !request.headers.get("Authorization")) {
    return fail(401, "login required");
  }

  return withDatabase(async () => {
    await migrate();
    const user = await reader(request, cookies);
    if (!user) return fail(401, "login required");

    const rows = await sql`
      SELECT blob_path, user_id FROM reviews WHERE id = ${params.id}`;
    if (!rows.length) return fail(404, "not found");
    if (Number(rows[0].user_id) !== user.id) return fail(403, "not yours to delete");

    // `del` addresses the object by pathname and takes no access option.
    await del(rows[0].blob_path, blobToken()).catch(() => {});
    await sql`DELETE FROM reviews WHERE id = ${params.id}`;
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
