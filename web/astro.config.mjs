import { defineConfig } from "astro/config";
import vercel from "@astrojs/vercel";

export default defineConfig({
  // Static by default; API routes and /r/<id> opt out with `prerender = false`.
  // The review page itself is client-rendered — the server never holds the key
  // that opens a review, so there is nothing it could render.
  output: "static",
  adapter: vercel(),
  build: { inlineStylesheets: "auto" },
});
