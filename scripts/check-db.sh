#!/usr/bin/env bash
# Sync DB schema to SQLAlchemy models and verify — run after every feature.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

uv run python3 << 'PY'
from app.db import engine
from app.db_migrate import apply_migrations, ensure_schema_synced, schema_errors

before = schema_errors(engine)
applied = apply_migrations(engine)
ensure_schema_synced(engine)

if before:
    print("Migrations applied:")
    for err in before:
        print(f"  - fixed: {err}")
elif applied:
    for col in applied:
        print(f"  - added: {col}")
else:
    print("✓ Database schema matches models (no migration needed)")
PY
