/**
 * Server-side environment access.
 *
 * `import.meta.env.FOO` is replaced by Vite at build time, so a secret read
 * that way is frozen into the bundle: changing it in the dashboard does
 * nothing until the next rebuild, and rotating a leaked key silently fails.
 * That is wrong for anything the deployment reads at runtime.
 *
 * process.env is read when the request runs, which is what we want. The
 * import.meta.env fallback keeps `astro dev` working, where a .env file is
 * loaded into import.meta.env but not always into process.env.
 */
export function env(name: string): string | undefined {
  const runtime = typeof process !== "undefined" ? process.env?.[name] : undefined;
  if (runtime) return runtime;
  const built = (import.meta.env as Record<string, unknown>)[name];
  return typeof built === "string" && built ? built : undefined;
}

export const required = (name: string): string => {
  const value = env(name);
  if (!value) throw new Error(`${name} is not set`);
  return value;
};

/**
 * Which credential the blob SDK should use, if we have to name one.
 *
 * The SDK reads `BLOB_READ_WRITE_TOKEN` on its own, and a function running on
 * Vercel against a connected private store can authenticate without any static
 * token at all. Neither is guaranteed: connecting a store whose default
 * variable name is already taken forces a prefix, and the credential then
 * exists under a name the SDK has never heard of.
 *
 * So: hand it nothing when the default name is in play — let the SDK do what
 * it does, including its own token refresh — and name a token only when the
 * prefixed variable is the only one there is. Spread into a blob call:
 * `put(path, body, { access: "private", ...blobToken() })`.
 */
export function blobToken(): { token?: string } {
  if (env("BLOB_READ_WRITE_TOKEN")) return {};
  const prefixed = env("TONY_BLOB_READ_WRITE_TOKEN");
  return prefixed ? { token: prefixed } : {};
}
