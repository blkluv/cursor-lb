#!/usr/bin/env bash
# Start the dev server and stream logs until Ctrl+C.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "No .env found — copying from .env.example"
  cp .env.example .env
fi

uv sync --dev 2>/dev/null || uv sync

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
export HOST PORT

cleanup() {
  echo ""
  echo "Stopping app..."
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
}
trap cleanup INT TERM

echo "Starting Matt Invoice Assistant on http://${HOST}:${PORT}"
# Watch only app/ — full-tree --reload exhausts file descriptors (.venv, caches, etc.)
uv run uvicorn app.main:app --host "$HOST" --port "$PORT" --reload --reload-dir app &
PID=$!

# Wait for startup signal in logs
for i in $(seq 1 30); do
  if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
    echo "✓ Healthy — streaming logs (Ctrl+C to stop)"
    wait "$PID"
    exit 0
  fi
  sleep 0.5
done

echo "✗ Startup failed — check logs above"
kill "$PID" 2>/dev/null || true
exit 1
