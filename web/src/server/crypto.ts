/**
 * Encryption at rest for review payloads.
 *
 * A review is AES-256-GCM sealed under a single server key before it reaches
 * the blob store, so the stored object is useless on its own — a leaked blob,
 * a mis-set access control, or a stray public URL exposes nothing. The key
 * lives in TONY_ENCRYPTION_KEY, not in the database, so reading the database
 * is not enough either.
 *
 * What this deliberately does NOT defend against: anyone who can run code on
 * this server, or a lawful demand made to whoever operates it. Say that
 * plainly in the privacy policy rather than implying more.
 *
 * Layout is nonce (12 bytes) + ciphertext, matching src/tony_cli/hosted.py's
 * older client-side format so the two stay legible to each other.
 */

let cached: CryptoKey | null = null;

async function key(): Promise<CryptoKey> {
  if (cached) return cached;
  const raw = import.meta.env.TONY_ENCRYPTION_KEY;
  if (!raw) throw new Error("TONY_ENCRYPTION_KEY is not set");
  const bytes = Uint8Array.from(atob(raw.replace(/-/g, "+").replace(/_/g, "/")), (c) =>
    c.charCodeAt(0),
  );
  if (bytes.length !== 32) {
    throw new Error(`TONY_ENCRYPTION_KEY must decode to 32 bytes, got ${bytes.length}`);
  }
  cached = await crypto.subtle.importKey("raw", bytes, "AES-GCM", false, ["encrypt", "decrypt"]);
  return cached;
}

export async function seal(plaintext: string): Promise<Uint8Array> {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const body = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce },
    await key(),
    new TextEncoder().encode(plaintext),
  );
  const out = new Uint8Array(nonce.length + body.byteLength);
  out.set(nonce, 0);
  out.set(new Uint8Array(body), nonce.length);
  return out;
}

export async function open(sealed: ArrayBuffer): Promise<string> {
  const bytes = new Uint8Array(sealed);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bytes.slice(0, 12) },
    await key(),
    bytes.slice(12),
  );
  return new TextDecoder().decode(plain);
}
