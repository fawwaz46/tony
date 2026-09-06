import { defineConfig } from "astro/config";
import vercel from "@astrojs/vercel";

export default defineConfig({
  // Static by default; API routes and /r/<id> opt out with `prerender = false`.
  // The review page is client-rendered: the payload is fetched and decrypted
  // in the browser, and src/renderer draws it.
  output: "static",
  adapter: vercel(),
  // Astro's built-in CSRF check compares the Origin header against the origin
  // it computed for the request, which behind Vercel's proxy is localhost —
  // so every same-site POST was rejected as cross-site. We run the equivalent
  // check in middleware against the forwarded host instead.
  security: { checkOrigin: false },
  build: { inlineStylesheets: "auto" },
});
