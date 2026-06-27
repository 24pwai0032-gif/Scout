"""Database engine/session. SQLite for local dev, Postgres-ready via the URL.

`init_db()` (create_all) is a convenience for local/demo. Production uses Alembic
migrations (see /migrations) so schema changes are versioned.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scout.capture.schema import Base
from scout.config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def _connect_args(url: str) -> dict:
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        _engine = create_engine(url, connect_args=_connect_args(url), future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
