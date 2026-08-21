/**
 * Finish a browser login: verify state, trade the code, start a session.
 *
 * The GitHub access token is used once to ask who this is and never stored —
 * the session cookie is tony's own, and revocable from tony's own tables.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, createSession, migrate, upsertUser } from "../../../server/db";
import { env } from "../../../server/env";
import { safeNext, siteOrigin } from "../../../server/safe";

export const prerender = false;

export const GET: APIRoute = async ({ url, request, cookies, redirect }) => {
  const raw = cookies.get("tony_oauth")?.value;
  cookies.delete("tony_oauth", { path: "/" });

  const origin = siteOrigin(request, url.origin);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!raw || !code || !state) return redirect("/?error=login", 302);

  let expected: { state: string; next: string };
  try {
    expected = JSON.parse(raw);
  } catch {
    return redirect("/?error=login", 302);
  }
  if (expected.state !== state) return redirect("/?error=login", 302);

  const tokenResp = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env("GITHUB_CLIENT_ID"),
      client_secret: env("GITHUB_CLIENT_SECRET"),
      code,
      redirect_uri: `${origin}/api/auth/callback`,
    }),
  });
  const token = (await tokenResp.json())?.access_token;
  if (!token) return redirect("/?error=login", 302);

  const ghResp = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${token}`, "User-Agent": "tony" },
  });
  if (!ghResp.ok) return redirect("/?error=login", 302);
  const gh = await ghResp.json();

  await migrate();
  const sessionId = await createSession(await upsertUser(gh));
  cookies.set(SESSION_COOKIE, sessionId, {
    httpOnly: true,
    secure: origin.startsWith("https:"),
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });

  // Re-validated on the way back: the cookie is ours, but it round-tripped
  // through the browser and costs nothing to check twice.
  return redirect(safeNext(expected.next, origin), 302);
};
