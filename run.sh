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
# Stop everything this script started (Ollama if we started it, the web app, the worker and its reader)
trap 'trap - EXIT INT TERM; kill 0 2>/dev/null' EXIT INT TERM

# The AI model: use a running Ollama, or start one (from the PATH or ~/.local/ollama/bin)
OLLAMA_BIN=${OLLAMA_BIN:-$(command -v ollama || true)}
[ -z "$OLLAMA_BIN" ] && [ -x "$HOME/.local/ollama/bin/ollama" ] && OLLAMA_BIN="$HOME/.local/ollama/bin/ollama"
MODEL=$(sed -n 's/^OLLAMA_MODEL=//p' .env | head -1)
MODEL=${MODEL:-granite4:micro}
ollama_up() { curl -s -m 2 http://localhost:11434/api/version >/dev/null; }
if ! ollama_up; then
  if [ -n "$OLLAMA_BIN" ]; then
    echo "Starting Ollama ($OLLAMA_BIN); its log is in data/ollama.log"
    mkdir -p data
    "$OLLAMA_BIN" serve >> data/ollama.log 2>&1 &
    for _ in $(seq 1 30); do ollama_up && break; sleep 0.5; done
  fi
fi
if ! ollama_up; then
  echo "Warning: Ollama is not running. Demos still load from the cache, but new documents cannot be read."
  echo "         Install it (https://ollama.com/download), or set OLLAMA_BIN=/path/to/ollama."
elif [ -n "$OLLAMA_BIN" ] && ! "$OLLAMA_BIN" list 2>/dev/null | grep -q "^$MODEL"; then
  echo "Warning: the model $MODEL is not downloaded. Run: $OLLAMA_BIN pull $MODEL"
fi

"$PY" -m uvicorn app.main:app --port "$PORT" 2>&1 | sed -u 's/^/[web]    /' &
"$PY" -m app.worker 2>&1 | sed -u 's/^/[worker] /' &

echo
echo "TallyTime is starting at http://localhost:$PORT  (Ctrl+C to stop)"
echo "New account? The confirmation link is printed below as a line containing '#verify='."
echo
wait -n   # if either process stops, stop the other too
