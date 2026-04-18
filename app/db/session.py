from __future__ import annotations

import threading
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base

_lock = threading.Lock()
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None  # type: ignore[type-arg]


def get_engine() -> Engine:
    """Returns the shared SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                s = get_settings()
                _engine = create_engine(
                    s.database_url,
                    pool_pre_ping=True,
                    pool_size=s.db_pool_size,
                    max_overflow=s.db_max_overflow,
                    pool_timeout=s.db_pool_timeout,
                )
    return _engine


def _get_session_factory() -> sessionmaker:  # type: ignore[type-arg]
    global _SessionLocal
    if _SessionLocal is None:
        with _lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(
                    bind=get_engine(),
                    autoflush=False,
                    autocommit=False,
                    expire_on_commit=False,
                )
    return _SessionLocal


def SessionLocal() -> Session:
    """Create a new DB session. Caller is responsible for closing it."""
    return _get_session_factory()()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Dev/CI convenience only — production uses schema.sql + migration files."""
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def check_db_connection() -> None:
    """Healthcheck — SELECT 1."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
