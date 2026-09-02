/**
 * The identity providers tony accepts, behind one shape.
 *
 * Adding a provider should be adding an entry here and nothing else: the login
 * page lists whatever is configured, and the callback treats them all alike.
 * A provider with no credentials in the environment is not offered at all,
 * which is what lets a preview deployment run with only GitHub set up.
 *
 * `email` comes back ONLY when the provider says it is verified. Accounts are
 * merged on that address (see `upsertUser`), so an unverified one is a way into
 * someone else's reviews — every provider here has to prove it, or say nothing.
 */
import type { Profile } from "./db";
import { env } from "./env";

export interface Provider {
  id: string;
  label: string;
  authorizeUrl: string;
  tokenUrl: string;
  scope: string;
  /** Extra parameters this provider wants on the authorize redirect. */
  authorizeParams?: Record<string, string>;
  profile(accessToken: string): Promise<Profile | null>;
}

const asJson = async (resp: Response): Promise<any> =>
  resp.ok ? await resp.json().catch(() => null) : null;

/**
 * A GitHub address is only usable if GitHub says it is both primary and
 * verified. The `/user` endpoint's `email` field is neither — it is whatever
 * the profile shows publicly, which the account holder types in freely.
 */
async function githubEmail(accessToken: string): Promise<string | undefined> {
  const emails = await asJson(await fetch("https://api.github.com/user/emails", {
    headers: { Authorization: `Bearer ${accessToken}`, "User-Agent": "tony" },
  }));
  if (!Array.isArray(emails)) return undefined;
  const primary = emails.find((e) => e?.primary && e?.verified && typeof e.email === "string");
  return primary?.email;
}

const github: Provider = {
  id: "github",
  label: "GitHub",
  authorizeUrl: "https://github.com/login/oauth/authorize",
  tokenUrl: "https://github.com/login/oauth/access_token",
  scope: "read:user user:email",
  async profile(accessToken) {
    const user = await asJson(await fetch("https://api.github.com/user", {
      headers: { Authorization: `Bearer ${accessToken}`, "User-Agent": "tony" },
    }));
    if (typeof user?.id !== "number" || typeof user?.login !== "string") return null;
    return {
      provider: "github",
      providerId: String(user.id),
      login: user.login,
      avatarUrl: user.avatar_url ?? "",
      email: await githubEmail(accessToken),
    };
  },
};

const google: Provider = {
  id: "google",
  label: "Google",
  authorizeUrl: "https://accounts.google.com/o/oauth2/v2/auth",
  tokenUrl: "https://oauth2.googleapis.com/token",
  scope: "openid email profile",
  // Google will not issue a refresh token or re-prompt without these, and
  // without `prompt` a second sign-in silently reuses the first account —
  // which looks like tony ignoring the account you picked.
  authorizeParams: { response_type: "code", prompt: "select_account" },
  async profile(accessToken) {
    const user = await asJson(await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }));
    if (typeof user?.sub !== "string") return null;
    return {
      provider: "google",
      providerId: user.sub,
      // Google has no usernames. The local part of the address is the closest
      // thing to one, and beats showing a full email in the page header.
      login: user.name || String(user.email ?? "").split("@")[0] || "you",
      avatarUrl: user.picture ?? "",
      email: user.email_verified === true ? user.email : undefined,
    };
  },
};

const ALL: Provider[] = [github, google];

/** Where a provider's credentials live in the environment. */
const credentials = (id: string) => ({
  clientId: env(`${id.toUpperCase()}_CLIENT_ID`),
  clientSecret: env(`${id.toUpperCase()}_CLIENT_SECRET`),
});

export function provider(id: string | null): Provider | null {
  return ALL.find((p) => p.id === id) ?? null;
}

/** The providers this deployment can actually complete a login with. */
export function configured(): Provider[] {
  return ALL.filter((p) => {
    const { clientId, clientSecret } = credentials(p.id);
    return Boolean(clientId && clientSecret);
  });
}

export function clientId(p: Provider): string | undefined {
  return credentials(p.id).clientId;
}

/** Trade an authorization code for an access token, or null. */
export async function exchangeCode(
  p: Provider, code: string, redirectUri: string,
): Promise<string | null> {
  const { clientId, clientSecret } = credentials(p.id);
  if (!clientId || !clientSecret) return null;

  // Form encoding, not JSON: GitHub accepts either, Google accepts only this.
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    code,
    redirect_uri: redirectUri,
    grant_type: "authorization_code",
  });
  const resp = await fetch(p.tokenUrl, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const token = (await asJson(resp))?.access_token;
  return typeof token === "string" && token ? token : null;
}
