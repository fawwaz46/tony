import { defineConfig } from "astro/config";

export default defineConfig({
  // The page is text and code. No framework runtime ships — the tab and step
  // players are the same vanilla JS the Python renderer used.
  build: { inlineStylesheets: "auto" },
});
