"""Tests for auth: register, login, me, logout."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Use SQLite for tests
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.db.session import init_db, get_session_factory, reset_engine
from server.dependencies import get_settings


def test_register_login_me_logout():
    """Register, login, me, logout flow."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings()
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            # Register
            r = client.post("/auth/register", json={"email": "test@example.com", "password": "password123"})
            assert r.status_code == 200
            assert r.json()["email"] == "test@example.com"
            assert "atrium_session" in r.cookies

            # Me
            r = client.get("/auth/me", cookies=r.cookies)
            assert r.status_code == 200
            assert r.json()["email"] == "test@example.com"

            # Logout
            r = client.post("/auth/logout", cookies=client.cookies)
            assert r.status_code == 200

            # Me after logout (no cookie)
            r = client.get("/auth/me")
            assert r.status_code == 401
        finally:
            app.dependency_overrides.clear()


def test_login():
    """Login with correct credentials."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings()
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            client.post("/auth/register", json={"email": "u@x.com", "password": "secret123"})
            r = client.post("/auth/login", json={"email": "u@x.com", "password": "secret123"})
            assert r.status_code == 200
            assert "atrium_session" in r.cookies
        finally:
            app.dependency_overrides.clear()


def test_register_duplicate_email():
    """Register with existing email fails."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings()
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            client.post("/auth/register", json={"email": "dup@x.com", "password": "password123"})
            r = client.post("/auth/register", json={"email": "dup@x.com", "password": "other456"})
            assert r.status_code == 400
        finally:
            app.dependency_overrides.clear()
