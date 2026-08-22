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

export const onRequest: MiddlewareHandler = async (context, next) => {
  // CSRF. A browser attaches Origin to every state-changing request, so a
  // present-but-wrong Origin is a cross-site attempt and gets refused. An
  // absent Origin means the caller is not a browser — the CLI, curl — and
  // those authenticate with a bearer token, which a hostile page cannot make
  // a browser send.
  const method = context.request.method.toUpperCase();
  if (UNSAFE.has(method)) {
    const origin = context.request.headers.get("origin");
    if (origin && origin !== siteOrigin(context.request, context.url.origin)) {
      return new Response("cross-site request refused", { status: 403 });
    }
  }

  const response = await next();
  // The installer is a shell script piped into sh; page security headers do
  // not apply to it and only add noise.
  if (context.url.pathname === "/install.sh") return response;
  const h = response.headers;
  h.set("Content-Security-Policy", CSP);
  h.set("X-Content-Type-Options", "nosniff");
  h.set("Referrer-Policy", "no-referrer");
  // Reviews are private; a referrer or an embedding page has no business
  // learning a review id.
  h.set("X-Frame-Options", "DENY");
  h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
};
