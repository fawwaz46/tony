/**
 * Postgres (Neon) for identity, sessions, and review metadata.
 *
 * Review bodies live in a private Vercel Blob store, encrypted at rest under
 * a server-held key
 * (see crypto.ts). That is a deliberate step down from the earlier
 * zero-knowledge design: gating reads behind login and offering a history of
 * past reviews both require the server to be able to open a review. It
 * protects against a leaked blob store; it does not protect against a
 * compromise of this server. The privacy policy has to say so.
 *
 * Bearer tokens (CLI) and session ids (browser) are stored only as hashes, so
 * a database leak yields nothing that can be replayed.
 */
import { neon } from "@neondatabase/serverless";
import { env } from "./env";

// Constructed on first query, not at import. `neon()` throws when the
// connection string is missing, and eager construction meant importing this
// module anywhere — including the shell every page renders — took the whole
// site down whenever the database was unset or unreachable. The marketing
// page needs no database and must not depend on one.
// `neon()` types its result as a union covering every response mode it can be
// configured for, which leaves `rows.length` and `rows[0]` errors at every call
// site. We only ever use the default mode — an array of row objects — so the
// tagged template is declared as that. Without this the project cannot be
// type-checked at all, and an undefined identifier in a query once reached
// production because of it.
type Row = Record<string, any>;
type Sql = (strings: TemplateStringsArray, ...values: unknown[]) => Promise<Row[]>;
let client: ReturnType<typeof neon> | null = null;

export const sql: Sql = ((strings: TemplateStringsArray, ...values: unknown[]) => {
  if (!client) {
    const url = env("DATABASE_URL");
    if (!url) throw new Error("DATABASE_URL is not set");
    client = neon(url);
  }
  return (client as any)(strings, ...values);
}) as Sql;

export function databaseConfigured(): boolean {
  return Boolean(env("DATABASE_URL"));
}

/** JSON error body, so a fetch() caller never has to parse an HTML error page. */
export const fail = (status: number, error: string) =>
  new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/**
 * Run a handler that needs the database, turning an outage into an honest 503
 * rather than a stack trace. Auth checks belong *before* this where possible —
 * an unauthenticated request should be rejected without a query.
 */
export async function withDatabase(run: () => Promise<Response>): Promise<Response> {
  if (!databaseConfigured()) return fail(503, "the database is not configured");
  try {
    return await run();
  } catch (e) {
    console.error("database error:", e);
    return fail(503, "the database is unavailable");
  }
}

let migrated = false;

export async function migrate(): Promise<void> {
  if (migrated) return;
  await sql`
    CREATE TABLE IF NOT EXISTS users (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      github_id BIGINT UNIQUE NOT NULL,
      github_login TEXT NOT NULL,
      avatar_url TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )`;
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT NOT NULL DEFAULT ''`;
  // A user is no longer one GitHub account. `login` is whatever they are called
  // wherever they signed in; `email` is only ever written when the provider
  // said it was verified, because it is what accounts are merged on.
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS login TEXT NOT NULL DEFAULT ''`;
  await sql`ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT`;
  await sql`UPDATE users SET login = github_login WHERE login = ''`;

  // One row per provider account, so one person can sign in with GitHub on
  // Monday and Google on Tuesday and land on the same reviews.
  await sql`
    CREATE TABLE IF NOT EXISTS identities (
      provider TEXT NOT NULL,
      provider_id TEXT NOT NULL,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (provider, provider_id)
    )`;
  // Everyone who existed before this table got here through GitHub.
  await sql`
    INSERT INTO identities (provider, provider_id, user_id)
    SELECT 'github', github_id::text, id FROM users WHERE github_id IS NOT NULL
    ON CONFLICT DO NOTHING`;
  // github_id was UNIQUE NOT NULL, which a Google-only user cannot satisfy.
  // The column stays for now — dropping it is a separate, later migration —
  // but it stops being required.
  await sql`ALTER TABLE users ALTER COLUMN github_id DROP NOT NULL`;
  await sql`ALTER TABLE users ALTER COLUMN github_login DROP NOT NULL`;
  // Merging happens on a verified email, so two accounts must never share one.
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS users_by_email
      ON users (lower(email)) WHERE email IS NOT NULL`;
  await sql`
    CREATE TABLE IF NOT EXISTS tokens (
      hash TEXT PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL
    )`;
  // CLI tokens predate the expiry and have no value for the column. The
  // default gives them a full window from the moment this runs rather than
  // signing everyone out at deploy; new rows always supply their own.
  await sql`
    ALTER TABLE tokens ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NOT NULL
      DEFAULT now() + interval '30 days'`;
  await sql`
    CREATE TABLE IF NOT EXISTS sessions (
      hash TEXT PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL
    )`;
  await sql`
    CREATE TABLE IF NOT EXISTS reviews (
      id TEXT PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      repo TEXT NOT NULL DEFAULT '',
      range TEXT NOT NULL DEFAULT '',
      intent TEXT NOT NULL DEFAULT '',
      files INTEGER NOT NULL DEFAULT 0,
      annotations INTEGER NOT NULL DEFAULT 0,
      size INTEGER NOT NULL,
      blob_path TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )`;
  // Older rows predate the summary columns; adding them is idempotent.
  for (const stmt of [
    sql`ALTER TABLE reviews ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT ''`,
    sql`ALTER TABLE reviews ADD COLUMN IF NOT EXISTS files INTEGER NOT NULL DEFAULT 0`,
    sql`ALTER TABLE reviews ADD COLUMN IF NOT EXISTS annotations INTEGER NOT NULL DEFAULT 0`,
  ]) await stmt;
  // Earlier revisions stored a public blob URL; the store is private now and
  // objects are addressed by pathname. Renaming is idempotent and a no-op on
  // a database that never saw the old column.
  await sql`
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'reviews' AND column_name = 'blob_url')
         AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'reviews' AND column_name = 'blob_path')
      THEN ALTER TABLE reviews RENAME COLUMN blob_url TO blob_path;
      END IF;
    END $$;`;
  await sql`CREATE INDEX IF NOT EXISTS reviews_by_user ON reviews (user_id, created_at DESC)`;
  // The handoff from a browser login back to the waiting CLI. The browser is
  // redirected to the CLI's loopback port carrying one of these, never a token:
  // a redirect URL lands in history and in the referrer of anything the landing
  // page loads, and this is worth nothing sixty seconds later or twice.
  await sql`
    CREATE TABLE IF NOT EXISTS cli_codes (
      hash TEXT PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at TIMESTAMPTZ NOT NULL
    )`;
  migrated = true;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function randomToken(): string {
  return [...crypto.getRandomValues(new Uint8Array(32))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export interface User {
  id: number;
  /** Whatever this person is called wherever they signed in. */
  login: string;
  avatarUrl: string;
}

/** The CLI's identity: an `Authorization: Bearer` token. */
export async function userForToken(header: string | null): Promise<User | null> {
  const token = header?.match(/^Bearer (.+)$/)?.[1];
  if (!token) return null;
  const rows = await sql`
    SELECT u.id, u.login, u.avatar_url
    FROM tokens t JOIN users u ON u.id = t.user_id
    WHERE t.hash = ${await sha256Hex(token)} AND t.expires_at > now()`;
  if (!rows.length) return null;
  return { id: Number(rows[0].id), login: rows[0].login, avatarUrl: rows[0].avatar_url };
}

export const SESSION_COOKIE = "tony_session";

/**
 * How long a credential lasts before its owner signs in again.
 *
 * The same window for the browser and the CLI. A CLI token used to last
 * forever, which made a copied `~/.tony/credentials.json` a permanent one —
 * there is no device list to revoke it from, so the expiry is the only thing
 * that ever takes it away.
 */
export const CREDENTIAL_DAYS = 30;

/**
 * Crude per-IP throttle for endpoints that have no account behind them yet.
 *
 * In-memory, so it resets on cold start and is per-instance rather than
 * global. That makes it a speed bump, not a wall — but the alternative was
 * nothing at all on the one route that mints sessions.
 */
const hits = new Map<string, number[]>();

export function throttle(key: string, limit: number, windowMs: number): boolean {
  const now = Date.now();
  const recent = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
  recent.push(now);
  hits.set(key, recent);
  if (hits.size > 5000) hits.clear(); // bounded; this is a speed bump, not state
  return recent.length > limit;
}

/** The browser's identity: a session cookie. */
export async function userForSession(sessionId: string | undefined): Promise<User | null> {
  if (!sessionId) return null;
  const rows = await sql`
    SELECT u.id, u.login, u.avatar_url
    FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.hash = ${await sha256Hex(sessionId)} AND s.expires_at > now()`;
  if (!rows.length) return null;
  return { id: Number(rows[0].id), login: rows[0].login, avatarUrl: rows[0].avatar_url };
}

export async function createSession(userId: number): Promise<string> {
  const id = randomToken();
  await sql`
    INSERT INTO sessions (hash, user_id, expires_at)
    VALUES (${await sha256Hex(id)}, ${userId},
            now() + make_interval(days => ${CREDENTIAL_DAYS}::int))`;
  return id;
}

/** The CLI's credential. Same shape as a session, same window. */
export async function createToken(userId: number): Promise<string> {
  const token = randomToken();
  await sql`
    INSERT INTO tokens (hash, user_id, expires_at)
    VALUES (${await sha256Hex(token)}, ${userId},
            now() + make_interval(days => ${CREDENTIAL_DAYS}::int))`;
  return token;
}

/** One account as a provider described it. `email` is set ONLY if verified. */
export interface Profile {
  provider: string;
  providerId: string;
  login: string;
  avatarUrl?: string;
  email?: string;
}

/**
 * The user behind a provider account, created or updated.
 *
 * Two accounts merge only on an email the provider swore was verified. That
 * restriction is the whole security of this function: an unverified address is
 * something a signup form will accept without proof, so merging on one would
 * let anyone reach an existing account by claiming its owner's email at a
 * provider that never checked. A profile arriving without a verified email
 * gets its own user, which is the safe failure.
 */
export async function upsertUser(profile: Profile): Promise<number> {
  const { provider, providerId, login } = profile;
  const avatarUrl = profile.avatarUrl ?? "";
  const email = profile.email ?? null;

  const known = await sql`
    SELECT user_id FROM identities
    WHERE provider = ${provider} AND provider_id = ${providerId}`;
  if (known.length) {
    const userId = Number(known[0].user_id);
    await sql`
      UPDATE users SET login = ${login}, avatar_url = ${avatarUrl},
                       email = COALESCE(${email}, email)
      WHERE id = ${userId}`;
    return userId;
  }

  // A first sign-in with this provider. If a verified email already belongs to
  // an account, this is the same person arriving by a second door.
  let userId: number | null = null;
  if (email) {
    const byEmail = await sql`SELECT id FROM users WHERE lower(email) = lower(${email})`;
    if (byEmail.length) userId = Number(byEmail[0].id);
  }

  if (userId === null) {
    const created = await sql`
      INSERT INTO users (login, avatar_url, email)
      VALUES (${login}, ${avatarUrl}, ${email})
      RETURNING id`;
    userId = Number(created[0].id);
  }

  await sql`
    INSERT INTO identities (provider, provider_id, user_id)
    VALUES (${provider}, ${providerId}, ${userId})
    ON CONFLICT (provider, provider_id) DO NOTHING`;
  return userId;
}

/** How long the browser has to hand its code back to the waiting CLI. */
const CLI_CODE_SECONDS = 120;

/** A one-time code the CLI can trade for a token. */
export async function createCliCode(userId: number): Promise<string> {
  const code = randomToken();
  await sql`
    INSERT INTO cli_codes (hash, user_id, expires_at)
    VALUES (${await sha256Hex(code)}, ${userId},
            now() + make_interval(secs => ${CLI_CODE_SECONDS}::int))`;
  return code;
}

/**
 * Spend a code and return whose it was, or null.
 *
 * The delete is the check: `DELETE ... RETURNING` is atomic, so two requests
 * racing with the same code cannot both come back with a user. Expired rows
 * are removed on the way past rather than by a job.
 */
export async function spendCliCode(code: string): Promise<number | null> {
  const rows = await sql`
    DELETE FROM cli_codes
    WHERE hash = ${await sha256Hex(code)} AND expires_at > now()
    RETURNING user_id`;
  await sql`DELETE FROM cli_codes WHERE expires_at <= now()`;
  return rows.length ? Number(rows[0].user_id) : null;
}
