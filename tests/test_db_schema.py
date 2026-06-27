"""Database schema sync tests."""

from app.db import engine
from app.db_migrate import apply_migrations, ensure_schema_synced, schema_errors


def test_schema_matches_models_after_migrate():
    apply_migrations(engine)
    assert schema_errors(engine) == []


def test_ensure_schema_synced():
    ensure_schema_synced(engine)
    assert schema_errors(engine) == []
