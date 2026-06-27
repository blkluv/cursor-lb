#!/usr/bin/env bash
# Typecheck → lint → db sync → unit tests → integration/e2e tests
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/5] Typecheck (pyright)"
uv run pyright app tests 2>/dev/null || {
  echo "  pyright not configured or failed — install with: uv add --dev pyright"
  exit 1
}

echo "[2/5] Lint (ruff)"
uv run ruff check app tests

echo "[3/5] Database sync + migration"
./scripts/check-db.sh

echo "[4/5] Unit tests (pytest)"
if [[ -d tests/unit ]]; then
  uv run pytest tests/unit -v --tb=short
else
  echo "  (no tests/unit — skipped)"
fi

echo "[5/5] Integration / e2e (pytest)"
uv run pytest tests/ -v --tb=short

echo "✓ verify.sh passed"
