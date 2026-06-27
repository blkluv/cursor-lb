"""Database engine and session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
_pool_kwargs: dict = {}
if settings.database_url in ("sqlite://", "sqlite:///:memory:"):
    _pool_kwargs["poolclass"] = StaticPool
elif settings.database_url.startswith("sqlite"):
    _pool_kwargs["poolclass"] = NullPool
engine = create_engine(
    settings.database_url, connect_args=connect_args, **_pool_kwargs,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
