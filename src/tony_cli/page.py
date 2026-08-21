"""Assemble the local review page from the payload and the shared viewer bundle.

There is exactly one renderer: the TypeScript bundle built from web/src/renderer,
prebuilt at release time and shipped inside this package as viewer.js/viewer.css.
The hosted page runs the same bundle against a decrypted payload; this module
runs it against an inlined one. Local and hosted output are identical by
construction, not by discipline.

The page stays one self-contained file that works offline: fonts are base64'd
in (see fonts.py), the CSS and JS are inlined, and the payload rides along as a
JSON script tag.
"""

import html
import os

from tony_cli.fonts import fontFaces

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _asset(name):
    with open(os.path.join(ASSET_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def renderPage(payloadJson, title="tony"):
    """One self-contained HTML page around an already-serialised payload."""
    css = _asset("viewer.css")
    js = _asset("viewer.js")
    # The hosted stylesheet loads fonts from /fonts; the local page carries them.
    css = "\n".join(
        line for line in css.split("\n") if not line.startswith("@font-face")
    )
    # A `</script` inside a string would end the JSON block early.
    safePayload = payloadJson.replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{fontFaces()}
{css}
</style>
</head>
<body>
<div id="tony-root"></div>
<script type="application/json" id="tony-payload">{safePayload}</script>
<script>{js}</script>
</body>
</html>
"""
