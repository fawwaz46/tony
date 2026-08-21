/**
 * Public configuration the CLI needs before it can log in.
 *
 * A GitHub OAuth client id is public by design (the device flow has no client
 * secret), so serving it here means the CLI never ships one and the app can be
 * rotated without a CLI release.
 */
import type { APIRoute } from "astro";

export const prerender = false;

export const GET: APIRoute = () =>
  new Response(
    JSON.stringify({ githubClientId: import.meta.env.GITHUB_CLIENT_ID ?? "" }),
    { headers: { "Content-Type": "application/json" } },
  );
