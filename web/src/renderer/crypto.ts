/**
 * Decrypting a hosted review in the reader's browser.
 *
 * The CLI seals the payload with AES-256-GCM under a key that travels only in
 * the URL fragment — the part of a URL a browser never sends to any server.
 * The blob layout is nonce (12 bytes) + ciphertext, and the fragment is the
 * unpadded urlsafe-base64 key. Mirrors `encrypt` in src/tony_cli/hosted.py.
 */

function fromUrlSafeBase64(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function decryptPayload(sealed: ArrayBuffer, fragment: string): Promise<string> {
  const keyBytes = fromUrlSafeBase64(fragment);
  if (keyBytes.length !== 32) throw new Error("bad key");
  const key = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["decrypt"]);
  const nonce = sealed.slice(0, 12);
  const ciphertext = sealed.slice(12);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, key, ciphertext);
  return new TextDecoder().decode(plain);
}
