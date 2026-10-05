/**
 * Revoke one of your tokens. Browser session only, like every other change to
 * an account; middleware's same-origin check covers the click. A token is
 * addressed by its row id, never by the secret or its hash.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, fail, migrate, sql, userForSession, withDatabase } from "../../../server/db";

export const prerender = false;

export const DELETE: APIRoute = async ({ params, cookies }) => {
  if (!cookies.get(SESSION_COOKIE)?.value) return fail(401, "login required");
  const id = Number(params.id);
  if (!Number.isSafeInteger(id) || id <= 0) return fail(400, "bad token id");

  return withDatabase(async () => {
    await migrate();
    const user = await userForSession(cookies.get(SESSION_COOKIE)?.value);
    if (!user) return fail(401, "login required");
    // Scoped to the owner in the same statement: someone else's id is a miss.
    const rows = await sql`
      DELETE FROM tokens WHERE id = ${id} AND user_id = ${user.id} RETURNING id`;
    if (!rows.length) return fail(404, "not found");
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
