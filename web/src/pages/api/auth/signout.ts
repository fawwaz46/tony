/**
 * End a browser session. Deletes the row, then clears the cookie — in that
 * order, so a cookie that survives the round trip is already useless.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, migrate, sha256Hex, sql } from "../../../server/db";
import { safeNext, siteOrigin } from "../../../server/safe";

export const prerender = false;

export const POST: APIRoute = async ({ request, url, cookies, redirect }) => {
  const sessionId = cookies.get(SESSION_COOKIE)?.value;
  if (sessionId) {
    await migrate();
    await sql`DELETE FROM sessions WHERE hash = ${await sha256Hex(sessionId)}`;
  }
  cookies.delete(SESSION_COOKIE, { path: "/" });

  // Signing out to pick a different account has to come back to the page that
  // asked — otherwise a CLI login loses the port and nonce it was carrying, and
  // the terminal waits for a browser that never returns. Validated as a
  // same-site path, since an open redirect here is a phishing gift.
  const form = await request.formData().catch(() => null);
  const next = form?.get("next");
  return redirect(safeNext(typeof next === "string" ? next : null,
                           siteOrigin(request, url.origin), "/"), 302);
};
