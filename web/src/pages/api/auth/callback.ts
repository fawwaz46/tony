/**
 * Finish a login: verify state, trade the code, start a session.
 *
 * The provider's access token is used once to ask who this is and never
 * stored — the session cookie is tony's own, and revocable from tony's own
 * tables.
 *
 * A CLI login ends here too. It gets the same session cookie, so the browser
 * it just used is signed in as well, and is then sent to the loopback port the
 * CLI is listening on carrying a one-time code. Never the token itself: a
 * redirect URL lands in browser history and in the referrer of anything the
 * landing page loads.
 */
import type { APIRoute } from "astro";
import {
  SESSION_COOKIE, createCliCode, createSession, migrate, upsertUser,
} from "../../../server/db";
import { exchangeCode, provider } from "../../../server/providers";
import { safeNext, siteOrigin } from "../../../server/safe";

export const prerender = false;

interface Pending {
  state: string;
  provider: string;
  next: string;
  cliPort?: number;
  cliState?: string;
}

export const GET: APIRoute = async ({ url, request, cookies, redirect }) => {
  const raw = cookies.get("tony_oauth")?.value;
  cookies.delete("tony_oauth", { path: "/" });

  const origin = siteOrigin(request, url.origin);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!raw || !code || !state) return redirect("/login?error=login", 302);

  let expected: Pending;
  try {
    expected = JSON.parse(raw);
  } catch {
    return redirect("/login?error=login", 302);
  }
  if (expected.state !== state) return redirect("/login?error=login", 302);

  // Which provider this is comes from the cookie, not the URL. Reading it from
  // the query would let a crafted callback have one provider's code redeemed
  // against another's credentials.
  const chosen = provider(expected.provider);
  if (!chosen) return redirect("/login?error=login", 302);

  const accessToken = await exchangeCode(chosen, code, `${origin}/api/auth/callback`);
  if (!accessToken) return redirect("/login?error=login", 302);

  const profile = await chosen.profile(accessToken);
  if (!profile) return redirect("/login?error=login", 302);

  await migrate();
  const userId = await upsertUser(profile);
  const sessionId = await createSession(userId);
  cookies.set(SESSION_COOKIE, sessionId, {
    httpOnly: true,
    secure: origin.startsWith("https:"),
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });

  if (expected.cliPort && expected.cliState) {
    const handoff = await createCliCode(userId);
    const loopback = new URL(`http://127.0.0.1:${expected.cliPort}/`);
    loopback.searchParams.set("code", handoff);
    loopback.searchParams.set("state", expected.cliState);
    return redirect(loopback.toString(), 302);
  }

  // Re-validated on the way back: the cookie is ours, but it round-tripped
  // through the browser and costs nothing to check twice.
  return redirect(safeNext(expected.next, origin), 302);
};
