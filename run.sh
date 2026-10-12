#!/usr/bin/env bash
# Run TallyTime locally: the web app and the worker together. Ctrl+C stops both.
#
#     ./run.sh                 http://localhost:8000
#     PORT=8001 ./run.sh       another port
#
# Needs the one-time setup from the README first (Ollama, the .venv and the Docling models).
set -euo pipefail
cd "$(dirname "$0")"

VENV=${VENV:-.venv}
PORT=${PORT:-8000}
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "No Python environment at $VENV. Do the one-time setup in the README (Quick start, steps 1-3) first."
  exit 1
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (local defaults)."
fi
if ! curl -s -m 2 http://localhost:11434/api/version >/dev/null; then
  echo "Warning: Ollama is not running. Demos still load from the cache, but new documents cannot be read."
  echo "         Start it with: sudo systemctl start ollama   (or: ollama serve &)"
fi

# Stop everything this script started (including the worker's reader process) on exit or Ctrl+C
trap 'trap - EXIT INT TERM; kill 0 2>/dev/null' EXIT INT TERM

"$PY" -m uvicorn app.main:app --port "$PORT" 2>&1 | sed -u 's/^/[web]    /' &
"$PY" -m app.worker 2>&1 | sed -u 's/^/[worker] /' &

echo
echo "TallyTime is starting at http://localhost:$PORT  (Ctrl+C to stop)"
echo "New account? The confirmation link is printed below as a line containing '#verify='."
echo
wait -n   # if either process stops, stop the other too
