/**
 * Approving a sandboxed agent with one click.
 *
 * A sandbox (an Amp orb, Codex cloud, Claude Code on the web) starts with no
 * credentials, so `tony_start` asks for a link instead: the agent shows it to
 * its person, they approve it in a browser where they are signed in, and the
 * agent's next `tony_start` collects a token.
 *
 * Three values, each doing one job:
 *
 * - The link id is long and random and lives only in the URL. It is what the
 *   approve page is found by, so it must be unguessable: with a short one,
 *   someone could walk pending ids and approve a stranger's sandbox into
 *   their own account, and read the code it publishes next.
 * - The code is six characters, shown by the agent and on the page, so the
 *   person can see the page belongs to their agent. It protects nothing by
 *   itself, which is why it can be short.
 * - The poll key never leaves the sandbox. Only it can collect the token, so
 *   knowing the link is never enough to take one.
 *
 * Approval happens only on a POST from the page's button, never on GET: chat
 * apps fetch links to draw previews, and a preview must not approve anything.
 * Requests last ten minutes and are spent the moment their token is collected.
 */
import { createToken, randomToken, sha256Hex, sql } from "./db";

/** How long a request waits for its person, and again for its agent once approved. */
export const LINK_SECONDS = 600;

// No 0/O or 1/I, so the code cannot be misread. 32 symbols, so a random byte
// maps onto one without bias.
const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function linkCode(): string {
  return [...crypto.getRandomValues(new Uint8Array(6))]
    .map((b) => CODE_ALPHABET[b % CODE_ALPHABET.length])
    .join("");
}

/** What the agent says it is, shown on the page. Plain text, a few words. */
export function agentLabel(raw: unknown): string {
  return typeof raw === "string" ? raw.replace(/[^\w .+-]/g, "").trim().slice(0, 40) : "";
}

export async function createLinkRequest(agent: string) {
  const id = randomToken();
  const pollKey = randomToken();
  const code = linkCode();
  await sql`
    INSERT INTO link_requests (hash, poll_hash, code, agent, expires_at)
    VALUES (${await sha256Hex(id)}, ${await sha256Hex(pollKey)}, ${code}, ${agent},
            now() + make_interval(secs => ${LINK_SECONDS}::int))`;
  // Expired requests go on the way past rather than by a job.
  await sql`DELETE FROM link_requests WHERE expires_at <= now()`;
  return { id, pollKey, code };
}

export interface LinkRequest {
  code: string;
  agent: string;
  approvedBy: number | null;
  createdAt: Date;
}

/** A request that is still live, by its link id, or null. */
export async function linkRequest(id: string): Promise<LinkRequest | null> {
  const rows = await sql`
    SELECT code, agent, user_id, created_at FROM link_requests
    WHERE hash = ${await sha256Hex(id)} AND expires_at > now()`;
  if (!rows.length) return null;
  return {
    code: rows[0].code,
    agent: rows[0].agent,
    approvedBy: rows[0].user_id === null ? null : Number(rows[0].user_id),
    createdAt: new Date(rows[0].created_at),
  };
}

/**
 * Approve a request for a user. False if it was not there to approve: gone,
 * expired, or already approved, by anyone. Approval restarts the clock, so the
 * person has the full window to get back to their agent.
 */
export async function approveLink(id: string, userId: number): Promise<boolean> {
  const rows = await sql`
    UPDATE link_requests
    SET user_id = ${userId}, approved_at = now(),
        expires_at = now() + make_interval(secs => ${LINK_SECONDS}::int)
    WHERE hash = ${await sha256Hex(id)} AND approved_at IS NULL AND expires_at > now()
    RETURNING code`;
  return rows.length > 0;
}

export type Collected =
  | { status: "approved"; token: string; login: string }
  | { status: "pending" }
  | { status: "expired" };

/**
 * Trade a poll key for a token, once.
 *
 * The delete is the check, as with CLI codes: `DELETE ... RETURNING` is
 * atomic, so two polls racing with one key cannot both come away with a token.
 */
export async function collectLink(pollKey: string): Promise<Collected> {
  const hash = await sha256Hex(pollKey);
  const spent = await sql`
    DELETE FROM link_requests
    WHERE poll_hash = ${hash} AND approved_at IS NOT NULL AND expires_at > now()
    RETURNING user_id, agent`;
  if (spent.length) {
    const userId = Number(spent[0].user_id);
    const token = await createToken(userId, "link", spent[0].agent);
    const users = await sql`SELECT login FROM users WHERE id = ${userId}`;
    return { status: "approved", token, login: users[0]?.login ?? "" };
  }
  const waiting = await sql`
    SELECT 1 FROM link_requests WHERE poll_hash = ${hash} AND expires_at > now()`;
  return waiting.length ? { status: "pending" } : { status: "expired" };
}
