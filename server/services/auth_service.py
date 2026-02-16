"""Authentication service: register, login, session management."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session as DBSession

from server.db.models import Session, User

ph = PasswordHasher()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(db: DBSession, email: str, password: str) -> User:
    """Create a new user. Raises ValueError if email exists."""
    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        raise ValueError("Email already registered")
    user = User(
        email=email.lower().strip(),
        password_hash=ph.hash(password),
    )
    db.add(user)
    db.flush()
    return user


def verify_password(password: str, password_hash: str) -> bool:
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def create_session(db: DBSession, user_id: str, ttl_hours: int = 24 * 7) -> str:
    """Create session, return raw token (to set in cookie)."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    sess = Session(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=expires,
    )
    db.add(sess)
    db.flush()
    return token


def get_user_by_session(db: DBSession, token: str) -> Optional[User]:
    """Return user if valid session token, else None."""
    if not token:
        return None
    h = hash_token(token)
    sess = db.query(Session).filter(
        Session.token_hash == h,
        Session.expires_at > datetime.now(timezone.utc),
    ).first()
    if not sess:
        return None
    return db.query(User).filter(User.id == sess.user_id).first()


def logout_session(db: DBSession, token: str) -> bool:
    """Delete session by token. Returns True if found."""
    if not token:
        return False
    h = hash_token(token)
    deleted = db.query(Session).filter(Session.token_hash == h).delete()
    return deleted > 0
