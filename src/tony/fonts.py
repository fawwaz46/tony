"""ABC Favorit, embedded so a review page is one file that works offline.

The faces ship with the package as woff2 and are base64'd into the page at render
time. Five faces, ~300KB encoded — the cost of the page being self-contained.
"""

import base64
import functools
import os

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")

# family, weight, file. Book (500) is the emphasis weight — the step below Bold.
FACES = [
    ("Favorit", 400, "Favorit-Regular.woff2"),
    ("Favorit", 500, "Favorit-Book.woff2"),
    ("Favorit", 700, "Favorit-Bold.woff2"),
    ("Favorit Mono", 400, "FavoritMono-Regular.woff2"),
    ("Favorit Mono", 500, "FavoritMono-Medium.woff2"),
]


@functools.lru_cache(maxsize=1)
def fontFaces():
    """The @font-face block. Missing files degrade to the fallback stack, silently."""
    out = []
    for family, weight, name in FACES:
        path = os.path.join(FONT_DIR, name)
        try:
            with open(path, "rb") as fh:
                data = base64.b64encode(fh.read()).decode("ascii")
        except OSError:
            continue
        out.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
            f"font-display:swap;src:url(data:font/woff2;base64,{data}) format('woff2')}}"
        )
    return "\n".join(out)
