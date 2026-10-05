/**
 * Start an approval link for an agent that has no credentials. See
 * server/link.ts for why there are three values and what each is for.
 *
 * No account is behind this request yet, so it is throttled per address: it
 * only ever creates a row that does nothing until a signed-in person approves
 * it, but rows are not free.
 */
import type { APIRoute } from "astro";
import { fail, migrate, throttle, withDatabase } from "../../server/db";
import { LINK_SECONDS, agentLabel, createLinkRequest } from "../../server/link";
import { siteOrigin } from "../../server/safe";

export const prerender = false;

export const POST: APIRoute = async ({ request, url, clientAddress }) => {
  if (throttle(`link:${clientAddress}`, 10, 60_000)) {
    return fail(429, "too many approval links started in the last minute");
  }
  const body = await request.json().catch(() => ({}));

  return withDatabase(async () => {
    await migrate();
    const { id, pollKey, code } = await createLinkRequest(agentLabel(body?.agent));
    return new Response(
      JSON.stringify({
        url: `${siteOrigin(request, url.origin)}/link/${id}`,
        code,
        pollKey,
        expiresIn: LINK_SECONDS,
      }),
      { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } },
    );
  });
};
