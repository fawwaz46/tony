/**
 * Collect the token for an approved link, with the poll key only the sandbox
 * holds. 200 with the token once approved, 202 while waiting, 404 once the
 * request has expired or was already collected.
 */
import type { APIRoute } from "astro";
import { fail, migrate, throttle, withDatabase } from "../../../server/db";
import { collectLink } from "../../../server/link";

export const prerender = false;

export const POST: APIRoute = async ({ request, clientAddress }) => {
  // An agent polls a few times a minute at most; anything faster is guessing.
  if (throttle(`poll:${clientAddress}`, 60, 60_000)) {
    return fail(429, "polling too fast");
  }
  const { pollKey } = await request.json().catch(() => ({}));
  if (typeof pollKey !== "string" || !/^[a-f0-9]{64}$/.test(pollKey)) {
    return fail(400, "missing poll key");
  }

  return withDatabase(async () => {
    await migrate();
    const result = await collectLink(pollKey);
    const status = result.status === "approved" ? 200 : result.status === "pending" ? 202 : 404;
    return new Response(JSON.stringify(result), {
      status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  });
};
