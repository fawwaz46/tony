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

export const onRequest: MiddlewareHandler = async (_context, next) => {
  const response = await next();
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
