/**
 * Begin a browser login.
 *
 * The CLI uses GitHub's device flow; a browser uses the ordinary redirect
 * flow, and both run against the same OAuth app. `next` carries where the
 * visitor was headed so a link they clicked while logged out still lands on
 * the review afterwards — it is validated as a same-site path, since an open
 * redirect here would be a phishing gift.
 */
import type { APIRoute } from "astro";
import { throttle } from "../../../server/db";
import { env } from "../../../server/env";
import { safeNext } from "../../../server/safe";

export const prerender = false;

export const GET: APIRoute = ({ url, cookies, redirect, clientAddress }) => {
  if (throttle(`start:${clientAddress}`, 30, 60_000)) {
    return new Response("too many attempts", { status: 429 });
  }

  const clientId = env("GITHUB_CLIENT_ID");
  // A misconfigured site should say so on a page the visitor can read, not
  // hand them a bare 500 from an endpoint they never chose to visit.
  if (!clientId) return redirect("/?error=unconfigured", 302);

  const next = safeNext(url.searchParams.get("next"), url.origin);

  // Bound to the browser, checked on the way back: this is the CSRF guard.
  const state = crypto.randomUUID();
  cookies.set("tony_oauth", JSON.stringify({ state, next }), {
    httpOnly: true,
    secure: url.protocol === "https:",
    sameSite: "lax",
    path: "/",
    maxAge: 600,
  });

  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", clientId);
  authorize.searchParams.set("redirect_uri", new URL("/api/auth/callback", url.origin).toString());
  authorize.searchParams.set("scope", "read:user");
  authorize.searchParams.set("state", state);
  return redirect(authorize.toString(), 302);
};
