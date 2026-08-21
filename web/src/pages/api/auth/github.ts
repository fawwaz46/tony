/**
 * Trade a GitHub access token (from the CLI's device flow) for a tony token.
 *
 * The GitHub token is used once, to ask GitHub who this is, and never stored.
 * The tony token is minted here, returned once, and kept only as a hash — the
 * same posture as the delete tokens: a database leak leaks no usable secret.
 */
import type { APIRoute } from "astro";
import { migrate, sha256Hex, sql, throttle } from "../../../server/db";

export const prerender = false;

export const POST: APIRoute = async ({ request, clientAddress }) => {
  // This route mints a long-lived CLI token, so it must not be free to hammer.
  if (throttle(`auth:${clientAddress}`, 10, 60_000)) {
    return new Response("too many attempts", { status: 429 });
  }

  const { accessToken } = await request.json().catch(() => ({}));
  if (typeof accessToken !== "string" || !accessToken) {
    return new Response("missing accessToken", { status: 400 });
  }

  const ghUser = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${accessToken}`, "User-Agent": "tony" },
  });
  if (!ghUser.ok) return new Response("github rejected the token", { status: 401 });
  const gh = await ghUser.json();

  await migrate();
  const rows = await sql`
    INSERT INTO users (github_id, github_login) VALUES (${gh.id}, ${gh.login})
    ON CONFLICT (github_id) DO UPDATE SET github_login = ${gh.login}
    RETURNING id`;
  const userId = rows[0].id;

  const token = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
  await sql`INSERT INTO tokens (hash, user_id) VALUES (${await sha256Hex(token)}, ${userId})`;

  return new Response(JSON.stringify({ token, githubLogin: gh.login }), {
    headers: { "Content-Type": "application/json" },
  });
};
