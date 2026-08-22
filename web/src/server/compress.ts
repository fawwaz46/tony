/**
 * Gzip, either side of the encryption boundary.
 *
 * Order is not a preference: AES-GCM output is indistinguishable from random
 * and does not compress, so compression has to happen before `seal` or not at
 * all. Review payloads are JSON full of repeated source lines and key names,
 * which is close to the best case for gzip — roughly 10:1 in practice.
 *
 * That buys two things: blobs cost a tenth as much to store and serve, and the
 * upload limit is measured against compressed bytes, so the same cap admits
 * about ten times the review.
 */

/** Thrown when decompressed output runs past its ceiling. */
export class TooLarge extends Error {}

export async function gzip(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream()
    .pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/**
 * Inflate, refusing to keep going past `maxBytes`.
 *
 * The ceiling is the point. A gzip bomb is a kilobyte on the wire and a
 * gigabyte in memory, so a limit checked only against what arrived is not a
 * limit at all — this reads incrementally and gives up the moment the output
 * exceeds what a review is allowed to be.
 */
export async function gunzip(bytes: Uint8Array, maxBytes: number): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream()
    .pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.length;
    if (total > maxBytes) {
      await reader.cancel();
      throw new TooLarge(`decompressed past ${maxBytes} bytes`);
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

/**
 * Does this look like a gzip member?
 *
 * Blobs written before compression existed are plain ciphertext of JSON, and
 * they still have to open. The two-byte magic tells them apart without a
 * version column or a migration.
 */
export const isGzip = (bytes: Uint8Array) =>
  bytes.length > 1 && bytes[0] === 0x1f && bytes[1] === 0x8b;
