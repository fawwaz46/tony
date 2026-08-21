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

// Constructed on first query, not at import. `neon()` throws when the
// connection string is missing, and eager construction meant importing this
// module anywhere — including the shell every page renders — took the whole
// site down whenever the database was unset or unreachable. The marketing
// page needs no database and must not depend on one.
type Sql = ReturnType<typeof neon>;
let client: Sql | null = null;

export const sql: Sql = ((strings: TemplateStringsArray, ...values: unknown[]) => {
  if (!client) {
    const url = import.meta.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    client = neon(url);
  }
  return (client as any)(strings, ...values);
}) as Sql;

export function databaseConfigured(): boolean {
  return Boolean(import.meta.env.DATABASE_URL);
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
  await sql`
    CREATE TABLE IF NOT EXISTS tokens (
      hash TEXT PRIMARY KEY,
      user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )`;
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
  githubLogin: string;
  avatarUrl: string;
}

/** The CLI's identity: an `Authorization: Bearer` token. */
export async function userForToken(header: string | null): Promise<User | null> {
  const token = header?.match(/^Bearer (.+)$/)?.[1];
  if (!token) return null;
  const rows = await sql`
    SELECT u.id, u.github_login, u.avatar_url
    FROM tokens t JOIN users u ON u.id = t.user_id
    WHERE t.hash = ${await sha256Hex(token)}`;
  if (!rows.length) return null;
  return { id: Number(rows[0].id), githubLogin: rows[0].github_login, avatarUrl: rows[0].avatar_url };
}

export const SESSION_COOKIE = "tony_session";

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
    SELECT u.id, u.github_login, u.avatar_url
    FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.hash = ${await sha256Hex(sessionId)} AND s.expires_at > now()`;
  if (!rows.length) return null;
  return { id: Number(rows[0].id), githubLogin: rows[0].github_login, avatarUrl: rows[0].avatar_url };
}

export async function createSession(userId: number): Promise<string> {
  const id = randomToken();
  await sql`
    INSERT INTO sessions (hash, user_id, expires_at)
    VALUES (${await sha256Hex(id)}, ${userId}, now() + interval '30 days')`;
  return id;
}

export async function upsertUser(gh: { id: number; login: string; avatar_url?: string }): Promise<number> {
  const rows = await sql`
    INSERT INTO users (github_id, github_login, avatar_url)
    VALUES (${gh.id}, ${gh.login}, ${gh.avatar_url ?? ""})
    ON CONFLICT (github_id) DO UPDATE
      SET github_login = ${gh.login}, avatar_url = ${gh.avatar_url ?? ""}
    RETURNING id`;
  return Number(rows[0].id);
}
