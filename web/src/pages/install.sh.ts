/**
 * Serves the installer at https://tony-cli.com/install.sh
 *
 * The published install command should point at a URL we own, not at a raw
 * GitHub path that breaks the moment the repo is renamed, moved, or made
 * private. The script itself is imported from the repository root so there is
 * exactly one copy — this route cannot drift from the file people read.
 */
import type { APIRoute } from "astro";
import script from "../../../install.sh?raw";

export const GET: APIRoute = () =>
  new Response(script, {
    headers: {
      "Content-Type": "text/x-shellscript; charset=utf-8",
      // Short: this is piped into a shell, so a stale copy is worse than a
      // slow one, but a thundering herd on every install is pointless too.
      "Cache-Control": "public, max-age=300",
    },
  });
