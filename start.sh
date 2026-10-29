#!/usr/bin/env bash
# TEXT-TO-SPACESHIP (macOS / Linux): build the UI if needed, start the app on http://127.0.0.1:8768 and open it.
# Usage: bash start.sh [--project NAME] [--add /path/friend_part.stl ...]
# Needs uv and Node.js 24: the project's portable copies in tools/ (setup.sh puts them there), else installed ones.
set -euo pipefail
cd "$(dirname "$0")"
. tools/env.sh
command -v uv >/dev/null || { echo "First run bash setup.sh (macOS), or install uv: https://docs.astral.sh/uv/"; exit 1; }
command -v npm >/dev/null || { echo "First run bash setup.sh (macOS), or install Node.js 24: https://nodejs.org/"; exit 1; }
if [ ! -f frontend/dist/index.html ]; then
  echo "Building the user interface..."
  (cd frontend && { [ -d node_modules ] || npm ci; } && npm run build)
fi
echo "Starting TEXT-TO-SPACESHIP on http://127.0.0.1:8768/ (Ctrl+C stops it)"
if [ "$(uname -s)" = "Darwin" ]; then     # open the browser once the server answers
  ( for _ in $(seq 120); do curl -fs -o /dev/null http://127.0.0.1:8768/ && exec open http://127.0.0.1:8768/; sleep 1; done ) &
fi
cd backend
exec uv run --frozen python run_server.py "$@"
