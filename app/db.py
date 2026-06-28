"""Database engine and session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings

# DON'T create engine here - use lazy initialization
_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def get_engine():
    """Lazy initialize and return the database engine."""
    global _engine
    if _engine is None:
        connect_args = {}
        pool_kwargs = {}
        
        # SQLite configuration
        if settings.database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            if settings.database_url in ("sqlite://", "sqlite:///:memory:"):
                pool_kwargs["poolclass"] = StaticPool
            else:
                pool_kwargs["poolclass"] = NullPool
        # PostgreSQL configuration
        elif "postgresql" in settings.database_url:
            pool_kwargs = {
                "pool_pre_ping": True,
                "pool_recycle": 300,
            }
            # SSL for cloud databases
            if "neon.tech" in settings.database_url or "supabase" in settings.database_url:
                connect_args = {"sslmode": "require"}
        
        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            **pool_kwargs,
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


# IMPORTANT: These are functions, NOT objects created at import time
# Don't create engine or SessionLocal here!


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting a database session."""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
