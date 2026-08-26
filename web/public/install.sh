#!/bin/sh
# tony installer: puts a persistent `tony` command on your PATH.
#
#   curl -fsSL https://tony-cli.com/install.sh | sh
#
# Uses whatever Python tool-installer you already have (uv, then pipx). If you
# have neither, it tells you how to get one rather than piping a second
# stranger's script into your shell on your behalf.
#
# This file is canonical. web/public/install.sh is a copy the site serves;
# `npm run sync:install` regenerates it and CI fails if the two drift.
set -eu

PKG="tony-cli"
MIN="0.3.0"

# Resolve from PyPI explicitly. Both installers honour an ambient index
# setting, so on a machine configured for an internal mirror `tony-cli` would
# otherwise be whatever that mirror serves under the name.
INDEX="https://pypi.org/simple"
UV_INDEX_URL="$INDEX"; export UV_INDEX_URL
UV_DEFAULT_INDEX="$INDEX"; export UV_DEFAULT_INDEX
PIP_INDEX_URL="$INDEX"; export PIP_INDEX_URL

if command -v uv >/dev/null 2>&1; then
  echo "tony: installing with uv..."
  uv tool install --force "$PKG>=$MIN"
elif command -v pipx >/dev/null 2>&1; then
  echo "tony: installing with pipx..."
  pipx install --force "$PKG>=$MIN"
else
  echo "tony: needs uv or pipx to install, and found neither."
  echo
  echo "  Install one, then re-run this:"
  echo
  echo "    brew install uv                  # macOS"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "    python3 -m pip install --user pipx"
  echo
  echo "  The second line runs a script from astral.sh, the makers of uv."
  echo "  It is not ours, so we would rather you ran it deliberately."
  exit 1
fi

echo
echo "tony: installed. Try it inside any git repo:"
echo
echo "    tony main...my-branch"
echo
echo "First run will ask for an ANTHROPIC_API_KEY and tell you where to put it."
command -v tony >/dev/null 2>&1 || echo "note: open a new shell if 'tony' is not found yet."
