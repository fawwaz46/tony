#!/bin/sh
# tony installer: puts a persistent `tony` command on your PATH.
#
#   curl -fsSL https://tony-cli.com/install.sh | sh
#
# Uses whatever Python tool-installer you already have (uv, then pipx) and only
# bootstraps uv if you have neither — and says so before it does.
set -eu

PKG="tony-cli"

if command -v uv >/dev/null 2>&1; then
  echo "tony: installing with uv..."
  uv tool install --force "$PKG"
elif command -v pipx >/dev/null 2>&1; then
  echo "tony: installing with pipx..."
  pipx install --force "$PKG"
else
  echo "tony: no uv or pipx found — installing uv (https://astral.sh/uv) first."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs into ~/.local/bin, which may not be on PATH in this shell yet.
  export PATH="$HOME/.local/bin:$PATH"
  uv tool install --force "$PKG"
fi

echo
echo "tony: installed. Try it inside any git repo:"
echo
echo "    tony main...my-branch"
echo
echo "First run will ask for an ANTHROPIC_API_KEY and tell you where to put it."
command -v tony >/dev/null 2>&1 || echo "note: open a new shell if 'tony' is not found yet."
