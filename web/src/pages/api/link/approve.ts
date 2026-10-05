/**
 * The Approve button on /link/[id]. A form POST from a signed-in browser:
 * the session cookie says who is approving, and middleware's same-origin check
 * says the click came from this site. A GET of the page never gets here, which
 * is the point: link previews fetch URLs, and must not approve anything.
 */
import type { APIRoute } from "astro";
import { SESSION_COOKIE, migrate, userForSession, withDatabase } from "../../../server/db";
import { approveLink } from "../../../server/link";

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  const form = await request.formData().catch(() => null);
  const id = String(form?.get("id") ?? "");
  if (!/^[a-f0-9]{64}$/.test(id)) return new Response("bad link", { status: 400 });

  return withDatabase(async () => {
    await migrate();
    const user = await userForSession(cookies.get(SESSION_COOKIE)?.value);
    if (!user) return redirect(`/link/${id}`, 303);
    await approveLink(id, user.id);
    // Back to the page, which now shows the outcome: done, or why not.
    return redirect(`/link/${id}?approved=1`, 303);
  });
};
