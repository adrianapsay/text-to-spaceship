#!/usr/bin/env bash
# Codespaces / dev container, run on every attach: start the app on port 8765 unless it is already running.
cd "$(dirname "$0")/../backend"
export PATH="$HOME/.local/bin:$PATH"
if curl -fsS http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
  echo "TEXT-TO-SPACESHIP is already running on port 8765."
  exit 0
fi
nohup uv run python run_server.py --project default > /tmp/t2s-server.log 2>&1 &
echo "Starting TEXT-TO-SPACESHIP on port 8765 (log: /tmp/t2s-server.log). Open it from the Ports tab."
