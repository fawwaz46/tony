/**
 * Trade a GitHub access token (from the CLI's device flow) for a tony token.
 *
 * The GitHub token is used once, to ask GitHub who this is, and never stored.
 * The tony token is minted here, returned once, and kept only as a hash — so a
 * database leak leaks no usable secret.
 */
import type { APIRoute } from "astro";
import { createToken, migrate, throttle, upsertUser, withDatabase } from "../../../server/db";
import { env } from "../../../server/env";
import { provider } from "../../../server/providers";

export const prerender = false;

interface GitHubUser {
  id: number;
  login: string;
  avatar_url?: string;
}

/**
 * Who this token belongs to — but only if our own OAuth app issued it.
 *
 * `GET /user` is the obvious call and the wrong one: it answers for any valid
 * token from any OAuth app. Someone who persuades a victim to authorise an
 * unrelated app for something as innocuous as `read:user` could then post that
 * token here and walk away with a tony token bound to the victim's account.
 * `POST /applications/{client_id}/token` is the audience-checked equivalent —
 * it authenticates as the app and 404s a token the app did not issue — and it
 * returns the user, so it replaces the `/user` call rather than adding to it.
 */
async function tokenHolder(accessToken: string): Promise<GitHubUser | null> {
  const clientId = env("GITHUB_CLIENT_ID");
  const clientSecret = env("GITHUB_CLIENT_SECRET");
  // Fail closed: without credentials there is no way to check the audience,
  // and an unchecked token is exactly what this function exists to refuse.
  if (!clientId || !clientSecret) return null;

  const resp = await fetch(`https://api.github.com/applications/${clientId}/token`, {
    method: "POST",
    headers: {
      Authorization: `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "tony",
    },
    body: JSON.stringify({ access_token: accessToken }),
  });
  if (!resp.ok) return null;

  const user = (await resp.json())?.user;
  if (typeof user?.id !== "number" || typeof user?.login !== "string") return null;
  return user as GitHubUser;
}

export const POST: APIRoute = async ({ request, clientAddress }) => {
  // This route mints a long-lived CLI token, so it must not be free to hammer.
  if (throttle(`auth:${clientAddress}`, 10, 60_000)) {
    return new Response("too many attempts", { status: 429 });
  }

  const { accessToken } = await request.json().catch(() => ({}));
  if (typeof accessToken !== "string" || !accessToken) {
    return new Response("missing accessToken", { status: 400 });
  }

  const gh = await tokenHolder(accessToken);
  if (!gh) return new Response("github rejected the token", { status: 401 });

  return withDatabase(async () => {
    await migrate();
    // The device flow talks to GitHub directly, so it reuses the GitHub
    // provider's own profile reader rather than keeping a second idea of what
    // a GitHub account looks like — including which email counts as verified.
    const profile = (await provider("github")!.profile(accessToken)) ?? {
      provider: "github", providerId: String(gh.id), login: gh.login,
      avatarUrl: gh.avatar_url ?? "",
    };
    const token = await createToken(await upsertUser(profile));

    return new Response(JSON.stringify({ token, login: gh.login, githubLogin: gh.login }), {
      headers: { "Content-Type": "application/json" },
    });
  });
};
