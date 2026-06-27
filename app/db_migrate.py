"""Database schema sync and migration for SQLite."""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine import Engine

from app.db import Base

logger = logging.getLogger(__name__)


def _sqlite_column_type(column) -> str:
    return str(column.type.compile(dialect=sqlite.dialect()))


def schema_errors(engine: Engine) -> list[str]:
    """Return human-readable errors if DB schema does not match SQLAlchemy models."""
    errors: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            errors.append(f"missing table: {table_name}")
            continue
        db_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in db_columns:
                errors.append(f"missing column: {table_name}.{column.name}")
    return errors


def apply_migrations(engine: Engine) -> list[str]:
    """Create tables and add missing columns. Returns list of columns added."""
    Base.metadata.create_all(bind=engine)
    applied: list[str] = []

    inspector = inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in inspector.get_table_names():
            continue
        db_columns = {col["name"] for col in inspector.get_columns(table_name)}
        pending_cols = [col for col in table.columns if col.name not in db_columns]

        if not pending_cols:
            continue

        with engine.begin() as conn:
            for column in pending_cols:
                col_type = _sqlite_column_type(column)
                conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}")
                )
                applied.append(f"{table_name}.{column.name}")
                logger.info("Applied migration: %s.%s", table_name, column.name)

    return applied


def normalize_user_roles(engine: Engine) -> None:
    """Set photographer role on legacy users created before role column."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE users SET role = 'photographer' "
                "WHERE role IS NULL OR trim(role) = ''"
            )
        )


def normalize_client_emails(engine: Engine) -> None:
    """Lowercase client emails so customer portal queries match legacy rows."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET client_email = lower(trim(client_email)) "
                "WHERE client_email != lower(trim(client_email))"
            )
        )
        conn.execute(
            text(
                "UPDATE invoices SET client_email = lower(trim(client_email)) "
                "WHERE client_email != lower(trim(client_email))"
            )
        )


def ensure_schema_synced(engine: Engine) -> None:
    """Migrate then verify. Raises RuntimeError if schema still out of sync."""
    applied = apply_migrations(engine)
    normalize_user_roles(engine)
    normalize_client_emails(engine)
    errors = schema_errors(engine)
    if errors:
        msg = "Database schema out of sync after migration: " + "; ".join(errors)
        raise RuntimeError(msg)
    if applied:
        logger.info("DB migrations applied: %s", ", ".join(applied))
