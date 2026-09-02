/**
 * Begin a login, for a browser or for a waiting CLI.
 *
 * Both go through the same provider redirect. The difference is only where the
 * callback sends the visitor afterwards: an ordinary login lands back on the
 * site, a CLI login lands on the loopback port `tony login` is listening on.
 *
 * Everything that has to survive the round trip rides in a short-lived
 * httpOnly cookie rather than in the URL, so none of it can be chosen by
 * whoever crafted the link.
 */
import type { APIRoute } from "astro";
import { throttle } from "../../../server/db";
import { clientId, configured, provider } from "../../../server/providers";
import { safeNext, siteOrigin } from "../../../server/safe";

export const prerender = false;

/**
 * The loopback port a CLI says it is listening on.
 *
 * Only used to build a `http://127.0.0.1:<port>` redirect, so the entire risk
 * is sending the visitor somewhere on their own machine. Bounded to the
 * unprivileged range and to digits, which is what keeps it from being anything
 * other than a port.
 */
function cliPort(raw: string | null): number | null {
  if (!raw || !/^\d{1,5}$/.test(raw)) return null;
  const port = Number(raw);
  return port >= 1024 && port <= 65535 ? port : null;
}

/** The nonce the CLI generated, echoed back to it so it can trust the callback. */
function cliState(raw: string | null): string | null {
  return raw && /^[a-f0-9]{16,64}$/.test(raw) ? raw : null;
}

export const GET: APIRoute = ({ url, request, cookies, redirect, clientAddress }) => {
  if (throttle(`start:${clientAddress}`, 30, 60_000)) {
    return new Response("too many attempts", { status: 429 });
  }

  const chosen = provider(url.searchParams.get("provider"));
  // An unconfigured provider must not reach the redirect: it would send the
  // visitor to a provider with an empty client_id and an error page nobody can
  // act on. Say so on a page instead.
  if (!chosen || !configured().some((p) => p.id === chosen.id)) {
    return redirect("/login?error=unavailable", 302);
  }

  const origin = siteOrigin(request, url.origin);
  const port = cliPort(url.searchParams.get("cli"));
  const cli = cliState(url.searchParams.get("cliState"));

  // Bound to the browser, checked on the way back: this is the CSRF guard.
  const state = crypto.randomUUID();
  cookies.set("tony_oauth", JSON.stringify({
    state,
    provider: chosen.id,
    next: safeNext(url.searchParams.get("next"), origin),
    ...(port && cli ? { cliPort: port, cliState: cli } : {}),
  }), {
    httpOnly: true,
    secure: origin.startsWith("https:"),
    sameSite: "lax",
    path: "/",
    maxAge: 600,
  });

  const authorize = new URL(chosen.authorizeUrl);
  authorize.searchParams.set("client_id", clientId(chosen)!);
  authorize.searchParams.set("redirect_uri", `${origin}/api/auth/callback`);
  authorize.searchParams.set("scope", chosen.scope);
  authorize.searchParams.set("state", state);
  for (const [k, v] of Object.entries(chosen.authorizeParams ?? {})) {
    authorize.searchParams.set(k, v);
  }
  return redirect(authorize.toString(), 302);
};
