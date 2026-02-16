"""Database session management."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession, sessionmaker

from server.config import Settings
from server.db.models import Base


_engine = None
_SessionLocal = None


def get_engine(settings: Settings):
    global _engine
    if _engine is None:
        url = settings.database_url
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            _engine = create_engine(url)
    return _engine


def get_session_factory(settings: Settings) -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine(settings)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal


@contextmanager
def get_db(settings: Settings) -> Generator[DBSession, None, None]:
    """Yield a database session. Caller must close/commit."""
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Clear cached engine and session factory. Use between tests for isolation."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db(settings: Settings) -> None:
    """Create all tables."""
    engine = get_engine(settings)
    Base.metadata.create_all(bind=engine)
