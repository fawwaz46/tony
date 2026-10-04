/**
 * How long a review lives, and the two ways it stops living.
 *
 * A review is somebody's source code, decrypted on request by a server that
 * holds the key. The least of it worth keeping is as long as a change takes to
 * be read: a PR's life, a week of onboarding. Thirty days covers that, and it
 * puts a ceiling on both what a breach could reach and what storage costs —
 * the one cost here that otherwise grows with use forever.
 *
 * Expiry is enforced at read, not by the sweep: `[id].ts` refuses anything
 * older than the window, so the promise holds even when nothing has swept in a
 * while. The sweep is what makes the bytes actually go away, and it runs in
 * small batches off the back of uploads rather than on a cron — no schedule to
 * configure, no secret to provision, and a site nobody publishes to has
 * nothing new to sweep.
 */
import { del } from "@vercel/blob";
import { blobToken } from "./env";
import { sql } from "./db";

// Every query that tests age spells the window as
// `make_interval(days => ${RETENTION_DAYS}::int)`, so this is the one number.
export const RETENTION_DAYS = 30;

/**
 * Delete up to `limit` expired reviews, blobs first. Returns how many went.
 *
 * Blobs before rows: a row whose blob is gone is a 404, which is what an
 * expired review should be anyway; a blob whose row is gone is source code
 * nothing will ever find again to delete.
 */
export async function sweepExpired(limit = 25): Promise<number> {
  const rows = await sql`
    SELECT id, blob_path FROM reviews
    WHERE created_at < now() - make_interval(days => ${RETENTION_DAYS}::int)
    ORDER BY created_at LIMIT ${limit}`;
  if (!rows.length) return 0;
  await del(rows.map((r: any) => r.blob_path), blobToken());
  await sql`DELETE FROM reviews WHERE id = ANY(${rows.map((r: any) => r.id)})`;
  return rows.length;
}

/**
 * Delete an account and everything it owns.
 *
 * Every table hangs off `users` with ON DELETE CASCADE — identities, tokens,
 * sessions, CLI codes, review rows — so the row goes in one statement. The
 * blobs are not in Postgres and cascade nowhere, so they go first, for the
 * same reason as in the sweep.
 */
export async function deleteAccount(userId: number): Promise<void> {
  const rows = await sql`SELECT blob_path FROM reviews WHERE user_id = ${userId}`;
  if (rows.length) await del(rows.map((r: any) => r.blob_path), blobToken());
  await sql`DELETE FROM users WHERE id = ${userId}`;
}
