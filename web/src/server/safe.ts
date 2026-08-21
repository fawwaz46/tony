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
