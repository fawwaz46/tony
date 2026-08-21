/**
 * Revoke one machine's token.
 *
 * `tony logout` calls this before deleting its local copy, so a token that
 * leaked off a laptop stops working rather than living forever. Tokens are
 * stored as hashes, so this deletes by hash — the plaintext is never here to
 * compare against.
 */
import type { APIRoute } from "astro";
import { migrate, sha256Hex, sql } from "../../../server/db";

export const prerender = false;

export const POST: APIRoute = async ({ request }) => {
  const token = request.headers.get("Authorization")?.match(/^Bearer (.+)$/)?.[1];
  if (!token) return new Response("no token", { status: 400 });

  await migrate();
  await sql`DELETE FROM tokens WHERE hash = ${await sha256Hex(token)}`;
  // Always 200: whether the token existed is not information a caller needs,
  // and "log me out" succeeding either way is the behaviour people expect.
  return new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json" },
  });
};
