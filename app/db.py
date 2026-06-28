"""Database engine and session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def _get_connect_args():
    """Get connection arguments based on database type."""
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    if "neon.tech" in settings.database_url or "supabase" in settings.database_url:
        return {"sslmode": "require"}
    return {}


def _get_pool_kwargs():
    """Get pool arguments based on database type."""
    if settings.database_url.startswith("sqlite"):
        if settings.database_url in ("sqlite://", "sqlite:///:memory:"):
            return {"poolclass": StaticPool}
        return {"poolclass": NullPool}
    if "postgresql" in settings.database_url:
        return {
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    return {}


def get_engine():
    """Lazy initialize and return the database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            connect_args=_get_connect_args(),
            **_get_pool_kwargs(),
        )
    return _engine


def get_session_local():
    """Lazy initialize and return the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


# Properties for backward compatibility
@property
def engine():
    return get_engine()


@property
def SessionLocal():
    return get_session_local()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting a database session."""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
