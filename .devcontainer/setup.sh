#!/usr/bin/env bash
# Codespaces / dev container, run once after the container is created: uv (official installer, pinned to the
# version the Windows toolchain uses), the backend's locked Python packages (uv also fetches CPython 3.14), and
# the built user interface.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
(cd backend && uv sync --frozen)
(cd frontend && npm ci && npm run build)
echo "Setup done. The app starts on port 8765 (Ports tab: TEXT-TO-SPACESHIP)."
