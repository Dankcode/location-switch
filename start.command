#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -x "$HOME/.local/bin/uv" ]]; then
  path=("$HOME/.local/bin" $path)
fi
if ! command -v uv >/dev/null 2>&1; then
  print "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
  read -r "?Press Return to close. "
  exit 1
fi
uv sync --frozen
print "Location Switch: http://127.0.0.1:8765"
print "Keep this window open. Press Ctrl+C to stop (best-effort GPS restore)."
uv run --frozen python -m location_switch
