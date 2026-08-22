/**
 * Guards for values that arrive from outside and end up somewhere dangerous.
 */

/**
 * Where a login may return to.
 *
 * String prefix checks do not work here. `/\evil.com` and `/..//evil.com` both
 * start with a single slash, and browsers normalise both to `//evil.com`,
 * which is protocol-relative — an open redirect, and a ready-made phishing
 * page on our own domain. Both were reachable before this existed.
 *
 * Parsing against the real origin is the only reliable test: whatever the URL
 * resolves to must be us, and only its path and query survive.
 */
export function safeNext(raw: string | null | undefined, origin: string, fallback = "/reviews"): string {
  if (!raw) return fallback;
  let parsed: URL;
  try {
    parsed = new URL(raw, origin);
  } catch {
    return fallback;
  }
  const self = new URL(origin).origin;
  if (parsed.origin !== self) return fallback;

  // Never carry a fragment back; it is not ours to preserve.
  const path = parsed.pathname + parsed.search;

  // Resolving is not enough on its own. `/..//evil.com` normalises to the
  // pathname `//evil.com`, which is same-origin as a *parse* but becomes a
  // protocol-relative URL the moment it is written to a Location header. So
  // re-resolve the answer and require that it still points at us.
  try {
    if (new URL(path, origin).origin !== self) return fallback;
  } catch {
    return fallback;
  }
  return path.startsWith("/") ? path : fallback;
}

/**
 * A user-supplied string on its way into a database column and then a page.
 *
 * Payloads are uploaded whole and nothing else bounds these, so without a cap
 * a single review could carry a megabyte of "intent" into every dashboard row.
 */
export function capped(value: unknown, max: number): string {
  const s = typeof value === "string" ? value : "";
  return s.length > max ? s.slice(0, max) : s;
}

/**
 * The origin this request actually arrived on.
 *
 * Behind Vercel's proxy `Astro.url.origin` is the internal address, not the
 * public one — it resolved to `https://localhost`, which we then handed to
 * GitHub as the OAuth redirect_uri. Login could never have completed.
 *
 * Order matters. A configured canonical URL wins, because the forwarded
 * headers are attacker-influenced on a host that does not sanitise them and
 * this value ends up in redirects and OAuth callbacks. The headers are the
 * fallback so preview deployments, which have no fixed domain, still work.
 */
export function siteOrigin(request: Request, fallback: string): string {
  const configured =
    (typeof process !== "undefined" ? process.env?.TONY_SITE_URL : undefined) ?? "";
  if (configured) return configured.replace(/\/+$/, "");

  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (host && /^[a-zA-Z0-9.:-]+$/.test(host)) {
    // Fall back to the scheme this request actually came in on rather than
    // assuming https, so http://localhost during development still matches.
    const proto =
      request.headers.get("x-forwarded-proto")?.split(",")[0] ??
      new URL(fallback).protocol.replace(":", "");
    return `${proto}://${host}`;
  }
  return fallback;
}
