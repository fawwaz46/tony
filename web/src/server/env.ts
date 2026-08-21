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
