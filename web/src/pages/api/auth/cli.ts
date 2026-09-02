/**
 * Trade the one-time code from a browser login for a CLI token.
 *
 * `tony login` opens a browser, the browser comes back to the CLI's loopback
 * port with a code, and the CLI posts it here. The code is spent atomically and
 * is worth nothing twice, so an entry left in browser history is not a
 * credential.
 */
import type { APIRoute } from "astro";
import {
  createToken, migrate, spendCliCode, sql, throttle, withDatabase,
} from "../../../server/db";

export const prerender = false;

export const POST: APIRoute = async ({ request, clientAddress }) => {
  // This mints a long-lived token, so guessing at codes must not be free.
  if (throttle(`cli:${clientAddress}`, 10, 60_000)) {
    return new Response("too many attempts", { status: 429 });
  }

  const { code } = await request.json().catch(() => ({}));
  if (typeof code !== "string" || !code) {
    return new Response("missing code", { status: 400 });
  }

  return withDatabase(async () => {
    await migrate();
    const userId = await spendCliCode(code);
    if (userId === null) {
      return new Response("that code is expired or already used", { status: 401 });
    }
    const token = await createToken(userId);
    const rows = await sql`SELECT login FROM users WHERE id = ${userId}`;
    const login = rows[0]?.login ?? "";
    return new Response(JSON.stringify({ token, login, githubLogin: login }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
