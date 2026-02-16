"""Auth dependency: extract session from cookie, resolve user."""

from typing import Optional

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from server.db.session import get_session_factory
from server.config import Settings
from server.dependencies import get_settings
from server.db.models import User
from server.services import auth_service


def get_db_session(settings: Settings = Depends(get_settings)):
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


def get_current_user_optional(
    atrium_session: Optional[str] = Cookie(None, alias="atrium_session"),
    db: DBSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """Return current user or None if not authenticated."""
    if not atrium_session:
        return None
    return auth_service.get_user_by_session(db, atrium_session)


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Require authenticated user. Raises 401 if not logged in."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
