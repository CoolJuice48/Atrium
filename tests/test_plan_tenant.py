"""Tests for plan generation: stores per user, inaccessible across users."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.db.session import init_db, reset_engine
from server.db.models import Syllabus, LearningPlan, User
from server.dependencies import get_settings


def test_plan_generation_stores_per_user():
    """Plan generation stores plan per user and is inaccessible across users."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        storage_path = Path(tmp) / "syllabus_storage"
        storage_path.mkdir()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings()
        settings.syllabus_storage_path = storage_path
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r1 = client.post("/auth/register", json={"email": "user1@x.com", "password": "password123"})
            r2 = client.post("/auth/register", json={"email": "user2@x.com", "password": "password123"})
            assert r1.status_code == 200 and r2.status_code == 200

            # User1 uploads syllabus (minimal - we need a syllabus_id)
            from server.db.session import get_session_factory
            from server.services import syllabus_service
            factory = get_session_factory(settings)
            db = factory()
            u1 = db.query(User).filter(User.email == "user1@x.com").first()
            syllabus_id = syllabus_service.store_syllabus(
                db, u1.id, "s.pdf", "application/pdf", 10,
                b"ct", b"wudk", None, storage_path,
            )
            db.commit()
            db.close()

            # User1 generates plan
            r = client.post(
                "/plan/generate_from_features",
                json={
                    "syllabus_id": syllabus_id,
                    "path_id": "cs",
                    "features": {"topics": ["A", "B"], "weeks": [1, 2], "textbooks": []},
                },
                cookies=r1.cookies,
            )
            assert r.status_code == 200
            plan_id = r.json()["plan_id"]

            # User2 cannot access User1's syllabus
            r = client.post(
                "/plan/generate_from_features",
                json={
                    "syllabus_id": syllabus_id,
                    "path_id": "cs",
                    "features": {"topics": []},
                },
                cookies=r2.cookies,
            )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()
