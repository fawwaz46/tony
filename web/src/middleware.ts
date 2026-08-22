/**
 * Security headers on every response.
 *
 * These are the layer that would have contained the stored-XSS bug in the
 * renderer rather than letting it reach a reader's session, so they are worth
 * having even though that specific hole is closed: the next escaping mistake
 * gets caught by the browser instead of by luck.
 *
 * The CSP is deliberately strict about where code and data may come from.
 * `'unsafe-inline'` for scripts is present because Astro inlines the small
 * page scripts, and moving to a nonce means threading one through every
 * inline block — worth doing, but not at the cost of shipping no CSP at all.
 * Everything else is locked down: no plugins, no framing, no form posts off
 * site, and images limited to ourselves plus GitHub avatars.
 */
import type { MiddlewareHandler } from "astro";
import { siteOrigin } from "./server/safe";

/** Methods that can change something, and therefore need CSRF protection. */
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  // GitHub avatars appear in the signed-in header.
  "img-src 'self' data: https://avatars.githubusercontent.com",
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

/**
 * Is this state-changing request one of ours?
 *
 * Origin alone is not enough. A `<form>` submission is a navigation, and for
 * navigations the browser serialises Origin according to the page's referrer
 * policy — under `no-referrer` it sends the literal string `null`, which is
 * truthy and never matches, so an Origin-only check refuses the site's own
 * sign-out form. `fetch()` is unaffected, which is why the dashboard delete
 * worked and sign-out did not.
 *
 * Sec-Fetch-Site says the same thing without the referrer-policy coupling: it
 * is set by the browser, cannot be spoofed by a page, and is the signal to
 * trust when present. Origin is the fallback for clients that omit it, and an
 * absent Origin there means the caller is not a browser — the CLI, curl — and
 * those authenticate with a bearer token, which a hostile page cannot make a
 * browser send.
 */
export function sameSite(request: Request, fallbackOrigin: string): boolean {
  const site = request.headers.get("sec-fetch-site");
  // `none` is a user-initiated load (typed URL, bookmark); no other site is
  // involved, so it is not cross-site.
  if (site) return site === "same-origin" || site === "none";
  const origin = request.headers.get("origin");
  return !origin || origin === siteOrigin(request, fallbackOrigin);
}

export const onRequest: MiddlewareHandler = async (context, next) => {
  const method = context.request.method.toUpperCase();
  const response =
    UNSAFE.has(method) && !sameSite(context.request, context.url.origin)
      ? new Response("cross-site request refused", {
          status: 403,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        })
      : await next();
  // The installer is a shell script piped into sh; page security headers do
  // not apply to it and only add noise.
  if (context.url.pathname === "/install.sh") return response;
  const h = response.headers;
  h.set("Content-Security-Policy", CSP);
  h.set("X-Content-Type-Options", "nosniff");
  // A review id is what grants access to a review, so it has no business
  // reaching a third-party destination; `same-origin` sends nothing across an
  // origin boundary. It is deliberately not `no-referrer`: that policy makes
  // browsers send `Origin: null` on form submissions, which the CSRF check
  // above then has to work around.
  h.set("Referrer-Policy", "same-origin");
  h.set("X-Frame-Options", "DENY");
  h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
};
