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
# Stop everything this script started (the web app, the worker and its reader) on exit or Ctrl+C
trap 'trap - EXIT INT TERM; kill 0 2>/dev/null' EXIT INT TERM

# The AI model: Ollama should already be running (as a service); if not, start it
MODEL=$(sed -n 's/^OLLAMA_MODEL=//p' .env | head -1)
MODEL=${MODEL:-granite4:micro}
ollama_up() { curl -s -m 2 http://localhost:11434/api/version >/dev/null; }
if ! ollama_up; then
  if systemctl --user cat ollama.service >/dev/null 2>&1; then
    systemctl --user start ollama
  elif command -v ollama >/dev/null; then
    ollama serve >/dev/null 2>&1 &   # stopped again when this script exits
  fi
  for _ in $(seq 1 30); do ollama_up && break; sleep 0.5; done
fi
if ! ollama_up; then
  echo "Warning: Ollama is not running. Demos still load from the cache, but new documents cannot be read."
  echo "         Install it from https://ollama.com/download, then run this again."
elif command -v ollama >/dev/null && ! ollama list 2>/dev/null | grep -q "^$MODEL"; then
  echo "Warning: the model $MODEL is not downloaded. Run: ollama pull $MODEL"
fi

"$PY" -m uvicorn app.main:app --port "$PORT" 2>&1 | sed -u 's/^/[web]    /' &
"$PY" -m app.worker 2>&1 | sed -u 's/^/[worker] /' &

echo
echo "TallyTime is starting at http://localhost:$PORT  (Ctrl+C to stop)"
echo "New account? The confirmation link is printed below as a line containing '#verify='."
echo
wait -n   # if either process stops, stop the other too
