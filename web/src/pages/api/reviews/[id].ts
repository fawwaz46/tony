/**
 * Serve or delete one review.
 *
 * GET requires a logged-in reader — any account will do, since the id is
 * unguessable and a link is still what grants access. It returns decrypted
 * JSON, which is what makes the hosted page and the dashboard possible at all.
 * DELETE is owner-only.
 */
import type { APIRoute } from "astro";
import { del } from "@vercel/blob";
import { open } from "../../../server/crypto";
import {
  SESSION_COOKIE, fail, migrate, sql, userForSession, userForToken, withDatabase,
} from "../../../server/db";

export const prerender = false;

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
    if (!(await reader(request, cookies))) return fail(401, "login required");

    const rows = await sql`SELECT blob_url FROM reviews WHERE id = ${params.id}`;
    if (!rows.length) return fail(404, "not found");

    const blob = await fetch(rows[0].blob_url);
    if (!blob.ok) return fail(404, "not found");

    return new Response(await open(await blob.arrayBuffer()), {
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
      SELECT blob_url, user_id FROM reviews WHERE id = ${params.id}`;
    if (!rows.length) return fail(404, "not found");
    if (Number(rows[0].user_id) !== user.id) return fail(403, "not yours to delete");

    await del(rows[0].blob_url).catch(() => {});
    await sql`DELETE FROM reviews WHERE id = ${params.id}`;
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
