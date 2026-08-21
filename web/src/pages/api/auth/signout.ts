/**
 * End a browser session. Deletes the row, then clears the cookie — in that
 * order, so a cookie that survives the round trip is already useless.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, migrate, sha256Hex, sql } from "../../../server/db";

export const prerender = false;

export const POST: APIRoute = async ({ cookies, redirect }) => {
  const sessionId = cookies.get(SESSION_COOKIE)?.value;
  if (sessionId) {
    await migrate();
    await sql`DELETE FROM sessions WHERE hash = ${await sha256Hex(sessionId)}`;
  }
  cookies.delete(SESSION_COOKIE, { path: "/" });
  return redirect("/", 302);
};
