#!/usr/bin/env bash
# TEXT-TO-SPACESHIP (macOS / Linux): build the UI if needed and start the app on http://127.0.0.1:8768.
# Usage: bash start.sh [--project NAME] [--add /path/friend_part.stl ...]      Needs uv and Node.js 24.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 24 is required: https://nodejs.org/"; exit 1; }
if [ ! -f frontend/dist/index.html ]; then
  echo "Building the user interface..."
  (cd frontend && { [ -d node_modules ] || npm ci; } && npm run build)
fi
echo "Starting TEXT-TO-SPACESHIP on http://127.0.0.1:8768/ (Ctrl+C stops it)"
cd backend
exec uv run python run_server.py "$@"
