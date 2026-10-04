/**
 * Delete the signed-in account and everything in it.
 *
 * Browser session only. A CLI token is a credential that sits in a file on a
 * laptop for thirty days; it can publish and read, and that is enough for it
 * to do. Ending an account should take someone at the site, signed in, who
 * clicked the button — and the CSRF check in middleware makes sure the click
 * came from this site.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, fail, migrate, userForSession, withDatabase } from "../../server/db";
import { deleteAccount } from "../../server/retention";

export const prerender = false;

export const DELETE: APIRoute = async ({ cookies }) => {
  const sessionId = cookies.get(SESSION_COOKIE)?.value;
  if (!sessionId) return fail(401, "login required");

  return withDatabase(async () => {
    await migrate();
    const user = await userForSession(sessionId);
    if (!user) return fail(401, "login required");

    await deleteAccount(user.id);
    // The session row went with the user; the cookie is all that is left.
    cookies.delete(SESSION_COOKIE, { path: "/" });
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
